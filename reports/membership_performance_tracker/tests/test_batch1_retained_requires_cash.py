"""BATCH 1 — retained requires dated, positive cash (R1 ruled 2026-08-12).

Three surgical changes, each with named live members behind it:

1. THE ALLOCATION WINDOW reaches close + 6 months. The old window ended with
   the pay window (M+1), so a payment landing later was invisible, the member
   undatable, and `retained_as_of` — which explicitly never demotes what it
   cannot date — counted them on Balance=0 alone. 20 members, $22,364.92,
   every one already named with its payment date. The demotion logic itself is
   proven by the 33 members it already catches; only the evidence was missing.

2. THE POSITIVE FILTER moves SERVER-SIDE. payAllocationViews returns ONE line
   per payment document, and WHICH line depends on the where clause (invoice
   0145480: −50.00 plain, +5,550.00 with `Allocationamt gt 0`). The production
   fetch filtered positives client-side, so a document whose projected line was
   negative silently vanished. A4 added the filter to `_first_payment_dates` —
   a function the nightly does not use. This is A4 landing on the real path.

3. CREDIT-MEMO-VOIDED CYCLES leave BOTH sides (R1 = option A). Production
   never fetched CM, so a charge cancelled by credit memo left Balance=0 and
   read as paid — 10 members, $17,105, proven 10/10 in the ledger. Jen's
   billing sheets do not carry them at all: a voided charge never reached a
   billing run, so the member was never asked to renew. Applying A alongside
   A1 and R5 reproduced her trackers EXACTLY (34/35, 26/27, 19/22).
"""
from datetime import date

import pytest

from reports.membership_performance_tracker.logic.retention import (
    _allocation_window, _allocation_where, _bill_month_date_window,
    _cm_cancelled_accounts, _payment_index_from_rows)


# ---------------------------------------------------------------------------
# 1 · the allocation window
# ---------------------------------------------------------------------------

def test_allocation_window_starts_where_the_invoice_window_starts():
    """Early payments were never the problem — do not widen backwards."""
    inv_start, _ = _bill_month_date_window(10, 2025)
    alloc_start, _ = _allocation_window(10, 2025)
    assert alloc_start == inv_start


@pytest.mark.parametrize("bm,fy,member,paid,close", [
    # the named B1 members whose real payment dates set the requirement
    (10, 2025, "Four Points Bellingham", date(2026, 5, 30), date(2025, 11, 30)),
    (1,  2025, "Hotel Hotel Hostel",     date(2026, 7, 22), date(2026, 2, 28)),
    # bm9 is evaluated against fiscal_year_start − 1 (engine.py FY-EDGE,
    # 2026-07-14): the FY25-26 Oct column is the Sep-2025 cohort
    (9,  2024, "Soi",                    date(2025, 12, 18), date(2025, 10, 31)),
    (2,  2025, "Hilton Garden Inn Renton", date(2026, 6, 3), date(2026, 3, 31)),
])
def test_allocation_window_reaches_the_measured_late_payers(bm, fy, member, paid, close):
    """close + 6 months, because the observed lateness runs 1.6–6 months —
    the cutoff was read off the list of 20, not guessed."""
    start, end = _allocation_window(bm, fy)
    assert start <= paid.isoformat() <= end, (
        f"{member}: paid {paid}, window [{start}..{end}] must see it")


def test_allocation_window_is_close_plus_six_months_exactly():
    # bm10: close = 2025-11-30 → end = 2026-05-31
    assert _allocation_window(10, 2025)[1] == "2026-05-31"
    # bm12: close = 2026-01-31 → end = 2026-07-31
    assert _allocation_window(12, 2025)[1] == "2026-07-31"
    # bm9: close = 2026-10-31 → end = 2027-04-30 (crosses the FY boundary on purpose:
    # a late payment for an FY25-26 bill is still late, whatever year it lands in)
    assert _allocation_window(9, 2025)[1] == "2027-04-30"


# ---------------------------------------------------------------------------
# 2 · the server-side positive filter
# ---------------------------------------------------------------------------

def test_allocation_where_asks_for_the_positive_line():
    w = _allocation_where(10, 2025)
    assert "Allocationamt gt 0" in w, (
        "without the server-side filter the projection can return the "
        "reversal line and the document vanishes from the index")
    assert "Comp_code eq 'WRA'" in w


def test_allocation_where_uses_the_widened_window():
    w = _allocation_where(10, 2025)
    assert "@2026-05-31@" in w
    assert "@2025-07-01@" in w or "@" + _allocation_window(10, 2025)[0] + "@" in w


def test_payment_index_still_ignores_client_side_negatives():
    """Belt and braces: even with the server filter, a negative row that
    arrives must never date a payment."""
    rows = [
        {"Invoice_number": "0001", "Allocationamt": -50.0,
         "AllocationDate": "/Date(1767225600000)/"},
        {"Invoice_number": "0002", "Allocationamt": 700.0,
         "AllocationDate": "/Date(1767225600000)/"},
    ]
    idx = _payment_index_from_rows(rows)
    assert "0001" not in idx
    assert "0002" in idx


# ---------------------------------------------------------------------------
# 3 · credit-memo-voided cycles leave both sides (R1 = A)
# ---------------------------------------------------------------------------

def _in_row(inv, net, comment="10"):
    # the GROUPED shape from _group_invoice_rows — what _retention_counts
    # actually holds. The first draft used raw SData keys here; the tests
    # passed and the live eval failed 12/12, because the production rows
    # carry invoice_number/invoice_total, not Invoice_number/Net_invoice.
    return {"invoice_number": inv, "invoice_total": net,
            "balance": 0.0, "adjustments": 0.0, "invoice_date": None}


def _cm_row(inv, net):
    return {"Invoice_number": inv, "Invoice_Type": "CM", "Net_invoice": net}


def test_toreros_shape_every_charge_voided_leaves():
    """Torero's, proven in the ledger: billed 65, 1,755 and 1,820 — every one
    cancelled by an exactly-offsetting CM. They were never actually charged."""
    by_account = {"T1": [_in_row("A", 65.0), _in_row("B", 1755.0), _in_row("C", 1820.0)]}
    cms = [_cm_row("A", -65.0), _cm_row("B", -1755.0), _cm_row("C", -1820.0)]
    assert _cm_cancelled_accounts(by_account, cms, "10") == {"T1"}


def test_a_partial_credit_does_not_remove():
    """A CM smaller than the charge is a price adjustment, not a void —
    the member still owes/paid the remainder and stays in the cohort."""
    by_account = {"P1": [_in_row("A", 1000.0)]}
    assert _cm_cancelled_accounts(by_account, [_cm_row("A", -400.0)], "10") == set()


def test_void_and_rebill_keeps_the_member():
    """Sparta's-safe: if one invoice was voided but a live rebill exists in
    the same cohort, the member WAS billed — only fully-voided cycles leave."""
    by_account = {"R1": [_in_row("A", 730.0), _in_row("B", 730.0)]}
    assert _cm_cancelled_accounts(by_account, [_cm_row("A", -730.0)], "10") == set()


def test_a_cm_on_someone_elses_invoice_does_nothing():
    by_account = {"X1": [_in_row("A", 510.0)]}
    assert _cm_cancelled_accounts(by_account, [_cm_row("ZZZ", -510.0)], "10") == set()


def test_no_cms_no_removals():
    by_account = {"X1": [_in_row("A", 510.0)]}
    assert _cm_cancelled_accounts(by_account, [], "10") == set()


def test_a_live_rebill_row_keeps_the_member():
    """void-and-rebill: the grouping already joins the blank-comment rebill
    row for anchored members. It carries no offsetting CM, so it fails its
    own cancellation test and keeps the member — no special casing."""
    by_account = {"V1": [_in_row("A", 730.0), _in_row("B", 730.0)]}
    assert _cm_cancelled_accounts(by_account, [_cm_row("A", -730.0)], "10") == set()
