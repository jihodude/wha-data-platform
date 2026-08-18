"""
test_nt_penetration.py — Non-Target penetration emits to the trend sheet (R5).

The Target (≥10 FTE restaurants, ≥40 room hotels) penetration % cells were
already feeding TM Table 5. The Non-Target pool (sub-threshold hospitality —
smaller restaurants, smaller hotels; excludes Allied) is queried by the engine
into pen_active_nt_* / pen_market_nt_* but was never surfaced in the mapper.
Result: the NT % cells in the MPR rendered 0, blocking Chip B-full from laying
out the TM Table 5 NT → T → Aggregate row order Anthony asked for.

These tests pin the contract: when the engine populates NT counts for a
territory, the mapper emits three NT penetration % rows for the snapshot month.

Penetration formula (per Hannah's Penetration Report):
    penetration = Active / (Active + Inactive)
where the engine's `pen_market_nt_*` already represents Active + Inactive.

See reports/membership_performance_tracker/mapper.py — METRIC_FIELD_MAP +
_emit_derived_rows.
"""

import pytest

from reports.membership_performance_tracker.mapper import TrackerV4Mapper
from reports.membership_performance_tracker.logic.model import empty_scoreboard


FY_MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
             "Apr", "May", "Jun", "Jul", "Aug", "Sep"]

NT_PENETRATION_METRICS = {
    "Penetration - Restaurant Non-Target %",
    "Penetration - Lodging Non-Target %",
    "Penetration - Combined Non-Target %",
}


def test_nt_penetration_emitted_for_territory_with_counts():
    """Pierce has known NT counts → mapper emits all three NT % rows for Mar."""
    data = empty_scoreboard(FY_MONTHS)
    # Realistic small-restaurant + small-hotel pool for Pierce.
    data.pen_active_nt_restaurant["Pierce"] = 30
    data.pen_market_nt_restaurant["Pierce"] = 120   # 25% NT restaurant
    data.pen_active_nt_lodging["Pierce"]    = 4
    data.pen_market_nt_lodging["Pierce"]    = 10    # 40% NT lodging

    mapper = TrackerV4Mapper(fiscal_year_start=2025, current_month="Mar")
    rows = mapper.map(data)

    nt_rows = [r for r in rows if r["metric"] in NT_PENETRATION_METRICS
               and r["territory"] == "Pierce"]
    by_metric = {r["metric"]: r for r in nt_rows}

    assert set(by_metric) == NT_PENETRATION_METRICS, (
        f"expected all three NT % metrics for Pierce, got {set(by_metric)}"
    )

    # Restaurant NT = 30 / 120 = 0.25
    assert by_metric["Penetration - Restaurant Non-Target %"]["value"] == pytest.approx(0.25)
    # Lodging NT = 4 / 10 = 0.40
    assert by_metric["Penetration - Lodging Non-Target %"]["value"] == pytest.approx(0.40)
    # Combined NT = (30 + 4) / (120 + 10) = 34 / 130
    assert by_metric["Penetration - Combined Non-Target %"]["value"] == pytest.approx(34 / 130)

    # All three are snapshot-month only.
    assert {r["month"] for r in nt_rows} == {"Mar"}


def test_nt_penetration_skips_territory_without_counts():
    """Territories with no NT counts populated don't generate ghost zero rows."""
    data = empty_scoreboard(FY_MONTHS)
    # Only Pierce has NT data — Snohomish, etc. left as None.
    data.pen_active_nt_restaurant["Pierce"] = 30
    data.pen_market_nt_restaurant["Pierce"] = 120
    data.pen_active_nt_lodging["Pierce"]    = 4
    data.pen_market_nt_lodging["Pierce"]    = 10

    mapper = TrackerV4Mapper(fiscal_year_start=2025, current_month="Mar")
    rows = mapper.map(data)

    nt_rows = [r for r in rows if r["metric"] in NT_PENETRATION_METRICS]
    assert {r["territory"] for r in nt_rows} == {"Pierce"}, (
        "NT % must not emit for territories with empty counts"
    )


def test_nt_penetration_skips_when_denominator_is_zero():
    """Zero-denominator territory (no NT market at all) must not emit % rows
    (same divide-by-zero guard as the Target derived path)."""
    data = empty_scoreboard(FY_MONTHS)
    data.pen_active_nt_restaurant["Pierce"] = 0
    data.pen_market_nt_restaurant["Pierce"] = 0
    data.pen_active_nt_lodging["Pierce"]    = 0
    data.pen_market_nt_lodging["Pierce"]    = 0

    mapper = TrackerV4Mapper(fiscal_year_start=2025, current_month="Mar")
    rows = mapper.map(data)

    nt_rows = [r for r in rows if r["metric"] in NT_PENETRATION_METRICS]
    assert nt_rows == [], (
        "NT % must skip rows with zero denominator (no ZeroDivisionError, no 0% row)"
    )


def test_nt_penetration_emits_only_for_snapshot_month():
    """Like Target penetration, NT % is point-in-time — never fans across months."""
    data = empty_scoreboard(FY_MONTHS)
    data.pen_active_nt_restaurant["Pierce"] = 30
    data.pen_market_nt_restaurant["Pierce"] = 120

    mapper = TrackerV4Mapper(fiscal_year_start=2025, current_month="Mar")
    rows = mapper.map(data)

    nt_rest_rows = [r for r in rows
                    if r["metric"] == "Penetration - Restaurant Non-Target %"]
    assert {r["month"] for r in nt_rest_rows} == {"Mar"}
