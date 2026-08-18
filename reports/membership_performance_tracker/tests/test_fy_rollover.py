"""THE FISCAL-YEAR ROLLOVER CONTRACT — what must be true on and around Oct 1.

Written 2026-08-11 after tracing the rollover end-to-end. Every claim below is
asserted by a test in this file, so the statement cannot quietly drift from the
code.

===========================================================================
THE PLAIN-WORDS VERSION (for a human, not an engineer)
===========================================================================

**The report does not switch fiscal years on October 1. It switches when
September closes — around October 7.**

Three different clocks run at the boundary, and confusing them is what makes
the rollover feel mysterious:

1. **The fiscal year** turns over Oct 1. New year, new empty columns.

2. **September's REPORT** is still being built during the first week of
   October. September's ITD runs early October (SOP: by the 7th), and the
   nightly deliberately keeps pulling September until somebody closes it.
   Only then does it advance to October. So for about a week, the nightly is
   still working on last fiscal year.

3. **September's BILL-MONTH cycle** — the members invoiced in September — has
   a pay window that does not shut until **October 31**, because their third
   and final notice goes out during October. Their ITD cleanup is early
   November.

So the fiscal year cannot "reset" on Oct 1, and it is not supposed to. During
October, **two fiscal years are legitimately live at once**: FY25-26 is
finishing (September's members are still inside their pay window) while
FY26-27 has already started billing its October members.

What that means in practice:

- A number in last year's report can still move during the first week of
  October. That is correct — the month is not closed yet.
- Once September is closed, last fiscal year is frozen and never moves again.
- The new fiscal year starts EMPTY. October's report shows October and eleven
  blank columns. That is correct, not data loss.
- Anything belonging to last fiscal year — a sealed month, a drops export, a
  goal — must never appear in the new year's columns. A column labelled "Sep"
  in the FY26-27 workbook means September 2027, which has not happened yet.

The one thing a human must DO: **the annual October chores.** Set the Crystal
drops schedules' StatusDate range to the new Oct 1 (the report flags this
itself), and add the new fiscal year to `config/goals.yaml` and
`config/admin_inputs.yaml`. Without the config entries every goal renders
blank, and the only complaint is a line in the nightly log.

===========================================================================
"""
from datetime import date

import pytest

from reports.membership_performance_tracker.logic import month_close as mc
from reports.membership_performance_tracker.logic import retention as R
from src import scheduler


FY25 = 2025   # FY2025-26 = 2025-10-01 .. 2026-09-30
FY26 = 2026   # FY2026-27 = 2026-10-01 .. 2027-09-30


# ---------------------------------------------------------------------------
# 1 · The overlap is real: the old year is still open after the new one starts
# ---------------------------------------------------------------------------

def test_septembers_pay_window_closes_inside_the_NEXT_fiscal_year():
    """Bill month 9 is the last cycle of FY25-26, and its third notice lands in
    October. The window shuts Oct 31 2026 — a month into FY26-27. This is the
    reason the fiscal year cannot simply reset on Oct 1."""
    assert R.cycle_close_date(9, FY25) == date(2026, 10, 31)


def test_octobers_own_cycle_belongs_to_the_new_year_and_closes_in_november():
    assert R.cycle_close_date(10, FY26) == date(2026, 11, 30)


def test_both_fiscal_years_are_live_in_the_middle_of_october():
    """Oct 15 2026: FY25-26's September cycle has not shut, and FY26-27's
    October cycle has already opened. Two years, both legitimately moving."""
    mid_october = date(2026, 10, 15)
    assert R.as_of_date(9, FY25, today=mid_october) == mid_october, \
        "September FY25-26 is still open — its number may still move"
    assert R.as_of_date(10, FY26, today=mid_october) == mid_october, \
        "October FY26-27 is open too"


def test_september_stops_moving_once_its_window_shuts():
    """The property the whole product rests on: a past month is reproducible on
    any future run."""
    after = date(2027, 3, 1)
    assert R.as_of_date(9, FY25, today=after) == date(2026, 10, 31)


# ---------------------------------------------------------------------------
# 2 · The nightly finishes the old year before it starts the new one
# ---------------------------------------------------------------------------

@pytest.fixture
def closed(monkeypatch):
    """Control which periods report as closed, without touching data/closes."""
    state: set = set()
    monkeypatch.setattr(mc, "is_closed",
                        lambda p, closes_dir=None: p in state)
    return state


def test_the_nightly_keeps_building_september_until_it_is_closed(closed):
    """Oct 1-7: September's ITD has not run, so the nightly must stay on
    FY25-26 rather than abandoning a month that never closed."""
    for day in (1, 3, 7):
        assert scheduler.period_for_run(date(2026, 10, day)) == "2026-09"


def test_the_nightly_advances_to_the_new_fiscal_year_once_september_closes(closed):
    closed.add("2026-09")
    assert scheduler.period_for_run(date(2026, 10, 8)) == "2026-10"


def test_the_rollover_is_a_close_event_not_a_calendar_event(closed):
    """Same calendar day, opposite answers — the trigger is the close file."""
    day = date(2026, 10, 8)
    assert scheduler.period_for_run(day) == "2026-09"
    closed.add("2026-09")
    assert scheduler.period_for_run(day) == "2026-10"


# ---------------------------------------------------------------------------
# 3 · Nothing from the old year may appear in the new year's columns
# ---------------------------------------------------------------------------

def _close(period, month):
    return {"period": period, "month": month,
            "frozen": {"ret_billed": {"Pierce": 16}},
            "sealed": {"drops_target": {"Pierce": {month: 9}}}}


class _Grid:
    def __init__(self):
        months = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
                  "Apr", "May", "Jun", "Jul", "Aug", "Sep"]
        self.ret_billed = {"Pierce": {m: 0 for m in months}}
        self.drops_target = {"Pierce": {m: 0 for m in months}}


def test_a_whole_year_of_old_closes_cannot_touch_the_new_years_grid():
    """The state on the first FY26-27 build: twelve FY25-26 close files sit on
    disk and load_all_closes() returns every one of them."""
    all_of_last_year = [
        _close(f"2025-{m:02d}" if m >= 10 else f"2026-{m:02d}", abb)
        for m, abb in [(10, "Oct"), (11, "Nov"), (12, "Dec"), (1, "Jan"),
                       (2, "Feb"), (3, "Mar"), (4, "Apr"), (5, "May"),
                       (6, "Jun"), (7, "Jul"), (8, "Aug"), (9, "Sep")]]
    grid = _Grid()
    notes = mc.apply_frozen(grid, all_of_last_year, period="2026-10")

    assert all(v == 0 for v in grid.ret_billed["Pierce"].values()), \
        "not one FY25-26 retention cell may land in the FY26-27 grid"
    assert all(v == 0 for v in grid.drops_target["Pierce"].values()), \
        "not one FY25-26 sealed drops cell may land in the FY26-27 grid"
    assert any("12 close file(s) skipped" in n for n in notes), \
        "the skip is stated once, with a count — not silently, not 12 times"


def test_the_new_years_own_close_still_applies_normally():
    """The guard must not lock the new year out of its own seals."""
    grid = _Grid()
    mc.apply_frozen(grid, [_close("2026-10", "Oct")], period="2026-11")
    assert grid.ret_billed["Pierce"]["Oct"] == 16
    assert grid.drops_target["Pierce"]["Oct"] == 9


# ---------------------------------------------------------------------------
# 4 · The new year starts empty — and that is not data loss
# ---------------------------------------------------------------------------

def test_the_first_october_period_covers_exactly_one_month():
    from src.config.period import parse_period
    p = parse_period("2026-10")
    assert p.fy_start == FY26 and p.fiscal_year == "2026-27"
    assert p.months == ["Oct"], \
        "a new fiscal year is one month wide; eleven blank columns are correct"


def test_a_january_period_is_still_the_october_fiscal_year():
    from src.config.period import parse_period
    p = parse_period("2027-01")
    assert p.fy_start == FY26 and p.months[0] == "Oct"
