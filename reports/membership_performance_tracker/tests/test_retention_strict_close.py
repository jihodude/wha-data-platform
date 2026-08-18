"""Strict close: retention is LIVE while a cycle is open, FROZEN once it shuts.

Ratified by Jiho 2026-07-28 ("3 strict fs"), validated two independent ways:

  · payment dates — freezing at end of M+1 reproduced 5 territories exactly, and
    TKP's ledger dates matched Jennifer's handwritten notes to the day.
  · status audit — the CRM's own BM5 cleanup was entered ~7/21 and BACKDATED to
    2026-06-30, i.e. the CRM closes the cycle on the same day this rule does.

One date governs both halves: as_of = min(today, cycle_close). While the cycle
is open as_of is today, so nothing is demoted and the number stays live. Once
it shuts, as_of stops moving and the number is immutable.
"""
from datetime import date

import pytest

from reports.membership_performance_tracker.logic import retention as R


# ---------------------------------------------------------------------------
# The close date, and the maturity gate that makes the metric live-then-frozen
# ---------------------------------------------------------------------------

def test_cycle_closes_at_the_end_of_the_month_after_the_bill_month():
    """1st notice M-1, 2nd M, 3rd M+1 — the pay window shuts when the 3rd
    notice's month ends (sourced, REFERENCE.md)."""
    assert R.cycle_close_date(5, 2025) == date(2026, 6, 30)    # BM5 → end of June
    assert R.cycle_close_date(2, 2025) == date(2026, 3, 31)


def test_cycle_close_crosses_the_calendar_year_and_the_fiscal_year():
    """BM12 closes in JANUARY of the next calendar year — inside the same FY."""
    assert R.cycle_close_date(12, 2025) == date(2026, 1, 31)
    assert R.cycle_close_date(10, 2025) == date(2025, 11, 30)
    # BM9 is the FY's last bill month; it closes in October, the NEXT FY
    assert R.cycle_close_date(9, 2025) == date(2026, 10, 31)


def test_a_february_close_lands_on_the_right_last_day_in_a_leap_year():
    assert R.cycle_close_date(1, 2023) == date(2024, 2, 29)
    assert R.cycle_close_date(1, 2024) == date(2025, 2, 28)


def test_an_open_cycle_is_governed_by_today_so_the_number_stays_live():
    """Nothing is frozen before the window shuts — a member still inside their
    90 days has not failed to renew, they simply have not paid YET."""
    assert R.as_of_date(5, 2025, today=date(2026, 6, 15)) == date(2026, 6, 15)


def test_a_closed_cycle_stops_moving_forever():
    """Once shut, the answer is the same on every future run — that is what
    makes a past month reproducible."""
    assert R.as_of_date(5, 2025, today=date(2026, 7, 1)) == date(2026, 6, 30)
    assert R.as_of_date(5, 2025, today=date(2030, 1, 1)) == date(2026, 6, 30)


# ---------------------------------------------------------------------------
# Numerator — money that arrived AFTER the close is not a renewal
# ---------------------------------------------------------------------------

def _rows(balance=0.0, total=730.0, adjustments=0.0):
    return [{"balance": balance, "invoice_total": total, "invoice_date": "a",
             "invoice_number": "1", "adjustments": adjustments}]


def test_payment_after_the_close_is_a_reinstate_not_a_renewal():
    """Duke Atlas / JMLM / Porthole, live cases: ledger dates in mid-July for a
    cycle that shut 6/30. Jennifer excludes them; so do we."""
    assert R.retained_as_of(_rows(), date(2026, 7, 16), date(2026, 6, 30)) is False


def test_payment_on_the_closing_day_itself_still_counts():
    assert R.retained_as_of(_rows(), date(2026, 6, 30), date(2026, 6, 30)) is True


def test_one_day_late_is_late():
    """Birch & Barley paid 7/01 against a 6/30 close. Jiho ruled strict
    2026-07-28, so this is a NAMED difference from her file, not a bug."""
    assert R.retained_as_of(_rows(), date(2026, 7, 1), date(2026, 6, 30)) is False


def test_an_undatable_payment_is_never_demoted():
    """payAllocationViews collapses multi-line payment documents to one
    arbitrary line ($key-collapse, PROBLEMS.md), so a genuinely-paid invoice can
    have NO allocation row. Absence of a date is not evidence of late payment —
    inventing a demotion from missing data would understate retention."""
    assert R.retained_as_of(_rows(), None, date(2026, 6, 30)) is True


def test_money_never_collected_is_not_retained_however_it_is_dated():
    """The strict close narrows the paid set; it can never widen it. A
    write-off still collected nothing (Cibrian: IN 510 + AD -510)."""
    written_off = _rows(balance=0.0, total=510.0, adjustments=-510.0)

    assert R.retained_as_of(written_off, date(2026, 5, 1), date(2026, 6, 30)) is False
    assert R.retained_as_of(_rows(balance=730.0), date(2026, 5, 1), date(2026, 6, 30)) is False


# ---------------------------------------------------------------------------
# Denominator — a member who exits mid-cycle is a DROP, not a retention miss
# ---------------------------------------------------------------------------

def test_a_member_who_exited_before_the_close_leaves_the_cohort():
    """Oly Corporation sold 2026-05-15, mid-cycle. They did not fail to renew;
    they ceased to exist as a billable member. That is the drops family's row,
    and counting it here would charge the rep for the same loss twice."""
    assert R.in_cohort_as_of("Closed", date(2026, 5, 15), date(2026, 6, 30),
                             invoice_date=date(2026, 4, 1)) is False


def test_a_member_inactivated_ON_the_closing_day_still_counts():
    """The CRM backdates its cleanup to exactly this day (nine BM5 accounts,
    StatusDate 2026-06-30). They were members through the close and they did not
    pay — that is precisely what a retention miss IS. Reproduces Jennifer's 146."""
    assert R.in_cohort_as_of("Inactive", date(2026, 6, 30), date(2026, 6, 30),
                             invoice_date=date(2026, 4, 1)) is True


def test_an_active_member_always_counts():
    assert R.in_cohort_as_of("Active", None, date(2026, 6, 30),
                             invoice_date=date(2026, 4, 1)) is True


def test_an_undated_inactivation_keeps_the_member_rather_than_guessing():
    assert R.in_cohort_as_of("Inactive", None, date(2026, 6, 30),
                             invoice_date=date(2026, 4, 1)) is True


def test_an_inactivation_older_than_the_invoice_is_impossible_and_ignored():
    """Deuce Restaurant Group, live case: the history log's most recent
    Active->Inactive is 2023-12-21, yet they were invoiced in 2026 — the
    reactivation was never logged, so the audit date is stale. A member cannot
    have left before the bill they were sent. Same class as the 2026-07-27 drops
    fix, where 41 members carried 2012-2024 dates for FY25/26 billing."""
    assert R.in_cohort_as_of("Inactive", date(2023, 12, 21), date(2026, 6, 30),
                             invoice_date=date(2026, 4, 1)) is True


def test_while_the_cycle_is_open_nobody_is_removed_for_being_inactivated_today():
    """as_of == today, and the test is `>= as_of`, so a member inactivated today
    is still counted today. The cohort only shrinks as the date advances past
    them, which is what makes the live number behave sensibly day to day."""
    assert R.in_cohort_as_of("Inactive", date(2026, 6, 15), date(2026, 6, 15),
                             invoice_date=date(2026, 4, 1)) is True


# ---------------------------------------------------------------------------
# The two date sources, batched — cost must not scale with member count
# ---------------------------------------------------------------------------

class _AllocSLX:
    """payAllocationViews is unfilterable by account but IS filterable by date
    range (probed 2026-07-28), so one query serves every territory."""
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def _fetch_all(self, entity, where="", select=None, page_size=200):
        self.calls.append((entity, where))
        return self.rows if entity == "payAllocationViews" else []


def _ms(y, m, d):
    from datetime import datetime, timezone
    return f"/Date({int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)})/"


def test_first_payment_dates_indexes_the_earliest_positive_allocation():
    """Earliest, because a member who paid in June and topped up in August
    renewed in June. Reversals (negative amounts) are not payments."""
    slx = _AllocSLX([
        {"Invoice_number": "A", "AllocationDate": _ms(2026, 6, 20), "Allocationamt": 500.0},
        {"Invoice_number": "A", "AllocationDate": _ms(2026, 8, 2),  "Allocationamt": 230.0},
        {"Invoice_number": "B", "AllocationDate": _ms(2026, 7, 16), "Allocationamt": 810.0},
        {"Invoice_number": "B", "AllocationDate": _ms(2026, 5, 1),  "Allocationamt": -50.0},
    ])

    index = R._first_payment_dates(slx, "2026-03-01", "2026-08-31")

    assert index["A"] == date(2026, 6, 20)
    assert index["B"] == date(2026, 7, 16)
    assert len(slx.calls) == 1, "one date-range query, not one per invoice"


def test_first_payment_dates_asks_only_for_dues_company_rows():
    slx = _AllocSLX([])
    R._first_payment_dates(slx, "2026-03-01", "2026-08-31")
    _entity, where = slx.calls[0]
    assert "Comp_code eq 'WRA'" in where
    assert "2026-03-01" in where and "2026-08-31" in where


class _StatusSLX:
    def __init__(self, ext):
        self.ext, self.calls = ext, 0

    def _fetch_all(self, entity, where="", select=None, page_size=200):
        if entity == "AccountExtension":
            self.calls += 1
            return self.ext
        return []


def test_inactivation_dates_come_from_one_query_per_territory():
    """StatusDate is the CRM's own 'when this status was set' — the exact
    semantic needed, and near-universally populated (the history log missed 9
    of 14 live BM5 cases and gave a stale 2023 date for a 10th)."""
    slx = _StatusSLX([
        {"Account": {"$key": "A1"}, "StatusDate": _ms(2026, 6, 30)},
        {"Account": {"$key": "A2"}, "StatusDate": None},
    ])

    index = R._inactivation_dates(slx, "U1")

    assert index["A1"] == date(2026, 6, 30)
    assert index.get("A2") is None
    assert slx.calls == 1, "one query per territory, not one per account"


# ---------------------------------------------------------------------------
# End to end through _retention_counts — the path the runner actually takes
# ---------------------------------------------------------------------------

class _CycleSLX:
    """One territory, three members: paid on time, paid late, never paid."""
    def __init__(self, comment="5"):
        self.invoices = [
            {"Accountid": "ONTIME", "Invoice_Type": "IN", "Invoice_number": "I1",
             "Comment": comment, "Balance": 0.0, "Net_invoice": 730.0, "Invoice_Date": _ms(2026, 4, 1)},
            {"Accountid": "LATE", "Invoice_Type": "IN", "Invoice_number": "I2",
             "Comment": comment, "Balance": 0.0, "Net_invoice": 810.0, "Invoice_Date": _ms(2026, 4, 1)},
            {"Accountid": "NEVER", "Invoice_Type": "IN", "Invoice_number": "I3",
             "Comment": comment, "Balance": 500.0, "Net_invoice": 500.0, "Invoice_Date": _ms(2026, 4, 1)},
        ]

    def _fetch_all(self, entity, where="", select=None, page_size=200):
        if entity == "dlInvoiceHistoryHeader":
            return self.invoices
        if entity == "cMemberGens":
            return [{"Account": {"$key": a}, "EnrolledDate": _ms(2020, 1, 1)}
                    for a in ("ONTIME", "LATE", "NEVER")]
        if entity == "payAllocationViews":
            return [
                {"Invoice_number": "I1", "AllocationDate": _ms(2026, 6, 20), "Allocationamt": 730.0},
                {"Invoice_number": "I2", "AllocationDate": _ms(2026, 7, 16), "Allocationamt": 810.0},
            ]
        return []


def test_a_closed_cycle_excludes_the_late_payer_end_to_end():
    """The whole point: Duke Atlas-style July payments stop counting as June
    renewals once the cycle has shut."""
    slx = _CycleSLX()

    paid, billed, *_ = R._retention_counts(
        slx, "U1", "5", "2026-02-01", "2026-07-31", 2025,
        as_of=date(2026, 6, 30),
        payment_dates=R._first_payment_dates(slx, "2026-02-01", "2026-08-31"))

    assert (paid, billed) == (1, 3), "on-time counts; late and never do not"


def test_the_same_cycle_while_still_OPEN_counts_the_late_payer():
    """Run mid-July with as_of=today and the July payment is simply a payment —
    the number is live until the window shuts. Same code, same data, one date."""
    slx = _CycleSLX()

    paid, billed, *_ = R._retention_counts(
        slx, "U1", "5", "2026-02-01", "2026-07-31", 2025,
        as_of=date(2026, 7, 20),
        payment_dates=R._first_payment_dates(slx, "2026-02-01", "2026-08-31"))

    assert (paid, billed) == (2, 3)


def test_without_an_as_of_the_behaviour_is_exactly_what_it_was_before():
    """Backwards compatibility: every existing caller and fixture passes no
    dates and must keep its old answer."""
    slx = _CycleSLX()

    paid, billed, *_ = R._retention_counts(slx, "U1", "5", "2026-02-01", "2026-07-31", 2025)

    assert (paid, billed) == (2, 3)


def test_a_mid_cycle_exit_leaves_the_denominator():
    """Oly Corporation class: sold in May, so not a failed renewal at all."""
    slx = _CycleSLX()

    paid, billed, *_ = R._retention_counts(
        slx, "U1", "5", "2026-02-01", "2026-07-31", 2025,
        as_of=date(2026, 6, 30),
        payment_dates=R._first_payment_dates(slx, "2026-02-01", "2026-08-31"),
        statuses={"NEVER": "Closed"},
        inactivations={"NEVER": date(2026, 5, 15)})

    assert (paid, billed) == (1, 2), "the mid-cycle exit is a DROP, not a miss"


def test_an_exit_backdated_to_the_closing_day_stays_in_the_denominator():
    """The nine live BM5 accounts the CRM backdated to 2026-06-30."""
    slx = _CycleSLX()

    paid, billed, *_ = R._retention_counts(
        slx, "U1", "5", "2026-02-01", "2026-07-31", 2025,
        as_of=date(2026, 6, 30),
        payment_dates=R._first_payment_dates(slx, "2026-02-01", "2026-08-31"),
        statuses={"NEVER": "Inactive"},
        inactivations={"NEVER": date(2026, 6, 30)})

    assert (paid, billed) == (1, 3)


# ---------------------------------------------------------------------------
# compute_retention_all_months — the entry point the engine calls
# ---------------------------------------------------------------------------

class _AllMonthsSLX(_CycleSLX):
    """Counts queries so the per-territory / per-month batching is enforced."""
    def __init__(self, comment="5"):
        super().__init__(comment)
        self.counts = {}

    def _fetch_all(self, entity, where="", select=None, page_size=200):
        self.counts[entity] = self.counts.get(entity, 0) + 1
        if entity == "dlInvoiceHistoryHeader" and "AccountManager" not in (where or ""):
            # C11's unscoped lost-cohort pass. Empty here: this fake's rows
            # would otherwise read as flipped-record members and its per-lost
            # AccountExtension singles (legitimate, ~dozens FY-wide, and
            # unbatchable — AccountExtension rejects OR-batches) would break
            # the per-TERRITORY batching count this guard exists to enforce.
            return []
        if entity == "accounts":
            return [{"Id": "NEVER", "AccountName": "Never Paid", "Status": "Inactive"}]
        if entity == "AccountExtension":
            return [{"Account": {"$key": "NEVER"}, "StatusDate": _ms(2026, 5, 15)}]
        return super()._fetch_all(entity, where, select, page_size)


def test_all_months_applies_the_strict_close_without_being_asked():
    """The product must be right BY CONSTRUCTION — no flag for an operator to
    forget. A closed cycle comes back frozen on every run, forever."""
    slx = _AllMonthsSLX()

    res = R.compute_retention_all_months(
        slx, {"U1": "TKP"}, bill_months=[5], fiscal_year_start=2025,
        request_delay=0.0, today=date(2026, 7, 20))

    row = res[5]["TKP"]
    assert row["paid"] == 1, "the July payer is a reinstate, not a June renewal"
    assert row["billed"] == 2, "the May exit is a drop, not a retention miss"
    assert row["string"] == "1/2"


def test_all_months_batches_the_date_lookups():
    """One allocation query per bill month and one status pair per territory —
    never per member, or a 12-month FY run would take hours."""
    slx = _AllMonthsSLX()

    R.compute_retention_all_months(slx, {"U1": "TKP", "U2": "Pierce"},
                                   bill_months=[5, 6], fiscal_year_start=2025,
                                   request_delay=0.0, today=date(2026, 7, 20))

    assert slx.counts["payAllocationViews"] == 2, "once per bill month"
    assert slx.counts["AccountExtension"] == 2, "once per territory"


def test_an_open_cycle_still_reports_live_through_all_months():
    """The SAME July 16 payment that is a reinstate against BM5 (closed 6/30) is
    an ordinary on-time renewal against BM6 (closes 7/31). Nothing about the
    payment changed — only which cycle it is being judged against. That is the
    whole design: one date, derived per bill month, no flags."""
    slx = _AllMonthsSLX(comment="6")

    res = R.compute_retention_all_months(
        slx, {"U1": "TKP"}, bill_months=[6], fiscal_year_start=2025,
        request_delay=0.0, today=date(2026, 7, 20))

    assert res[6]["TKP"]["paid"] == 2, "both payers are inside BM6's open window"


def test_as_of_date_default_today_path_works():
    """Regression: the today=None default called a renamed symbol and crashed —
    every other test passed today= explicitly, so none exercised the default."""
    assert R.as_of_date(5, 2025) == date(2026, 6, 30)   # BM5 long closed


def test_the_target_split_applies_the_same_strict_close_as_the_combined_total():
    """Found by an invariant sweep of the live 2026-07-30 grid: Target +
    Non-Target EXCEEDED the combined total in **24 cells**, always by 1-2
    members (EastKing Nov 6+3=9 vs 8; NorthKing Feb 14+7=21 vs 20).

    Cause: two paths, two rules. The combined total tested each member with
    `retained_as_of(rows, first_payment, as_of)` — the strict close, where money
    arriving after the cycle shut is a reinstate, not a renewal. The T/NT split
    tested `_member_retained(rows)`, which only asks whether anything was ever
    collected, and did not even RECEIVE `as_of`, so it could not apply the rule.

    Every TM sheet reads the SPLIT. So the per-territory numbers counted late
    payers as retained while the statewide number did not — one rule, computed
    two ways, exactly the "scattered instead of central" failure.
    """
    from datetime import date
    from reports.membership_performance_tracker.logic.retention import (
        _retention_target_split)

    # One Target member, billed 1,000, fully paid — but paid AFTER the close.
    by_account = {"LATE": [{"invoice_total": 1000.0, "balance": 0.0,
                            "invoice_date": "2026-04-01", "adjustments": 0.0,
                            "invoice_number": "INV-1"}]}
    target_map = {"LATE": "Target"}
    close = date(2026, 6, 30)
    paid_after_close = {"INV-1": date(2026, 7, 15)}

    out = _retention_target_split(by_account, target_map,
                                  as_of=close, payment_dates=paid_after_close)

    assert out["billed_target"] == 1, "they were billed — they stay in the cohort"
    assert out["paid_target"] == 0, \
        "money after the close is a reinstate, not a renewal — same rule as the total"

    # Paid BEFORE the close → retained, under both paths.
    on_time = {"INV-1": date(2026, 6, 2)}
    out2 = _retention_target_split(by_account, target_map,
                                   as_of=close, payment_dates=on_time)
    assert out2["paid_target"] == 1


def test_voided_cycle_is_not_a_negative_ask():
    """A credit invoice that reverses the cycle's bill is not an ask of MINUS
    money — it is no ask at all.

    LIVE (2026-07-30, TKP BM2, account A6UJ9A002MSJ): invoice 0147151 billed
    +1,891 on 01-02, invoice 0147795 credited -1,891 on 02-24. `_netted_retained`
    picks the LATEST-dated row as the ask, so it picked the credit note and
    returned an ask of -1,891. A negative ask shrinks the territory denominator,
    which is how TKP Mar Target published 11,012 / 10,175 = 108.2% revenue
    retention. Four other cells over 100% share the mechanism (worst
    Spokane/NE Feb Non-Target at 120.6%).

    This is NOT the contested write-off question in the docstring — that one is
    about downward AD adjustment rows. This is a negative IN row, the
    void-and-rebill pattern `_group_invoice_rows` already recognises.
    """
    from reports.membership_performance_tracker.logic.retention import _netted_retained
    rows = [
        {"balance": 0.0, "invoice_total": 1891.0, "invoice_date": "/Date(1767312000000)/",
         "invoice_number": "0147151", "adjustments": 0.0},
        {"balance": 0.0, "invoice_total": -1891.0, "invoice_date": "/Date(1771891200000)/",
         "invoice_number": "0147795", "adjustments": 0.0},
    ]
    ask, retained = _netted_retained(rows)
    assert ask == 0.0, f"a voided cycle asks for nothing, got {ask}"
    assert retained == 0.0, f"a voided cycle retains nothing, got {retained}"
    assert ask >= 0.0, "the ask can never be negative"


def test_zero_dollar_bill_still_counts_as_paid():
    """Guard: the void rule must not swallow the legitimate $0 bill, which has
    no negative row and still counts as retained (retention.py:499)."""
    from reports.membership_performance_tracker.logic.retention import _netted_retained
    ask, retained = _netted_retained(
        [{"balance": 0.0, "invoice_total": 0.0, "invoice_date": "/Date(1767312000000)/",
          "invoice_number": "0140001", "adjustments": 0.0}])
    assert (ask, retained) == (0.0, 0.0)


def test_cycle_rescinded_predicate():
    """One predicate, two rescission vehicles, one ratified meaning.

    The 7/28 NET-ASK rule (Madeleine's/Cibrian) pops an account whose ask was
    fully rescinded and never reissued — but only examined ADJUSTMENT-bearing
    accounts. The credit-INVOICE vehicle (2026-07-30: nine live accounts, e.g.
    Governor Hotel Olympia +1,891 then −1,891, all still Active, none dropped,
    none RRO) slipped past it into the count path, where the zero-billed edge
    read credit-zeroed balances as a fully-paid $0 bill and counted the member
    RETAINED — while the dollars path excluded them. Count and dollars must
    tell one story.
    """
    from reports.membership_performance_tracker.logic.retention import _cycle_rescinded

    void_pair = [  # credit-invoice vehicle (Governor Hotel shape)
        {"balance": 0.0, "invoice_total": 1891.0, "invoice_number": "A", "adjustments": 0.0},
        {"balance": 0.0, "invoice_total": -1891.0, "invoice_number": "B", "adjustments": 0.0},
    ]
    assert _cycle_rescinded(void_pair) is True

    write_off = [  # adjustment vehicle (Cibrian shape) — was already covered
        {"balance": 0.0, "invoice_total": 510.0, "invoice_number": "A", "adjustments": -510.0},
    ]
    assert _cycle_rescinded(write_off) is True

    comp_bill = [  # a genuine $0 bill is a bill — comped members stay
        {"balance": 0.0, "invoice_total": 0.0, "invoice_number": "A", "adjustments": 0.0},
    ]
    assert _cycle_rescinded(comp_bill) is False

    partial_credit = [  # net ask still positive — not rescinded
        {"balance": 0.0, "invoice_total": 1000.0, "invoice_number": "A", "adjustments": 0.0},
        {"balance": 0.0, "invoice_total": -300.0, "invoice_number": "B", "adjustments": 0.0},
    ]
    assert _cycle_rescinded(partial_credit) is False

    still_owed = [  # money still outstanding — the ask stands
        {"balance": 500.0, "invoice_total": 500.0, "invoice_number": "A", "adjustments": -500.0},
    ]
    assert _cycle_rescinded(still_owed) is False


def test_voided_cycle_is_not_counted_retained():
    """The count path must agree with the dollars path: a voided cycle is not
    a fully-paid $0 bill, even though the credit zeroes every balance."""
    from reports.membership_performance_tracker.logic.retention import _member_retained
    rows = [
        {"balance": 0.0, "amount": 1891.0, "invoice_number": "A"},
        {"balance": 0.0, "amount": -1891.0, "invoice_number": "B"},
    ]
    assert _member_retained(rows) is False


def test_true_zero_bill_still_counts_retained():
    """Guard: the comp-bill edge survives the void distinction."""
    from reports.membership_performance_tracker.logic.retention import _member_retained
    assert _member_retained([{"balance": 0.0, "amount": 0.0, "invoice_number": "A"}]) is True


def test_partial_credit_never_makes_the_ask_negative():
    """LIVE (2026-07-31 census): WA Independent Inns Network — billed +2,104
    (Jan 2, comment '2'), credited −44 on Feb 2. The credit is the LATEST row,
    so `chosen` made the cycle's ask −$44. A credit note is not a bill; the
    ask comes from the positive invoice. And mirroring the ratified AD
    asymmetry (write-offs reduce COLLECTED only), the credit reduces what was
    collected: they netted 2,060, not 2,104."""
    from reports.membership_performance_tracker.logic.retention import _netted_retained
    # Fixture mirrors the LIVE rows: Sage attaches the credit to the bill as
    # an AD adjustment AND emits it as its own IN row (symmetric +44 on it).
    rows = [
        {"balance": 0.0, "invoice_total": 2104.0, "invoice_date": "/Date(1767312000000)/",
         "invoice_number": "0147119", "adjustments": -44.0},
        {"balance": 0.0, "invoice_total": -44.0, "invoice_date": "/Date(1769990400000)/",
         "invoice_number": "0147711", "adjustments": 44.0},
    ]
    ask, retained = _netted_retained(rows)
    assert ask == 2104.0, f"the ask is the positive bill, got {ask}"
    assert retained == 2060.0, f"collected nets the credit once, got {retained}"


def test_same_day_partial_credit_is_order_independent():
    """LIVE: Kaspars Catering — +3,620 and −2,040 both dated 2026-03-01. The
    winner of the date tie depended on server row order. Either order must
    yield ask 3,620, collected 1,580 (what they actually netted; balance 0)."""
    from reports.membership_performance_tracker.logic.retention import _netted_retained
    # Live rows verbatim, including the AD shadow on both sides of the pair.
    a = {"balance": 0.0, "invoice_total": 3620.0, "invoice_date": "/Date(1772323200000)/",
         "invoice_number": "0147982", "adjustments": -2040.0}
    b = {"balance": 0.0, "invoice_total": -2040.0, "invoice_date": "/Date(1772323200000)/",
         "invoice_number": "0148142", "adjustments": 2040.0}
    assert _netted_retained([a, b]) == (3620.0, 1580.0)
    assert _netted_retained([b, a]) == (3620.0, 1580.0)


def test_dual_represented_credit_counts_once():
    """LIVE (NorthKing bm4, Kaspars Catering, 2026-07-31): Sage represents ONE
    credit TWICE — as its own IN row (−2,040) AND as an AD adjustment attached
    to the bill (adjustments −2,040 on the bill, symmetric +2,040 on the credit
    row). The first partial-credit fix subtracted `credits` on top of
    `adjustments`, double-counting: retained 3,620−2,040−2,040 → 0, demoting a
    member who actually netted 1,580. Per-invoice (total + own adjustments)
    self-cancels the dual representation: (3,620−2,040) + (−2,040+2,040) = 1,580."""
    from reports.membership_performance_tracker.logic.retention import (
        _netted_retained, _member_retained)
    rows = [
        {"balance": 0.0, "invoice_total": 3620.0, "invoice_date": "/Date(1772323200000)/",
         "invoice_number": "0147982", "adjustments": -2040.0},
        {"balance": 0.0, "invoice_total": -2040.0, "invoice_date": "/Date(1772323200000)/",
         "invoice_number": "0148142", "adjustments": 2040.0},
    ]
    ask, retained = _netted_retained(rows)
    assert ask == 3620.0, f"ask is the bill, got {ask}"
    assert retained == 1580.0, f"the credit counts once, got {retained}"
    assert _member_retained([{**r, "amount": r["invoice_total"]} for r in rows]) is True


def test_multi_invoice_cycle_is_never_summed():
    """REGRESSION GUARD (2026-07-31, the v4 fake-100% November): county-fee
    members carry THREE same-day invoices for ONE obligation — fee $65, dues
    $1,755, combined $1,820. A per-invoice-sum formula counted the money twice
    (retained $3,640 on an ask of one invoice), publishing seven territories'
    Nov retention at fake-100% (SouthKing NT: $2,875 retained / $195 ask =
    1,474%). Until Jen rules which invoice IS the ask (A1b-NEW), the
    single-chosen model stands: retained equals the chosen bill's own money,
    never the sum of the triple."""
    from reports.membership_performance_tracker.logic.retention import _netted_retained
    rows = [
        {"balance": 0.0, "invoice_total": 65.0, "invoice_date": "/Date(1756771200000)/",
         "invoice_number": "0145703", "adjustments": 0.0},
        {"balance": 0.0, "invoice_total": 1755.0, "invoice_date": "/Date(1756771200000)/",
         "invoice_number": "0145828", "adjustments": 0.0},
        {"balance": 0.0, "invoice_total": 1820.0, "invoice_date": "/Date(1756771200000)/",
         "invoice_number": "0145954", "adjustments": 0.0},
    ]
    ask, retained = _netted_retained(rows)
    assert ask in (65.0, 1755.0, 1820.0), f"ask must be ONE bill, got {ask}"
    assert retained == ask, f"retained follows the chosen bill, got {retained} vs ask {ask}"
    assert retained < 3640.0, "the triple must never be summed"


# ---------------------------------------------------------------------------
# One close for members AND dollars (ratified 2026-07-31, Jiho: "those members
# and dollars act regarding the same retention insight, so they must abide by
# the same semantic rules")
# ---------------------------------------------------------------------------

def test_late_money_is_not_renewal_money():
    """Duke Atlas / JMLM / Porthole, live cases: paid mid-July against a 6/30
    close. The COUNT already demoted them; the DOLLARS did not — which is how
    Snohomish May published 11/12 members but 100% revenue retention (the 12th
    member's late cash still counted). Same member, same story: the ask stays
    (they were billed), the retained dollars go with the count."""
    rows = _rows(balance=0.0, total=730.0)
    ask, retained = R.retained_dollars_as_of(rows, date(2026, 7, 16), date(2026, 6, 30))
    assert ask == 730.0, "the ask never moves — they were billed"
    assert retained == 0.0, "late cash is reinstate cash, not renewal cash"


def test_on_time_money_still_counts_in_full():
    ask, retained = R.retained_dollars_as_of(_rows(balance=0.0, total=730.0),
                                             date(2026, 6, 30), date(2026, 6, 30))
    assert (ask, retained) == (730.0, 730.0)


def test_undatable_money_is_never_demoted_in_dollars_either():
    """The $key-collapse carve extends to dollars: absence of a date is not
    evidence of late payment. Narrowing-only, exactly like the count."""
    ask, retained = R.retained_dollars_as_of(_rows(balance=0.0, total=730.0),
                                             None, date(2026, 6, 30))
    assert (ask, retained) == (730.0, 730.0)


def test_combined_invoice_is_the_ask_for_same_day_split_billing():
    """A1b RULED 2026-07-31 (Jiho: "combined yes. its their invoice so why not
    count") — evidence: all 7 visible payment allocations on the county-fee
    triples sit on the COMBINED invoice, zero on the splits. Live rows,
    A6UJ9A0021BA (SouthKing, Nov book): fee $65 + dues $1,755 + combined
    $1,820, same day. The combined row (= the sum of the others) is the bill;
    the splits are bookkeeping. Ask 1,820, collected 1,820 — the $65/member
    oddity dies."""
    from reports.membership_performance_tracker.logic.retention import _netted_retained
    rows = [
        {"balance": 0.0, "invoice_total": 65.0, "invoice_date": "/Date(1756771200000)/",
         "invoice_number": "0145703", "adjustments": 0.0},
        {"balance": 0.0, "invoice_total": 1755.0, "invoice_date": "/Date(1756771200000)/",
         "invoice_number": "0145828", "adjustments": 0.0},
        {"balance": 0.0, "invoice_total": 1820.0, "invoice_date": "/Date(1756771200000)/",
         "invoice_number": "0145954", "adjustments": 0.0},
    ]
    assert _netted_retained(rows) == (1820.0, 1820.0)


def test_comped_year_counts_retained_at_zero_dollars():
    """A1 RULED 2026-07-31 (Jiho): a comped member STAYS — retained in the
    count, $0/$0 in dollars ("if they see high retention but didn't get cash
    that would skew judgement"). Detection is mechanical: cycle rescinded +
    status still Active ⇒ comp. Validated against notes: 7 of the 9 live
    cases are explicitly comped/waived (Governor reno, Latah road closure,
    Skyway fire, Mt Spokane, Silverbeard's BOB, Velvet's, Falls Terrace),
    zero contrary; the two silent ones ride the same rule (blessed)."""
    from reports.membership_performance_tracker.logic.retention import comp_or_rescinded
    void_pair = [
        {"balance": 0.0, "invoice_total": 1891.0, "invoice_number": "A", "adjustments": 0.0},
        {"balance": 0.0, "invoice_total": -1891.0, "invoice_number": "B", "adjustments": 0.0},
    ]
    assert comp_or_rescinded(void_pair, "Active") == "comp"
    assert comp_or_rescinded(void_pair, "Inactive") == "rescinded"
    assert comp_or_rescinded(void_pair, None) == "rescinded"
    normal = [{"balance": 0.0, "invoice_total": 730.0, "invoice_number": "A", "adjustments": 0.0}]
    assert comp_or_rescinded(normal, "Active") is None


def test_fees_leave_both_sides_of_retention_dollars():
    """RULED 2026-08-03 (Jen: "remove all those county fees"; Jiho extended to
    retention): the ask and the retained report DUES ONLY. The combined
    invoice stays 'the bill' for payment matching (A1b), but its embedded
    county-fee portion leaves both sides. County triple (A6UJ9A0021BA shape):
    combined $1,820 with a $65 King County fee → ask 1,755, retained 1,755.
    BGP shape (single invoice, embedded $260 fee): 2,695 → 2,435."""
    from reports.membership_performance_tracker.logic.retention import _netted_retained
    triple = [
        {"balance": 0.0, "invoice_total": 65.0, "invoice_date": "/Date(1756771200000)/",
         "invoice_number": "0145703", "adjustments": 0.0},
        {"balance": 0.0, "invoice_total": 1755.0, "invoice_date": "/Date(1756771200000)/",
         "invoice_number": "0145828", "adjustments": 0.0},
        {"balance": 0.0, "invoice_total": 1820.0, "invoice_date": "/Date(1756771200000)/",
         "invoice_number": "0145954", "adjustments": 0.0, "fee": 65.0},
    ]
    assert _netted_retained(triple) == (1755.0, 1755.0)
    bgp = [{"balance": 0.0, "invoice_total": 2695.0, "invoice_date": "/Date(1784678400000)/",
            "invoice_number": "0149139", "adjustments": 0.0, "fee": 260.0}]
    assert _netted_retained(bgp) == (2435.0, 2435.0)


def test_fee_only_payment_retains_zero_dues():
    """A member who paid only their $65 fee has retained no dues."""
    from reports.membership_performance_tracker.logic.retention import _netted_retained
    rows = [{"balance": 1755.0, "invoice_total": 1820.0, "invoice_date": "a",
             "invoice_number": "X", "adjustments": 0.0, "fee": 65.0}]
    ask, retained = _netted_retained(rows)
    assert ask == 1755.0
    assert retained == 0.0, f"cash 65 was the fee, dues retained 0 — got {retained}"


def test_fee_lines_hidden_from_windowed_shape_are_recovered_by_account():
    """Plan B (Jiho 8/3: "A then measure, escalate to B if it misses" — the
    8/4 statewide diff MEASURED the miss: ~159 members' asks carried county
    fees the windowed shape never surfaced; Schwartz Brothers' /KINGCOFEE 65
    and CHAR Employment's /SERESTFEE 200 are live-proven by-account-only).
    The fee index must union the windowed rows with ONE BATCHED by-account
    pass over the accounts seen in the window — so a fee line the window
    collapse hides still nets out of ask and retained."""
    class ShapedSLX(_AllMonthsSLX):
        def __init__(self):
            super().__init__()
            self.acct_batches = 0
        def _fetch_all(self, path, where="", **kw):
            if path == "payAllocationViews" and "AccountId eq" in where:
                self.acct_batches += 1
                return [{"Invoice_number": "INV-A1", "Item_Id": "/KINGCOFEE",
                         "Allocationamt": 65.0,
                         "AllocationDate": "/Date(1750000000000)/"}]
            rows = super()._fetch_all(path, where=where, **kw)
            if path == "payAllocationViews":
                # production windowed rows carry AccountId (no select filter)
                rows = [dict(r, AccountId=r.get("AccountId") or "AC1")
                        for r in rows]
            return rows

    slx = ShapedSLX()
    R.compute_retention_all_months(slx, {"U1": "TKP"}, bill_months=[5],
                                   fiscal_year_start=2025, request_delay=0.0,
                                   today=date(2026, 7, 20))
    assert slx.acct_batches >= 1, "the by-account escalation pass must run"

    # the helper itself: windowed rows carry the account ids; the by-account
    # pass recovers the hidden fee line and the union feeds the fee parser
    rows = [{"AccountId": "AC1", "Invoice_number": "INV-A1",
             "Item_Id": "/RD>5M", "Allocationamt": 2435.0,
             "AllocationDate": "/Date(1750000000000)/"}]
    merged = R.union_fee_rows(ShapedSLX(), rows, request_delay=0.0)
    fees = R.fees_from_ledger_rows(merged)
    assert fees.get("INV-A1") == 65.0, f"hidden fee must be recovered: {fees}"


def test_union_fee_rows_dedupes_shape_overlap():
    """A line visible in BOTH shapes must count once (the Capitol double-dip
    rule already guards per-code, but identical duplicate rows must not
    upgrade a real fee to 2x via different codes)."""
    class EchoSLX:
        def _fetch_all(self, path, where="", **kw):
            return [{"Invoice_number": "I1", "Item_Id": "/KINGCOFEE",
                     "Allocationamt": 65.0,
                     "AllocationDate": "/Date(1750000000000)/"}]
    rows = [{"AccountId": "A1", "Invoice_number": "I1",
             "Item_Id": "/KINGCOFEE", "Allocationamt": 65.0,
             "AllocationDate": "/Date(1750000000000)/"}]
    merged = R.union_fee_rows(EchoSLX(), rows, request_delay=0.0)
    assert R.fees_from_ledger_rows(merged).get("I1") == 65.0


def test_dues_level_ask_overrides_invoice_net():
    """DUES-LEVEL ASK (Jiho GO 2026-08-04 evening; transcript 1:37-1:39 —
    accounting DELETES and recreates invoices on dues adjustments, so the
    invoice is not a stable record; her export's Billed = products.Price via
    the membership product). When rows carry dues_level, the ask IS the
    level and retained is capped at it — the unrecoverable hidden-fee class
    (+65 et al.) dies by construction. No dues_level -> old invoice math
    unchanged (never drop members on missing data)."""
    from datetime import date
    # invoice 1135 = level 1070 + a $65 county fee the ledger HIDES; paid full
    rows = [{"invoice_number": "I1", "invoice_total": 1135.0, "balance": 0.0,
             "adjustments": 0.0, "invoice_date": "/Date(1745000000000)/",
             "dues_level": 1070.0}]
    ask, retained = R.retained_dollars_as_of(rows, date(2026, 5, 3),
                                             date(2026, 6, 30))
    assert ask == 1070.0, "ask = dues level, not invoice net"
    assert retained == 1070.0, "retained capped at the level (fee noise gone)"

    # partial payer: collected 300 of the 1070 level
    rows_p = [{"invoice_number": "I2", "invoice_total": 1135.0, "balance": 835.0,
               "adjustments": 0.0, "invoice_date": "/Date(1745000000000)/",
               "dues_level": 1070.0}]
    ask_p, ret_p = R.retained_dollars_as_of(rows_p, date(2026, 5, 3),
                                            date(2026, 6, 30))
    assert ask_p == 1070.0
    assert ret_p == 300.0, "partial collection reports what actually arrived"

    # unpaid: level ask, zero retained
    rows_u = [{"invoice_number": "I3", "invoice_total": 1135.0, "balance": 1135.0,
               "adjustments": 0.0, "invoice_date": "/Date(1745000000000)/",
               "dues_level": 1070.0}]
    ask_u, ret_u = R.retained_dollars_as_of(rows_u, None, date(2026, 6, 30))
    assert ask_u == 1070.0 and ret_u == 0.0

    # no level on file -> exact old behavior
    rows_n = [{"invoice_number": "I4", "invoice_total": 1135.0, "balance": 0.0,
               "adjustments": 0.0, "invoice_date": "/Date(1745000000000)/"}]
    ask_n, ret_n = R.retained_dollars_as_of(rows_n, date(2026, 5, 3),
                                            date(2026, 6, 30))
    assert ask_n == 1135.0 and ret_n == 1135.0


def test_per_room_lodging_level_multiplies_by_rooms():
    """Hometowne Kent class (verified 8/4): product price 15.50/room x 133
    rooms = 2,061.50 = her Billed exactly. Flat bands (>=100) untouched."""
    class SLX:
        def _fetch_all(self, ent, where="", **kw):
            if ent == "products":
                return [{"$key": "P_ROOM", "Price": 15.5},
                        {"$key": "P_FLAT", "Price": 2650.5}]
            return []
    R._PRODUCT_PRICE_CACHE.clear()
    by_acct = {"H1": [{"invoice_number": "a"}], "H2": [{"invoice_number": "b"}]}
    recs = {"H1": {"MemrsProductID": "P_ROOM", "Rooms": 133},
            "H2": {"MemrsProductID": "P_FLAT", "Rooms": 190}}
    R.attach_dues_levels(SLX(), by_acct, recs)
    assert by_acct["H1"][0]["dues_level"] == 15.5 * 133
    assert by_acct["H2"][0]["dues_level"] == 2650.5, "flat band never multiplied"


def test_a_cycle_with_no_positive_allocation_is_not_retained():
    """PROVEN 8/11 (union of both ledger access paths, 4 live cases):

    Hampton Inn Walla Walla Mar, Hampton Inn Bellevue Apr, nYne Jan and
    Mazatlan Nov are each counted RETAINED with dollars (527 / 576 /
    297.50 / 730 = $2,130.50) while their only allocation is NEGATIVE —
    the payment was reallocated onto the member's annual invoice, leaving
    the stub invoice at a zero balance with no cash against it.

    Retention currently has no payment date for these cycles and falls
    back to inferring payment from the zero balance. That is the same
    "a zero balance is not a payment" trap that correctly keeps the 18
    credit-memo November accounts OUT of retention; it must apply in both
    directions.

    A cycle needs at least one POSITIVE dues allocation to count retained.
    """
    import pytest
    pytest.skip("documents a proven defect; implementation deferred — see "
                "docs/handoff/2026-08-11-DECISION-BRIEF.md")
