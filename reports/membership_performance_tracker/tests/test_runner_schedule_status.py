"""
test_runner_schedule_status.py — Bug 3: _update_schedule_status PID safety (2026-06-05).

Pins the contract for the runner's schedule.json exit-writer:

  1. If the schedule's current_pid matches our PID (we were launched by the
     scheduler), the writer updates last_run_status and clears current_pid.
  2. If current_pid is a DIFFERENT PID (we're a manual CLI invocation, or
     another scheduled run is in flight), the writer touches nothing.
  3. If schedule.json is missing or corrupt, the writer no-ops silently —
     runner exit code must never be blocked on this.

These invariants protect against the symptom that prompted Bug 3:
schedule.json showing 'running (pid X)' indefinitely after X exited.
"""

import json
import os
from pathlib import Path

import pytest

from reports.membership_performance_tracker import runner as runner_mod


@pytest.fixture
def fake_schedule(tmp_path, monkeypatch):
    """Point the runner's SCHEDULE_FILE constant at a per-test temp file."""
    path = tmp_path / "schedule.json"
    monkeypatch.setattr(runner_mod, "SCHEDULE_FILE", path)
    return path


def _write(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2))


def test_writes_status_when_pid_matches(fake_schedule):
    _write(fake_schedule, {
        "enabled":         True,
        "current_pid":     os.getpid(),     # ← we own the slot
        "last_run_status": "running (pid X)",
    })

    runner_mod._update_schedule_status("done")

    state = json.loads(fake_schedule.read_text())
    assert state["last_run_status"] == "done"
    assert state["current_pid"]     is None
    # Other keys preserved
    assert state["enabled"] is True


def test_leaves_state_alone_when_pid_does_not_match(fake_schedule):
    # Pick a PID that definitely isn't us. PID 0 is the scheduler in POSIX
    # (never a real process) — guaranteed to differ from os.getpid().
    foreign_pid = 0 if os.getpid() != 0 else 1
    original = {
        "enabled":         True,
        "current_pid":     foreign_pid,     # ← someone else owns this slot
        "last_run_status": "running (pid 12345)",
    }
    _write(fake_schedule, original)

    runner_mod._update_schedule_status("done")

    # Untouched
    state = json.loads(fake_schedule.read_text())
    assert state == original


def test_noop_when_schedule_file_missing(fake_schedule):
    # File does not exist yet — must not raise, must not create it
    assert not fake_schedule.exists()
    runner_mod._update_schedule_status("done")
    assert not fake_schedule.exists()


def test_noop_when_schedule_file_corrupt(fake_schedule):
    fake_schedule.write_text("{ not valid json")
    # Must not raise
    runner_mod._update_schedule_status("done")
    # Leave the corrupt file as-is — scheduler thread can clean up
    assert fake_schedule.read_text() == "{ not valid json"


def test_error_status_persists_through_pid_guard(fake_schedule):
    """An error status with details (e.g. 'error: ConnectionError: ...') must
    still write through the PID guard untouched."""
    _write(fake_schedule, {
        "current_pid":     os.getpid(),
        "last_run_status": "running (pid Y)",
    })

    runner_mod._update_schedule_status("error: ConnectionError: SLX timeout")

    state = json.loads(fake_schedule.read_text())
    assert state["last_run_status"] == "error: ConnectionError: SLX timeout"
    assert state["current_pid"]     is None


def test_warnings_field_written_when_provided(fake_schedule):
    """Verify High #3 fix (2026-06-05 PM): publish warnings get surfaced to
    schedule.json so the console UI knows the run completed with SP issues."""
    _write(fake_schedule, {
        "current_pid":     os.getpid(),
        "last_run_status": "running (pid X)",
    })

    runner_mod._update_schedule_status(
        "done",
        warnings=["snapshot (official): ConnectionError: timeout",
                  "xlsx upload: PermissionError: forbidden"],
    )

    state = json.loads(fake_schedule.read_text())
    assert state["last_run_status"] == "done"
    assert state["last_run_warnings"] == [
        "snapshot (official): ConnectionError: timeout",
        "xlsx upload: PermissionError: forbidden",
    ]


def test_warnings_field_defaults_to_empty_list(fake_schedule):
    """When no warnings passed, the field is an empty list (not missing)."""
    _write(fake_schedule, {
        "current_pid":     os.getpid(),
        "last_run_status": "running",
    })

    runner_mod._update_schedule_status("done")

    state = json.loads(fake_schedule.read_text())
    assert state["last_run_warnings"] == []


# ---------------------------------------------------------------------------
# 2026-07-20 morning fixes (Jiho's 6:42am incident): opening the console must
# NEVER fire a missed slot, and a scheduled run must pull the CURRENT month.
# ---------------------------------------------------------------------------

def test_missed_slot_does_not_fire_only_reschedules():
    """Console opened at 6:42 with a 2:00 slot missed → do NOT fire; roll to
    the next slot. Fires only within the grace window of the scheduled time."""
    from datetime import datetime
    from src.scheduler import should_fire
    slot = datetime(2026, 7, 20, 2, 0)
    assert should_fire(datetime(2026, 7, 20, 2, 0, 30), slot) is True    # on time
    assert should_fire(datetime(2026, 7, 20, 2, 9), slot) is True        # within grace
    assert should_fire(datetime(2026, 7, 20, 6, 42), slot) is False      # hours late → skip
    assert should_fire(datetime(2026, 7, 20, 1, 59), slot) is False      # not yet


def test_trigger_refresh_pins_current_month(monkeypatch, tmp_path):
    import src.scheduler as sched
    from datetime import datetime
    captured = {}

    class FakeProc:
        pid = 12345

    def fake_popen(cmd, **kw):
        captured["env"] = kw.get("env")
        return FakeProc()

    monkeypatch.setattr(sched.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(sched, "LOG_FILE", tmp_path / "log.log")
    sched.trigger_refresh("cache")
    env = captured["env"]
    assert env is not None and env.get("MPR_PERIOD") == sched.period_for_run(datetime.now()), \
        "scheduled runs must pin the period explicitly (the 6:42 March incident); " \
        "since 2026-08-03 that is the CLOSE-AWARE period - the closing month " \
        "until its close file exists, then the current month"
