"""
retention.py — Compute member retention rates per territory per bill month.

Feeds Scoreboard:
    CEO Summary rows 29-39: monthly retention % per territory
    Month-by-Month col G: Ret %

Definition:
    Retention % = accounts that paid dues / accounts billed (with invoices issued)
    Retention string = "{paid}/{billed}" for display

DATA SOURCE (confirmed 2026-05-01):
    dlInvoiceHistoryHeader — the current, authoritative invoicing entity.
    - Account.Id join CONFIRMED WORKING (cross-entity join supported)
    - Account.AccountManager.Id DOUBLE-JOIN CONFIRMED WORKING (territory filter)
    - Comment field = dues bill month (integer string, e.g. "3" = March)
    - Balance field semantics:
        0.0       = PAID (dues have been received)
        > 0       = OUTSTANDING (invoice sent, not yet paid)
        None/null = UNCLEAR (some records lack balance; may be legacy import artifacts)
    - Invoice_Date = date invoice/notice was sent (typically M-1 for first notice)

BILLING CYCLE (from SOP):
    Each account has a fixed dues bill month (cMemberGens.Duesbillmonth, int 1-12).
    Billing notices:
        1st notice: M-1 (one month before due) — this is when Invoice_Date is set
        2nd notice: M   (the due month)
        3rd notice: M+1 (one month after due)
    ITD runs after M+1: moves unpaid accounts from Active → Inactive.

FISCAL YEAR COVERAGE:
    For WHA FY2025-26 (Oct 2025 – Sep 2026):
    - November billers (Comment='11') → Invoice_Date ~Oct 2025
    - March billers    (Comment='3')  → Invoice_Date ~Feb 2026
    Safe window: @2025-07-01@ through @2026-09-30@ covers all bill months.

DUPLICATE RECORDS:
    Some accounts have two rows for the same invoice (same invoice_number):
    - One with Balance=0.0 (payment received)
    - One with Balance=None (original invoice record)
    This is a known Sage/SLX sync artifact. We deduplicate by AccountId
    when computing unique paid/billed counts.

BUG FIXED (2026-05-01):
    Old approach used cMemberGens Active/Inactive counts as a retention proxy.
    Fatal flaw: Salescode ne 'NRA' excluded NULL-salescode accounts in SData
    (SQL NULL != 'X' = NULL, not TRUE). Also, Active/Inactive counts don't
    reliably reflect billing state.
    New approach: dlInvoiceHistoryHeader gives actual invoice + payment status.

Usage:
    from src.slx.client import SLXClient
    from reports.membership_performance_tracker.logic.retention import compute_retention

    client = SLXClient(username, password)
    result = compute_retention(client, territory_user_map, bill_month=3)
    # result["Pierce"] == {"pct": 91.7, "paid": 22, "billed": 24, "string": "22/24"}
"""

import time
import warnings
from datetime import date
import calendar as _cal
import datetime as _dt
import re as _re
from typing import Dict, Optional, Tuple

from src.slx.client import SLXClient, fetch_by_id_batches
from reports.membership_performance_tracker.logic.target import build_target_map, TARGET, NON_TARGET, UNKNOWN


# Single source of truth for the retention target (a FRACTION). Finding #16: the
# status classifier, the alerts, and two console displays each hardcoded 0.92 and
# ignored the admin-configurable Retention Goal — so lowering a territory's goal
# changed nothing. This constant is the FALLBACK; per-territory admin goals win.
DEFAULT_RETENTION_GOAL = 0.92


def retention_goal_for(goal_retention: Dict, territory: str) -> float:
    """A territory's retention target (fraction, e.g. 0.92): its admin Retention
    Goal if set (constant across months per territory), else DEFAULT_RETENTION_GOAL."""
    for v in (goal_retention.get(territory) or {}).values():
        if v is not None:
            return v
    return DEFAULT_RETENTION_GOAL


def _bill_month_date_window(bill_month: int, fiscal_year_start: int) -> Tuple[str, str]:
    """
    Return a tight (start_date_str, end_date_str) covering only the dues invoices
    for a specific bill month in a given fiscal year.

    WHA billing cycle — SOURCED from Jennifer's call 2026-07-22 (see
    reports/dues_analysis/analysis/2026-07-22-call-jennifer-hard-facts.md §1,
    transcript [J 1:40-2:15]). A bill month gets exactly THREE notices:

        1st notice = M-1  (the month BEFORE the bill month)
        2nd notice = M    (the bill month itself)
        3rd notice = M+1  (the month after)

    so the pay window CLOSES at the end of M+1 (~90 days). The MA then runs the
    ITD utility early in M+2 (SOP deadline: the 7th) to inactivate whoever did
    not pay. Payments landing after M+1 are late/reinstate, NOT cycle renewals.

    An earlier version of this comment said "ITD runs at M+2" in a way that read
    as if the pay window ran to M+2. It does not — that is only when the cleanup
    job runs. The distinction decides which payments count toward a bill month.

    We use a ±2-month window around the 1st notice date to avoid catching
    records from prior fiscal years.

    Invoice calendar year:
        Bill months 10, 11, 12 (Oct/Nov/Dec) → invoice year = fiscal_year_start
        Bill months 1-9 (Jan-Sep)            → invoice year = fiscal_year_start + 1

    Args:
        bill_month:        Integer 1-12 (dues bill month).
        fiscal_year_start: Calendar year of FY start (e.g. 2025 for FY2025-26).

    Returns:
        Tuple of ISO date strings ("YYYY-MM-DD", "YYYY-MM-DD").
    """
    # Determine which calendar year this bill month belongs to.
    # WHA fiscal year starts in October: Oct(10)–Sep(9).
    # Months 10–12 (Oct–Dec) occur in fiscal_year_start calendar year.
    # Months 1–9   (Jan–Sep) occur in fiscal_year_start + 1 calendar year.
    invoice_year = fiscal_year_start if bill_month >= 10 else fiscal_year_start + 1

    # 1st notice month = M-1 (with wrap: Jan → Dec of previous year)
    notice_month = bill_month - 1 if bill_month > 1 else 12
    notice_year  = invoice_year if bill_month > 1 else invoice_year - 1

    # Window: notice_month-1 to M+2 (inclusive)
    start_month = notice_month - 1 if notice_month > 1 else 12
    start_year  = notice_year if notice_month > 1 else notice_year - 1

    end_month = bill_month + 2
    end_year  = invoice_year
    if end_month > 12:
        end_month -= 12
        end_year  += 1

    # Last day of end_month
    import calendar as _cal
    last_day = _cal.monthrange(end_year, end_month)[1]

    start = f"{start_year}-{start_month:02d}-01"
    end   = f"{end_year}-{end_month:02d}-{last_day}"
    return start, end


# ---------------------------------------------------------------------------
# STRICT CLOSE — retention is live while a cycle is open, frozen once it shuts.
# ---------------------------------------------------------------------------
# Ratified 2026-07-28. One date governs both halves of the fraction:
#
#       as_of = min(today, cycle_close)
#
# While the cycle is open that is today, so nothing is demoted and the number
# moves with reality. Once shut it stops moving, which is what makes a past
# month reproducible on any future run — the property the whole product needs.
#
# Validated two independent ways, both landing on end-of-M+1:
#   · payment dates — freezing there reproduced 5 territories exactly, and TKP's
#     ledger dates matched Jennifer's handwritten notes to the day.
#   · status audit — the CRM's own BM5 cleanup was entered ~2026-07-21 and
#     BACKDATED to 2026-06-30, so the CRM closes the cycle on the same day.

def cycle_close_date(bill_month: int, fiscal_year_start: int) -> date:
    """The last day of M+1 — when the 3rd notice's month ends and the ~90-day
    pay window shuts. Payments after this are reinstates, not renewals."""
    invoice_year = fiscal_year_start if bill_month >= 10 else fiscal_year_start + 1
    close_month = bill_month + 1
    close_year = invoice_year
    if close_month > 12:
        close_month -= 12
        close_year += 1
    return date(close_year, close_month,
                 _cal.monthrange(close_year, close_month)[1])


def as_of_date(bill_month: int, fiscal_year_start: int,
               today: Optional[date] = None) -> date:
    """The single date that governs the whole calculation for this cycle."""
    today = today or date.today()
    return min(today, cycle_close_date(bill_month, fiscal_year_start))


def retained_as_of(rows: list, first_payment_date: Optional[date],
                   as_of: Optional[date]) -> bool:
    """Did this member's money arrive, and arrive in time?

    The date test can only NARROW the paid set, never widen it: a write-off
    collected nothing whatever its date.

    An UNDATABLE payment is never demoted. payAllocationViews collapses
    multi-line payment documents onto one arbitrary line ($key-collapse,
    PROBLEMS.md 2026-07-24), so a genuinely-paid invoice can carry no
    allocation row at all. Absence of a date is not evidence of late payment.
    """
    if not _member_retained(rows):
        return False
    if as_of is None or first_payment_date is None:
        return True
    return first_payment_date <= as_of


def in_cohort_as_of(status: Optional[str], inactivated_on: Optional[date],
                    as_of: Optional[date],
                    invoice_date: Optional[date] = None) -> bool:
    """Was this member still a member when the cycle closed?

    A member who exits MID-cycle (sold, closed, moved) did not fail to renew —
    they stopped being billable. That loss is the drops family's row, and
    counting it here would charge the rep for the same member twice.

    A member inactivated ON the closing day stays: they were a member through
    the close and did not pay, which is exactly what a retention miss is. The
    CRM backdates its own cleanup to precisely this day.

    Two guards against bad audit data, both erring toward keeping the member:
      · no date at all → keep (don't invent an exit)
      · a date BEFORE the invoice → keep. A member cannot have left before the
        bill they were sent; the history log's most recent Active->Inactive
        goes stale when a reactivation is never logged (live case: Deuce
        Restaurant Group, 2023-12-21 against 2026 billing — the same class as
        the 2026-07-27 drops fix, where 41 members carried 2012-2024 dates).
    """
    if str(status or "").strip().upper().startswith("RRO"):
        # 2026-07-30 (Jen, recorded): a member who flips to RRO is "no longer
        # considered a billable... completely removed out of June's retention"
        # — numerator AND denominator, the built-in ~2% death rate.
        #
        # CORRECTED 2026-08-12: that ruling governs the cycle they flip IN.
        # This returned False ABOVE every date guard, so a flip reached
        # BACKWARDS and erased cycles that had already closed — months the
        # member was billed for, paid, and was retained in. Sparta's Pizza &
        # Pasta House - Bothell was billed $730 for bill month 12, paid in
        # full, closed 2026-01-31, then flipped RRO 2026-06-16 on the sale of
        # the business; January lost a member on both sides five months after
        # the fact. Jen, reviewing it: "during when that month closed, that
        # Member paid and they were retained."
        #
        # Same defect new sales carried until 2026-07-15 (target.py:79) — a
        # CURRENT status retroactively erasing a PAST event. An exit has a
        # date, so RRO now takes the same date test as every other exit.
        # Dateless keeps the 7/30 removal: without a date the flip cannot be
        # placed, and Jen's instruction was that the flip removes.
        if inactivated_on is None or as_of is None:
            return False
        return inactivated_on >= as_of
    if str(status or "").strip().lower() == "active":
        return True
    if inactivated_on is None or as_of is None:
        return True
    if invoice_date is not None and inactivated_on < invoice_date:
        return True
    return inactivated_on >= as_of


def _slx_day(raw) -> Optional[date]:
    """SLX /Date(ms)/ → a calendar day. The audit and ledger surfaces both
    serialize this way; comparisons here are day-grained, never instant-grained.
    Negative timestamps (pre-1970) parse too — drops._parse_slx_date rejects
    them, and a bad old date must not silently read as 'no date'."""
    if raw is None:
        return None
    match = _re.search(r"/Date\((-?\d+)", str(raw))
    if not match:
        return None
    return _dt.datetime.fromtimestamp(
        int(match.group(1)) / 1000, tz=_dt.timezone.utc).date()


def _first_payment_dates(client, window_start: str, window_end: str) -> Dict[str, date]:
    """{invoice_number: earliest positive allocation date} for the dues company.

    payAllocationViews is the AR payment-application ledger. It is UNFILTERABLE
    by account (DECISIONS.md 2026-07-21) but IS filterable by date range, so one
    query serves every territory instead of one per invoice.

    EARLIEST, because a member who paid in June and topped up in August renewed
    in June. Negative amounts are reversals, not payments.

    ⚠️ $key-collapse (PROBLEMS.md 2026-07-24): a multi-line payment document can
    emit rows that collapse onto one arbitrary line, so an invoice may be MISSING
    from this index even though it was paid. Callers must treat a missing entry
    as "undatable", never as "unpaid" — see retained_as_of.
    """
    # ASK FOR THE POSITIVE LINE (2026-08-11). payAllocationViews returns ONE
    # line per payment DOCUMENT, and WHICH line the server projects depends on
    # the where-clause — proven on invoice 0145480: the plain query returns
    # -50.00, the same query with `Allocationamt gt 0` returns +5,550.00, same
    # $key, same date. Repeating a query is stable, so this hides behind any
    # determinism check.
    #
    # Without the filter the server often hands back the reversal, which
    # `_payment_index_from_rows` then correctly discards as a negative — and
    # the invoice drops out of the index entirely. ~197 genuinely-paid members
    # were "undatable" for this reason alone, and `retained_as_of` never
    # demotes an undatable payment, so a late payer could not be caught.
    # Asking the server for the positive line is what makes the ratified
    # "paid after close is not retained" rule actually able to fire.
    rows = client._fetch_all(
        "payAllocationViews",
        where=(f"Comp_code eq 'WRA' "
               f"and Allocationamt gt 0 "
               f"and AllocationDate ge @{window_start}@ "
               f"and AllocationDate le @{window_end}@"),
        page_size=200,
    )
    return _payment_index_from_rows(rows)


def _allocation_window(bill_month: int, fiscal_year_start: int) -> Tuple[str, str]:
    """(start, end) for the PAYMENT fetch: invoice-window start → close + 6 months.

    The invoice window and the payment window are different questions. The
    invoice window asks "which bills belong to this cycle" and must stay tight
    (a wide one drags in other years' bills). The payment window asks "did the
    money for those bills ever arrive" — and the old code reused the invoice
    window for it, so a payment landing after M+1 was invisible, the member
    undatable, and `retained_as_of` (which never demotes what it cannot date)
    counted them on Balance=0 alone. 20 members, $22,364.92 (measured 8/12,
    every one named with its payment date; Jen's trackers independently score
    Motel 6 Vancouver, TOGO'S and Soi as unpaid).

    close + 6 months because the OBSERVED lateness runs 1.6–6 months — the
    cutoff was read off the list, not guessed (worst: Four Points Bellingham,
    Nov close, paid 2026-05-30). Late payments dated by this window are then
    DEMOTED by the existing date test — the same one that already correctly
    demotes 33 members — implementing the executives' ruling that a late
    payment is a late payment, no grace period.
    """
    start, _invoice_end = _bill_month_date_window(bill_month, fiscal_year_start)
    close = cycle_close_date(bill_month, fiscal_year_start)
    y, m = close.year, close.month + 6
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    last = _cal.monthrange(y, m)[1]
    return start, f"{y:04d}-{m:02d}-{last:02d}"


def _allocation_where(bill_month: int, fiscal_year_start: int) -> str:
    """The payAllocationViews where-clause for one bill month.

    `Allocationamt gt 0` is SERVER-SIDE on purpose and load-bearing: the view
    returns ONE line per payment document and WHICH line depends on the where
    clause (invoice 0145480: −50.00 plain, +5,550.00 with the filter). A
    client-side positive filter cannot recover a document whose projected line
    was the reversal — the document simply never arrives. This is the 8/11
    `_first_payment_dates` fix (A4) landing on the path the nightly actually
    uses; without it here, it had never run in production.
    """
    start, end = _allocation_window(bill_month, fiscal_year_start)
    return (f"Comp_code eq 'WRA' "
            f"and Allocationamt gt 0 "
            f"and AllocationDate ge @{start}@ "
            f"and AllocationDate le @{end}@")


def _cm_cancelled_accounts(by_account: Dict[str, list], cm_rows: list,
                           month_str: str) -> set:
    """Accounts whose EVERY cohort charge was voided by credit memos (R1 = A,
    ruled 2026-08-12): they leave numerator AND denominator.

    A credit memo is an accounting correction — "that invoice should not have
    gone out" — not a comp (a comp is a member we CHOSE not to charge, who
    stays in the denominator at $0 per the 7/31 ruling). A fully-voided cycle
    never reached a billing run: Jen's own billing sheets carry none of these
    members, and applying this treatment reproduced her trackers exactly
    (NorthKing Oct 34/35, EastKing Oct 26/27, Snohomish Jan 19/22).

    Deliberately narrow, judged per invoice on the account's COHORT charges:
      · every cohort IN must be exactly offset by CMs (±$0.005) — a partial
        credit is a price adjustment and the member stays
      · any live (uncancelled) cohort IN keeps the member — that is the
        void-and-rebill shape, where the member WAS ultimately billed
      · a blank-comment replacement IN also keeps them (same reason)
    Proven population: 10 members / $17,105 (Van Pizza, Torero's, General
    Porpoise, Serra SC, Walrus & The Carpenter, PWP PNW, Agave Expo,
    Westward & Little Gull, The Attic, Mazatlan-Graham), each verified 10/10
    against the ledger on 8/12.
    """
    # cm_rows are RAW SData dicts (this function's own fetch controls their
    # shape); by_account rows are the GROUPED shape from _group_invoice_rows —
    # invoice_number / invoice_total / adjustments, no Invoice_Type, no
    # Comment. The first draft read raw keys off grouped rows, every get()
    # returned None, and the predicate could never fire — unit tests passed
    # on raw-shaped fixtures while the live eval failed 12/12 (2026-08-12,
    # the same fixture-shape trap as the SimpleNamespace autoseal test that
    # morning). The live evaluation harness is what caught it.
    cm_by_invoice: Dict[str, float] = {}
    for row in cm_rows or []:
        inv = str(row.get("Invoice_number") or "").strip()
        amt = row.get("Net_invoice")
        if inv and isinstance(amt, (int, float)):
            cm_by_invoice[inv] = cm_by_invoice.get(inv, 0.0) + float(amt)

    cancelled: set = set()
    if not cm_by_invoice:
        return cancelled
    for aid, rows in (by_account or {}).items():
        if not rows:
            continue
        # Every row here is already this cycle's (the grouping anchors on the
        # cohort comment and joins only blank/text-comment rebills for
        # anchored members) — so the void-and-rebill shape needs no special
        # guard: a live rebill row has no offsetting CM, fails its own test,
        # and keeps the member.
        ok = True
        for r in rows:
            inv = str(r.get("invoice_number") or "").strip()
            charge = r.get("invoice_total")
            if not inv or not isinstance(charge, (int, float)) or charge <= 0:
                ok = False
                break
            if abs(float(charge) + cm_by_invoice.get(inv, 0.0)) > 0.005:
                ok = False
                break
        if ok:
            cancelled.add(aid)
    return cancelled


def _payment_index_from_rows(rows) -> Dict[str, date]:
    index: Dict[str, date] = {}
    for row in rows:
        amount = row.get("Allocationamt")
        if not isinstance(amount, (int, float)) or amount <= 0:
            continue
        invoice = str(row.get("Invoice_number") or "").strip()
        when = _slx_day(row.get("AllocationDate"))
        if not invoice or when is None:
            continue
        if invoice not in index or when < index[invoice]:
            index[invoice] = when
    return index


def _account_statuses(client, account_manager_id: str) -> Dict[str, str]:
    """{account_id: Status} for one territory, in a single query.

    Paired with _inactivation_dates: StatusDate alone cannot distinguish an
    ACTIVE member (whose StatusDate records when they were activated) from one
    who has left, so the cohort test needs both.
    """
    rows = client._fetch_all(
        "accounts", where=f"AccountManager.Id eq '{account_manager_id}'",
        select="Id,Status", page_size=200)
    out: Dict[str, str] = {}
    for row in rows:
        acct_id = row.get("$key") or row.get("Id")
        if acct_id:
            out[str(acct_id)] = str(row.get("Status") or "")
    return out


def _inactivation_dates(client, account_manager_id: str) -> Dict[str, date]:
    """{account_id: StatusDate} for one territory, in a single query.

    AccountExtension.StatusDate is the CRM's own "when the current status was
    set" — the exact semantic the cohort test needs, and near-universally
    populated. Preferred over the history audit log, which missed 9 of 14 live
    BM5 inactivations and returned a stale 2023 date for a 10th (Deuce, whose
    reactivation was never logged). `in_cohort_as_of` guards that class anyway.
    """
    rows = client._fetch_all(
        "AccountExtension",
        where=f"Account.AccountManager.Id eq '{account_manager_id}'",
        select="Account,StatusDate",
        page_size=200,
    )
    index: Dict[str, date] = {}
    for row in rows:
        acct = row.get("Account")
        acct_id = acct.get("$key") if isinstance(acct, dict) else acct
        when = _slx_day(row.get("StatusDate"))
        if acct_id and when is not None:
            index[str(acct_id)] = when
    return index


def compute_retention(
    client: SLXClient,
    territory_user_map: Dict[str, str],
    bill_month: int,
    fiscal_year_start: int,
    request_delay: float = 0.20,
    include_target_split: bool = False,
) -> Dict[str, Dict]:
    """
    Compute retention for all territories for a given dues bill month.

    Uses dlInvoiceHistoryHeader where Comment = bill_month (the dues bill month
    stored as a string, e.g. "3" for March) and Balance = 0.0 for paid.

    Args:
        client:               Authenticated SLXClient instance.
        territory_user_map:   Dict mapping SLX user ID -> canonical territory name.
        bill_month:           Integer dues bill month (1-12).
        fiscal_year_start:    Calendar year of FY start (e.g. 2025 for FY2025-26).
        request_delay:        Seconds between API calls.
        include_target_split: If True, adds Target/Non-Target breakdown fields.
                              Costs 3 extra API calls per territory (build_target_map).
                              Default False to keep the existing fast path unchanged.

    Returns:
        Dict keyed by canonical territory name:
        {
            "Pierce": {
                "pct": 91.7,
                "paid": 22,
                "billed": 24,
                "outstanding": 2,
                "unknown": 0,
                "string": "22/24",
                "revenue_retained": 12500.0,
                "revenue_up_for_renewal": 13800.0,
                "revenue_retention_pct": 90.6,

                # Only present when include_target_split=True:
                "paid_target": 18,
                "billed_target": 20,
                "revenue_retained_target": 10200.0,
                "revenue_up_target": 11500.0,
                "paid_non_target": 4,
                "billed_non_target": 4,
                "revenue_retained_non_target": 2300.0,
                "revenue_up_non_target": 2300.0,
            },
            ...
        }
    """
    if not 1 <= bill_month <= 12:
        raise ValueError(f"bill_month must be 1-12, got {bill_month}")

    fy_start, fy_end = _bill_month_date_window(bill_month, fiscal_year_start)
    month_str = str(bill_month)
    result = {}

    for user_id, territory in territory_user_map.items():
        if territory is None:
            continue

        paid, billed, outstanding, unknown, rev_retained, rev_up, by_account = \
            _retention_counts(client, user_id, month_str, fy_start, fy_end,
                              fiscal_year_start)
        pct = (paid / billed * 100) if billed > 0 else None
        rev_pct = (rev_retained / rev_up * 100) if rev_up > 0 else None

        row = {
            "pct": round(pct, 1) if pct is not None else None,
            "paid": paid,
            "billed": billed,
            "outstanding": outstanding,
            "unknown": unknown,
            "string": f"{paid}/{billed}",
            "revenue_retained": round(rev_retained, 2),
            "revenue_up_for_renewal": round(rev_up, 2),
            "revenue_retention_pct": round(rev_pct, 1) if rev_pct is not None else None,
        }

        if include_target_split and by_account:
            # build_target_map fetches all accounts for territory (active + inactive)
            # status=None because billed accounts may have gone inactive after ITD
            target_map = build_target_map(client, user_id, status=None,
                                          request_delay=request_delay)
            row.update(_retention_target_split(by_account, target_map,
                                               as_of=as_of,
                                               payment_dates=payment_dates))

        # Multi-user territories (e.g. Majors/NRA since 2026-07-13) must SUM,
        # not last-user-wins; the derived % is recomputed from merged dollars.
        result[territory] = (_merge_retention_rows(result[territory], row)
                             if territory in result else row)
        time.sleep(request_delay)

    return result


def _first_cycle_ids(enrolled_map: Dict, bill_month: int, fiscal_year_start: int) -> set:
    """A2 (2026-07-14): first-cycle members are NOT 'up for renewal'.

    Dues are annual — a member whose EnrolledDate is less than ~12 months before
    the cohort's due date is receiving their FIRST bill, not renewing. Returns
    the account ids to EXCLUDE from the retention cohort. Unknown enrollment
    dates stay in (don't drop real renewals on missing data).
    """
    due_year = fiscal_year_start if bill_month >= 10 else fiscal_year_start + 1
    excluded = set()
    for acct_id, enrolled in enrolled_map.items():
        if enrolled is None:
            continue
        months_before = (due_year - enrolled.year) * 12 + (bill_month - enrolled.month)
        if months_before < 12:
            excluded.add(acct_id)
    return excluded


_DERIVED_RETENTION_KEYS = {"pct", "string", "revenue_retention_pct"}


def _merge_retention_rows(dst: Dict, src: Dict) -> Dict:
    """Sum two per-territory retention rows, then RECOMPUTE every derived key from
    the merged counts — never sum a ratio or a display string.

    Finding #7/R3b (2026-07-17): the old guard skipped only keys ENDING in
    '_pct', so the plain 'pct' key was summed (90 + 80 → 170, a nonsense %) and
    'string' — already present as a str — was kept STALE ('9/10' while paid/billed
    became 17/20). Now pct / string / revenue_retention_pct are all rebuilt below.
    """
    out = dict(dst)
    for k, v in src.items():
        if k in _DERIVED_RETENTION_KEYS:
            continue  # derived — recomputed from merged counts below, never summed
        if isinstance(v, (int, float)):
            out[k] = (out.get(k) or 0) + v
        elif k not in out:
            out[k] = v
    paid = out.get("paid") or 0
    billed = out.get("billed") or 0
    out["pct"] = round(paid / billed * 100, 1) if billed > 0 else None
    out["string"] = f"{paid}/{billed}"
    up = out.get("revenue_up_for_renewal") or 0
    ret = out.get("revenue_retained") or 0
    out["revenue_retention_pct"] = round(ret / up * 100, 1) if up > 0 else None
    return out


def _member_retained(rows: list) -> bool:
    """Jennifer's convention, ratified by Jiho 2026-07-21: a member counts as
    RETAINED if they paid ANYTHING on their renewal — a partial payer stayed,
    they just couldn't pay in full. Decoded from her per-member retention file
    (EK bill-month 5: 5 full + 2 partial = her published 7/9) and matching her
    published report exactly. Unknown balance still never counts as retained.

    Accepts rows keyed either invoice_total (retention pipeline) or amount
    (tests/simple callers)."""
    fixed = [{"balance": r.get("balance"),
              "invoice_total": r.get("invoice_total", r.get("amount")),
              "invoice_date": r.get("invoice_date"),
              # per-invoice collected needs the number — dropping it here
              # collapsed every row onto one pseudo-invoice (Contreras
              # regression, caught by its ratified test 2026-07-31)
              "invoice_number": r.get("invoice_number"),
              # fee + level pass through since 2026-08-06 (Jiho's ruling:
              # "a fee should be excluded from retention or any other
              # metric — they did not pay their actual dues, so it's not
              # retained"). Fee money alone no longer counts a member
              # (Smokin' Pete's $20); the fee-swallowed-dues-bill artifact
              # rule inside _netted_retained keeps genuinely-paid dues
              # members counted (Wapato class).
              "fee": r.get("fee"),
              "dues_level": r.get("dues_level"),
              "adjustments": r.get("adjustments", 0.0)} for r in rows]
    amount, retained = _netted_retained(fixed)
    if retained > 0.005:
        return True
    # fee-only cycle (ruled 2026-08-06): every collected dollar was fee, so
    # the zero-billed edge below must not read "gross − fee == 0" as a paid
    # $0 dues bill (Smokin' Pete's: one $20 county-fee invoice, no dues
    # bill at all). Artifact-class members never reach here — their fee is
    # zeroed upstream and they return True on real dollars.
    _tot = sum((r.get("invoice_total") or 0) for r in fixed
               if (r.get("invoice_total") or 0) > 0)
    _fees = sum((r.get("fee") or 0) for r in fixed
                if (r.get("invoice_total") or 0) > 0)
    if _tot > 0.005 and _tot - _fees <= 0.005:
        return False
    # zero-billed edge: a fully-paid $0 bill still counts as paid — but a
    # VOIDED cycle is not a $0 bill. The credit note zeroes every balance, so
    # without the negative-row check nine live accounts (2026-07-30, e.g.
    # Governor Hotel Olympia +1,891/−1,891) counted as RETAINED here while the
    # dollars path excluded them. Count and dollars must tell one story.
    if any((r.get("invoice_total", r.get("amount")) or 0) < 0 for r in rows):
        return False
    return amount == 0 and any(b == 0.0 for b in (r.get("balance") for r in rows))


def _group_invoice_rows(records: list, cohort_comment: str = None,
                        extra_anchor_ids=None) -> Dict[str, list]:
    """Group header rows per account: IN rows carry the cohort, AD rows attach
    to their IN row (by invoice number) as an `adjustments` sum.

    An AD-only account was never billed in this cohort and is excluded — an
    adjustment is not a bill. Duplicate AD rows (the Sage sync artifact that
    already affects IN rows) are counted once via a (invoice, net, date) key.

    VOID-AND-REBILL (live pattern, 2026-07-28: Contreras, Otter): a cycle's
    invoice can be voided (IN + AD netting to zero) and re-issued as a NEW
    invoice whose Comment is BLANK — invisible to a Comment='M' filter. So
    when `cohort_comment` is given, membership is anchored by a Comment=M IN
    row, and blank-comment rows are joined ONLY for anchored members (their
    in-window WRA activity is this cycle's — dues bill once a year). A member
    with only blank-comment rows was never billed in this cycle.
    """
    def _comment(r):
        return str(r.get("Comment") or "").strip()

    if cohort_comment is not None:
        anchors = {r.get("Accountid") or (r.get("Account") or {}).get("$key")
                   for r in records
                   if r.get("Invoice_Type", "IN") == "IN" and _comment(r) == cohort_comment}
        # ROSTER ANCHOR (2026-07-28, Deb Green Group): a member whose ONLY bill
        # carries a blank comment is anchored by their own Duesbillmonth — the
        # Comment field is data entry, not structure, and has now failed three
        # ways (rebills, late bills). The caller supplies the roster-verified ids.
        anchors |= set(extra_anchor_ids or ())
        anchors.discard(None)
        # Anchored members join their blank-comment rows (Deb Green) AND
        # their TEXT-comment rows (2026-08-04, Serious Soul Cafe: BOB bills
        # carry '2026 Dues - BOB Initiative'). A DIFFERENT numeric comment
        # still means another cycle and stays excluded.
        records = [r for r in records
                   if _comment(r) == cohort_comment
                   or (not _comment(r).isdigit()
                       and (r.get("Accountid") or (r.get("Account") or {}).get("$key")) in anchors)]
    ad_by_invoice: Dict[str, float] = {}
    seen_ad = set()
    for r in records:
        if r.get("Invoice_Type") != "AD":
            continue
        inv = str(r.get("Invoice_number") or "")
        key = (inv, r.get("Net_invoice"), str(r.get("Invoice_Date")))
        if not inv or key in seen_ad:
            continue
        seen_ad.add(key)
        net = r.get("Net_invoice")
        if isinstance(net, (int, float)):
            ad_by_invoice[inv] = ad_by_invoice.get(inv, 0.0) + net

    by_account: Dict[str, list] = {}
    for r in records:
        # Missing Invoice_Type counts as IN: the pre-2026-07-28 fetch was
        # IN-only, so older fixtures and callers never carry the field.
        if r.get("Invoice_Type", "IN") != "IN":
            continue
        acct_id = r.get("Accountid") or (r.get("Account") or {}).get("$key")
        if not acct_id:
            continue
        inv = str(r.get("Invoice_number") or "")
        by_account.setdefault(acct_id, []).append({
            "balance": r.get("Balance"),
            "invoice_total": r.get("Net_invoice"),  # Invoice_total is null; Net_invoice is the populated amount
            "invoice_date": r.get("Invoice_Date"),  # raw SLX /Date(ms)/ string; deterministic latest-pick
            "invoice_number": inv,
            "adjustments": ad_by_invoice.get(inv, 0.0),
        })
    return by_account


def retained_dollars_as_of(rows: list, first_payment_date: Optional[date],
                           as_of: Optional[date]) -> Tuple[float, float]:
    """(ask, retained dollars) under the SAME close the member count uses.

    Ratified 2026-07-31 (Jiho): *"those members and dollars act regarding the
    same retention insight, so they must abide by the same semantic rules."*
    Until then the date test lived only on the count branch — a late payer was
    demoted from Members Retained while their cash still counted in Revenue
    Retained, which is how Snohomish May published 11 of 12 members but 100%
    dollars. One member, one story.

    The ask NEVER moves — they were billed regardless of when they paid.
    Demotion is narrowing-only, inherited from `retained_as_of`: money is
    removed only when a payment date exists and is provably late; the
    undatable-payment carve ($key-collapse) applies to dollars exactly as it
    does to the count. Both accumulation loops (combined and T/NT split) call
    THIS function so the two can never drift again — the bug-#1 lesson.
    """
    amount, retained = _netted_retained(rows)
    if retained > 0 and not retained_as_of(rows, first_payment_date, as_of):
        retained = 0.0      # arrived after the window shut — reinstate cash
    # DUES-LEVEL ASK (Jiho GO 2026-08-04; transcript 1:37-1:39 — accounting
    # DELETES and recreates invoices on dues adjustments, so the invoice is
    # not a stable record; her export's Billed = the membership product's
    # price). When the account's dues level is known, the ASK is the level
    # and retained is capped at it — the ledger's unrecoverable hidden-fee
    # class dies by construction. Partial payers still report what actually
    # arrived; missing level falls back to the invoice math (never drop a
    # member on missing data). Closed months freeze this value at close
    # (month_close), so a later level change cannot rewrite history.
    level = next((r.get("dues_level") for r in rows
                  if isinstance(r.get("dues_level"), (int, float))
                  and r.get("dues_level") > 0), None)
    if level is not None:
        amount = float(level)
        retained = min(retained, amount)
    return amount, retained


def comp_or_rescinded(rows: list, status: Optional[str]) -> Optional[str]:
    """Classify a fully-rescinded cycle: 'comp', 'rescinded', or None.

    A1 RULED 2026-07-31 (Jiho): a member whose bill was credited off while
    they REMAIN ACTIVE was comped — they stay, counted RETAINED, at $0/$0
    dollars (cash-anchored: "if they see high retention but didn't get cash
    that would skew judgement"). Validated by reading all nine live accounts'
    notes: seven explicitly comped/waived with approvers named (Governor
    renovation · Latah road-closure waiver via Steven · Skyway fire ·
    Mt Spokane "comp membership this year" · Silverbeard's "will be using
    Bob" · Velvet's hardship free year · Falls Terrace "Comped Membership"),
    zero contrary; the two note-silent ride the same mechanical rule
    (blessed). A rescinded cycle whose member is NOT active (or whose status
    is unknown) stays excluded from both sides, as before.
    """
    if not _cycle_rescinded(rows):
        return None
    if str(status or "").strip() == "Active":
        # COMP vs VOID (approved 2026-08-04): a comp's credit is issued LATER
        # (the decision took time - Hama Hama 83d, Governor 53d, every row in
        # the GS Dues Discounts ledger); a SAME-DAY mirror is a data-entry
        # void (Southern Kitchen 10/16/2025 - absent from the GS ledger).
        # 1-6 day gaps stay comps but are marked for review on the receipts.
        bill_dates = [d for r in rows
                      if isinstance(r.get("invoice_total"), (int, float))
                      and r.get("invoice_total") > 0
                      and (d := _slx_day(r.get("invoice_date"))) is not None]
        credit_dates = [d for r in rows
                        if isinstance(r.get("invoice_total"), (int, float))
                        and r.get("invoice_total") < 0
                        and (d := _slx_day(r.get("invoice_date"))) is not None]
        if bill_dates and credit_dates:
            gap = (min(credit_dates) - max(bill_dates)).days
            if gap <= 0:
                return "void"
            if gap < 7:
                for r in rows:
                    r["_comp_review"] = True
        return "comp"
    return "rescinded"


def _cycle_rescinded(rows: list) -> bool:
    """Was this cycle's ask fully rescinded and never reissued?

    ONE ratified meaning (NET ASK, 2026-07-28 — Madeleine's/Cibrian: "an ask
    fully rescinded and never reissued is not an ask"), TWO vehicles:

      · an AD write-off zeroing the invoice        (the vehicle covered since 7/28)
      · a CREDIT INVOICE reversing the bill        (2026-07-30: nine live
        accounts, all still Active, none dropped/RRO — e.g. Governor Hotel
        Olympia billed +1,891 Jan 2, credited −1,891 Feb 24, no replacement)

    The cohort builder pops rescinded accounts from BOTH sides under a named
    rule (GATE C accountability). Before this predicate existed the second
    vehicle slipped past the adjustments-only gate into the count path, where
    credit-zeroed balances read as a fully-paid $0 bill: counted retained,
    dollars excluded — two stories from one member.

    Guards: a genuine $0 bill triggers NEITHER vehicle and stays a bill; a
    partial credit leaves a positive net ask; outstanding balance means the
    ask still stands. WHY the team credits these bills off (comp?
    consolidation? in-progress non-payment?) is an open Jen question — until
    her ruling, rescinded cycles follow the ratified default for novelties:
    out of the headline, named in the run output.
    """
    triggered = (any(r.get("adjustments") for r in rows)
                 or any((r.get("invoice_total") or 0) < 0 for r in rows))
    if not triggered:
        return False
    per_invoice: Dict[str, float] = {}
    for row in rows:
        inv = row.get("invoice_number")
        if inv not in per_invoice and row.get("invoice_total") is not None:
            per_invoice[inv] = row["invoice_total"] + (row.get("adjustments") or 0.0)
    if not per_invoice:
        return False
    still_owed = any((row.get("balance") or 0) > 0 for row in rows)
    return sum(per_invoice.values()) <= 0.005 and not still_owed


def _netted_retained(rows: list) -> Tuple[float, float]:
    """Return (net_ask, retained_amount) for one account's invoice rows.

    ASYMMETRIC BY DESIGN, and the asymmetry is the point:

      · an UPWARD adjustment raises the ASK as well as collected. We asked them
        for more, so both sides move (Anacortes Brewing: invoice 1,040, AD +330
        → asked 1,370, collected 1,370 = 100%).
      · a DOWNWARD adjustment (a write-off) reduces COLLECTED ONLY. We asked for
        the original amount and chose not to collect part of it, which is a
        retention loss, not a smaller ask (Cibrian: 510 billed, AD −510 → asked
        510, collected 0).

    Before 2026-07-30 the ask ignored adjustments entirely while collected
    netted them, so an upward AD inflated the numerator alone and the ratio
    could exceed 100% — Snohomish Oct published **Revenue Retention 100.9%**
    (caught by Jiho's eyeball on the workbook; 13 of 188 revenue cells were
    over 100%, worst 120.6%). ("Cannot exceed 100% by construction" was
    claimed here and DISPROVEN twice on 2026-07-30/31 — negative asks and the
    per-invoice sum both breached it. The invariant is asserted by tests now,
    never assumed.)

    VOIDED CYCLE (2026-07-30): `chosen` is the LATEST-dated invoice, so when a
    cycle is reversed by a CREDIT INVOICE the credit note won and the ask came
    back NEGATIVE — TKP BM2 account A6UJ9A002MSJ: +1,891 on 01-02, −1,891 on
    02-24, ask −1,891. A negative ask shrinks the territory denominator, which
    is what published TKP Mar Target at 108.2% (and four more cells, worst
    Spokane/NE Feb Non-Target 120.6%). Netting to ≤0 with a negative row present
    means the bill was rescinded: no ask, no retention, out of both sides. This
    is the void-and-rebill pattern `_group_invoice_rows` already describes, and
    it is SEPARATE from the open AD question below — a credit INVOICE is not an
    adjustment. The `any(t < 0)` guard keeps the legitimate $0 bill (line ~499)
    on its existing path.

    ⚠️ OPEN (do not silently resolve): whether a write-off should ALSO reduce
    the ask is contested — `docs/metrics/retention-revenue.md` states a net-ask
    rule ("a fully rescinded invoice is not an ask"), the 2026-07-28 tests
    assert the ask stays gross, and the ratified-but-unimplemented Dues-Level
    ruling says the ask is neither. Only the upward half is fixed here because
    only the upward half is unambiguous.

    retained = ask + downward adjustments − outstanding balance (NETTING) — so a
               partial payer contributes their paid portion, not $0. Unknown
               balance (all None) → $0 retained (don't invent). Never negative.
               Dedup-safe: the Sage artifact of Balance=0.0 + Balance=None for
               one invoice nets to full.
    """
    totals = [r["invoice_total"] for r in rows if r["invoice_total"] is not None]
    if totals and sum(totals) <= 0 and any(t < 0 for t in totals):
        return 0.0, 0.0     # cycle voided by a credit invoice — see below

    # PARTIAL CREDIT (2026-07-31, WA Independent Inns / Kaspars): the cycle's
    # bill is the latest POSITIVE invoice — a credit note can never be the ask
    # (billed +2,104 then credited −44: the credit, dated later, made the ask
    # −$44; Kaspars' same-day pair made it depend on server row order). Fall
    # back to any non-None row so the genuine $0 bill keeps its existing path.
    sorted_rows = sorted(rows, key=lambda r: r.get("invoice_date") or "", reverse=True)

    # SPLIT BILLING (A1b, ruled 2026-07-31): county-fee members carry fee +
    # dues + COMBINED invoices same-day for one obligation. All visible
    # payment allocations sit on the combined row (7 of 7 live), so the
    # combined invoice IS the bill — detected mechanically: a positive invoice
    # equal to the sum of the other positive invoices. Jiho: "combined yes.
    # its their invoice so why not count."
    positives = [r for r in sorted_rows if (r["invoice_total"] or 0) > 0]
    chosen = None
    if len(positives) >= 3:
        biggest = max(positives, key=lambda r: r["invoice_total"])
        rest = sum(r["invoice_total"] for r in positives if r is not biggest)
        if abs(biggest["invoice_total"] - rest) < 0.01:
            chosen = biggest
    # FEE-ONLY SUPPLEMENT (2026-08-06, Thai Ginger + 8 more, amendment #3):
    # accounting also bills county/alliance fees as their OWN later invoice,
    # and the latest-positive rule made that supplement THE BILL — fees-out
    # then reported a fully-paid cycle as $0 collected. A fee-only invoice is
    # never the bill while any dues-bearing positive invoice exists; genuine
    # fee-only cycles (no dues-bearing invoice at all) keep their old path.
    dues_bearing = [r for r in positives
                    if (r["invoice_total"] or 0) - (r.get("fee") or 0) > 0.01]
    chosen = chosen or next(iter(dues_bearing), None) \
        or next(iter(positives), None) \
        or next((r for r in sorted_rows if r["invoice_total"] is not None), None)
    gross = chosen["invoice_total"] if chosen else 0.0
    adjustments = (chosen or {}).get("adjustments", 0.0) or 0.0
    # FEES-OUT (ruled 2026-08-03, Jen: "remove all those county fees"): the
    # chosen invoice may embed county/local/alliance fee lines (BGP 0149139:
    # /KINGCOFEE 260 inside 2,695). The combined invoice stays THE BILL for
    # payment matching (A1b), but ask and retained report DUES ONLY.
    fee = (chosen or {}).get("fee", 0.0) or 0.0
    # FEE-SWALLOWED DUES BILL (ruled 2026-08-06, amendment #4): when the
    # attributed fee is the ENTIRE invoice and the invoice is the dues bill
    # itself (gross == the known dues level), the $key-collapse landed the
    # whole payment on a fee line — an attribution artifact, not a fee
    # (Wapato Point / Kemper / Slumber: one genuine WRA dues invoice each in
    # SLX). A genuine fee-only bill (gross != level, Smokin' Pete's $20 vs
    # $730) keeps its fee and retains nothing.
    _lvl = next((r.get("dues_level") for r in rows
                 if isinstance(r.get("dues_level"), (int, float))
                 and r.get("dues_level") > 0), None)
    if fee >= (gross or 0) - 0.005 and _lvl is not None \
            and abs((gross or 0) - _lvl) < 0.005:
        fee = 0.0
    amount = max(0.0, gross + max(0.0, adjustments) - fee)
    non_none = [r["balance"] for r in rows if r["balance"] is not None]
    if not non_none:
        return amount, 0.0  # unknown balance — can't determine paid

    # COLLECTED stays on the CHOSEN bill: gross + its adjustments − outstanding.
    # Sage attaches the credit to the bill as an AD (Kaspars, live: bill 3,620
    # carrying adjustments −2,040; WA Inns: 2,104 carrying −44), so once
    # `chosen` can no longer BE a credit note, this computes both live partial
    # credits exactly (1,580 / 2,060) — the redundant credit-IN row needs no
    # separate handling, and pure-IN void pairs are popped at cohort level
    # before valuation. Two rejected alternatives, both tried 2026-07-31:
    #   · subtracting negative-IN rows on top of adjustments DOUBLE-COUNTED the
    #     dual-represented credit (a paid member demoted to $0);
    #   · Σ per-invoice (total + own adj) DOUBLE-COUNTED multi-invoice cycles —
    #     county-fee members carry fee + dues + combined SAME-DAY invoices for
    #     one obligation, and summing them published seven territories' Nov
    #     retention at fake-100% (SouthKing NT: $2,875 retained on a $195 ask).
    # Which of a multi-invoice cycle's bills is THE ask remains Jen question
    # A1b-NEW — until ruled, the single-chosen model stands.
    outstanding = sum(b for b in non_none if b > 0)
    collected = max(0.0, gross + adjustments - outstanding - fee)
    # cent tolerance (amendment #4, Notable Restaurant Group): 710 − 473.33
    # − 236.67 leaves 2.84e-14, and "> 0" read that float crumb as a paid
    # member. Below half a cent is zero — count and dollars, one story.
    return amount, (0.0 if collected < 0.005 else collected)


def _retention_target_split(
    by_account: Dict,
    target_map: Dict[str, str],
    as_of: Optional[date] = None,
    payment_dates: Optional[Dict[str, date]] = None,
) -> Dict:
    """
    Split retention paid/billed/revenue counts into Target and Non-Target.

    Args:
        by_account:  The by_account dict from _retention_counts
                     {account_id: [{"balance": ..., "invoice_total": ...}]}
        target_map:  Output of build_target_map() for this territory.

    The Unknown bucket (accounts missing FTE/rooms size data, ~35% of billed
    accounts in practice) is folded into Non-Target, matching the v4 reporting
    convention (model.py) and the billables engine path. This guarantees
    Combined = Target + Non-Target = the true total with no leaked revenue.

    Returns:
        Dict with keys:
            paid_target, billed_target, revenue_retained_target, revenue_up_target,
            paid_non_target, billed_non_target, revenue_retained_non_target, revenue_up_non_target
    """
    counts = {
        TARGET:     {"paid": 0, "billed": 0, "rev_retained": 0.0, "rev_up": 0.0},
        NON_TARGET: {"paid": 0, "billed": 0, "rev_retained": 0.0, "rev_up": 0.0},
        UNKNOWN:    {"paid": 0, "billed": 0, "rev_retained": 0.0, "rev_up": 0.0},
    }

    for acct_id, rows in by_account.items():
        # THE ALLIED BACKSTOP. Allied members are removed from the cohort
        # upstream (ruled 2026-08-14), so `_allied` should never be set here.
        # The lock stays as a second line of defence: if a future path ever
        # re-admits one, it must not be able to land in Target and quietly
        # change the number the team is paid on.
        if rows and rows[0].get("_allied"):
            label = NON_TARGET
        else:
            label = target_map.get(acct_id, UNKNOWN)
        bucket = counts[label]

        # THE SAME strict close the combined total uses. Before 2026-07-30 this
        # called `_member_retained`, which only asks whether anything was ever
        # collected — so a member who paid AFTER the cycle shut counted as
        # retained here while the combined total (correctly) refused them.
        # Target + Non-Target exceeded the combined figure in 24 live cells, and
        # every TM sheet reads THIS path. One rule, one implementation.
        if rows and rows[0].get("_comp"):
            # A1 ruling: comped member — retained, $0/$0 (marker set by the
            # cohort builder; identical treatment to the combined loop).
            bucket["billed"] += 1
            bucket["paid"] += 1
            continue
        if rows and any(r.get("_bob") for r in rows):
            # BOB ruling (8/4): comped renewal counts at FACE, both sides.
            # The 8/6 wiring check caught this branch missing HERE while the
            # combined loop had it — the TM sheets read THIS path, so the
            # face ran one member and one dues-level low (Velvet's Big
            # Easy). One rule, both paths.
            face = next((r.get("dues_level") for r in rows
                         if isinstance(r.get("dues_level"), (int, float))
                         and r.get("dues_level") > 0), None) or max(
                (r.get("invoice_total") or 0 for r in rows), default=0.0)
            bucket["billed"] += 1
            bucket["paid"] += 1
            bucket["rev_up"] += float(face)
            bucket["rev_retained"] += float(face)
            continue

        first_payment = None
        if as_of is not None:
            if payment_dates:
                dates = [payment_dates[n] for n in
                         (str(r.get("invoice_number") or "") for r in rows)
                         if n in payment_dates]
                first_payment = min(dates) if dates else None
            has_paid = retained_as_of(rows, first_payment, as_of)
        else:
            has_paid = _member_retained(rows)
        # Dollars under the SAME close as the count (ratified 2026-07-31) —
        # a late payer's cash is reinstate cash. See retained_dollars_as_of.
        amount, retained = retained_dollars_as_of(rows, first_payment, as_of)

        bucket["billed"]       += 1
        bucket["rev_up"]       += amount
        bucket["rev_retained"] += retained   # netted: partial payers count their paid portion
        if has_paid:
            bucket["paid"] += 1

    t  = counts[TARGET]
    nt = counts[NON_TARGET]
    uk = counts[UNKNOWN]

    # Fold Unknown into Non-Target so Combined (T + NT) reconciles to the total.
    return {
        "paid_target":                    t["paid"],
        "billed_target":                  t["billed"],
        "revenue_retained_target":        round(t["rev_retained"], 2),
        "revenue_up_target":              round(t["rev_up"], 2),
        "paid_non_target":                nt["paid"]         + uk["paid"],
        "billed_non_target":              nt["billed"]       + uk["billed"],
        "revenue_retained_non_target":    round(nt["rev_retained"] + uk["rev_retained"], 2),
        "revenue_up_non_target":          round(nt["rev_up"]       + uk["rev_up"], 2),
    }


def _retention_counts(
    client: SLXClient,
    account_manager_id: str,
    month_str: str,
    fy_start: str,
    fy_end: str,
    fiscal_year_start: int,
    as_of: Optional[date] = None,
    payment_dates: Optional[Dict[str, date]] = None,
    fees_by_invoice: Optional[Dict[str, float]] = None,
    statuses: Optional[Dict[str, str]] = None,
    inactivations: Optional[Dict[str, date]] = None,
    bob_ids: Optional[set] = None,
    flags_out: Optional[Dict[str, list]] = None,
    lost_bundle: Optional[dict] = None,
) -> Tuple[int, int, int, int, float, float, Dict]:
    """
    Return (paid, billed, outstanding, unknown, revenue_retained, revenue_up_for_renewal)
    for a territory + dues bill month.

    Uses dlInvoiceHistoryHeader:
        - Account.AccountManager.Id join confirmed working (double cross-entity join)
        - Comment = dues bill month string (e.g. "3")
        - Balance = 0.0 → paid; > 0 → outstanding; None → unknown
        - Net_invoice = invoice dollar amount after discounts (Invoice_total field is null
          in practice — Net_invoice is the populated field, confirmed 2026-05-08)

    Deduplicates by AccountId to handle the known Sage sync duplicate artifact
    (same invoice imported twice: once Balance=0.0, once Balance=None).

    Dollar amount logic:
        - Per account, take the first non-null Invoice_total across all records for
          that account. The duplicate artifact means two rows may exist for the same
          invoice; both should carry the same amount, but one may be null.
        - revenue_retained          = sum of Invoice_total for paid accounts only
        - revenue_up_for_renewal    = sum of Invoice_total for ALL billed accounts
          (paid + outstanding + unknown)
        - If Invoice_total is null for an account, it contributes $0 to both sums.
          This is intentional — we don't want to invent a number.

    Returns:
        paid:                    unique accounts with at least one Balance=0.0 record
        billed:                  total unique accounts with any invoice for this month
        outstanding:             unique accounts with Balance>0 and NO Balance=0.0 record
        unknown:                 unique accounts with ONLY Balance=None records
        revenue_retained:        dollar sum for paid accounts
        revenue_up_for_renewal:  dollar sum for all billed accounts
        by_account:              raw {account_id: [row_dicts]} — used for Target/Non-Target split
    """
    # Comp_code='WRA' excludes PAC local fees, MSC payment-plan installments and
    # other ancillary billing. AD (adjustment) rows are fetched ALONGSIDE the IN
    # rows since 2026-07-28: an adjustment zeroes an invoice's Balance without
    # any money arriving, and reading that as "paid" shipped write-offs as
    # retained members (live cases: Cibrian LLC IN 510 + AD -510; Osteria La
    # Spiga IN 1,170 + AD -1,070 with $100 genuinely collected).
    # NO Comment clause in the query: void-and-rebill replacements carry a
    # BLANK comment and must be fetched so _group_invoice_rows can join them
    # to cohort members. Cohort membership itself is anchored client-side on
    # Comment == month_str.
    base_where = (
        f"Account.AccountManager.Id eq '{account_manager_id}' "
        f"and Comp_code eq 'WRA' "
        f"and (Invoice_Type eq 'IN' or Invoice_Type eq 'AD') "
        f"and Invoice_Date ge @{fy_start}@ "
        f"and Invoice_Date le @{fy_end}@"
    )

    # Fetch all records for this territory + month — now includes Invoice_total
    records = client._fetch_all("dlInvoiceHistoryHeader", where=base_where, page_size=200)

    # CM fetched in its OWN query with its OWN window (R1 = option A, ruled
    # 2026-08-12): a credit memo voids an invoice and zeroes its Balance
    # without money arriving, so a voided cycle read as "paid" — 10 members /
    # $17,105, proven 10/10 in the ledger. The window is invoice-start →
    # close+6 (NOT the invoice window): a CM is issued whenever accounting
    # gets to it — the four NorthKing Oct CMs postdate the invoice window
    # entirely, which is the same "current state rewriting a closed month"
    # wrinkle as the RRO flip. A separate query also means the IN/AD fetch
    # and everything downstream of it (grouping, netting, fees) is untouched.
    _, cm_end = _allocation_window(int(month_str), fiscal_year_start)
    cm_rows = client._fetch_all(
        "dlInvoiceHistoryHeader",
        where=(f"Account.AccountManager.Id eq '{account_manager_id}' "
               f"and Comp_code eq 'WRA' and Invoice_Type eq 'CM' "
               f"and Invoice_Date ge @{fy_start}@ "
               f"and Invoice_Date le @{cm_end}@"),
        select="Invoice_number,Invoice_Type,Net_invoice,Comment",
        page_size=200)

    # C11 (2026-08-12): rows the territory fetch can never see — members whose
    # records were flipped to retro/house users — arrive pre-resolved from
    # lost_cohort.collect_lost_cohort. Supplement, never re-scope: the guard
    # skips anything the territory fetch already returned, by invoice number
    # AND by (WRA number, bill month) — a flip pair can re-bill the same cycle
    # under a new number. Statuses and flip dates ride along so the ratified
    # cohort rules below judge these members like everyone else.
    if lost_bundle:
        _have_inv = {str(r.get("Invoice_number") or "") for r in records}
        _have_cust = {(str(r.get("CustomerNo") or "").strip(),
                       str(r.get("Comment") or "").strip()) for r in records}
        for _lr in lost_bundle.get("records", ()):
            _inv = str(_lr.get("Invoice_number") or "")
            _key = (str(_lr.get("CustomerNo") or "").strip(),
                    str(_lr.get("Comment") or "").strip())
            if _inv in _have_inv or (_key[0] and _key in _have_cust):
                continue
            records.append(_lr)
            _have_inv.add(_inv)
            _have_cust.add(_key)
        _have_cm = {str(r.get("Invoice_number") or "") for r in cm_rows}
        cm_rows = cm_rows + [
            r for r in lost_bundle.get("cm_rows", ())
            if str(r.get("Invoice_number") or "") not in _have_cm]
        if lost_bundle.get("statuses"):
            statuses = {**(statuses or {}), **lost_bundle["statuses"]}
        if lost_bundle.get("inactivations"):
            inactivations = {**(inactivations or {}),
                             **lost_bundle["inactivations"]}

    if not records:
        return 0, 0, 0, 0, 0.0, 0.0, {}

    by_account = _group_invoice_rows(records, cohort_comment=month_str)
    _removed_by: Dict[str, str] = {}    # account id -> the rule that claimed it
    # Ledger evidence that this month HAS a cohort, captured before the rules
    # start removing members (feeds GATE C below).
    invoiced_accounts = {
        r.get("Accountid") or (r.get("Account") or {}).get("$key")
        for r in records
        if r.get("Invoice_Type", "IN") == "IN"
        and str(r.get("Comment") or "").strip() == str(month_str)
    } - {None}

    # ONE cMemberGens batch serves three ratified rules (2026-07-28) — A2
    # first-cycle, the roster anchor, and D2 allied — because its records carry
    # EnrolledDate, Duesbillmonth and MembershipProduct together. (Fetched by
    # Account.Id batches, cursor-safe, no select= per the cMemberGens quirk.)
    try:
        from reports.membership_performance_tracker.logic.drops import _parse_slx_date

        # Blank-comment-only accounts are cohort CANDIDATES pending a roster check.
        candidates = set()
        for r in records:
            if r.get("Invoice_Type", "IN") != "IN":
                continue
            # 2026-08-04 (Serious Soul Cafe class): BOB invoices carry TEXT
            # comments ('2026 Dues - BOB Initiative'), which are neither the
            # numeric cohort comment nor blank — they were invisible to every
            # bill-month cohort. Any NON-NUMERIC comment is now a candidate;
            # the ratified roster anchor (Duesbillmonth + membership product)
            # decides admission, same as the blank-comment Deb Green path.
            _cmt = str(r.get("Comment") or "").strip()
            if _cmt and _cmt.isdigit():
                continue
            aid = r.get("Accountid") or (r.get("Account") or {}).get("$key")
            if aid and aid not in by_account:
                candidates.add(aid)

        member_recs: Dict[str, dict] = {}
        for rec in fetch_by_id_batches(
                client, "cMemberGens", list(by_account) + sorted(candidates),
                page_size=100, request_delay=0.05):
            aid = (rec.get("Account") or {}).get("$key")
            if aid and aid not in member_recs:
                member_recs[aid] = rec

        # ROSTER ANCHOR: admit a candidate only when their own Duesbillmonth
        # says this is their cycle (Deb Green Group: sole bill blank-commented)
        # AND they actually hold a membership product — a productless member
        # record has no dues relationship to renew, and its blank-comment
        # invoices are retro-program fee pass-throughs, not asks (Ada's
        # Technical Books: $63.27 WRA invoice == its own 'Retro Fee Adj' line;
        # both CRM surfaces exclude it).
        roster_ids = {
            aid for aid in candidates
            if str(member_recs.get(aid, {}).get("Duesbillmonth") or "").strip()
            == str(int(month_str))
            and (member_recs.get(aid, {}).get("MemrsProductID")
                 or member_recs.get(aid, {}).get("MembershipProduct"))}
        if roster_ids:
            by_account = _group_invoice_rows(records, cohort_comment=month_str,
                                             extra_anchor_ids=roster_ids)
        # AFTER any roster re-group — a rebuild creates fresh row dicts and
        # would wipe earlier stamps (caught in review, 8/4).
        attach_dues_levels(client, by_account, member_recs)

        # R1 = OPTION A (ruled 2026-08-12): a cycle whose every charge was
        # voided by credit memos leaves BOTH sides of the fraction — the
        # member was never actually asked to renew. Jen's billing sheets
        # carry none of these members; adopting her treatment (together with
        # the flip fix and R5) reproduced her trackers exactly: NorthKing Oct
        # 34/35, EastKing Oct 26/27, Snohomish Jan 19/22.
        for aid in _cm_cancelled_accounts(by_account, cm_rows, month_str):
            if by_account.pop(aid, None) is not None:
                _removed_by[aid] = ("charge voided by credit memo — never "
                                    "billed (R1, 8/12)")

        # D2 (billables, 2026-07-16), applied to retention 2026-07-28: allied is
        # decided by the membership PRODUCT — Dick's Restaurant Supply is Type
        # 'Corporate' with product 'Allied Corporate', and Jennifer's own Allied
        # PDF classifies that shape allied. Hospitality retention excludes them;
        # missing product data NEVER shrinks the cohort.
        def _product_name(prod):
            if isinstance(prod, dict):
                cache = getattr(client, "_product_name_cache", None)
                if cache is None:
                    cache = {pr.get("$key"): (pr.get("Name") or "")
                             for pr in client._fetch_all("products", select="Name",
                                                         page_size=200)}
                    client._product_name_cache = cache
                return cache.get(prod.get("$key"), "")
            return str(prod or "")
        for aid in list(by_account):
            prod = member_recs.get(aid, {}).get("MembershipProduct")
            if prod is not None and "allied" in _product_name(prod).lower():
                # RULED 2026-08-14 (Steven Sweeney, Marla Fruit, Jennifer
                # Hurley): allied is OUT of hospitality retention — count and
                # revenue, every band. This supersedes the 2026-08-11 ruling
                # that put them in as Non-Target, and restores the D2 outcome.
                #
                # Marla read Spokane at 93.2% against her own 95% (Jen: 24 of
                # 27, bill month 6). The four extra members were allied, riding
                # inside Non-Target. Allied retain poorly on purpose — "if they
                # leave, we leave" — and no TM carries a goal on them, so
                # including them measured people on work they are not
                # accountable for, on a line that decides commission.
                #
                # Removed, not flagged: a flag only works if every consumer
                # honours it, and the combined line did not. The reason string
                # is what Trace shows under "considered but excluded".
                by_account.pop(aid, None)
                _removed_by[aid] = ("allied member — tracked separately, not "
                                    "part of hospitality retention "
                                    "(ruled 2026-08-14)")

        # A2 (2026-07-14): a member's first bill is not a renewal. Unknown
        # enrollments stay in.
        enrolled_map: Dict[str, object] = {}
        for aid, rec in member_recs.items():
            dt = _parse_slx_date(rec.get("EnrolledDate"))
            enrolled_map[aid] = dt.date() if dt else None
        # A2 fix (meaning audit 2026-07-17): use the REAL fiscal-year start, not
        # int(fy_start[:4]). fy_start is the per-bill-month invoice window, whose
        # year = fiscal_year_start+1 for Jan-Sep, so the old line made the
        # exclusion a no-op for bill months 1-9 (Oct-Dec worked by coincidence).
        for aid in _first_cycle_ids(enrolled_map, int(month_str), fiscal_year_start):
            if by_account.pop(aid, None) is not None:
                _removed_by[aid] = "first cycle (A2)"

        # NET ASK (2026-07-28, Madeleine's/Cibrian; extended 2026-07-30 to the
        # credit-invoice vehicle): an ask fully rescinded and never reissued is
        # not an ask — nothing was requested by close, so there is nothing to
        # retain or fail to retain. Popping HERE (not in the valuation) keeps
        # count and dollars telling one story. See _cycle_rescinded.
        # FEES-OUT (2026-08-03): stamp each row with its invoice's fee so
        # netting reports dues-only. Before rescission/counting.
        attach_fees(by_account, fees_by_invoice or {})

        rescinded_names, comp_names = [], []
        for aid in list(by_account):
            verdict = comp_or_rescinded(by_account[aid], (statuses or {}).get(aid))
            if verdict in ("comp", "void") and aid in (bob_ids or ()):
                # BOB (ruled 2026-08-04): the comped renewal COUNTS at face —
                # "counting towards their revenue renewal" — on its own line,
                # never the comp line. (Same-day credits are how BOB bills are
                # issued, so the void discriminator does not apply to BOBs.)
                for r in by_account[aid]:
                    r["_bob"] = True
                continue
            if verdict == "comp":
                # A1 ruling: comped year — stays, retained, $0/$0. The row
                # marker travels with by_account so the T/NT split (a separate
                # call) applies the identical treatment without a signature
                # change on the 7-tuple return.
                for r in by_account[aid]:
                    r["_comp"] = True
                comp_names.append(aid)
                # DATA-DEFECT NET (2026-08-04): a comp whose credit landed
                # 1-6 days after the bill is kept but flagged for review.
                if flags_out is not None and any(
                        r.get("_comp_review") for r in by_account[aid]):
                    flags_out.setdefault("comp_review", []).append(
                        {"account": aid, "bill_month": int(month_str),
                         "defect": "comp credit landed <7 days after the "
                                   "bill — verify against the GS ledger"})
            elif verdict == "void":
                by_account.pop(aid)
                _removed_by[aid] = "bill voided (same-day reversal, not a comp)"
                if flags_out is not None:
                    flags_out.setdefault("voided_bills", []).append(
                        {"account": aid, "bill_month": int(month_str),
                         "defect": "bill and credit dated the SAME DAY — "
                                   "treated as a data-entry void, excluded "
                                   "from the cycle entirely"})
            elif verdict == "rescinded":
                by_account.pop(aid)
                _removed_by[aid] = "ask fully rescinded, never reissued"
                rescinded_names.append(aid)
                if flags_out is not None and (statuses or {}).get(aid) is None:
                    flags_out.setdefault("status_unknown_excluded", []).append(
                        {"account": aid, "bill_month": int(month_str),
                         "defect": "SLX carries no Status for this account — "
                                   "conservatively excluded as rescinded; "
                                   "if they are Active this is a comp"})
        if comp_names:
            warnings.warn(
                f"[retention] bill_month {month_str}: {len(comp_names)} comped "
                f"member(s) — bill credited off while still Active; counted "
                f"RETAINED at $0/$0 (A1 ruling 2026-07-31): "
                f"{', '.join(sorted(comp_names))}")
        if rescinded_names:
            warnings.warn(
                f"[retention] bill_month {month_str}: {len(rescinded_names)} "
                f"account(s) removed — ask fully rescinded, never reissued, "
                f"member no longer active ({', '.join(sorted(rescinded_names))}).")
    except Exception as exc:
        # GOLD-PLATE (2026-07-17): first-cycle exclusion is RATIFIED rule A2 —
        # silently skipping it ships INFLATED retention. Fail LOUD so a bad run is
        # caught, never shipped. If this fires, investigate the cMemberGens fetch.
        raise RuntimeError(
            f"[retention] first-cycle exclusion (ratified rule A2) FAILED for "
            f"manager={account_manager_id} bill_month={month_str}: "
            f"{type(exc).__name__}: {exc} — refusing to ship inflated retention"
        ) from exc

    # STRICT CLOSE (2026-07-28) — the denominator as it stood on `as_of`.
    # A member who exited mid-cycle stopped being billable; that loss is the
    # drops family's row, and counting it here would charge the rep twice.
    if as_of is not None and (statuses or inactivations):
        statuses = statuses or {}
        inactivations = inactivations or {}
        for acct_id in list(by_account):
            invoiced_on = next(
                (d for d in (_slx_day(r.get("invoice_date")) for r in by_account[acct_id])
                 if d is not None), None)
            if not in_cohort_as_of(statuses.get(acct_id), inactivations.get(acct_id),
                                   as_of, invoice_date=invoiced_on):
                by_account.pop(acct_id)
                _removed_by[acct_id] = "exited mid-cycle (a drop, not a miss)"

    # GATE C (2026-07-28) — CONSERVATION. An empty cohort is not itself a bug:
    # a one-member territory whose member is genuinely first-cycle really does
    # report 0/0, and deciding whether an exclusion was MEANT needs judgement,
    # which makes it validation, not a gate. What IS objective: every invoiced
    # account must end up either counted or claimed by a named rule. An account
    # that disappears with no rule owning it was lost, not excluded.
    unaccounted = invoiced_accounts - set(by_account) - set(_removed_by)
    if unaccounted:
        raise RuntimeError(
            f"[gate] retention lost {len(unaccounted)} account(s) for "
            f"manager={account_manager_id} bill_month={month_str}: they hold "
            f"Comment='{month_str}' WRA invoices but are neither in the cohort "
            f"nor claimed by any exclusion rule "
            f"({', '.join(sorted(unaccounted)[:5])}). Refusing to publish a "
            f"denominator that cannot be explained account by account.")

    paid = 0
    outstanding = 0
    unknown = 0
    revenue_retained = 0.0
    revenue_up_for_renewal = 0.0

    for acct_id, rows in by_account.items():
        balances = [row["balance"] for row in rows]
        # STRICT CLOSE: money that arrived after the window shut is a reinstate,
        # not a renewal. Undatable payments are never demoted (see retained_as_of).
        first_payment = None
        if payment_dates:
            dates = [payment_dates[n] for n in
                     (str(r.get("invoice_number") or "") for r in rows) if n in payment_dates]
            first_payment = min(dates) if dates else None
        has_paid = retained_as_of(rows, first_payment, as_of)
        has_outstanding = any(b is not None and b > 0 for b in balances)

        if rows and rows[0].get("_bob"):
            # BOB (ruled 2026-08-04): retained at FACE on both sides.
            faces = [r.get("invoice_total") for r in rows
                     if isinstance(r.get("invoice_total"), (int, float))
                     and r.get("invoice_total") > 0]
            face = max(faces) if faces else 0.0
            paid += 1
            revenue_up_for_renewal += face
            revenue_retained += face
            continue

        if rows and rows[0].get("_comp"):
            # A1 ruling: comped year — retained in the count, $0/$0 dollars
            # regardless of the rescission vehicle (an AD-writeoff comp would
            # otherwise contribute a phantom ask).
            paid += 1
            continue

        # Dollars under the SAME close as the count (ratified 2026-07-31).
        amount, retained = retained_dollars_as_of(rows, first_payment, as_of)
        revenue_up_for_renewal += amount
        revenue_retained += retained  # netted: Paid = Billed − Balance (partial payers count their paid portion)

        if has_paid:
            paid += 1
        elif has_outstanding:
            outstanding += 1
        else:
            unknown += 1

    billed = paid + outstanding + unknown
    # RECEIPTS (2026-07-31): the raw cohort with dispositions — record-only.
    # The renderer re-derives display rows with the same pure functions.
    from reports.membership_performance_tracker.logic import receipts_capture as _rc
    _rc.record("retention", f"{account_manager_id}|{month_str}", {
        "by_account": by_account, "removed_by": _removed_by,
        "as_of": as_of, "manager": account_manager_id, "bill_month": month_str})
    return paid, billed, outstanding, unknown, revenue_retained, revenue_up_for_renewal, by_account


def compute_retention_all_months(
    client: SLXClient,
    territory_user_map: Dict[str, str],
    bill_months: list,
    fiscal_year_start: int,
    request_delay: float = 0.20,
    include_target_split: bool = False,
    today: Optional[date] = None,
    invoiced_out: set = None,
    flags_out: Optional[Dict[str, list]] = None,
) -> Dict[int, Dict[str, Dict]]:
    """
    Compute retention for multiple bill months across all territories.

    Iterates territories × months, issuing one focused query per combination
    (server-side Comment filter + tight date window per month). This avoids the
    server-side pagination issue observed when fetching a large all-invoices batch
    and doing client-side Comment filtering: SLX reliably returns a smaller
    filtered result set but may omit records from large unfiltered fetches.

    Args:
        client:               Authenticated SLXClient instance.
        territory_user_map:   Dict mapping SLX user ID -> canonical territory name.
        bill_months:          List of integer bill months (e.g. [9,10,11,12,1,2,3]).
        fiscal_year_start:    Calendar year of FY start (e.g. 2025 for FY2025-26).
        request_delay:        Seconds between API calls.
        include_target_split: When True, adds T/NT breakdown to each row. Costs
                              one extra build_target_map() call per territory
                              (NOT per bill_month — the same map is reused across
                              all months for that territory).

    Returns:
        Dict keyed by bill_month (int) -> territory name -> retention dict.
        Same structure as compute_retention() per entry.
    """
    results: Dict[int, Dict[str, Dict]] = {m: {} for m in bill_months}

    # STRICT CLOSE (2026-07-28) — applied by construction, with no flag for an
    # operator to forget. Both lookups are batched OUTSIDE the inner loop:
    # payment dates once per bill month (the ledger is territory-blind), account
    # status once per territory (it does not vary by bill month). Per-member
    # queries here would turn a 12-month run into hours.
    today = today or date.today()
    # BOB roster (ruled 2026-08-04): CDiverseOwnership is populated ONLY on
    # BOB accounts (verified live 8/4 — all 39 True rows are the BOB list).
    try:
        bob_ids = {r.get("$key") or r.get("Id")
                   for r in client._fetch_all(
                       "accounts", where="CDiverseOwnership eq true",
                       select="Id,Status")} - {None}
    except Exception:
        bob_ids = set()
    payment_index: Dict[int, Dict[str, date]] = {}
    fee_index: Dict[int, Dict[str, float]] = {}
    for m in bill_months:
        # BATCH 1 (R1 ruled 2026-08-12): the payment window now reaches
        # close + 6 months (_allocation_window) and asks the server for the
        # POSITIVE line (_allocation_where). Late payments become visible and
        # the existing date test demotes them — the executives' "late is
        # late" rule finally enforced. See both docstrings for the evidence.
        _lrows = client._fetch_all(
            "payAllocationViews",
            where=_allocation_where(m, fiscal_year_start),
            page_size=200,
        )
        payment_index[m] = _payment_index_from_rows(_lrows)
        # PLAN B (8/4): the windowed shape hides fee lines (the $key-collapse)
        # — union with one batched by-account pass before parsing fees. The
        # payment index stays windowed-only: dues lines are the collapse's
        # usual survivors, and by-account MISSES dues rows (Pond class).
        fee_index[m] = fees_from_ledger_rows(
            union_fee_rows(client, _lrows, request_delay=request_delay))

    # C11 (2026-08-12): ONE unscoped pass finds invoices on flipped/house
    # records and resolves them to territories (lost_cohort docstring has the
    # full story). Best-effort by design — a failure here must degrade to the
    # pre-C11 numbers with a loud flag, never kill the nightly. The payment
    # index above needs no supplement: payAllocationViews is fetched
    # territory-blind, so lost members' payments were always in it.
    lost_by_territory: Dict[str, dict] = {}
    try:
        from reports.membership_performance_tracker.logic.lost_cohort import (
            collect_lost_cohort)
        lost_by_territory = collect_lost_cohort(
            client, fiscal_year_start, territory_user_map,
            request_delay=request_delay, flags_out=flags_out)
    except Exception as exc:
        if flags_out is not None:
            flags_out.setdefault("lost_cohort_failed", []).append(
                f"{type(exc).__name__}: {exc} — this run's cells exclude "
                f"flipped-record members (the pre-C11 behavior)")
        warnings.warn(f"[retention] lost-cohort supplement failed: {exc}")

    for user_id, territory in territory_user_map.items():
        if territory is None:
            continue

        # Build target map ONCE per territory — reused for every bill_month below.
        # status=None because billed accounts may have gone inactive after ITD.
        target_map = None
        if include_target_split:
            target_map = build_target_map(client, user_id, status=None,
                                          request_delay=request_delay)

        statuses = _account_statuses(client, user_id)
        inactivations = _inactivation_dates(client, user_id)

        for m in bill_months:
            fy_start, fy_end = _bill_month_date_window(m, fiscal_year_start)
            # Bound, not inlined: the T/NT split needs the SAME close the
            # combined total uses — computing it twice invites them to drift,
            # which is the defect this call site just had.
            cycle_as_of = as_of_date(m, fiscal_year_start, today)
            month_payments = payment_index.get(m)
            from reports.membership_performance_tracker.logic import receipts_capture as _rc
            _rc.record("retention_payments", str(m), month_payments or {})
            paid, billed, outstanding, unknown, rev_retained, rev_up, by_account = \
                _retention_counts(client, user_id, str(m), fy_start, fy_end,
                                  fiscal_year_start,
                                  as_of=cycle_as_of,
                                  payment_dates=month_payments,
                                  statuses=statuses,
                                  inactivations=inactivations,
                                  fees_by_invoice=fee_index.get(m),
                                  bob_ids=bob_ids,
                                  flags_out=flags_out,
                                  lost_bundle=lost_by_territory.get(territory))
            pct = (paid / billed * 100) if billed > 0 else None
            rev_pct = (rev_retained / rev_up * 100) if rev_up > 0 else None

            # COMP LINE (ruled 2026-08-04): the calc above is untouched —
            # comps count retained at $0/$0 — but the report now SHOWS how
            # many members were comped and the face dollars "we could have
            # collected". Face = the credited bill (largest positive invoice
            # of the cycle).
            comped_count = 0
            comped_dollars = 0.0
            bob_count = 0
            bob_dollars = 0.0
            # BAND SPLIT (ruled 8/5, supersedes the 8/4 combined-only): the
            # comp line shows in both band sections so the combined number
            # traces to its band. Unknown classification folds into
            # non-target — the same display convention the revenue side
            # uses. Invariant (tested): target + non-target == combined.
            comped_t_count = comped_nt_count = 0
            comped_t_dollars = comped_nt_dollars = 0.0
            from reports.membership_performance_tracker.logic.target import (
                TARGET as _TARGET)
            for _aid, _rows in (by_account or {}).items():
                _lvl = next((r.get("dues_level") for r in _rows
                             if isinstance(r.get("dues_level"), (int, float))
                             and r.get("dues_level") > 0), None)
                faces = [_lvl] if _lvl else [
                    r.get("invoice_total") for r in _rows
                    if isinstance(r.get("invoice_total"), (int, float))
                    and r.get("invoice_total") > 0]
                if any(r.get("_comp") for r in _rows):
                    comped_count += 1
                    face = max(faces) if faces else 0.0
                    comped_dollars += face
                    if (target_map or {}).get(_aid) == _TARGET:
                        comped_t_count += 1
                        comped_t_dollars += face
                    else:
                        comped_nt_count += 1
                        comped_nt_dollars += face
                elif any(r.get("_bob") for r in _rows):
                    bob_count += 1
                    bob_dollars += max(faces) if faces else 0.0

            row = {
                "pct": round(pct, 1) if pct is not None else None,
                "paid": paid,
                "billed": billed,
                "outstanding": outstanding,
                "unknown": unknown,
                "string": f"{paid}/{billed}",
                "revenue_retained": round(rev_retained, 2),
                "revenue_up_for_renewal": round(rev_up, 2),
                "revenue_retention_pct": round(rev_pct, 1) if rev_pct is not None else None,
                "comped_count": comped_count,
                "comped_dollars": round(comped_dollars, 2),
                "bob_count": bob_count,
                "bob_dollars": round(bob_dollars, 2),
            }
            # Band fields exist ONLY when a target map was actually built —
            # without one, "everything folds to NT" is indistinguishable
            # from data (the 8/5 backfill shipped exactly that garbage:
            # include_target_split defaulted False, the invariant gate
            # couldn't object because a fold always sums). Absent keys make
            # the mistake loud at the caller instead.
            if target_map is not None:
                row.update({
                    "comped_target_count": comped_t_count,
                    "comped_non_target_count": comped_nt_count,
                    "comped_target_dollars": round(comped_t_dollars, 2),
                    "comped_non_target_dollars": round(comped_nt_dollars, 2),
                })

            if include_target_split and by_account and target_map:
                row.update(_retention_target_split(by_account, target_map,
                                                   as_of=cycle_as_of,
                                                   payment_dates=month_payments))

            # Every account that held an invoice this year — feeds the
            # "carries a product but was never invoiced" check (Jen 7/30:
            # "that is a no-no. I'd like to see that"). Free: already fetched.
            if invoiced_out is not None and by_account:
                invoiced_out.update(by_account.keys())

            # Multi-user territories (Majors/NRA since 2026-07-13) must SUM across
            # seat users, not last-user-wins (finding #6/R3a — this is the ONLY
            # retention path the engine calls). Mirror single-month compute_retention.
            results[m][territory] = (_merge_retention_rows(results[m][territory], row)
                                     if territory in results[m] else row)
            time.sleep(request_delay)

    return results




def _fees_by_invoice(client, window_start: str, window_end: str) -> Dict[str, float]:
    """{invoice_number: county/local fee $} from the windowed ledger.

    FEES-OUT (ruled 2026-08-03, Jen: "remove all those county fees"): fee
    lines (/KINGCOFEE etc.) ride INSIDE dues invoices; the classifier is
    ledger_revenue.item_is_fee. One fee per code per invoice (the Capitol
    double-dip rule). The $key-collapse can hide fee lines from this window
    shape (BGP's fee was by-account-only) — the residue is measured against
    Jen's numbers; escalate to the union-fetch primitive where it misses.
    """
    from reports.membership_performance_tracker.logic.ledger_revenue import item_is_fee
    rows = client._fetch_all(
        "payAllocationViews",
        where=(f"Comp_code eq 'WRA' "
               f"and AllocationDate ge @{window_start}@ "
               f"and AllocationDate le @{window_end}@"),
        page_size=200,
    )
    return fees_from_ledger_rows(rows)


def fees_from_ledger_rows(rows) -> Dict[str, float]:
    """Parse fee lines out of already-fetched ledger rows (shared with the
    payment index so the cost stays ONE windowed query per bill month)."""
    from reports.membership_performance_tracker.logic.ledger_revenue import item_is_fee
    out: Dict[str, Dict[str, float]] = {}
    for row in rows:
        amt = row.get("Allocationamt")
        item = (row.get("Item_Id") or "").strip()
        inv = str(row.get("Invoice_number") or "").strip()
        if not inv or not item_is_fee(item):
            continue
        if isinstance(amt, (int, float)) and amt > 0:
            per = out.setdefault(inv, {})
            per[item] = max(per.get(item, 0.0), amt)
    return {inv: sum(codes.values()) for inv, codes in out.items()}


_PRODUCT_PRICE_CACHE: Dict[str, float] = {}


def attach_dues_levels(client, by_account: Dict, member_recs: Dict) -> None:
    """Stamp every cohort row with the account's DUES LEVEL — the membership
    product's price (cMemberGens.MemrsProductID → products.Price; verified
    live 8/4: Southern Kitchen RD<500 → 510.00 == the UI's Dues Level).
    Prices are memoized per run (a few dozen band products, one small OR
    batch per new set). Missing product/price = no stamp = invoice fallback.
    """
    want = {}
    for aid, rec in (member_recs or {}).items():
        pid = rec.get("MemrsProductID")
        if isinstance(rec.get("MembershipProduct"), dict):
            pid = rec["MembershipProduct"].get("$key") or pid
        if pid:
            want[aid] = pid
    missing = sorted({p for p in want.values() if p not in _PRODUCT_PRICE_CACHE})
    for i in range(0, len(missing), 12):
        chunk = missing[i:i + 12]
        ors = " or ".join(f"Id eq '{x}'" for x in chunk)
        try:
            for pr in client._fetch_all("products", where=f"({ors})",
                                        select="Price,DefaultPrice"):
                price = pr.get("Price") or pr.get("DefaultPrice")
                if isinstance(price, (int, float)) and price > 0:
                    _PRODUCT_PRICE_CACHE[pr.get("$key")] = float(price)
        except Exception:
            return                       # best effort — fallback is invoice math
        time.sleep(0.05)
    for aid, rows in by_account.items():
        price = _PRODUCT_PRICE_CACHE.get(want.get(aid))
        if price:
            # PER-ROOM lodging products (verified 8/4: Hometowne Kent
            # 15.50 x 133 rooms = her billed 2,061.50 exactly): a small
            # per-unit price with Rooms on file means level = price x rooms.
            # Flat bands (both restaurant and lodging) are all >= 100.
            rooms = (member_recs.get(aid) or {}).get("Rooms")
            if price < 100 and isinstance(rooms, (int, float)) and rooms > 0:
                price = price * rooms
            for r in rows:
                r["dues_level"] = price


def attach_fees(by_account: Dict, fees_by_invoice: Dict[str, float]) -> Dict:
    """Stamp each cohort row with its invoice's fee $ so the netting can
    report dues-only (fees-out, 2026-08-03). In place; returns by_account."""
    if not fees_by_invoice:
        return by_account
    for rows in by_account.values():
        for r in rows:
            fee = fees_by_invoice.get(str(r.get("invoice_number") or "").strip())
            if fee:
                r["fee"] = fee
    return by_account


def union_fee_rows(client, window_rows, request_delay: float = 0.05):
    """PLAN B — the by-account escalation (ruled by Jiho 8/3: "A then
    measure, escalate to B if it misses"; the 8/4 statewide member-diff
    measured the miss: ~159 members' asks carried fees the windowed shape
    never surfaced — the ledger's $key-collapse returns a different
    surviving line per query shape, and fee lines provably surface
    BY-ACCOUNT: Schwartz Brothers' /KINGCOFEE 65, CHAR Employment's
    /SERESTFEE 200, Lucky Eagle's /AHLA 513, BGP's /KINGCOFEE 260).

    Takes the windowed rows, collects the distinct AccountIds they carry,
    and runs ONE OR-BATCHED by-account pass (12 ids per query — live-probed
    8/4: ~0.1s per batch). Returns windowed + by-account rows deduped by
    (invoice, item, amount, date) so a line visible in both shapes counts
    once. The union feeds fees_from_ledger_rows unchanged.

    Known residual, documented in RULED-DIFFS R1: an UNPAID invoice has no
    allocation rows in any shape, so a fee inside a non-payer's ask stays
    invisible until the invoice is paid or written off (~11 members FY26).
    """
    aids = sorted({str(r.get("AccountId") or "").strip()
                   for r in window_rows} - {""})
    merged = list(window_rows)
    for i in range(0, len(aids), 12):
        chunk = aids[i:i + 12]
        ors = " or ".join(f"AccountId eq '{a}'" for a in chunk)
        try:
            merged.extend(client._fetch_all(
                "payAllocationViews", where=f"({ors})",
                select="Allocationamt,Item_Id,Invoice_number,AllocationDate"))
        except Exception:
            pass          # by-account misses rows too (Pond class) — best effort
        time.sleep(request_delay)
    seen, out = set(), []
    for r in merged:
        k = (str(r.get("Invoice_number") or "").strip(),
             (r.get("Item_Id") or "").strip(),
             r.get("Allocationamt"), str(r.get("AllocationDate") or ""))
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out
