"""
test_retention_fy_boundary.py — _bill_month_date_window must place each bill
month in the correct calendar year under the Oct-first fiscal year.

Regression for the surviving Sep-first boundary (retention.py): the FY migration
(commit 2626bd5) moved the pipeline to Oct-first but left this function's year
cutoff at `bill_month >= 9`, which mis-assigns September (month 9) to the prior
fiscal year. For FY2025-26 (Oct 2025 – Sep 2026), Sep is month 9 of the FY and
belongs to calendar 2026, not 2025.
"""
from reports.membership_performance_tracker.logic.retention import _bill_month_date_window


FY_START = 2025  # FY2025-26 = Oct 2025 → Sep 2026


def test_september_belongs_to_end_of_fiscal_year():
    # Sep (bill month 9) is the LAST month of FY2025-26 → calendar 2026.
    start, end = _bill_month_date_window(9, FY_START)
    assert start.startswith("2026-"), f"Sep window should be in 2026, got {start}"
    assert end.startswith("2026-"), f"Sep window should be in 2026, got {end}"


def test_october_is_start_of_fiscal_year():
    # Oct (bill month 10) opens FY2025-26 → calendar 2025.
    start, end = _bill_month_date_window(10, FY_START)
    assert start.startswith("2025-")
    assert end.startswith("2025-")


def test_january_rolls_into_second_calendar_year():
    # Jan (bill month 1) → calendar 2026.
    start, end = _bill_month_date_window(1, FY_START)
    assert end.startswith("2026-")


def test_august_is_second_calendar_year():
    # Aug (bill month 8) → calendar 2026 (mid-late FY).
    start, end = _bill_month_date_window(8, FY_START)
    assert end.startswith("2026-")
