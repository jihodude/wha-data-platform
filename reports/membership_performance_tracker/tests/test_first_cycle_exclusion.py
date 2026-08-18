"""
test_first_cycle_exclusion.py — A2: first-cycle members are NOT "up for renewal".

A member billed for the first time isn't renewing — including them inflates the
retention denominator (and usually the numerator). Rule: enrolled less than ~12
months before their bill-month due date = first bill = excluded from retention.
(Dues are annual; a member enrolled 13+ months before the cohort is renewing.)
"""
from datetime import date

from reports.membership_performance_tracker.logic.retention import _first_cycle_ids


def test_enrolled_recently_is_first_cycle():
    enrolled = {"A1": date(2026, 3, 10)}   # enrolled March 2026
    # bill month 5 (May) FY2025-26 → due 2026-05: only ~2 months after enrollment
    assert _first_cycle_ids(enrolled, bill_month=5, fiscal_year_start=2025) == {"A1"}


def test_enrolled_over_a_year_ago_is_renewal():
    enrolled = {"A2": date(2025, 4, 20)}   # enrolled Apr 2025
    # bill month 5 FY2025-26 → due 2026-05: 13 months later = their renewal
    assert _first_cycle_ids(enrolled, bill_month=5, fiscal_year_start=2025) == set()


def test_oct_bill_month_uses_fy_start_year():
    enrolled = {"A3": date(2025, 9, 15)}   # enrolled Sep 2025
    # bill month 10 FY2025-26 → due 2025-10 (fy start year): 1 month = first cycle
    assert _first_cycle_ids(enrolled, bill_month=10, fiscal_year_start=2025) == {"A3"}


def test_unknown_enrollment_stays_in_cohort():
    enrolled = {"A4": None}
    assert _first_cycle_ids(enrolled, bill_month=5, fiscal_year_start=2025) == set()
