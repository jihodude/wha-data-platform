"""
drops.py — Query dropped and closed-business accounts from SLX.

Feeds v4 Tracker:
    Data - Drops sheet          (one row per dropped account)
    Data - Closed Businesses    (one row per closed business)

DEFINITIONS (ratified 2026-07-14 — see docs/DECISIONS.md):
    Drop             = account went Inactive. ALL Statusreasons are counted and
                       CATEGORIZED (Closed / Sold / Non-Payment / Voluntary); the
                       ADMIN_REASONS (Admin / Retro-program) are EXCLUDED from the
                       counts. SUPERSEDED: the old 2-reason whitelist
                       ('Non-Payment'/'Sold' only), which undercounted 206 vs 450.
    Closed Business  = the physical business no longer exists (reported on its own
                       Data - Closed Businesses sheet).

DATA SOURCES (all confirmed live 2026-05-08):
    accounts                — account name, type, territory (via AccountManager.Id)
    AccountExtension        — Statusreason, Dateclosed (Dateclosed mostly unpopulated)
    history                 — 'Change to Status' records give us the actual drop date
                              (39,323 records confirmed; Dateclosed is unreliable)
    cRestProfiles           — Avgrangefteperloc (93% coverage) for employee count range
                              and Target classification for restaurants
    cMemberGens             — Rooms (reliable) for hotel Target classification;
                              Duesbillmonth for renewal month

TARGET CLASSIFICATION:
    Restaurant: parse Avgrangefteperloc range string — '10 to 19' or higher = Target
                Totalemployees is 97% null — do not use.
    Hotel:      Rooms >= 40 = Target (Jen 7/21, ruled 7/29; the 7/13 41+ reading is superseded)
    Allied:     always Non-Target

EMPLOYEE COUNT:
    Avgrangefteperloc → midpoint approximation via target._RANGE_MIDPOINTS (the
    single source of truth, imported from target.py — findings #11/#20). Do not
    re-declare the table here or it will drift.

DROP DATE SOURCE:
    AccountExtension.Dateclosed is mostly unpopulated — do not rely on it.
    Primary: query history entity for 'Change to Status' records on the account,
    find the most recent Active → Inactive transition, use that CreateDate.
    Fallback: AccountExtension.StatusDate — populated on virtually all records,
    represents when the Statusreason was recorded (may lag the actual drop by days
    or weeks if entered retroactively, but consistently available).

TRACKER OUTPUT FORMAT:
    See writer.DROPS_COLUMNS / the Data - Drops sheet for the authoritative column
    order. Beyond the historical fields (Account/Business info, Employee Count,
    Target Y/N, Renewal Year/Month, Drop Reason, Amount Billed, Drop Date) the
    sheet now also emits the user-facing Member ID and a Drop Category column
    (Closed / Sold / Non-Payment / Voluntary), which the gates check.

    Data - Closed Businesses columns (row 4 onward):
        Account ID | Account Name | Territory | Territory Manager | Business Type
        | Target (Y/N) | Was Member at Closure (Y/N) | Date Closed | Notes

TERRITORY NAME MAPPING:
    The v4 tracker uses different names for three territories:
        EastKing    → 'East King'
        SouthKing   → 'South King'
        NorthKing   → 'North King'
    All others match canonical names exactly.
    Use CANONICAL_TO_TRACKER dict below when writing to the tracker.
"""

import re
import time
import warnings
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple

from src.slx.client import SLXClient
from reports.membership_performance_tracker.logic.target import (
    _KNOWN_RANGES, _RANGE_MIDPOINTS, _TARGET_RANGES, TARGET_ROOMS_MIN,
    _normalize_band)


# ---------------------------------------------------------------------------
# Territory name translation (canonical → v4 tracker display name)
# ---------------------------------------------------------------------------

CANONICAL_TO_TRACKER = {
    "EastKing":    "East King",
    "SouthKing":   "South King",
    "NorthKing":   "North King",
    # All others are identical — kept here for completeness
    "Pierce":      "Pierce",
    "Snohomish":   "Snohomish",
    "Spokane/NE":  "Spokane/NE",
    "Southwest":   "Southwest",
    "TKP":         "TKP",
    "Southeast":   "Southeast",
    "NorthCentral":"NorthCentral",
    "Majors/NRA":  "Majors/NRA",
}

# ---------------------------------------------------------------------------
# Drop and closed-business reason code classification
# ---------------------------------------------------------------------------

CLOSED_REASONS = {"Out of Business", "COVID 19 – Permanently Closed", "Fire",
                  "Never Opened"}

# RATIFIED 2026-07-14 (Jiho: "more info > less"): drops count ALL status reasons,
# categorized. The CRM's own dropped-members report spans 19 reasons; our old
# 4-reason whitelist undercounted (206 vs 450). Admin/housekeeping reasons are
# EXCLUDED from counts but kept in the detail sheet (ratified 13:40).
ADMIN_REASONS = {"Old Record Cleanup", "New Lead", "New Record from a Closed/ Sold",
                 "New Record from a Closed/Sold",
                 # surfaced by the ne-Active status scope (pull #8, 2026-07-14):
                 # record hygiene + retro-program lifecycle, not member losses —
                 # without these the unknown-reason fallback counted them Voluntary
                 "Copied Record", "Duplicate Record", "Retro Final Distribution",
                 # annual-update housekeeping on chain sub-records (7/16; absent
                 # from their own drops export — 5 rows, one dated 2018)
                 "Per Annual Update",
                 # 2026-07-22 drops reconciliation (account-level vs the CRM
                 # No-Allieds export): never-was-a-member records cannot "drop" —
                 # they were leaking into Voluntary via the unknown-reason
                 # fallback. Record hygiene, not member losses.
                 "Never a Member", "Not a valid WRA Lead", "L I Account Change",
                 # further hygiene surfaced by the closed-vocabulary sweep
                 # (2026-07-22, live enumeration of every fallback reason):
                 "New Record from Import", "2024 List Clean Up",
                 "Member Under New Name", "Confirmed Open",
                 "No Reason Cleaning up Records and Required to put one in"}


# Known VOLUNTARY reasons — the closed vocabulary (2026-07-22). The old
# behavior counted ANY unrecognized string as Voluntary, which is how hygiene
# reasons ('Never a Member', 'New Record from Import', 'Confirmed Open') leaked
# into drop counts for weeks. Same cure as unclassified charge codes: classify
# every known string explicitly; truly-unknown strings WARN and count Voluntary
# (never silently — and never silently excluded either, a real loss must count).
VOLUNTARY_REASONS = {"No Answer", "No Benefit", "Budget", "No Hospitality Contact",
                     "New Focus", "No Response from Member", "Retired", "No Comment",
                     "Political", "Member Request", "Lost Lease", "No Business Gained",
                     "No Longer Dual WIIN Member", "Seattle Minimum Wage"}


# New-status capture for history "Change to Status" notes ("... Status: X")
_STATUS_NEW_RE = re.compile(r"Status:\s*([A-Za-z][A-Za-z ]*)")


# accounts.Status values that mean "retro refund only" — never a drop
# (Jen, 2026-07-30 recorded: "RRO is not a dropped"; they sit on her report
# "just as FYI"). The detail sheet KEEPS them — it is that FYI list — but the
# category must say so, or the sheet contradicts the counts beside it.
RRO_STATUSES = ("RRO", "RRO LNI Active")
RRO_CATEGORY = "RRO — not a drop (FYI)"


def _drop_category(reason: str, status: str = "") -> str:
    """Plain-words drop category for a status reason (closed vocabulary).

    `status` is accounts.Status. An RRO status overrides the reason entirely:
    the member did not drop, they converted, and the counts exclude them.
    """
    if str(status or "").strip() in RRO_STATUSES:
        return RRO_CATEGORY
    r = (reason or "").strip()
    if r in CLOSED_REASONS or r == "Closing":
        return "Closed"
    if r in ("Sold", "Selling"):
        return "Sold"
    if r == "Non-Payment":
        return "Non-Payment"
    if r in ADMIN_REASONS:
        return "Admin"
    if r in VOLUNTARY_REASONS or r == "":
        return "Voluntary"   # blank = real drop, reason not recorded
    import warnings
    warnings.warn(f"[drops] UNRECOGNIZED status reason {r!r} → counted Voluntary. "
                  f"Classify it (VOLUNTARY_REASONS / ADMIN_REASONS / CLOSED_REASONS).")
    return "Voluntary"

# ---------------------------------------------------------------------------
# Employee count range → midpoint approximation
# ---------------------------------------------------------------------------

# _RANGE_MIDPOINTS / _TARGET_RANGES / _KNOWN_RANGES / TARGET_ROOMS_MIN are the
# canonical classification tables — imported from target.py above (one source of
# truth, findings #11/#20). Do NOT re-declare them here.


def _parse_fte_range(raw: Optional[str]) -> Tuple[Optional[int], Optional[bool]]:
    """
    Parse Avgrangefteperloc string into (employee_count_approx, is_restaurant_target).

    Returns:
        (employee_count, is_target)
        employee_count: midpoint int, or None if unparseable
        is_target:      True if range implies >= 10 FTE, False if < 10, None if unknown
    """
    if not raw or not raw.strip():
        return None, None
    cleaned = _normalize_band(raw)
    if cleaned in _TARGET_RANGES:
        return _RANGE_MIDPOINTS.get(cleaned), True
    if cleaned in _KNOWN_RANGES:
        return _RANGE_MIDPOINTS.get(cleaned), False
    # Non-empty but UNRECOGNIZED band → Unknown (blank on the sheet), LOUDLY —
    # a silent False would misclassify a new/renamed CRM band as Non-Target (#11).
    warnings.warn(f"[drops] unrecognized FTE band {cleaned!r} → Unknown "
                  f"(add it to target._RANGE_MIDPOINTS if it is a real band)")
    return None, None


def _parse_slx_date(raw: Optional[str]) -> Optional[datetime]:
    """Convert SLX /Date(ms)/ timestamp to datetime, or None."""
    if not raw:
        return None
    m = re.search(r"/Date\((\d+)\)/", str(raw))
    if not m:
        return None
    return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)


def _get_drop_date(
    client: SLXClient,
    acct_id: str,
    status_date_raw: Optional[str] = None,
) -> Optional[datetime]:
    """
    Find the most recent Active → Inactive status change date for an account.

    Primary source: history audit log.
        Queries 'Change to Status' records, finds the most recent one where
        Notes contains 'Old Value: Active' (i.e. Active → Inactive transition).
        Coverage is partial — not all accounts have history records.

    Fallback: AccountExtension.StatusDate.
        Populated on virtually all records. Represents when Statusreason was
        set — may lag the actual drop by days if entered retroactively, but
        is consistently available and far better than None.

    Args:
        client:          Authenticated SLXClient.
        acct_id:         Account ID (from AccountExtension.Account.$key).
        status_date_raw: Raw StatusDate string from AccountExtension record
                         (e.g. '/Date(1551312000000)/').  Used as fallback.

    Returns:
        Datetime of most recent Active→Inactive transition, or StatusDate
        fallback, or None if neither is available.
    """
    where = f"AccountId eq '{acct_id}' and Description eq 'Change to Status'"
    records = client._fetch_all("history", where=where,
                                select="AccountId,CreateDate,Notes", page_size=50)

    best_date = None
    for rec in records:
        notes = rec.get("Notes") or ""
        # Any Active -> non-Active transition counts; most recent wins.
        # (2026-07-27 fix: the old literal match on 'Status: Inactive' made
        # Active->Closed flips INVISIBLE, so an ancient status blip outdated
        # the real membership end — 41 members billed into FY25/26 carried
        # 2012-2024 drop dates because of this.) Reverse transitions
        # (-> Active) never count.
        if "Old Value: Active" not in notes:
            continue
        m = _STATUS_NEW_RE.search(notes)
        if not m or m.group(1).strip() == "Active":
            continue
        dt = _parse_slx_date(rec.get("CreateDate"))
        if dt and (best_date is None or dt > best_date):
            best_date = dt

    # 2026-08-10 audit (152 counted drops vs live CRM): StatusDate is the
    # date staff ASSIGN to the drop and the field that drives the Crystal
    # drops report's own month buckets; the history log records when the
    # entry was TYPED. Staff bulk-process a class days later (18 members
    # staff-dated 11/30 were typed 12/3 — a month-boundary drift), and a
    # re-dropped member's latest flip can be missing from the log entirely
    # (El Ranchito: stale 2025 hit shadowed a correct 4/29/2026 StatusDate).
    # So: StatusDate FIRST; the history log only when StatusDate is empty.
    # Downstream plausibility guards (_file_month) still catch stale
    # StatusDates (the 41-stale-dates class) and file at the class close.
    status_dt = _parse_slx_date(status_date_raw)
    return status_dt if status_dt is not None else best_date


def _get_last_invoice_amount(client: SLXClient, acct_id: str) -> Optional[float]:
    """
    Get the most recent WRA dues invoice amount for an account from dlInvoiceHistoryHeader.
    Used as 'Amount Billed ($)' for the Drops sheet.

    Filters to Comp_code='WRA' + Invoice_Type='IN' so we don't pick up PAC local
    fees, MSC claims-program fees (CMP/Retro — never dues, Jen 7/21), or AD
    adjustments. Matches the canonical retention filter
    (reports/retention_detail/data.py).
    """
    def _most_recent(records):
        # A bill is a POSITIVE dues invoice. Credit notes are Invoice_Type='IN'
        # rows with a negative Net_invoice (the retention void pattern, third
        # sighting 2026-07-30): with no sign filter the credit — dated later —
        # always won, publishing Larry Gargett's drop as −$690, and a same-day
        # reversal (59'er Diner, ±340 on 2013-06-24) made the winner depend on
        # server row order. Filtering to > 0 fixes both at once.
        best = best_date = None
        for rec in records:
            amount = rec.get("Net_invoice")
            if amount is None or amount <= 0:
                continue
            dt = _parse_slx_date(rec.get("Invoice_Date"))
            if best_date is None or (dt and dt > best_date):
                best, best_date = amount, dt
        return best

    where = (
        f"Accountid eq '{acct_id}' "
        f"and Comp_code eq 'WRA' "
        f"and Invoice_Type eq 'IN'"
    )
    records = client._fetch_all(
        "dlInvoiceHistoryHeader", where=where,
        select="Accountid,Net_invoice,Invoice_Date", page_size=50
    )
    # WRA only. The 7/20 MSC "CMP Fee" fallback is REVERTED (Jen 7/21: CMP =
    # Claims Management Program fees, not dues — showing them as lost
    # membership revenue was wrong; a blank beats a wrong number). Accounts
    # with no WRA dues invoice report no lost-$.
    return _most_recent(records)


def _amount_billed(client: SLXClient, acct_id: str, product) -> Optional[float]:
    """What this member was being billed — the drop's lost dollars.

    The last POSITIVE WRA dues invoice is the primary source: it is literally
    the amount billed. The product price is the FALLBACK, for members who were
    never invoiced themselves (parent-billed children — the case the old
    dues-level-first ordering existed to protect; they still land here).

    ⚠️ ORDER REVERSED 2026-07-30 (was: dues level first, 7/27). Why: for
    lodging, products.Price is a PER-ROOM RATE, not a level — three different
    hotels published at exactly $15.50 ('WHA Lodging Dues (51+)') while Sun
    Mountain Lodge's actual last dues bill was $2,034. No price threshold can
    tell a rate from a level (real flat levels go down to $155), so the bill
    itself is the only honest witness. For flat-product members invoice ≈
    price, making this a near-no-op outside the bug class. Multiplying rate ×
    rooms-on-file was rejected: 15.5 × 113 = $1,751.50 ≠ the $2,034 billed —
    it fabricates a number instead of reading one.
    """
    amount = _get_last_invoice_amount(client, acct_id)
    if amount is not None:
        return amount
    return _dues_level(client, product)


def _dues_level(client: SLXClient, product) -> Optional[float]:
    """The account's "Dues Level" = its MembershipProduct's products.Price
    (verified live 7/16: El Sombrero product RD>1M → Price 1070.0 = the UI
    field = their drops export's `dues` column). One cached products fetch.

    ⚠️ Only true for FLAT products. Lodging/alliance products carry per-unit
    RATES in Price (15.5, 5.5, 3.0, 2.5) — see `_amount_billed`, which is why
    this is now the fallback, not the primary."""
    if not isinstance(product, dict):
        return None
    cache = getattr(client, "_product_price_cache", None)
    if cache is None:
        cache = {p.get("$key"): p.get("Price")
                 for p in client._fetch_all("products", select="Name,Price,Family",
                                            page_size=200)}
        client._product_price_cache = cache
    return cache.get(product.get("$key"))


def _get_renewal_info(client: SLXClient, acct_id: str):
    """
    Get renewal month/year, the user-facing MEMBER ID, the membership
    product nav (for dues-level resolution), and the WRA number — all riding
    ONE fetch.

    Returns:
        (renewal_year, renewal_month_name, member_id, product_nav, wra)

    The WRA number (dlInvoiceHistoryHeader.CustomerNo) is C3's bridge key
    (2026-08-12): it lets the Crystal overlay match a drop row to THIS member
    exactly, where name matching cannot separate two same-named members in
    one territory (Bob's Burgers & Brew ×2, NorthCentral). It rides the
    invoice fetch renewal-year already makes, so it costs nothing.
    """
    _MONTH_NAMES = {
        1: "January", 2: "February", 3: "March", 4: "April",
        5: "May", 6: "June", 7: "July", 8: "August",
        9: "September", 10: "October", 11: "November", 12: "December",
    }

    where = f"Account.Id eq '{acct_id}'"
    # NO select= — the cMemberGens select quirk silently dropped Membernum
    # (pull #4 shipped 0/206 member ids because of it). Fetch all fields.
    records = client._fetch_all(
        "cMemberGens", where=where, page_size=10
    )
    if not records:
        return None, None, None, None, None

    member_id = next((r.get("Membernum") for r in records if r.get("Membernum")), None)
    product = next((r.get("MembershipProduct") for r in records
                    if r.get("MembershipProduct")), None)
    # Scan for the first non-null Duesbillmonth across the (often duplicated,
    # Sage-sync) rows — same pattern as Membernum/MembershipProduct above.
    # records[0]-only (finding #15) blanked the renewal month for exactly the
    # duplicate-row accounts whose first row happens to carry a null bill month.
    bill_month = next((r.get("Duesbillmonth") for r in records if r.get("Duesbillmonth")), None)

    # Renewal year + the WRA number (C3) from one invoice fetch. Fetched even
    # when Duesbillmonth is blank: the WRA bridge matters most for exactly the
    # messy records, and a never-invoiced member simply yields wra=None.
    invoice_records = client._fetch_all(
        "dlInvoiceHistoryHeader", where=f"Accountid eq '{acct_id}'",
        select="Invoice_Date,CustomerNo", page_size=10
    )
    wra = next((r.get("CustomerNo") for r in invoice_records
                if r.get("CustomerNo")), None)
    renewal_year = None
    if invoice_records:
        dates = [_parse_slx_date(r.get("Invoice_Date")) for r in invoice_records]
        dates = [d for d in dates if d]
        if dates:
            renewal_year = max(dates).year

    if not bill_month:
        return None, None, member_id, product, wra

    try:
        bill_month = int(bill_month)
    except (ValueError, TypeError):
        return None, None, member_id, product, wra

    month_name = _MONTH_NAMES.get(bill_month)

    return renewal_year, month_name, member_id, product, wra


# ---------------------------------------------------------------------------
# Main public functions
# ---------------------------------------------------------------------------

def fetch_drops_and_closed(
    client: SLXClient,
    territory_user_map: Dict[str, str],
    rep_map: Dict[str, str],
    request_delay: float = 0.25,
    min_status_date: Optional["date"] = None,
) -> Tuple[List[Dict], List[Dict]]:
    """
    Fetch all dropped and closed-business accounts across all territories.

    Args:
        client:              Authenticated SLXClient.
        territory_user_map:  {slx_user_id: canonical_territory_name}
        rep_map:             {canonical_territory_name: rep_display_name}
                             Used to populate 'Territory Manager' column.
        request_delay:       Seconds between API calls (be polite to SLX).
        min_status_date:     Optional StatusDate floor (a datetime.date). When set,
                             the AccountExtension query is bounded by
                             `StatusDate ge @YYYY-MM-DD@`, so we stop pulling (and
                             sub-querying) every inactive account back to ~2001.
                             StatusDate lags the real drop date, so pass a floor a
                             few months before FY start (see engine.py) to be sure
                             a genuine in-window drop can't be excluded. The
                             aggregated counts are FY-windowed downstream regardless,
                             so this is a speed + detail-sheet cleanliness fix, not a
                             change to the numbers. Default None = no floor (fetch all).

    Returns:
        (drops, closed_businesses)

        drops: list of dicts matching Data - Drops columns:
            {
                "account_id": str,
                "account_name": str,
                "territory": str,          # tracker display name (e.g. 'East King')
                "territory_manager": str,
                "business_type": str,
                "employee_count": int|None,
                "is_target": str,          # 'Y' or 'N' or '?'
                "renewal_year": int|None,
                "renewal_month": str|None,
                "drop_reason": str,
                "amount_billed": float|None,
                "drop_date": str|None,     # ISO date string YYYY-MM-DD
            }

        closed_businesses: list of dicts matching Data - Closed Businesses columns:
            {
                "account_id": str,
                "account_name": str,
                "territory": str,
                "territory_manager": str,
                "business_type": str,
                "is_target": str,
                "was_member_at_closure": str,  # 'Y' (always — they were inactive members)
                "date_closed": str|None,
                "notes": str,
            }
    """
    drops = []
    closed = []

    for user_id, territory in territory_user_map.items():
        if not territory:
            continue

        tracker_territory = CANONICAL_TO_TRACKER.get(territory, territory)
        rep_name = rep_map.get(territory, "")

        # Fetch all dropped accounts with a Statusreason for this territory.
        # Choice: query AccountExtension filtered by account manager via Account.AccountManager.Id
        # ALL status reasons (ratified 2026-07-14) — categorized client-side;
        # reason-less rows are excluded (no drop signal).
        # Status scope is ne 'Active', NOT eq 'Inactive': dropped members land in
        # several statuses (OOB accounts are 97% 'Closed'; Sold split Closed/RRO —
        # SLX probe 2026-07-14 after the gate matched 1/167 OOB).
        where = (
            f"Account.AccountManager.Id eq '{user_id}' "
            f"and Account.Status ne 'Active' "
            f"and Statusreason ne null"
        )
        # Bound by StatusDate so we don't pull (and sub-query) every inactive
        # account back to ~2001. StatusDate lags the real drop date, so the caller
        # passes a floor a few months before FY start; aggregation is FY-windowed
        # downstream, so this can't change the counts — only the pull size.
        if min_status_date is not None:
            where += f" and StatusDate ge @{min_status_date.isoformat()}@"
        # Note: do NOT pass select= here — AccountExtension drops Account.$key
        # when a select clause is used. Fetch all fields; Account.$key is always present.
        records = client._fetch_all(
            "AccountExtension",
            where=where,
            page_size=200,
        )
        time.sleep(request_delay)

        # Membership filter: their "dropped members" report carries a member ID
        # on every row — an account only counts as a drop if it has a membership
        # record. Without this, prospects flagged OOB/No Answer flood the counts
        # (SLX holds 1,944 OOB accounts since 2025-07; their report shows 167).
        # One bulk cMemberGens fetch per territory; NO select= (field-drop quirk),
        # NO status constraint (dropped members' accounts aren't Active).
        member_rows = client._fetch_all(
            "cMemberGens",
            where=f"Account.AccountManager.Id eq '{user_id}'",
            page_size=200,
        )
        member_keys = set()
        for mr in member_rows:
            macct = mr.get("Account")
            mkey = (macct or {}).get("$key") if isinstance(macct, dict) else None
            if mkey:
                member_keys.add(mkey)
        time.sleep(request_delay)

        # Progress: the enrichment loop runs 60-90 min with ~4 sub-queries per
        # account and no stage output — pull #7 was killed healthy because this
        # was a black box. Print every 50 enriched accounts.
        candidates = sum(
            1 for rec in records
            if ((rec.get("Account") or {}).get("$key") or None) in member_keys
        )
        enriched = 0

        for rec in records:
            acct = rec.get("Account") or {}
            acct_id = acct.get("$key")
            # accounts.Status rides on the nested Account object — needed so the
            # detail row can mark RRO conversions as the FYI rows they are.
            acct_status = str(acct.get("Status") or "")
            if not acct_id:
                continue
            if acct_id not in member_keys:
                continue  # no membership record → prospect noise, not a drop
            enriched += 1
            if enriched % 50 == 0:
                print(f"  [drops] {enriched}/{candidates} {territory}", flush=True)

            reason = rec.get("Statusreason", "")
            # StatusDate is used as drop-date fallback when history has no records
            status_date_raw = rec.get("StatusDate")

            # AccountExtension doesn't carry AccountName or Type — fetch from accounts
            acct_records = client._fetch_all(
                "accounts",
                where=f"Id eq '{acct_id}'",
                select="Id,AccountName,Type",
                page_size=1,
            )
            acct_name = acct_records[0].get("AccountName", "") if acct_records else ""
            biz_type = acct_records[0].get("Type", "") if acct_records else ""
            time.sleep(request_delay)

            # --- Employee count + Target classification ---
            # Hotels: use Rooms field (reliable)
            # Restaurants: use Avgrangefteperloc (93% coverage)
            employee_count = None
            is_target = "?"

            if biz_type == "Allied":
                is_target = "N"
            elif biz_type in ("Hotel", "Lodging"):
                rooms_records = client._fetch_all(
                    "cMemberGens",
                    where=f"Account.Id eq '{acct_id}'",
                    select="Rooms",
                    page_size=5,
                )
                if rooms_records:
                    rooms = rooms_records[0].get("Rooms")
                    if rooms is not None:
                        employee_count = rooms  # rooms used as proxy in hotel context
                        is_target = "Y" if rooms >= TARGET_ROOMS_MIN else "N"  # 40+ (Jen 7/21)
                time.sleep(request_delay)
            else:
                # Restaurant or other hospitality type
                fte_records = client._fetch_all(
                    "cRestProfiles",
                    where=f"Account.Id eq '{acct_id}'",
                    select="Avgrangefteperloc",
                    page_size=5,
                )
                if fte_records:
                    raw_range = fte_records[0].get("Avgrangefteperloc")
                    emp, target_flag = _parse_fte_range(raw_range)
                    employee_count = emp
                    if target_flag is True:
                        is_target = "Y"
                    elif target_flag is False:
                        is_target = "N"
                time.sleep(request_delay)

            # --- Drop date: history audit log first, StatusDate as fallback ---
            drop_date_dt = _get_drop_date(client, acct_id, status_date_raw)
            drop_date_str = drop_date_dt.strftime("%Y-%m-%d") if drop_date_dt else None
            time.sleep(request_delay)

            # 2026-07-27 fix: closed-reason members previously went ONLY to
            # closed_detail — a member lost to "Out of Business" never produced
            # a drop row, so the loss reached drop counts only via the
            # closure-union (which keys on the business-death date, often years
            # earlier). EVERY member loss now emits a drop row; closures
            # ADDITIONALLY emit their closed-business row. 5 members billed
            # into FY26 were invisible to drops because of the old split.
            # --- Renewal info ---
            renewal_year, renewal_month, member_id, product, wra = _get_renewal_info(client, acct_id)
            time.sleep(request_delay)

            # --- Amount billed ---
            # The last positive dues invoice IS the bill; product price only
            # for the never-invoiced (parent-billed children). See
            # _amount_billed for the 2026-07-30 ordering reversal.
            amount_billed = _amount_billed(client, acct_id, product)
            time.sleep(request_delay)

            drops.append({
                "account_id":       acct_id,
                "member_id":        member_id,
                "wra":              wra,
                "drop_category":    _drop_category(reason, acct_status),
                "account_status":    acct_status,
                "account_name":     acct_name,
                "territory":        tracker_territory,
                "territory_manager": rep_name,
                "business_type":    biz_type,
                "employee_count":   employee_count,
                "is_target":        is_target,
                "renewal_year":     renewal_year,
                "renewal_month":    renewal_month,
                "drop_reason":      reason,
                "amount_billed":    amount_billed,
                "drop_date":        drop_date_str,
            })

            if reason in CLOSED_REASONS:
                closed.append({
                    "account_id":           acct_id,
                    "account_name":         acct_name,
                    "territory":            tracker_territory,
                    "territory_manager":    rep_name,
                    "business_type":        biz_type,
                    "is_target":            is_target,
                    "was_member_at_closure": "Y",  # by definition — they were inactive members
                    "date_closed":          drop_date_str,
                    "notes":                reason,  # reason code as notes; humans can enrich
                })

    return drops, closed
