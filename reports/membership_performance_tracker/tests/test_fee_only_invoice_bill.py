"""Fee-only supplemental invoice must never be the cycle's bill.

Found 2026-08-06 by Jiho on the Trace page (Thai Ginger, EastKing Oct):
accounting bills county/alliance fees as their OWN invoice dated after the
dues bill. The latest-positive-invoice rule (built for credit-note pairs)
made the fee supplement THE BILL, and fees-out (dues only) then reported a
fully-paid cycle as $0 collected — "paid in window" with retained 0.
Blast-radius scan: 9 members / 8 cells, ~$12.4K of collected renewal
revenue published as $0 (amendment #3 on the July close).

Rule: when any dues-bearing positive invoice exists, a fee-only invoice
cannot be chosen. Genuine fee-only cycles (no dues-bearing invoice at all)
keep their existing path.
"""
from reports.membership_performance_tracker.logic.retention import (
    retained_dollars_as_of)


def _inv(number, total, fee, date_ms, balance=0.0, level=1755.0):
    return {"balance": balance, "invoice_total": total,
            "invoice_date": f"/Date({date_ms})/", "invoice_number": number,
            "adjustments": 0.0, "dues_level": level, "fee": fee}


def test_fee_only_supplement_is_not_the_bill():
    # Thai Ginger's literal rows: dues bill $1,800 (fee $100, paid) dated
    # Aug 1; fee-only supplement $85 (fee $85, paid) dated Oct 21.
    rows = [_inv("0145339", 1800.0, 100.0, 1754006400000),
            _inv("0146312", 85.0, 85.0, 1761004800000)]
    ask, retained = retained_dollars_as_of(rows, None, None)
    assert ask == 1755.0          # dues-level ask (ruled 8/4)
    assert retained == 1700.0     # 1,800 paid minus the $100 embedded fee


def test_genuine_fee_only_cycle_keeps_existing_path():
    # No dues-bearing invoice at all -> the fee invoice stays chosen and
    # dues-only reporting yields $0 (unchanged behavior, no level known).
    rows = [_inv("0150000", 85.0, 85.0, 1761004800000, level=None)]
    ask, retained = retained_dollars_as_of(rows, None, None)
    assert ask == 0.0
    assert retained == 0.0


def test_credit_note_pair_unchanged():
    # WA-Inns class: dues bill then a later credit NOTE (negative) — the
    # credit is not a positive, so the bill stays chosen exactly as before.
    rows = [_inv("0146382", 1480.0, None, 1754006400000, level=1415.0),
            {"balance": 0.0, "invoice_total": -44.0,
             "invoice_date": "/Date(1761004800000)/", "invoice_number": "X",
             "adjustments": 0.0, "dues_level": 1415.0, "fee": None}]
    ask, retained = retained_dollars_as_of(rows, None, None)
    assert ask == 1415.0
    assert retained == 1415.0
