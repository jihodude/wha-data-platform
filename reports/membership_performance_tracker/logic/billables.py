"""
billables.py — Hospitality and Allied billable counts per territory (with the
               Target/Non-Target split) plus segment penetration.

BILLABLE RULE (ratified 2026-07-14 — see docs/DECISIONS.md + the report SPEC):
    A billable is an ACTIVE account that CARRIES A MEMBERSHIP BILL (a
    MembershipProduct on cMemberGens). Hospitality vs Allied is decided by the
    membership PRODUCT NAME, not the account Type. Implemented by
    compute_billables_by_target(); build_target_map() (target.py) adds the
    Target/Non-Target split via 3 territory-wide queries (not per-account).
    Output keys: hospitality, allied, hospitality_target, hospitality_non_target,
    hospitality_unknown. Allied is always Non-Target.

    SUPERSEDED + REMOVED (2026-07-17): the older "Active, Type != 'Allied',
    ParentId eq null" rule (compute_billables) and the DISPROVEN "Duesbillmonth
    > 12 = NRA" marker (count_nra_billables). Do not reintroduce them.

PENETRATION (compute_penetration_by_segment):
    Active member locations / market, split into Restaurant and Lodging segments
    (Target-filtered: restaurants >= 10 FTE, hotels >= TARGET_ROOMS_MIN rooms).
    The combined pen_pct is derived in engine._compute_layer1 (P1-5: a missing
    segment contributes zero). Shared classification tables live in target.py.

Territory assignment:
    account.AccountManager.Id -> slx_user_to_territory (territory_map.yaml)

ITD dependency:
    Counts are only valid AFTER ITD (Inactivate Members Utility) has run for the
    current month.

Usage:
    from reports.membership_performance_tracker.logic.billables import compute_billables_by_target

    result = compute_billables_by_target(client, territory_user_map)
    # result["Pierce"] == {
    #   "hospitality": 184, "allied": 23,
    #   "hospitality_target": 120, "hospitality_non_target": 60,
    #   "hospitality_unknown": 4,
    # }
"""

import time
from typing import Dict

from src.slx.client import SLXClient
from reports.membership_performance_tracker.logic.target import build_target_map, get_type_map, split_counts, TARGET, NON_TARGET


def _count_locations(type_map, class_map, *, target_class, subtype_map=None):
    """
    Generic location counter — counts accounts classified as `target_class`,
    split into (restaurant, lodging). Corporate accounts excluded (billing
    entities, not locations); only PENETRATION_RESTAURANT_TYPES count as
    restaurants; Hotel/Lodging types count as lodging.

    When `subtype_map` is given, lodging is further limited to the Crystal
    report's market subtypes (LODGING_MARKET_SUBTYPES, adopted 2026-07-19):
    a 40+-space RV park / campground / vacation rental is Target-SIZED but not
    the hotel MARKET. A subtype in neither the market nor the known-excluded
    set is a new CRM subtype → warn loudly, never silently count or drop.

    Call with target_class=TARGET for the existing target-pool penetration,
    or target_class=NON_TARGET for the non-target-pool penetration.
    """
    r_ids, l_ids = _location_ids(type_map, class_map,
                                 target_class=target_class,
                                 subtype_map=subtype_map)
    return len(r_ids), len(l_ids)


def _location_ids(type_map, class_map, *, target_class, subtype_map=None):
    """The SAME classification as _count_locations, returning the account
    ids (restaurant_ids, lodging_ids). Counts are lens of these lists —
    one implementation, so the penetration receipts can never drift from
    the published counts (8/6 transparency build)."""
    import warnings
    from reports.membership_performance_tracker.logic.target import (
        HOTEL_TYPES, PENETRATION_RESTAURANT_TYPES,
        LODGING_MARKET_SUBTYPES, LODGING_NON_MARKET_SUBTYPES)
    r_ids, l_ids = [], []
    for acct_id, type_str in type_map.items():
        if class_map.get(acct_id) != target_class:
            continue
        if type_str in HOTEL_TYPES:
            if subtype_map is not None:
                sub = (subtype_map.get(acct_id) or "").strip()
                if sub not in LODGING_MARKET_SUBTYPES:
                    if sub not in LODGING_NON_MARKET_SUBTYPES:
                        warnings.warn(f"[penetration] {'MISSING' if not sub else 'unrecognized'} "
                                      f"lodging subtype {sub!r} on {acct_id} → excluded from "
                                      f"the market (add to target.LODGING_*_SUBTYPES if real)")
                    continue
            l_ids.append(acct_id)
        elif type_str in PENETRATION_RESTAURANT_TYPES:
            r_ids.append(acct_id)
    return r_ids, l_ids


def _count_target_locations(type_map, class_map):
    """
    Count TARGET accounts as physical locations, split into (restaurant, lodging).

    Corporate accounts are billing entities for multi-location chains, not
    physical locations — counting them would double-count the chain alongside
    its child locations — so they are excluded from both numerator and
    denominator. Hotel/Lodging types count as lodging. Only types in WHA's
    food-service whitelist (Restaurant, Catering, Recreational, Concession)
    count as restaurant locations; everything else (Grocery, Non-Commercial,
    unknown new types) is excluded from BOTH numerator and denominator so
    the metric stays restricted to actual food-service penetration.

    UNKNOWN treatment — POLICY DECISION 2026-06-05 (revisitable):
        Accounts whose FTE size data is missing return Unknown from
        _classify_one. This counter excludes them entirely. Rationale: a
        live 11-territory probe (`scripts/`-grade one-off) compared three
        policies against Hannah's published 78.9% for Pierce restaurant:
            A. Drop Unknown            → Pierce 80.3% ✓ matches Hannah
            B. Include in num + denom  → Pierce 62.7% (under by 16pp)
            C. Include in num only     → Pierce 100% (mathematically broken)
        Policy A was adopted. If a future dev wants to revisit this — e.g.
        once Hannah's numbers are available for more territories, or once
        the missing-FTE rate drops materially below today's ~7% — this is
        the single function to change. See backlog item "Pen Active
        automation" (closed 2026-06-05) for full evidence; the research-
        data inlet adapter (separate backlog item) is the cleaner long-term
        override surface than editing this function in place.
    """
    from reports.membership_performance_tracker.logic.target import HOTEL_TYPES, FOOD_SERVICE_TYPES

    r = l = 0
    for acct_id, type_str in type_map.items():
        if class_map.get(acct_id) != TARGET:
            continue
        if type_str in HOTEL_TYPES:
            l += 1
        elif type_str in FOOD_SERVICE_TYPES:
            r += 1
        # else: Corporate / Grocery / Non-Commercial / Unknown / new types
        # — not counted (see UNKNOWN treatment in docstring).
    return r, l


def compute_penetration_by_segment(
    client: SLXClient,
    territory_user_map: Dict[str, str],
    request_delay: float = 0.15,
) -> Dict[str, Dict[str, Dict[str, int]]]:
    """
    Compute Target-filtered penetration per territory, split Restaurant / Lodging.

    Definition (2026-06-04, reconciled against the Crystal penetration report;
    subtype rule adopted 2026-07-19):
      Target restaurant = Avgrangefteperloc >= 10 FTE (normalized band formats)
      Target lodging    = Rooms >= TARGET_ROOMS_MIN (40+) AND SubType in
                          LODGING_MARKET_SUBTYPES — the Crystal report's universe
                          (RV parks / campgrounds / vacation rentals / military
                          housing are not the hotel market even at 40+ spaces)
      Numerator (active)   = active Target locations
      Denominator (market) = active + inactive Target locations

    Penetration % = active Target / (active + inactive Target).

    The "market" universe is Active + Inactive members ONLY — matching the
    Crystal report. We deliberately do NOT use status=None (all statuses),
    because that pulls Closed/RRO accounts that are not part of the member
    universe and inflated the denominator in every territory. Corporate billing
    entities are excluded by _count_locations (they are not physical locations).

    Uses the session-cached build_target_map + get_type_map, so the SLX cost is
    two target-map builds per territory (status='Active' and status='Inactive'),
    which the cache shares with billables/retention if they ran first.

    Returns per territory:
        {
          "restaurant": {"active": N, "market": M},
          "lodging":    {"active": N, "market": M},
        }
    """
    from reports.membership_performance_tracker.logic.target import build_target_map, get_type_map, get_subtype_map

    result: Dict[str, Dict[str, Dict[str, int]]] = {}
    for user_id, territory in territory_user_map.items():
        if territory is None:
            continue

        # Numerator = active members. Market denominator = active + inactive.
        active_class   = build_target_map(client, user_id, status="Active",
                                          request_delay=request_delay)
        inactive_class = build_target_map(client, user_id, status="Inactive",
                                          request_delay=request_delay)
        active_types   = get_type_map(client, user_id, status="Active",
                                      request_delay=request_delay)
        inactive_types = get_type_map(client, user_id, status="Inactive",
                                      request_delay=request_delay)
        active_subs    = get_subtype_map(client, user_id, status="Active",
                                         request_delay=request_delay)
        inactive_subs  = get_subtype_map(client, user_id, status="Inactive",
                                         request_delay=request_delay)

        market_class = {**active_class, **inactive_class}
        market_types = {**active_types, **inactive_types}
        market_subs  = {**active_subs, **inactive_subs}

        # Target pool (existing) — active target ÷ target market
        ra_ids, la_ids = _location_ids(active_types, active_class,
                                       target_class=TARGET, subtype_map=active_subs)
        rm_ids, lm_ids = _location_ids(market_types, market_class,
                                       target_class=TARGET, subtype_map=market_subs)
        nra_ids, nla_ids = _location_ids(active_types, active_class,
                                         target_class=NON_TARGET, subtype_map=active_subs)
        nrm_ids, nlm_ids = _location_ids(market_types, market_class,
                                         target_class=NON_TARGET, subtype_map=market_subs)
        ra, la = len(ra_ids), len(la_ids)
        rm, lm = len(rm_ids), len(lm_ids)
        nra, nla = len(nra_ids), len(nla_ids)
        nrm, nlm = len(nrm_ids), len(nlm_ids)
        # RECEIPTS (8/6): the rosters behind every penetration count —
        # record-only, same ids the counts are lens of.
        from reports.membership_performance_tracker.logic import (
            receipts_capture as _rc)
        _rc.record("penetration", user_id, {
            "territory": territory,
            "restaurant": {"active": ra_ids, "market": rm_ids},
            "lodging": {"active": la_ids, "market": lm_ids},
            "restaurant_nt": {"active": nra_ids, "market": nrm_ids},
            "lodging_nt": {"active": nla_ids, "market": nlm_ids}})

        seg = {
            "restaurant":    {"active": ra,  "market": rm},
            "lodging":       {"active": la,  "market": lm},
            "restaurant_nt": {"active": nra, "market": nrm},
            "lodging_nt":    {"active": nla, "market": nlm},
        }
        # Multi-user territories (e.g. Majors/NRA = MajorAccounts rep + NRA
        # house user, 2026-07-13): SUM per territory, don't overwrite.
        if territory in result:
            for cat, d in seg.items():
                for k, v in d.items():
                    result[territory][cat][k] += v
        else:
            result[territory] = seg

    return result


def enrolled_after_period(member_gen: dict, period_end) -> bool:
    """True when this member enrolled AFTER the month being reported.

    2026-07-30 (Jen, recorded): she withholds activation of members joining
    between the 1st and the 5th "because I don't want them counted yet" — the
    close runs in the first week of the following month, and billables is a
    LIVE snapshot, so an early-August activation would land in July's count.
    Her ask: *"I would love to be able to activate members right away."*
    Shannon's step 8 names the fix — exclude by enroll date rather than make a
    human hold the data back.

    No enroll date ⇒ KEEP. Absence of evidence is not evidence of a late sale,
    and excluding them would silently shrink the billable base.
    """
    if period_end is None:
        return False
    raw = (member_gen or {}).get("EnrolledDate")
    if not raw:
        return False
    from reports.membership_performance_tracker.logic.ledger_revenue import (
        parse_slx_date)
    when = parse_slx_date(raw)
    return bool(when and when > period_end)


def compute_billables_by_target(
    client: SLXClient,
    territory_user_map: Dict[str, str],
    request_delay: float = 0.15,
    period_end=None,
    carriers_out: Dict[str, str] = None,
) -> Dict[str, Dict]:
    """
    Compute billable counts split by Target / Non-Target per territory.

    Adds Target/Non-Target breakdown to the standard hospitality count, plus
    an NRA count (Duesbillmonth > 12) so NRA can be excluded from totals and
    shown separately. Allied is always Non-Target — no split needed there.

    BILLABLE RULE (2026-07-13): billable = the ACTIVE record that CARRIES THE BILL —
    cMemberGens.Duesbillmonth in 1..12 (WHA-invoiced). This matches the CRM
    billables reports, which list exactly the invoiced records grouped by bill
    month (verified against the 7/13 exports: Hospitality 2,132 / Allied 161 /
    NRA 34). Replaces the old ParentId=null approximation, which undercounted
    hospitality (~350 bills that go to non-top-of-family records) and
    overcounted Allied (~31 active Allied records that carry no bill).
    NRA = Duesbillmonth > 12 (billed by the national association, $0 to WHA) —
    reported separately and inherently excluded from "hospitality".

    Uses build_target_map() internally (accounts + cMemberGens + cRestProfiles)
    plus one bill-month cMemberGens query. ~4 API calls per territory.

    Args:
        client:              Authenticated SLXClient instance.
        territory_user_map:  Dict mapping SLX user ID -> canonical territory name.
        request_delay:       Seconds to pause between API calls.

    Returns:
        Dict keyed by canonical territory name:
        {
            "Pierce": {
                "hospitality":         184,    # WHA-billed, non-Allied
                "allied":               23,    # WHA-billed, Type = Allied
                "hospitality_target":  120,    # meets FTE/rooms threshold
                "hospitality_non_target": 60,  # below threshold
                "hospitality_unknown":   4,    # size data missing (7% restaurants)
            },
            ...
        }
    """
    result: Dict[str, Dict] = {}

    for user_id, territory in territory_user_map.items():
        if territory is None:
            continue

        # BILLABLE RULE — SOLVED 2026-07-14 PM: billable = ACTIVE account that
        # carries a **MembershipProduct** (the product IS what generates dues,
        # per Sheryl's notes). Verified against the CRM by-territory report:
        # 10/10 territories EXACT (Pierce 239=239, EastKing 185=185, ...,
        # statewide 2,294 vs 2,293). Supersedes both prior rules (ParentId=null
        # undercounted ~350; bill-month over-counted to 5,148). Child locations
        # with their own product COUNT (Jen-confirmed). NRA needs no special
        # heuristic: the Majors/NRA house-user mapping puts the ~34 NRA billing
        # entities in their own column naturally (bm>12 was NOT an NRA marker —
        # BMs 13-16 are unrelated special groups).
        target_map = build_target_map(client, user_id, status="Active",
                                      request_delay=request_delay)
        type_map = get_type_map(client, user_id, status="Active",
                                request_delay=request_delay)

        # NO select= on cMemberGens (documented field-dropping quirk).
        mg_records = client._fetch_all(
            "cMemberGens",
            where=(
                f"Account.AccountManager.Id eq '{user_id}' "
                f"and Account.Status eq 'Active'"
            ),
            page_size=100,
        )
        time.sleep(request_delay)

        products = {}
        late = 0
        for rec in mg_records:
            acct = rec.get("Account")
            key = (acct or {}).get("$key") if isinstance(acct, dict) else None
            prod = rec.get("MembershipProduct")
            # Members enrolled AFTER the month being reported are not part of
            # that month's base (Jen, 2026-07-30 — the reason she withholds
            # activation in the first week; this replaces that manual hold).
            if key and enrolled_after_period(rec, period_end):
                late += 1
                continue
            if key and prod is not None and str(prod).strip():
                products.setdefault(key, prod)  # RAW (nav dict or string) — name resolved at classify time
        if late:
            print(f"  [billables] {territory}: excluded {late} member(s) enrolled "
                  f"after {period_end} — not part of this month's base")

        # Classification basis = the membership PRODUCT (D2, 2026-07-16, decoded
        # from Jen's own BillableByBMDetailAllied PDF: Harbor Foods is Type
        # Corporate but product "Allied Corporate" → SHE counts it allied).
        # Live payloads carry MembershipProduct as a nav {$key} object, so names
        # resolve through a one-fetch products-entity lookup (cached on client).
        # The Allied-11 house partners remain OUT (separate ruling — unmapped
        # AlliedRelationsManager user, not a classification matter).
        product_names = getattr(client, "_product_name_cache", None)
        if product_names is None:
            product_names = {
                p.get("$key"): (p.get("Name") or "")
                for p in client._fetch_all("products", select="Name", page_size=200)
            }
            client._product_name_cache = product_names

        def _product_name(prod):
            if isinstance(prod, dict):
                return product_names.get(prod.get("$key"), "")
            return str(prod or "")

        def _is_allied(k):
            return "allied" in _product_name(products.get(k)).lower()

        product_ids = set(products)
        # RECEIPTS (2026-07-31): record every billable member with band —
        # the raw material for the transparency sheet. Record-only.
        from reports.membership_performance_tracker.logic import receipts_capture as _rc
        for _k in product_ids:
            _rc.record("billables", _k, {
                "territory": territory,
                "allied": _is_allied(_k),
                "band": target_map.get(_k, "Unknown"),
                "product": _product_name(products.get(_k))})
        if carriers_out is not None:
            # Stash for the no-invoice check (Jen's "that is a no-no") — free,
            # since these are already computed here.
            for _k in product_ids:
                carriers_out[_k] = territory
        hosp_ids = [k for k in product_ids if not _is_allied(k)]
        allied = sum(1 for k in product_ids if _is_allied(k))

        t, nt, unk = split_counts(target_map, hosp_ids)

        counts = {
            "hospitality":            len(hosp_ids),
            "allied":                 allied,
            "hospitality_target":     t,
            "hospitality_non_target": nt,
            "hospitality_unknown":    unk,
        }
        # A territory can have MULTIPLE mapped users (e.g. Majors/NRA =
        # MajorAccounts rep + the NRA house user, added 2026-07-13) — SUM
        # across users instead of letting the last user's pass overwrite.
        if territory in result:
            for k, v in counts.items():
                result[territory][k] += v
        else:
            result[territory] = counts

    return result


def yoy_delta(current: Dict[str, Dict[str, int]], prior: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
    """
    Compute year-over-year delta for each territory's billable counts.

    Args:
        current: This year's billables dict (from compute_billables_by_target).
        prior:   Same-month last year's billables dict.

    Returns:
        Dict keyed by territory: {"hospitality_delta": int, "allied_delta": int}
        Positive = gained accounts, negative = lost accounts.
        Missing territories in either year produce delta of None.
    """
    all_territories = set(current) | set(prior)
    deltas = {}
    for territory in all_territories:
        cur = current.get(territory, {})
        prv = prior.get(territory, {})
        deltas[territory] = {
            "hospitality_delta": (
                cur.get("hospitality") - prv.get("hospitality")
                if cur.get("hospitality") is not None and prv.get("hospitality") is not None
                else None
            ),
            "allied_delta": (
                cur.get("allied") - prv.get("allied")
                if cur.get("allied") is not None and prv.get("allied") is not None
                else None
            ),
        }
    return deltas
