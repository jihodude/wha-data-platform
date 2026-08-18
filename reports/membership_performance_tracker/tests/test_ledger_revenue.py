"""
test_ledger_revenue.py — the payment-ledger new-sales core (Jen's pinned rules,
2026-07-21, DECISIONS.md):

  · $$$   — each dues PAYMENT counts in the month it was PAID (AllocationDate).
  · #     — a member counts ONCE, in the month of their FIRST-EVER dues payment.
  · new vs rejoin — SUPERSEDED 2026-07-30 by the recorded call: a member who
    dropped and returns after ~6 months IS a new member ("That exact same
    member" — Jen), and the admin REWRITES the enroll date on such rejoins, so
    the EnrolledDate cohort needs no prior-payment screen at all. Within-window
    reinstates are excluded upstream by ReinstatedDate/Salescode-510.
  · A new member's later installments (within their first 12 months) are still
    NEW revenue in the months paid; after 12 months they're renewal money.

The core is pure: it takes allocation rows + each account's first-ever dues
payment date, and returns per-account month dollars + the count set.
"""
from datetime import date

from reports.membership_performance_tracker.logic.ledger_revenue import (
    summarize_month,
)


def _alloc(aid, d, amt, code="WRA", item="/RD<1M"):
    return {"AccountId": aid, "AllocationDate": d, "Allocationamt": amt,
            "Comp_code": code, "Item_Id": item}


DUES_ITEMS = {"/RD<1M", "/HD>50", "/AL<2M"}


def test_split_payment_lands_by_pay_month_count_once():
    """Jen's worked example: enroll June, pay $250 June + $250 July.
    June: $250 revenue AND the member counts. July: $250 revenue, NO count."""
    june = [_alloc("A", date(2026, 6, 10), 250.0)]
    july = [_alloc("A", date(2026, 7, 8), 250.0)]
    first_pay = {"A": date(2026, 6, 10)}

    jun_rev, jun_new = summarize_month(june, first_pay, DUES_ITEMS,
                                       date(2026, 6, 1), date(2026, 6, 30))
    jul_rev, jul_new = summarize_month(july, first_pay, DUES_ITEMS,
                                       date(2026, 7, 1), date(2026, 7, 31))
    assert jun_rev == {"A": 250.0} and jun_new == {"A"}
    assert jul_rev == {"A": 250.0} and jul_new == set()


def test_rejoin_counts_as_new_under_the_six_month_rule():
    """2026-07-30 (Jen, recorded): "They dropped six months later. They
    reinstate. It's considered a new member. That exact same member."
    `first_pay` is COHORT-scoped (first payment as this cohort's member), so a
    returning member whose cohort-first payment lands in June counts in June —
    their 2019 history is irrelevant.
    """
    allocs = [_alloc("R", date(2026, 6, 5), 730.0)]
    first_pay = {"R": date(2026, 6, 5)}
    rev, new = summarize_month(allocs, first_pay, DUES_ITEMS,
                               date(2026, 6, 1), date(2026, 6, 30))
    assert rev == {"R": 730.0} and new == {"R"}


def test_first_cycle_boundary_320_days():
    """Installments within ~10.5 months of the first payment are new revenue;
    beyond 320 days they're the year-2 anniversary renewal — excluded (real
    cases: Grassa 341d, Primo/Rosie's 356d, Village Inn 330d)."""
    inside = [_alloc("A", date(2026, 1, 1), 100.0)]     # 200 days
    outside = [_alloc("B", date(2026, 5, 30), 100.0)]   # 349 days
    first_pay = {"A": date(2025, 6, 15), "B": date(2025, 6, 15)}
    rev_in, _ = summarize_month(inside, first_pay, DUES_ITEMS,
                                date(2026, 1, 1), date(2026, 1, 31))
    rev_out, _ = summarize_month(outside, first_pay, DUES_ITEMS,
                                 date(2026, 5, 1), date(2026, 5, 31))
    assert rev_in == {"A": 100.0}, "day-200 installment is still new revenue"
    assert rev_out == {}, "day-349 payment is an anniversary renewal"


def test_non_dues_items_and_non_wra_never_count():
    """Claims/program money (CMP, MSC batch) and non-dues WRA items
    (sponsorships, reimbursements) are not sales."""
    allocs = [
        _alloc("A", date(2026, 6, 5), 766.76, code="MSC", item="/CMP2026"),
        _alloc("A", date(2026, 6, 5), 500.0, code="WRA", item="/XWRASPONSOR"),
        _alloc("A", date(2026, 6, 5), 510.0, code="WRA", item="/RD<1M"),
    ]
    first_pay = {"A": date(2026, 6, 5)}
    rev, new = summarize_month(allocs, first_pay, DUES_ITEMS,
                               date(2026, 6, 1), date(2026, 6, 30))
    assert rev == {"A": 510.0}, "only the dues item counts"
    assert new == {"A"}


def test_negative_allocations_net_refunds():
    """A refund/reversal allocation (negative) nets against the month."""
    allocs = [
        _alloc("A", date(2026, 6, 5), 545.0),
        _alloc("A", date(2026, 6, 6), -545.0),
        _alloc("A", date(2026, 6, 7), 575.0),
    ]
    first_pay = {"A": date(2026, 6, 5)}
    rev, _ = summarize_month(allocs, first_pay, DUES_ITEMS,
                             date(2026, 6, 1), date(2026, 6, 30))
    assert rev == {"A": 575.0}


def test_accounts_with_no_first_pay_are_skipped_loudly():
    """An in-month dues allocation whose account has no first-pay record is a
    pipeline bug (the history fetch missed it) — skip, never guess."""
    allocs = [_alloc("A", date(2026, 6, 5), 510.0)]
    rev, new = summarize_month(allocs, {}, DUES_ITEMS,
                               date(2026, 6, 1), date(2026, 6, 30))
    assert rev == {} and new == set()


def test_cohort_screen_keeps_rejoins_and_still_screens_fees():
    """2026-07-30 (recorded call): the prior-payer exclusion is DEAD. A member
    with 2021 paid history who re-enrolls IS new (Jen: "That exact same
    member") — the enroll-date rewrite upstream is the gate, not us. The
    screen's surviving jobs: fee identification BY INVOICE NUMBER (the
    reliable query shape) and the cohort first-pay date."""
    from reports.membership_performance_tracker.logic.ledger_revenue import cohort_screen

    class FakeSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            if entity == "dlInvoiceHistoryHeader":
                if "'POND'" in where:
                    return [{"Invoice_number": "148892", "Net_invoice": 1135.0, "Balance": 0.0,
                             "Invoice_Type": "IN", "Invoice_Date": date(2026, 6, 12)}]
                if "'REJOIN'" in where:
                    return [{"Invoice_number": "77", "Net_invoice": 495.0, "Balance": 0.0,
                             "Invoice_Type": "IN", "Invoice_Date": date(2021, 3, 1)},
                            {"Invoice_number": "148900", "Net_invoice": 730.0, "Balance": 0.0,
                             "Invoice_Type": "IN", "Invoice_Date": date(2026, 6, 3)}]
                return []
            if entity == "payAllocationViews" and "'148892'" in where:
                return [{"Allocationamt": 1070.0, "Item_Id": "/RD>1M"},
                        {"Allocationamt": 65.0, "Item_Id": "/SPOKCOFEE"}]
            return []

    kept, fees, _fp = cohort_screen(FakeSLX(), {"POND", "REJOIN", "FRESH"},
                                    date(2026, 6, 1), request_delay=0.0)
    assert kept == {"POND", "REJOIN", "FRESH"}, "rejoins are new members now"
    assert fees["POND"] == 65.0 and fees["FRESH"] == 0.0


def test_fee_subtraction_one_per_code():
    """Capitol class (7/22): two $65 SPOKCOFEE installments allocated against
    the same invoice — subtract the fee once per code, not per row."""
    from reports.membership_performance_tracker.logic.ledger_revenue import cohort_screen

    class FakeSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            if entity == "dlInvoiceHistoryHeader":
                return [{"Invoice_number": "9", "Net_invoice": 795.0, "Balance": 0.0,
                         "Invoice_Type": "IN", "Invoice_Date": date(2026, 6, 2)}]
            return [{"Allocationamt": 65.0, "Item_Id": "/SPOKCOFEE"},
                    {"Allocationamt": 65.0, "Item_Id": "/SPOKCOFEE"}]

    kept, fees, _fp = cohort_screen(FakeSLX(), {"CAP"}, date(2026, 6, 1), request_delay=0.0)
    assert fees["CAP"] == 65.0, "one fee per code per cycle"


def test_unknown_charge_code_warns_loudly():
    """Future-proofing (7/22): a never-seen charge code on a new member's
    invoice must WARN, not silently count — the announcement the CMP and
    county-fee misclassifications never got."""
    import warnings as w
    from reports.membership_performance_tracker.logic.ledger_revenue import cohort_screen

    class FakeSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            if entity == "dlInvoiceHistoryHeader":
                return [{"Invoice_number": "5", "Net_invoice": 600.0, "Balance": 0.0,
                         "Invoice_Type": "IN", "Invoice_Date": date(2026, 9, 3)}]
            return [{"Allocationamt": 90.0, "Item_Id": "/NEWMYSTERYFEE"}]

    with w.catch_warnings(record=True) as caught:
        w.simplefilter("always")
        cohort_screen(FakeSLX(), {"A"}, date(2026, 9, 1), request_delay=0.0)
    assert any("UNCLASSIFIED" in str(c.message) for c in caught), \
        "unknown codes must announce themselves"


def test_a_same_day_reversal_is_not_a_second_bill():
    """GOLD COAST KITCHEN, live 2026-08-11. The account's real shape:

        0147747 IN  +730.00  "2025-2026 Dues"          1/29
        0147748 IN  -730.00  "2025-2026 BOB Discount"  1/29
        0147750 IN  -730.00  "2025-2026 BOB Discount"  2/2
        0147750 AD  +730.00  "2025-2026 BOB Discount"  2/2

    One $730 comped membership. The BOB discount was entered a SECOND time on
    2/2 and immediately reversed on the same invoice, the same day — a
    data-entry correction, not money.

    The comp face summed every positive net, so the reversal counted as a
    second bill: face $1,460 against a $730 BOB share. That gap is the entire
    "no rule covers a half-comped BOB" question — there is no half-comp.

    An IN and its reversal on the SAME invoice, the SAME day, netting to zero
    is a correction. Net each (invoice, day) group before valuing anything.
    """
    from reports.membership_performance_tracker.logic.ledger_revenue import cohort_screen
    from datetime import date as _d

    class SLX:
        def _fetch_all(self, entity, where="", **kw):
            if entity == "dlInvoiceHistoryHeader":
                return [
                    {"Invoice_number": "0147747", "Net_invoice": 730.0,
                     "Balance": 0.0, "Invoice_Type": "IN", "Invoice_Date": _d(2026, 1, 29)},
                    {"Invoice_number": "0147748", "Net_invoice": -730.0,
                     "Balance": 0.0, "Invoice_Type": "IN", "Invoice_Date": _d(2026, 1, 29)},
                    {"Invoice_number": "0147750", "Net_invoice": -730.0,
                     "Balance": 0.0, "Invoice_Type": "IN", "Invoice_Date": _d(2026, 2, 2)},
                    {"Invoice_number": "0147750", "Net_invoice": 730.0,
                     "Balance": None, "Invoice_Type": "AD", "Invoice_Date": _d(2026, 2, 2)},
                ]
            return []

    comped = {}
    cohort_screen(SLX(), ["GOLDCOAST"], _d(2026, 1, 1),
                  request_delay=0, comped_out=comped)

    assert comped.get("GOLDCOAST") == 730.0, (
        f"one $730 comped membership, not two — got {comped.get('GOLDCOAST')}")
