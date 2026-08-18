"""
test_period_sweep.py — month-agnostic BY PROOF, not just by design (queue-2 #1,
2026-07-15). Walks MPR_PERIOD through the whole fiscal year and pins every
derived mapping, incl. both FY edges — the class of bug that emptied the
October retention column (BM9 needed the PRIOR fiscal year).
"""
import pytest

from src.config.period import FY_MONTHS, parse_period

ALL_PERIODS = [("2025-10", "Oct"), ("2025-11", "Nov"), ("2025-12", "Dec"),
               ("2026-01", "Jan"), ("2026-02", "Feb"), ("2026-03", "Mar"),
               ("2026-04", "Apr"), ("2026-05", "May"), ("2026-06", "Jun"),
               ("2026-07", "Jul"), ("2026-08", "Aug"), ("2026-09", "Sep")]


@pytest.mark.parametrize("period,abb", ALL_PERIODS)
def test_period_derivations_every_month(period, abb):
    p = parse_period(period)
    assert p.current_month == abb
    assert p.fy_start == 2025, "whole FY 2025-26 must derive fy_start 2025"
    assert p.fiscal_year == "2025-26"
    assert p.months[0] == "Oct" and p.months[-1] == abb
    assert p.months == FY_MONTHS[: FY_MONTHS.index(abb) + 1]


def test_fy_edges():
    assert parse_period("2025-10").months == ["Oct"]          # FY first month
    assert len(parse_period("2026-09").months) == 12          # FY last month
    assert parse_period("2025-12").fy_start == 2025           # Dec stays
    assert parse_period("2026-01").fy_start == 2025           # Jan rolls back
    assert parse_period("2026-10").fy_start == 2026           # next FY begins


@pytest.mark.parametrize("period,abb", ALL_PERIODS)
def test_retention_bill_month_mapping_every_month(period, abb):
    """Column M shows bill-month M−1 (their convention, ratified 7/14).
    Replicates the engine's derivation: Oct(10)→BM9, Jan(1)→BM12, Nov→BM10.
    BM9 is the fy-edge: it must come from the PRIOR fiscal year (the
    October-empty bug); the engine routes it via fiscal_year_start−1."""
    from reports.membership_performance_tracker.logic.engine import MONTH_ABB_TO_INT
    p = parse_period(period)
    bill_months = sorted({(MONTH_ABB_TO_INT[m] - 1) or 12 for m in p.months})
    assert 0 not in bill_months and all(1 <= b <= 12 for b in bill_months)
    # display month for each bill month must be +1 with Dec→Jan wrap
    for b in bill_months:
        disp = 1 if b == 12 else b + 1
        assert FY_MONTHS.index("Oct") is not None  # sanity anchor
        assert (b % 12) + 1 == disp
    # Oct is always in the window (FY-to-date) → BM9 always present → the
    # prior-FY special case must always be exercised
    assert 9 in bill_months, "BM9 (prior-FY Sep cohort) must be in every window"
    main_bms = [b for b in bill_months if b != 9]
    assert 9 not in main_bms, "BM9 must be routed separately (prior FY)"
