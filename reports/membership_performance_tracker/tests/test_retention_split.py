"""
test_retention_split.py — Target / Non-Target / Combined retention classification.

Master-list #2: ~35% of billed accounts (476 of 1351 in the 2026-03 cache) and
~$22.8k of revenue-up-for-renewal were leaking into an UNKNOWN bucket that the
engine silently dropped. Per the v4 reporting convention (model.py: "'unknown'
accounts ... are typically merged into non_target for reporting purposes") and
the billables path (engine.py folds hospitality_unknown into hosp_bills_non_target),
retention must do the same so that:

    Combined = Target + Non-Target = the true total (no leak).

These tests pin _retention_target_split to that contract: the Unknown bucket is
folded into Non-Target, and the per-bucket sums reconcile exactly to the totals.
"""

from reports.membership_performance_tracker.logic.retention import _retention_target_split
from reports.membership_performance_tracker.logic.target import TARGET, NON_TARGET


def _acct(balance, invoice_total):
    return {"balance": balance, "invoice_total": invoice_total}


def test_unknown_account_folds_into_non_target():
    # A1 = Target (paid $100), A2 = Non-Target (paid $40),
    # A3 = Unknown (not in target_map; paid $30) — must land in Non-Target.
    by_account = {
        "A1": [_acct(0.0, 100.0)],
        "A2": [_acct(0.0, 40.0)],
        "A3": [_acct(0.0, 30.0)],
    }
    target_map = {"A1": TARGET, "A2": NON_TARGET}  # A3 absent → Unknown

    out = _retention_target_split(by_account, target_map)

    assert out["billed_target"] == 1
    assert out["paid_target"] == 1
    # A2 + A3 both count as Non-Target
    assert out["billed_non_target"] == 2
    assert out["paid_non_target"] == 2
    assert out["revenue_up_non_target"] == 70.0       # 40 + 30
    assert out["revenue_retained_non_target"] == 70.0  # both paid


def test_combined_equals_total_no_leak():
    # One of each: Target, Non-Target, Unknown — Combined (T+NT) must equal the
    # total account count and total revenue with nothing left over.
    by_account = {
        "T": [_acct(0.0, 200.0)],     # target, paid
        "N": [_acct(15.0, 80.0)],     # non-target, outstanding (not paid)
        "U": [_acct(0.0, 25.0)],      # unknown, paid
    }
    target_map = {"T": TARGET, "N": NON_TARGET}

    out = _retention_target_split(by_account, target_map)

    total_billed = len(by_account)
    total_revenue_up = 200.0 + 80.0 + 25.0
    assert out["billed_target"] + out["billed_non_target"] == total_billed
    assert out["revenue_up_target"] + out["revenue_up_non_target"] == total_revenue_up


def test_no_separate_unknown_keys_remain():
    # The dropped/leaked bucket must not survive as its own reporting key —
    # otherwise a caller summing all three would double-count the folded values.
    by_account = {"U": [_acct(0.0, 25.0)]}
    target_map = {}  # everything Unknown

    out = _retention_target_split(by_account, target_map)

    for k in (
        "paid_unknown", "billed_unknown",
        "revenue_retained_unknown", "revenue_up_unknown",
    ):
        assert k not in out
    # The lone unknown account is reported as Non-Target.
    assert out["billed_non_target"] == 1
    assert out["revenue_up_non_target"] == 25.0
