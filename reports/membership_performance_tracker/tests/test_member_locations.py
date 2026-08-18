"""Member Locations rows (Jiho GO 8/5 — Anthony's consolidation check).

The read: billables drop + locations flat ⇒ a consolidation, not a loss.
One metric, per band, under each section's billables row: Combined = T+NT,
Target = target actives, Non-Target = NT actives — sourced from the same
penetration sweep the 7/19 Crystal verification covered. Photo metric:
current month only from a live build; prior months from their own
snapshots; blank when never photographed; sealed at close.

Consolidation is NOT target-by-definition (Jiho 8/5: size defines target,
corporate structure is independent — a franchise of small units is a
non-target corporate), which is why the non-target band gets its own line.
"""
from reports.membership_performance_tracker.mapper import (
    METRIC_FIELD_MAP, TrackerV4Mapper)
from reports.membership_performance_tracker.logic.model import empty_scoreboard

_FY = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
       "Apr", "May", "Jun", "Jul", "Aug", "Sep"]


def _data():
    d = empty_scoreboard(_FY)
    d.pen_active_restaurant["Pierce"] = 300
    d.pen_active_lodging["Pierce"] = 69
    d.pen_active_nt_restaurant["Pierce"] = 40
    d.pen_active_nt_lodging["Pierce"] = 12
    return d


def _rows_for(metric, rows):
    return [r for r in rows if r["metric"] == metric and r["territory"] == "Pierce"]


def test_member_location_metrics_emit_band_sums_for_current_month_only():
    rows = TrackerV4Mapper(fiscal_year_start=2025,
                           current_month="Jul").map(_data())
    t = _rows_for("Member Locations - Target (#)", rows)
    nt = _rows_for("Member Locations - Non-Target (#)", rows)
    assert [r["month"] for r in t] == ["Jul"], "photo metric: current month only"
    assert t[0]["value"] == 369, "target = restaurant + lodging actives"
    assert [r["month"] for r in nt] == ["Jul"]
    assert nt[0]["value"] == 52


def test_member_locations_skip_territories_without_pen_data():
    """A territory the pen sweep never covered (Majors/NRA) must stay blank,
    not read 0 — absence of a photo is not a zero."""
    rows = TrackerV4Mapper(fiscal_year_start=2025,
                           current_month="Jul").map(_data())
    terrs = {r["territory"] for r in rows
             if r["metric"] == "Member Locations - Target (#)"}
    assert terrs == {"Pierce"}


def test_member_locations_are_photo_metrics():
    """History assembly + the close seal both key off the photo kinds — the
    locations rows must ride the same protections as billables."""
    from reports.membership_performance_tracker.history import PHOTO_METRICS
    assert "Member Locations - Target (#)" in PHOTO_METRICS
    assert "Member Locations - Non-Target (#)" in PHOTO_METRICS
