"""
test_period.py — the reporting-period engine.

Pins that parse_period reproduces the previously-hardcoded 2026-03 behavior
EXACTLY (backward-compat) and derives any other month correctly.
"""
import pytest

from src.config.period import parse_period


def test_march_matches_the_old_hardcoded_constants():
    # These were the literal constants in runner.py before the period engine.
    p = parse_period("2026-03")
    assert p.fy_start == 2025
    assert p.current_month == "Mar"
    assert p.fiscal_year == "2025-26"
    assert p.months == ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]


def test_may_extends_the_fy_to_date_window():
    p = parse_period("2026-05")
    assert p.current_month == "May"
    assert p.fy_start == 2025
    assert p.months == ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May"]


def test_october_is_first_month_of_fy():
    p = parse_period("2025-10")
    assert p.current_month == "Oct"
    assert p.fy_start == 2025
    assert p.months == ["Oct"]


def test_september_is_full_fiscal_year():
    p = parse_period("2026-09")
    assert p.current_month == "Sep"
    assert p.fy_start == 2025            # Sep belongs to the FY that started prior Oct
    assert p.fiscal_year == "2025-26"
    assert len(p.months) == 12
    assert p.months[-1] == "Sep"


def test_bad_period_raises():
    for bad in ("2026", "2026-13", "nope", "2026-00"):
        with pytest.raises(ValueError):
            parse_period(bad)
