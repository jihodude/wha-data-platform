"""Drops rebuild contract (Jiho ratified 2026-07-23): billable gate, positive-
only valuation with remnant floor, closure union with native fields + dedup."""
from reports.membership_performance_tracker.logic.drops_value import (
    resolve_dues_value, closure_union)


def test_dues_level_wins():
    assert resolve_dues_value(1070.0, [510.0], 300.0) == 1070.0


def test_invoice_fallback_skips_remnants_and_credits():
    # AC Hotel class: most recent invoice $15.50 remnant; real dues $510 behind it
    assert resolve_dues_value(None, [15.5, 510.0], None) == 510.0
    # 59'er Diner class: a credit invoice can never value a drop
    assert resolve_dues_value(None, [-340.0, 730.0], None) == 730.0


def test_ledger_then_subfloor_last_resort():
    assert resolve_dues_value(None, [], 190.0) == 190.0
    assert resolve_dues_value(None, [15.5], None) == 15.5   # only when nothing better


def test_no_dues_anywhere_is_not_a_member_drop():
    # DQ / Tastebuds / family-child class
    assert resolve_dues_value(None, [], None) is None
    assert resolve_dues_value(None, [-65.0], 0.0) is None


def test_closure_union_fills_only_the_gap():
    drops = [{"account_id": "A1"}]
    closed = [
        {"account_id": "A1", "was_member_at_closure": "Y", "date_closed": "2025-10-15"},   # dedup: flip exists
        {"account_id": "A2", "was_member_at_closure": "Y", "date_closed": "2025-10-15",
         "account_name": "Starbucks FM Alderwood", "territory": "Snohomish",
         "business_type": "Grocery", "is_target": "Y", "notes": "Out of Business"},
        {"account_id": "A3", "was_member_at_closure": "N", "date_closed": "2025-11-01"},   # non-member: out
        {"account_id": "A4", "was_member_at_closure": "Y", "date_closed": None},           # unusable date: out
    ]
    got = closure_union(drops, closed)
    assert len(got) == 1 and got[0]["account_id"] == "A2"
    assert got[0]["drop_date"] == "2025-10-15" and got[0]["drop_category"] == "Closed"
    assert "closure-record" in got[0]["source"]


def test_closure_union_is_fy_scoped():
    closed = [{"account_id": "OLD", "was_member_at_closure": "Y",
               "date_closed": "2019-05-01"}]
    assert closure_union([], closed) == []   # all-time closures stay out


def test_drop_date_recognizes_any_nonactive_transition():
    """2026-07-27 root cause: the history parser matched only 'Status: Inactive',
    so a later Active->Closed flip was INVISIBLE and an ancient status blip won.
    41 members billed into FY25/26 carried drop dates of 2012-2024 because of
    this. Any Active -> non-Active transition must count; most recent wins."""
    from datetime import datetime
    from reports.membership_performance_tracker.logic.drops import _get_drop_date

    class FakeSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=50):
            return [
                {"Notes": "Old Value: Active  Status: Inactive", "CreateDate": "/Date(1577865600000)/"},  # 2020-01-01
                {"Notes": "Old Value: Active  Status: Closed",   "CreateDate": "/Date(1761868800000)/"},  # 2025-10-31
                {"Notes": "Old Value: Closed  Status: Active",   "CreateDate": "/Date(1600000000000)/"},  # re-open: ignore
            ]
    dt = _get_drop_date(FakeSLX(), "A1", None)
    assert dt is not None and dt.year == 2025 and dt.month == 10, dt


def test_drop_date_statusdate_first_history_fallback():
    """2026-08-10 audit: StatusDate is the staff-assigned drop date and the
    field the Crystal report buckets by; the history log is when the entry
    was typed (18 members staff-dated 11/30 were typed 12/3 — wrong month),
    and can carry a stale hit from a PREVIOUS drop (El Ranchito). StatusDate
    wins whenever present; the log is only the no-StatusDate fallback."""
    from reports.membership_performance_tracker.logic.drops import _get_drop_date

    class FakeSLX:
        def __init__(self, create_ms):
            self.create_ms = create_ms
        def _fetch_all(self, entity, where="", select=None, page_size=50):
            return [{"Notes": "Old Value: Active  Status: Inactive",
                     "CreateDate": f"/Date({self.create_ms})/"}]

    # El Ranchito: stale 2025-03-18 history hit vs StatusDate 2026-04-29
    dt = _get_drop_date(FakeSLX(1742256000000), "A1", "/Date(1777420800000)/")
    assert dt is not None and (dt.year, dt.month) == (2026, 4), dt
    # Nov-class block: typed 2025-12-03, staff-dated 2025-11-30 — Nov wins
    dt = _get_drop_date(FakeSLX(1764748800000), "A1", "/Date(1764489600000)/")
    assert dt is not None and (dt.year, dt.month) == (2025, 11), dt
