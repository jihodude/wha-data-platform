"""
test_retention_netting.py — retention $ must NET (Paid = Billed − Balance),
not all-or-nothing.

Old behavior: if any invoice balance hit 0, the FULL amount counted as retained;
a partial payer counted $0. Netting: a partial payer contributes their paid
portion, an unpaid account $0, unknown balance $0, a fully-paid account the full
amount. The Sage dedup artifact (same invoice twice: Balance=0.0 and None) must
not double-count.
"""
from reports.membership_performance_tracker.logic.retention import _netted_retained


def _rows(*pairs):
    """pairs of (balance, invoice_total)."""
    return [{"balance": b, "invoice_total": t, "invoice_date": None} for b, t in pairs]


def test_fully_paid_returns_full_amount():
    # Sage dedup: same invoice twice (Balance=0.0 paid record + Balance=None original)
    assert _netted_retained(_rows((0.0, 2000.0), (None, 2000.0))) == (2000.0, 2000.0)


def test_partial_payment_nets_to_paid_portion():
    # billed 2000, still-open balance 500 → retained 1500
    assert _netted_retained(_rows((500.0, 2000.0))) == (2000.0, 1500.0)


def test_unpaid_retains_zero():
    assert _netted_retained(_rows((2000.0, 2000.0))) == (2000.0, 0.0)


def test_unknown_balance_retains_zero():
    # all balances None → can't determine paid → $0 retained (don't invent)
    assert _netted_retained(_rows((None, 2000.0))) == (2000.0, 0.0)


def test_retained_never_negative():
    amount, retained = _netted_retained(_rows((3000.0, 2000.0)))
    assert (amount, retained) == (2000.0, 0.0)


def test_null_invoice_total_is_zero_billed():
    assert _netted_retained(_rows((0.0, None), (None, None))) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# Write-offs (2026-07-28): Balance 0 by ADJUSTMENT is not Balance 0 by PAYMENT
# ---------------------------------------------------------------------------

def test_full_write_off_is_not_retained():
    """Cibrian LLC, live case: IN 510 + AD -510, Balance 0.0.

    Nothing was collected — the balance was zeroed by an adjustment document,
    not a payment. The old Balance==0 test read forgiveness as payment; the
    ledger has no allocation and Jennifer's file shows paid=0.
    """
    from reports.membership_performance_tracker.logic.retention import (
        _member_retained, _netted_retained)
    rows = [{"balance": 0.0, "invoice_total": 510.0, "invoice_date": "b",
             "adjustments": -510.0}]

    amount, retained = _netted_retained(rows)

    assert amount == 510.0            # they WERE billed — stays in the cohort
    assert retained == 0.0            # but collected nothing
    assert _member_retained(rows) is False


def test_partial_write_off_with_residual_collected_is_retained():
    """Osteria La Spiga, live case: IN 1,170 + AD -1,070, Balance 0.0.

    Arithmetic says $100 was collected — corroborated by Jennifer's own note
    'Selling (Paid 6/10)'. A partial payer counts as retained (ratified rule),
    at the collected amount, not the full bill.
    """
    from reports.membership_performance_tracker.logic.retention import (
        _member_retained, _netted_retained)
    rows = [{"balance": 0.0, "invoice_total": 1170.0, "invoice_date": "b",
             "adjustments": -1070.0}]

    amount, retained = _netted_retained(rows)

    assert retained == 100.0
    assert _member_retained(rows) is True


def test_no_adjustment_behaviour_is_unchanged():
    """Accounts without AD rows must net exactly as before the fix."""
    from reports.membership_performance_tracker.logic.retention import (
        _member_retained, _netted_retained)
    full = [{"balance": 0.0, "invoice_total": 730.0, "invoice_date": "b"}]
    partial = [{"balance": 532.03, "invoice_total": 730.0, "invoice_date": "b"}]

    import pytest
    assert _netted_retained(full) == (730.0, 730.0)
    amount, retained = _netted_retained(partial)
    assert amount == 730.0 and retained == pytest.approx(197.97)
    assert _member_retained(full) and _member_retained(partial)


def test_group_invoice_rows_attaches_adjustments_and_excludes_ad_only_accounts():
    """AD rows join their IN row by invoice number; an AD-only account was
    never billed in the cohort and must not enter it. Duplicate AD rows (the
    Sage sync artifact) count once."""
    from reports.membership_performance_tracker.logic.retention import _group_invoice_rows
    records = [
        {"Accountid": "A1", "Invoice_Type": "IN", "Invoice_number": "0148248",
         "Balance": 0.0, "Net_invoice": 510.0, "Invoice_Date": "d1"},
        {"Accountid": "A1", "Invoice_Type": "AD", "Invoice_number": "0148248",
         "Balance": None, "Net_invoice": -510.0, "Invoice_Date": "d1"},
        {"Accountid": "A1", "Invoice_Type": "AD", "Invoice_number": "0148248",
         "Balance": None, "Net_invoice": -510.0, "Invoice_Date": "d1"},   # dup
        {"Accountid": "A2", "Invoice_Type": "AD", "Invoice_number": "0999999",
         "Balance": None, "Net_invoice": -100.0, "Invoice_Date": "d1"},   # AD-only
    ]

    grouped = _group_invoice_rows(records)

    assert set(grouped) == {"A1"}
    assert grouped["A1"][0]["adjustments"] == -510.0


def test_void_and_rebill_uses_the_replacement_invoice():
    """Contreras Group, live case: BM5 invoice voided (IN 1,755 + AD −1,755),
    replacement issued with a BLANK comment (IN 1,135, balance 925 → $210 paid).

    Collected must be summed per invoice: the voided original contributes 0,
    the replacement contributes its paid portion. The pre-fix code read the
    VOIDED invoice's zero balance as full payment — right answer, wrong facts.
    """
    from reports.membership_performance_tracker.logic.retention import (
        _member_retained, _netted_retained)
    import pytest
    rows = [
        {"balance": 0.0, "invoice_total": 1755.0, "invoice_date": "a",
         "invoice_number": "0148253", "adjustments": -1755.0},
        {"balance": 925.0, "invoice_total": 1135.0, "invoice_date": "b",
         "invoice_number": "0148917", "adjustments": 0.0},
    ]

    amount, retained = _netted_retained(rows)

    assert amount == pytest.approx(1135.0)     # the surviving ask
    assert retained == pytest.approx(210.0)    # the replacement's paid portion
    assert _member_retained(rows) is True


def test_void_and_rebill_fully_paid_replacement():
    """Otter Bar & Burger, live case: 830 voided, rebilled 610, paid in full."""
    from reports.membership_performance_tracker.logic.retention import (
        _member_retained, _netted_retained)
    rows = [
        {"balance": 0.0, "invoice_total": 830.0, "invoice_date": "a",
         "invoice_number": "0148304", "adjustments": -830.0},
        {"balance": 0.0, "invoice_total": 610.0, "invoice_date": "b",
         "invoice_number": "0148641", "adjustments": 0.0},
    ]

    amount, retained = _netted_retained(rows)

    assert (amount, retained) == (610.0, 610.0)
    assert _member_retained(rows) is True


def test_blank_comment_rebill_joins_only_cohort_members():
    """A blank-comment invoice belongs to the member's current cycle — but only
    members anchored in the cohort by a Comment=M invoice may absorb one.
    A member with ONLY blank-comment rows was never billed in this cycle."""
    from reports.membership_performance_tracker.logic.retention import _group_invoice_rows
    records = [
        {"Accountid": "A1", "Invoice_Type": "IN", "Invoice_number": "1", "Comment": "5",
         "Balance": 0.0, "Net_invoice": 830.0, "Invoice_Date": "a"},
        {"Accountid": "A1", "Invoice_Type": "AD", "Invoice_number": "1", "Comment": "5",
         "Balance": None, "Net_invoice": -830.0, "Invoice_Date": "a"},
        {"Accountid": "A1", "Invoice_Type": "IN", "Invoice_number": "2", "Comment": "",
         "Balance": 0.0, "Net_invoice": 610.0, "Invoice_Date": "b"},
        {"Accountid": "A2", "Invoice_Type": "IN", "Invoice_number": "3", "Comment": "",
         "Balance": 0.0, "Net_invoice": 500.0, "Invoice_Date": "b"},   # blank only
    ]

    grouped = _group_invoice_rows(records, cohort_comment="5")

    assert set(grouped) == {"A1"}
    assert {r["invoice_number"] for r in grouped["A1"]} == {"1", "2"}
