"""The nightly time must be settable from the console — and must warn.

2 AM was hardcoded (console/app.py forced hour=2/minute=0 on every save) after
an earlier attempt at an adjustable time broke the nightly. The reason is real
and is preserved here as a WARNING rather than a lock: the month close relies on
a clean before-ITD photo from each night, and the day's Crystal export must
already have landed. A later run time quietly breaks both.

Jiho 2026-08-12: WHA needs the time adjustable for GL/Sage timing, and we need
it today to prove the scheduler self-fires. So the rule becomes "you may move
it, but you will be told what you are trading away" — never a silent change.

Following the convention set at scheduler.py:325 (progress parsing lives here,
not in the console, because render-path code must be testable), the decision is
a pure function in src/scheduler.py and the console only renders it.
"""
import importlib
import os
from datetime import datetime

import pytest


@pytest.fixture(autouse=True)
def _reload_clean_after():
    yield
    os.environ.pop("WHA_SCHEDULE_DEFAULT_ENABLED", None)
    import src.scheduler as sched
    importlib.reload(sched)


def _sched(tmp_path, monkeypatch):
    import src.scheduler as sched
    importlib.reload(sched)
    monkeypatch.setattr(sched, "SCHEDULE_FILE", tmp_path / "schedule.json")
    return sched


# --- the pure decision -----------------------------------------------------

def test_the_safe_hour_returns_no_warning(tmp_path, monkeypatch):
    s = _sched(tmp_path, monkeypatch)
    assert s.schedule_time_warning(2, 0) is None


def test_any_other_time_warns_about_ITD_and_crystal(tmp_path, monkeypatch):
    s = _sched(tmp_path, monkeypatch)
    w = s.schedule_time_warning(11, 30)
    assert w, "a non-2AM time must not change silently"
    low = w.lower()
    assert "itd" in low, "the warning must name the before-ITD photo"
    assert "crystal" in low, "the warning must name the Crystal export"


def test_warning_is_advisory_not_a_block(tmp_path, monkeypatch):
    """WHA must be able to move it for GL/Sage timing — warn, never refuse."""
    s = _sched(tmp_path, monkeypatch)
    st = s.load_schedule()
    st.update({"enabled": True, "hour": 11, "minute": 30})
    s.save_schedule(st)
    assert s.load_schedule()["hour"] == 11


# --- the regression the console caused -------------------------------------

def test_a_custom_time_survives_a_save(tmp_path, monkeypatch):
    """The console forced hour=2/minute=0 on every save, so the stored time
    could never be anything else. That is the bug this feature restores."""
    s = _sched(tmp_path, monkeypatch)
    st = s.load_schedule()
    st.update({"enabled": True, "hour": 12, "minute": 20})
    s.save_schedule(st)
    reloaded = s.load_schedule()
    assert (reloaded["hour"], reloaded["minute"]) == (12, 20)


def test_next_run_follows_the_custom_time(tmp_path, monkeypatch):
    """`Next:` on the console reads next_run_ts — it must track the new time,
    because that line is the only honest signal the change took effect."""
    s = _sched(tmp_path, monkeypatch)
    st = s.load_schedule()
    st.update({"enabled": True, "hour": 12, "minute": 20})
    s.save_schedule(st)
    out = s.refresh_next_run()
    nxt = datetime.fromisoformat(out["next_run_ts"])
    assert (nxt.hour, nxt.minute) == (12, 20)


def test_disabled_still_clears_next_run(tmp_path, monkeypatch):
    s = _sched(tmp_path, monkeypatch)
    st = s.load_schedule()
    st.update({"enabled": False, "hour": 12, "minute": 20})
    s.save_schedule(st)
    assert s.refresh_next_run()["next_run_ts"] is None


# --- the console must not re-introduce the override -------------------------

def test_console_no_longer_hardcodes_the_hour():
    """A source-level gate: the exact regression was a literal assignment in
    the save handler, which no behavioural test of scheduler.py can see."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "console" / "app.py").read_text()
    assert '_sched["hour"]    = 2' not in src
    assert '_sched["hour"] = 2' not in src


def test_console_caption_is_not_a_hardcoded_2am_claim():
    """The caption said 'Runs at 2:00 AM — deliberately not adjustable' no
    matter what was stored, so the page lied whenever the state differed."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "console" / "app.py").read_text()
    assert "deliberately not adjustable" not in src
