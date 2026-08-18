"""
test_layer2_aggregations.py — the two Layer-2 rate aggregations must be
count/volume-WEIGHTED, not unweighted means of ratios.

M1 avg_retention[t]      : Σpaid / Σbilled across billed months
                           (a 100-billed month must outweigh a 2-billed month).
M2 statewide_avg_pen     : Σactive / Σmarket across territories
                           (a big-market territory must outweigh a tiny one).

Old behavior averaged the monthly/territory PERCENTAGES equally, which skews the
number toward low-volume outliers. See docs/handoff/2026-07-13-accuracy-fix-queue.md
(M1, M2) and the 2026-06-08 investigation R4.
"""
from reports.membership_performance_tracker.logic.engine import ScoreboardEngine
from reports.membership_performance_tracker.logic.model import empty_scoreboard

FY_MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
             "Apr", "May", "Jun", "Jul", "Aug", "Sep"]


def _engine():
    eng = ScoreboardEngine(
        client=None,
        territory_user_map={},
        fiscal_year_start=2025,
        months=FY_MONTHS,
        current_month="Mar",
        rep_name_map={},
    )
    eng.data = empty_scoreboard(FY_MONTHS)
    return eng


def test_avg_retention_is_count_weighted():
    eng = _engine()
    d = eng.data
    # Oct: 90/100 = 0.90 (high volume).  Nov: 0/2 = 0.00 (tiny volume).
    d.ret_billed["Pierce"]["Oct"] = 100
    d.ret_paid["Pierce"]["Oct"]   = 90
    d.retention_pct["Pierce"]["Oct"] = 0.90
    d.ret_billed["Pierce"]["Nov"] = 2
    d.ret_paid["Pierce"]["Nov"]   = 0
    d.retention_pct["Pierce"]["Nov"] = 0.00

    eng._compute_layer2()

    # Count-weighted = (90 + 0) / (100 + 2) = 0.882…  (unweighted mean would be 0.45)
    assert d.avg_retention["Pierce"] == 90 / 102


def test_avg_retention_none_when_nothing_billed():
    eng = _engine()
    eng._compute_layer2()
    assert eng.data.avg_retention["Pierce"] is None


def test_statewide_penetration_is_market_weighted():
    eng = _engine()
    d = eng.data
    # Pierce: (44+10)/(100+20) = 54/120 = 0.45   (large market)
    d.pen_active_restaurant["Pierce"] = 44
    d.pen_market_restaurant["Pierce"] = 100
    d.pen_active_lodging["Pierce"]    = 10
    d.pen_market_lodging["Pierce"]    = 20
    d.pen_pct["Pierce"] = 0.45
    # Snohomish: (30+5)/(50+10) = 35/60 = 0.583… (small market)
    d.pen_active_restaurant["Snohomish"] = 30
    d.pen_market_restaurant["Snohomish"] = 50
    d.pen_active_lodging["Snohomish"]    = 5
    d.pen_market_lodging["Snohomish"]    = 10
    d.pen_pct["Snohomish"] = 35 / 60

    eng._compute_layer2()

    # Aggregate = (54 + 35) / (120 + 60) = 89 / 180  (unweighted mean would be ~0.517)
    assert d.statewide_avg_pen == 89 / 180


def test_statewide_penetration_none_when_no_market():
    eng = _engine()
    eng._compute_layer2()
    assert eng.data.statewide_avg_pen is None


def test_combined_pen_with_missing_lodging_segment():
    """P1-5 (7/16): Majors/NRA has no lodging market — combined penetration
    must equal its restaurant-only ratio (their handmade shows NRA 87.5% =
    781/893), not None. A missing segment contributes zero; it doesn't veto."""
    eng = _engine()
    eng.data.pen_active_restaurant["Majors/NRA"] = 782
    eng.data.pen_market_restaurant["Majors/NRA"] = 894
    eng.data.pen_active_lodging["Majors/NRA"] = 0
    eng.data.pen_market_lodging["Majors/NRA"] = 0
    eng._compute_layer1()
    assert abs(eng.data.pen_pct["Majors/NRA"] - 782 / 894) < 1e-9


def test_statewide_penetration_includes_restaurant_only_territory():
    """Finding #3 (2026-07-17): the statewide aggregate must MIRROR the layer-1
    P1-5 rule. A restaurant-only territory (Majors/NRA: no lodging market) must
    contribute its 0-coalesced counts. The old guard required all four counts +
    both markets truthy, so Majors/NRA (lodging market 0 → falsy) was silently
    dropped from BOTH the statewide numerator and denominator — and via
    _pen_status that skewed every territory's Above/Near/Below flag."""
    eng = _engine()
    d = eng.data
    # Majors/NRA — restaurant only, lodging market 0 (the exact P1-5 case)
    d.pen_active_restaurant["Majors/NRA"] = 782
    d.pen_market_restaurant["Majors/NRA"] = 894
    d.pen_active_lodging["Majors/NRA"] = 0
    d.pen_market_lodging["Majors/NRA"] = 0
    # Pierce — full segments: active 54, market 120
    d.pen_active_restaurant["Pierce"] = 44
    d.pen_market_restaurant["Pierce"] = 100
    d.pen_active_lodging["Pierce"] = 10
    d.pen_market_lodging["Pierce"] = 20

    eng._compute_layer2()

    # (782 + 54) / (894 + 120) — Majors/NRA is NOT dropped
    assert d.statewide_avg_pen == (782 + 54) / (894 + 120)


def test_drop_category_monthly_rollups():
    """B10 (7/16): monthly drop counts BY CATEGORY (Closed/Sold/Non-Payment/
    Voluntary) per territory — the 'why did we lose members' answer the team
    asked for ('more info > less'). Admin/Retro stay excluded as everywhere."""
    eng = _engine()
    eng.data.drops_detail = [
        {"territory": "Pierce", "is_target": "Y", "drop_category": "Sold",
         "drop_date": "2026-06-10", "amount_billed": 100.0},
        {"territory": "Pierce", "is_target": "N", "drop_category": "Sold",
         "drop_date": "2026-06-11", "amount_billed": 100.0},
        {"territory": "Pierce", "is_target": "N", "drop_category": "Non-Payment",
         "drop_date": "2026-06-12", "amount_billed": 100.0},
        {"territory": "Pierce", "is_target": "N", "drop_category": "Admin",
         "drop_date": "2026-06-13", "amount_billed": 100.0},
        {"territory": "Retro Program", "is_target": "N", "drop_category": "Sold",
         "drop_date": "2026-06-14", "amount_billed": 100.0},
    ]
    eng.aggregate_drops_buckets()
    cats = eng.data.drops_by_category
    assert cats["Sold"]["Pierce"]["Jun"] == 2
    assert cats["Non-Payment"]["Pierce"]["Jun"] == 1
    assert "Admin" not in cats or not (cats.get("Admin", {}).get("Pierce", {}) or {}).get("Jun")
    assert "Retro Program" not in cats.get("Sold", {}), "retro stays out of counts"


def test_mapper_emits_category_rollup_rows():
    from reports.membership_performance_tracker.mapper import TrackerV4Mapper
    eng = _engine()
    eng.data.drops_by_category = {"Sold": {"Pierce": {"Jun": 2}}}
    rows = TrackerV4Mapper(current_month="Jun").map(eng.data)
    hit = [r for r in rows if r["metric"] == "Drops - Sold (#)"]
    assert hit and hit[0]["territory"] == "Pierce" and hit[0]["value"] == 2
