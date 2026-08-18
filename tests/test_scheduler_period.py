"""Close-aware scheduling (2026-08-03, designed with Jiho; supersedes the
2026-07-22 calendar cadence): the nightly pull keeps targeting the CLOSING
month until its close file exists, then advances. A month's ITD close
happens INSIDE the next calendar month (July's ITD runs ~Aug 5-7), so the
old rule — prior month on the 1st only — abandoned July on Aug 2 whether or
not it ever closed. Confirmed against the 8/3 leadership transcript:
"whatever he's exporting from SLX excludes the next month… that would also
affect accounting too, so they don't have to hold."
"""
from datetime import datetime

import src.scheduler as sched
from reports.membership_performance_tracker.logic import month_close as mc


def test_open_prior_month_keeps_the_period(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "CLOSES_DIR", tmp_path)
    monkeypatch.setattr(sched, "CLOSE_ANCHOR", "2026-07")
    # July never closed: every August day still reports July
    assert sched.period_for_run(datetime(2026, 8, 1, 2, 0)) == "2026-07"
    assert sched.period_for_run(datetime(2026, 8, 2, 2, 0)) == "2026-07"
    assert sched.period_for_run(datetime(2026, 8, 31, 2, 0)) == "2026-07"


def test_closed_prior_month_advances(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "CLOSES_DIR", tmp_path)
    monkeypatch.setattr(sched, "CLOSE_ANCHOR", "2026-07")
    (tmp_path / "close_2026-07.json").write_text("{}")
    assert sched.period_for_run(datetime(2026, 8, 6, 2, 0)) == "2026-08"
    # August itself not closed yet: September still reports August
    assert sched.period_for_run(datetime(2026, 9, 10, 2, 0)) == "2026-08"


def test_pre_anchor_months_never_drag_backwards(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "CLOSES_DIR", tmp_path)
    monkeypatch.setattr(sched, "CLOSE_ANCHOR", "2026-07")
    # June predates the close system (frozen history) - July reports July
    assert sched.period_for_run(datetime(2026, 7, 15, 2, 0)) == "2026-07"


def test_fy_rollover_keeps_september_alive(tmp_path, monkeypatch):
    """Oct 1: September (FY end) is still open until ITS close - the FY
    boundary gets no special treatment."""
    monkeypatch.setattr(mc, "CLOSES_DIR", tmp_path)
    monkeypatch.setattr(sched, "CLOSE_ANCHOR", "2026-07")
    assert sched.period_for_run(datetime(2026, 10, 1, 2, 0)) == "2026-09"
    (tmp_path / "close_2026-09.json").write_text("{}")
    assert sched.period_for_run(datetime(2026, 10, 1, 2, 0)) == "2026-10"
