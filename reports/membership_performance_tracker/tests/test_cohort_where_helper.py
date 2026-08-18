"""Gold-plating (2026-07-17): the new-member cohort filter was pasted verbatim in
4 places (revenue.py ×2, new_members.py ×2) — the 2026-07-16 boundary fix had to be
applied to all four. It's now ONE helper, `target.new_member_cohort_where`. This test
pins the ratified rules so a future edit can't silently drop one.
"""
from datetime import date

from reports.membership_performance_tracker.logic.target import new_member_cohort_where


def test_cohort_where_carries_all_ratified_rules():
    w = new_member_cohort_where("U123", "2026-06-01", date(2026, 6, 30))
    assert "Account.AccountManager.Id eq 'U123'" in w
    assert "EnrolledDate ge @2026-06-01@" in w
    # EXCLUSIVE next-day end boundary (2026-07-16): June 30 -> lt July 1
    assert "EnrolledDate lt @2026-07-01@" in w
    # NULL-safe reinstatement exclusion
    assert "(Salescode ne '510' or Salescode eq null)" in w
    assert "ReinstatedDate eq null" in w
    # NO current-status filter (2026-07-15) — a since-dropped sale is still a sale
    assert "Status eq" not in w


def test_cohort_boundary_includes_last_day_joiners():
    # the 3/31 midnight-Pacific joiners must fall inside the window (lt 4/1)
    w = new_member_cohort_where("U", "2026-03-01", date(2026, 3, 31))
    assert "lt @2026-04-01@" in w
