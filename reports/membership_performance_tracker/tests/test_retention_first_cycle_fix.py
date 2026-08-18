"""Defect #2 (meaning audit 2026-07-17): the first-cycle retention exclusion
(ratified rule A2 — a member's first bill is not a renewal) was a NO-OP for bill
months 1-9 because _retention_counts derived the fiscal year from the invoice
window string (int(fy_start[:4]) = fiscal_year_start+1 for Jan-Sep) instead of the
real fiscal_year_start. Fixed by threading fiscal_year_start through.

Warrant: jhurley's AdjustedRetention export EXCLUDES first-cycle members
(DECISIONS.md 2026-07-14) — this makes our numbers match that convention.
"""
from datetime import datetime, timezone

from reports.membership_performance_tracker.logic.retention import _retention_counts


def _slx_date(y, m, d):
    ms = int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
    return f"/Date({ms})/"


class FakeSLX:
    def __init__(self, enrolled_date):
        self.enrolled = enrolled_date

    def _fetch_all(self, entity, where="", select=None, page_size=200):
        if entity == "dlInvoiceHistoryHeader":
            # Comment carries the bill month since the 2026-07-28 change: the
            # fetch is no longer comment-filtered server-side (void-and-rebill
            # replacements have blank comments), so cohort membership anchors
            # on this field client-side.
            return [{"Accountid": "A1", "Balance": 0.0, "Net_invoice": 500.0,
                     "Invoice_Type": "IN", "Comment": "6", "Invoice_number": "1",
                     "Invoice_Date": _slx_date(2026, 6, 1)}]
        if entity == "cMemberGens":
            return [{"Account": {"$key": "A1"}, "EnrolledDate": self.enrolled}]
        raise AssertionError(entity)


FY_START = 2025  # FY2025-26 (Oct 2025 - Sep 2026); June (BM6) window is in 2026


def test_first_cycle_member_excluded_for_jun_bill_month():
    # Enrolled Jan 2026 -> 5 months before the June 2026 bill = first cycle.
    fake = FakeSLX(_slx_date(2026, 1, 15))
    paid, billed, *_ = _retention_counts(
        fake, "U1", "6", "2026-04-01", "2026-08-31", FY_START)
    assert billed == 0, "first-cycle member must be EXCLUDED from June retention"
    assert paid == 0


def test_established_member_still_counted_for_jun_bill_month():
    # Enrolled 2023 -> not first cycle -> stays in the renewal cohort.
    fake = FakeSLX(_slx_date(2023, 5, 10))
    paid, billed, *_ = _retention_counts(
        fake, "U1", "6", "2026-04-01", "2026-08-31", FY_START)
    assert billed == 1, "established member must remain in the renewal cohort"
    assert paid == 1
