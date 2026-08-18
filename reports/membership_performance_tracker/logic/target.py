"""
target.py — Target / Non-Target account classification for WHA v4 metrics.

Every metric in the v4 tracker is split into Target and Non-Target.
This module builds a territory-wide classification map and provides
helpers to split any set of account IDs.

DEFINITIONS:
    Target       = hospitality accounts meeting WHA's size threshold
                   Restaurant:  Avgrangefteperloc range >= '10 to 19' FTE
                   Hotel/Lodging: Rooms >= 40  (Jen 7/21, ruled 7/29; the 7/13 '41+' is superseded)
                   Corporate:   always Target — billing entity for a multi-location
                                chain; system aggregates FTE across all child locations,
                                so corporate-level FTE is always >= 10 by definition
                                (confirmed from Sheryl Jackson's notes, 2026-05-08)
    Non-Target   = below threshold + Allied members
    Unknown      = hospitality account but size data missing (7% restaurants,
                   rare for hotels)

WHY NOT PER-ACCOUNT QUERIES:
    Classifying 200+ accounts one-by-one would require 200+ API calls.
    Instead, build_target_map() fetches 3 territory-wide lookups (accounts,
    cMemberGens, cRestProfiles) and classifies everything in memory.
    Total: 3 API calls per territory regardless of account count.

ACCOUNT TYPE VALUES (confirmed from SLX live data):
    'Hotel', 'Lodging' → use Rooms from cMemberGens (Target if rooms >= 40;
    Jennifer confirmed 2026-07-21: 40+ = Target, 39 and under = Non-Target)
    'Allied'           → always Non-Target
    'Corporate'        → treated like restaurant (falls through to Avgrangefteperloc check);
                         if no cRestProfiles record on the corporate parent → Unknown.
                         TODO: confirm whether SLX stores aggregate FTE on corporate parent
                         or whether we need to sum child cRestProfiles records.
    All other types    → treat as restaurant, use Avgrangefteperloc

FTE RANGE COVERAGE:
    Avgrangefteperloc: ~93% of restaurant records populated.
    Totalemployees:    99% null — do NOT use (confirmed 2026-05-08).

Usage:
    from reports.membership_performance_tracker.logic.target import build_target_map, classify

    target_map = build_target_map(client, user_id)
    # target_map == {"A6UJ9A000SK8": "Non-Target", "A6UJ9A000S2Z": "Target", ...}

    label = classify(target_map, account_id)  # "Target" | "Non-Target" | "Unknown"

    # Split a list of account IDs into counts:
    t, nt, unk = split_counts(target_map, account_ids)
"""

import re
import time
import warnings
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from src.slx.client import SLXClient, fetch_by_id_batches


# ---------------------------------------------------------------------------
# New-member enrollment cohort — the CANONICAL SData filter, shared by
# revenue.py + new_members.py so a ratified change is made in exactly ONE place.
# (It was pasted verbatim 4×; the 2026-07-16 boundary fix had to be applied to
# all four — the exact drift this consolidation prevents.)
# ---------------------------------------------------------------------------

# 2026-07-30 (Jen, recorded): a dropped member who reinstates after this gap
# is "a new member. That exact same member." — and on such rejoins the ENROLL
# DATE IS REWRITTEN by the admin (old one preserved in a note), which is why
# the EnrolledDate cohort below needs no rejoin filter of its own. The exact
# window is Jen's homework ("might be 60 [days]… I believe it's six months");
# when she confirms, change THIS constant and nothing else.
REJOIN_NEW_MEMBER_MONTHS = 6


def new_member_cohort_where(user_id: str, start_str: str, end_date) -> str:
    """Ratified new-member enrollment cohort filter (one source of truth):
      - NO current-status filter (2026-07-15): a March sale is a sale even if the
        member later dropped; 'Status eq Active' retroactively erased since-dropped
        enrollees (CRM report Mar=22, we showed 18).
      - EXCLUSIVE next-day end boundary (2026-07-16): EnrolledDate carries midnight-
        PACIFIC (07:00Z), so 'le @last-day@' drops last-day-of-month joiners (the 4
        missing 3/31 members). Hence 'lt @end+1day@'.
      - Exclude reinstatements: Salescode '510' OR ReinstatedDate set. NULL-safe —
        'ne 510' alone would drop the NULL-salescode majority.
    """
    end_next = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")
    return (
        f"Account.AccountManager.Id eq '{user_id}' "
        f"and EnrolledDate ge @{start_str}@ "
        f"and EnrolledDate lt @{end_next}@ "
        f"and (Salescode ne '510' or Salescode eq null) "
        f"and ReinstatedDate eq null"
    )


# ---------------------------------------------------------------------------
# Classification constants (shared with drops.py)
# ---------------------------------------------------------------------------

HOTEL_TYPES = {"Hotel", "Lodging"}

# Food-service account types — WHA's own taxonomy per Suzanne's
# `BillablesbyTerritorynoAllied_..._2026_03_24` report (2026-06-04). Used by
# the location-penetration metric to whitelist what counts as a restaurant
# location. Types not in this set (Grocery, Non-Commercial, Bakery, ...) and
# Corporate (a billing entity, see _count_target_locations) are excluded from
# both numerator and denominator of restaurant penetration. Hotel/Lodging
# count separately under HOTEL_TYPES.
FOOD_SERVICE_TYPES = {"Restaurant", "Catering", "Recreational", "Concession"}

# PENETRATION restaurant scope (ratified 2026-07-14, "A"): the CRM penetration
# report — the number the team trusts — counts Type='Restaurant' ONLY (verified:
# 3,331/3,331 of its actives). Catering/Recreational/Concession members remain
# fully counted in billables/retention/new-sales; this ONLY scopes the
# restaurant-% market. (WHA's category memo says 4 types — their sources
# conflict; the report's convention wins per the truth doctrine. One-line
# revert if the team ever ratifies the broader view.)
PENETRATION_RESTAURANT_TYPES = {"Restaurant"}

# Hotel/Lodging Target threshold (rooms). **40+** — confirmed by Jennifer
# 2026-07-21 and ruled by Jiho 2026-07-29 ("it's 40 or higher"); the earlier
# 41+ reading is superseded. One named constant, shared with drops.py.
TARGET_ROOMS_MIN = 40

# Lodging PENETRATION market universe = the Crystal report's subtype in-list
# (ADOPTED 2026-07-19, Jiho; derived empirically from all 782 accounts in the
# raw "Penetration Lodging by County" Crystal export). A 40+-space RV park is
# Target-SIZED but not the hotel MARKET. Scope: penetration only — billables
# T/NT stays rooms-based (7/13 rule).
LODGING_MARKET_SUBTYPES = {
    "Full Service Lodging", "Limited Service Lodging", "Economy Service Lodging",
    "Extended Stay", "Resort", "Gaming",
}
# Known non-market lodging subtypes (verified as exactly what Crystal drops;
# 'Bed & Breakfast' confirmed absent from all 782 Crystal-listed accounts).
# A subtype in NEITHER set is a new/renamed CRM subtype → warn loudly.
LODGING_NON_MARKET_SUBTYPES = {
    "RV Park or Campground", "Vacation Rental", "Military Housing", "Construction",
    "Bed & Breakfast", "Apartments",
}

# Avgrangefteperloc bands → midpoint. This is EVERY recognized band; its keys are
# the "known" universe. Canonical home — drops.py imports these (one source of
# truth, findings #11/#20).
_RANGE_MIDPOINTS = {
    "1 to 4":         2,
    "5 to 9":         7,
    "10 to 19":       14,
    "20 to 49":       34,
    "50 to 99":       74,
    "100 to 249":     174,
    "250 to 499":     374,
    "500 to 999":     749,
    "1,000 to 4,999": 2999,
    "1000 to 4999":   2999,
    "5000 to 9999":   7499,
}

# Bands that qualify a restaurant as Target (>= 10 FTE).
_TARGET_RANGES = {
    "10 to 19", "20 to 49", "50 to 99", "100 to 249",
    "250 to 499", "500 to 999", "1,000 to 4,999",
    "1000 to 4999", "5000 to 9999",
}

# Every band we recognize (Target ∪ below-threshold). A non-empty band OUTSIDE
# this set is a NEW/renamed CRM band → classify Unknown + warn, never a silent
# Non-Target that hides the data-quality signal (finding #11).
_KNOWN_RANGES = set(_RANGE_MIDPOINTS)

_DIGIT_HYPHEN = re.compile(r"(?<=\d)\s*-\s*(?=\d)")


def _normalize_band(raw: str) -> str:
    """Canonicalize an Avgrangefteperloc string before table lookup.

    The 2026-07-18 live pull surfaced 1,198 profiles whose bands are the SAME
    ranges in variant FORMATS — hyphen forms ('10-19'), comma forms
    ('1,000-4,999'), double spaces ('10  to 19') — import drift, not new bands.
    Pre-guard these silently classified Non-Target (745 of them target-sized).
    Rules: strip, drop commas, collapse whitespace, digit-hyphen-digit → ' to '.
    """
    s = " ".join(raw.replace(",", "").split())
    return _DIGIT_HYPHEN.sub(" to ", s)

TARGET     = "Target"
NON_TARGET = "Non-Target"
UNKNOWN    = "Unknown"


# ---------------------------------------------------------------------------
# Core classification logic
# ---------------------------------------------------------------------------

def _classify_one(
    acct_type: Optional[str],
    rooms: Optional[float],
    fte_range: Optional[str],
) -> str:
    """
    Classify a single account given its type and size data.

    Args:
        acct_type: accounts.Type value (e.g. 'Hotel', 'Allied', 'Restaurant').
        rooms:     cMemberGens.Rooms (for hotel/lodging accounts).
        fte_range: cRestProfiles.Avgrangefteperloc range string for restaurants.

    Returns:
        "Target", "Non-Target", or "Unknown".
    """
    if not acct_type:
        return UNKNOWN

    if acct_type == "Allied":
        return NON_TARGET

    if acct_type in HOTEL_TYPES:
        if rooms is None:
            return UNKNOWN
        return TARGET if rooms >= TARGET_ROOMS_MIN else NON_TARGET  # 40+ (2026-07-21)

    # Restaurant or other hospitality type — use FTE range
    if not fte_range or not fte_range.strip():
        return UNKNOWN
    fr = _normalize_band(fte_range)
    if fr in _TARGET_RANGES:
        return TARGET
    if fr in _KNOWN_RANGES:
        return NON_TARGET
    # Non-empty but UNRECOGNIZED (new/renamed CRM band) → Unknown, LOUDLY, so a
    # silent Non-Target never hides a data-quality signal (finding #11).
    warnings.warn(f"[target] unrecognized FTE band {fr!r} → Unknown "
                  f"(add it to _RANGE_MIDPOINTS if it is a real band)")
    return UNKNOWN


# ---------------------------------------------------------------------------
# Territory-wide map builder
# ---------------------------------------------------------------------------

def build_target_map(
    client: SLXClient,
    account_manager_id: str,
    status: Optional[str] = None,
    request_delay: float = 0.15,
) -> Dict[str, str]:
    """
    Build a {account_id: classification} map for all accounts in a territory.

    Uses 3 territory-wide API calls (not per-account):
        1. accounts         → {account_id: type}
        2. cMemberGens      → {account_id: rooms}
        3. cRestProfiles    → {account_id: fte_range}

    Session-level caching:
        Stashes the result on `client._target_map_cache[(user_id, status)]`.
        Subsequent calls with the same (user_id, status) tuple return the cached
        map instantly — zero SLX calls. The cache lives for the lifetime of the
        SLXClient instance (one run). This is the single biggest efficiency win
        in the pipeline — without it, a full engine run rebuilds the same map
        ~15 times per territory across billables, retention, revenue, new_members,
        and drops, costing ~495 redundant SLX queries.

    Args:
        client:             Authenticated SLXClient.
        account_manager_id: SLX user ID for the territory.
        status:             Optional Status filter ('Active', 'Inactive', or None for both).
                            Use None when classifying retention/new-member accounts that
                            may have gone inactive after billing.
        request_delay:      Seconds between API calls.

    Returns:
        Dict mapping account_id (str) -> "Target" | "Non-Target" | "Unknown".
        All accounts in the territory (matching status filter) are included.
    """
    # Check session-level cache first
    cache_key = (account_manager_id, status)
    cache = getattr(client, "_target_map_cache", None)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    # --- Query 1: accounts — get all account IDs + types ---
    where_accts = f"AccountManager.Id eq '{account_manager_id}'"
    if status:
        where_accts += f" and Status eq '{status}'"

    acct_records = client._fetch_all(
        "accounts",
        where=where_accts,
        select="Id,Type,SubType",
        page_size=200,
    )
    time.sleep(request_delay)

    # Build type + subtype lookups: {account_id: type}, {account_id: subtype}
    # (subtype feeds the lodging penetration-market filter, 2026-07-19)
    type_map: Dict[str, str] = {}
    subtype_map: Dict[str, str] = {}
    for r in acct_records:
        acct_id = r.get("$key")
        if acct_id:
            type_map[acct_id] = r.get("Type") or ""
            subtype_map[acct_id] = (r.get("SubType") or "").strip()
    sub_cache = getattr(client, "_subtype_map_cache", None)
    if sub_cache is None:
        sub_cache = {}
        try:
            client._subtype_map_cache = sub_cache
        except AttributeError:
            pass
    sub_cache[cache_key] = subtype_map

    if not type_map:
        return {}

    # --- Query 2: cMemberGens — rooms for hotel accounts ---
    # Fetch territory-wide; extract account ID from nested Account object.
    # Note: no Status filter here — a hotel that went inactive after billing
    # is still in cMemberGens and we still need its room count.
    # Note: NO select= here — using select= with cross-entity join fields
    # on SLX SData can drop Account.$key from the response. Fetch all fields.
    where_mg = f"Account.AccountManager.Id eq '{account_manager_id}'"
    mg_records = client._fetch_all(
        "cMemberGens",
        where=where_mg,
        page_size=200,
    )
    time.sleep(request_delay)

    rooms_map: Dict[str, Optional[float]] = {}
    for r in mg_records:
        acct = r.get("Account") or {}
        acct_id = acct.get("$key")
        if acct_id:
            rooms = r.get("Rooms")
            # Only store if hotel type (no point storing rooms for restaurants).
            # PREFER NON-NULL across duplicate rows (2026-07-13): accounts can
            # have 2+ cMemberGens rows (Sage-sync duplicate pattern, same as
            # retention) and last-row-wins let a trailing null wipe a real room
            # count — misclassifying the hotel as Unknown → dropped from
            # penetration. Suspected mechanism behind the 276-hotel gap vs the
            # CRM report; morning check (fetch_hotel_rooms_check.py) confirms.
            if type_map.get(acct_id, "") in HOTEL_TYPES:
                if rooms is not None or acct_id not in rooms_map:
                    rooms_map[acct_id] = rooms

    # --- Query 3: cRestProfiles — FTE range for restaurant accounts ---
    # Note: NO select= for same reason as cMemberGens above.
    where_rp = f"Account.AccountManager.Id eq '{account_manager_id}'"
    rp_records = client._fetch_all(
        "cRestProfiles",
        where=where_rp,
        page_size=200,
    )
    time.sleep(request_delay)

    fte_map: Dict[str, Optional[str]] = {}
    for r in rp_records:
        acct = r.get("Account") or {}
        acct_id = acct.get("$key")
        if acct_id:
            fte = r.get("Avgrangefteperloc")
            # Prefer non-null across duplicate rows — same rationale as rooms_map
            # above (a trailing null cRestProfiles row must not wipe a real FTE
            # band; suspected mechanism behind FTE-blank restaurants vs the CRM).
            if (fte or "").strip() or acct_id not in fte_map:
                fte_map[acct_id] = fte

    # --- Backfill missing size data by account-Id batches (2026-07-14) ---
    # PROVEN live: the per-territory bulk queries above UNDER-FETCH — the
    # shortfall scales with territory size (Southeast, one page, was exact),
    # while per-account-Id fetches are complete (782/782 hotel rooms,
    # 4,907/4,910 restaurant FTE bands, verified against the CRM reports).
    # So re-fetch ONLY the accounts still missing values, in Id-batches:
    # a few extra queries per territory buys complete classification.
    def _backfill(entity: str, field: str, missing_ids, store) -> None:
        for r in fetch_by_id_batches(
                client, entity, missing_ids, page_size=100, request_delay=request_delay):
            acct = r.get("Account") or {}
            aid = acct.get("$key")
            if not aid:
                continue
            v = r.get(field)
            has_v = v is not None and (not isinstance(v, str) or v.strip())
            cur = store.get(aid)
            cur_empty = cur is None or (isinstance(cur, str) and not cur.strip())
            if has_v and cur_empty:
                store[aid] = v

    missing_rooms = [a for a, t in type_map.items()
                     if t in HOTEL_TYPES and rooms_map.get(a) is None]
    if missing_rooms:
        _backfill("cMemberGens", "Rooms", missing_rooms, rooms_map)

    missing_fte = [a for a, t in type_map.items()
                   if t not in HOTEL_TYPES and t != "Allied"
                   and not (fte_map.get(a) or "").strip()]
    if missing_fte:
        _backfill("cRestProfiles", "Avgrangefteperloc", missing_fte, fte_map)

    # --- Classify every account ---
    result: Dict[str, str] = {}
    for acct_id, acct_type in type_map.items():
        rooms     = rooms_map.get(acct_id)
        fte_range = fte_map.get(acct_id)
        result[acct_id] = _classify_one(acct_type, rooms, fte_range)

    # Stash in session cache so subsequent calls skip all 3 SLX queries
    if cache is None:
        cache = {}
        try:
            client._target_map_cache = cache
        except AttributeError:
            # Some clients may have __slots__ — silently skip caching in that case
            return result
    cache[cache_key] = result

    # Also stash the type map under the same key — penetration-by-segment needs
    # account types to split Restaurant vs Lodging, and this avoids re-querying.
    type_cache = getattr(client, "_type_map_cache", None)
    if type_cache is None:
        type_cache = {}
        try:
            client._type_map_cache = type_cache
        except AttributeError:
            pass
    if type_cache is not None:
        type_cache[cache_key] = type_map

    return result


def get_type_map(
    client: SLXClient,
    account_manager_id: str,
    status: Optional[str] = None,
    request_delay: float = 0.15,
) -> Dict[str, str]:
    """
    Return {account_id: type_string} for a territory, building the target map
    first if needed (which caches the type map as a side effect).

    Used by penetration-by-segment to classify accounts as Restaurant vs Lodging.
    """
    cache_key = (account_manager_id, status)
    type_cache = getattr(client, "_type_map_cache", None)
    if type_cache is not None and cache_key in type_cache:
        return type_cache[cache_key]
    # Build the target map (populates the type cache), then return it
    build_target_map(client, account_manager_id, status=status, request_delay=request_delay)
    return getattr(client, "_type_map_cache", {}).get(cache_key, {})


def get_subtype_map(
    client: SLXClient,
    account_manager_id: str,
    status: Optional[str] = None,
    request_delay: float = 0.15,
) -> Dict[str, str]:
    """{account_id: subtype} for a territory (built/cached alongside the target
    map). Feeds the lodging penetration-market subtype filter (2026-07-19)."""
    cache_key = (account_manager_id, status)
    sub_cache = getattr(client, "_subtype_map_cache", None)
    if sub_cache is not None and cache_key in sub_cache:
        return sub_cache[cache_key]
    build_target_map(client, account_manager_id, status=status, request_delay=request_delay)
    return getattr(client, "_subtype_map_cache", {}).get(cache_key, {})


# ---------------------------------------------------------------------------
# Helpers for callers
# ---------------------------------------------------------------------------

def classify(target_map: Dict[str, str], account_id: str) -> str:
    """
    Look up an account's classification from a pre-built target map.

    Returns "Unknown" for account IDs not in the map (e.g. accounts from
    another territory, or accounts created after the map was built).
    """
    return target_map.get(account_id, UNKNOWN)


def split_counts(
    target_map: Dict[str, str],
    account_ids: List[str],
) -> Tuple[int, int, int]:
    """
    Split a list of account IDs into (target_count, non_target_count, unknown_count).

    Args:
        target_map:  Output of build_target_map().
        account_ids: List of account IDs to classify and count.

    Returns:
        (target, non_target, unknown) integer tuple.
    """
    t = nt = unk = 0
    for aid in account_ids:
        label = target_map.get(aid, UNKNOWN)
        if label == TARGET:
            t += 1
        elif label == NON_TARGET:
            nt += 1
        else:
            unk += 1
    return t, nt, unk


def split_amounts(
    target_map: Dict[str, str],
    account_amounts: Dict[str, float],
) -> Tuple[float, float, float]:
    """
    Split {account_id: dollar_amount} into (target_total, non_target_total, unknown_total).

    Args:
        target_map:      Output of build_target_map().
        account_amounts: Dict mapping account_id -> dollar amount.

    Returns:
        (target_sum, non_target_sum, unknown_sum) float tuple.
    """
    t = nt = unk = 0.0
    for aid, amount in account_amounts.items():
        label = target_map.get(aid, UNKNOWN)
        if label == TARGET:
            t += (amount or 0.0)
        elif label == NON_TARGET:
            nt += (amount or 0.0)
        else:
            unk += (amount or 0.0)
    return t, nt, unk
