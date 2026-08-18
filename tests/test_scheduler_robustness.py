"""
test_scheduler_robustness.py — schedule.json reliability (2026-06-05).

Pins three robustness contracts surfaced by adversarial verify on the Bug 3 diff:

  • #4 Scheduler loop must clean up stale current_pid even when last_run_status
       is None (DEFAULT_STATE value), not silent-swallow an AttributeError.
  • #1a save_schedule must write atomically (tempfile + os.replace) so a
       SIGKILL or disk-full mid-write cannot leave the file truncated.
  • #1b load_schedule must quarantine a corrupt schedule.json (rename it aside
       with a timestamp) and persist DEFAULT_STATE so the next read is clean
       AND so the user has a forensic artifact explaining what happened.

These are not Bug 3 itself — they're hardening the schedule.json substrate that
Bug 3's _update_schedule_status writes into, so a single corrupt write or fresh
install doesn't silently break the nightly schedule.
"""

import json
import os
import time
from pathlib import Path

import pytest

from src import scheduler as sched_mod


@pytest.fixture
def temp_schedule(tmp_path, monkeypatch):
    """Point the scheduler at a per-test temp schedule.json."""
    path = tmp_path / "schedule.json"
    monkeypatch.setattr(sched_mod, "SCHEDULE_FILE", path)
    return path


# ---------------------------------------------------------------------------
# #4 — None-safe last_run_status check in _scheduler_loop's stale-PID cleanup
# ---------------------------------------------------------------------------

def test_stale_pid_cleanup_when_last_run_status_is_none(temp_schedule):
    """
    Fresh-install scenario: state has current_pid pointing at a dead process AND
    last_run_status=None (DEFAULT_STATE value). The loop body's stale-PID block
    must NOT raise AttributeError on None.startswith(), and must still clear
    current_pid so the dead PID doesn't linger.

    Failing today: line 156 does
        state.get("last_run_status", "").startswith("running")
    which returns None (key exists, value is None), and None.startswith() raises.
    The bare except Exception swallows it, so current_pid never gets cleared.
    """
    dead_pid = 99999  # almost certainly not running
    state = {
        "enabled":         False,
        "hour":             2,
        "minute":           0,
        "current_pid":     dead_pid,
        "last_run_status": None,        # ← the trap
        "last_run_ts":     None,
        "next_run_ts":     None,
    }
    sched_mod.save_schedule(state)

    # Execute exactly the loop-body cleanup logic, not the loop itself
    # (the real loop sleeps 60s between ticks). Inline the cleanup contract:
    cleaned = sched_mod._tick_stale_pid_cleanup()

    assert cleaned is True, "should report that it did cleanup work"
    after = sched_mod.load_schedule()
    assert after["current_pid"] is None, "dead PID must be cleared"


def test_stale_pid_cleanup_preserves_running_pid(temp_schedule):
    """Live PID should NOT be cleared — only dead ones."""
    live_pid = os.getpid()
    state = {
        "enabled":          False,
        "current_pid":      live_pid,
        "last_run_status":  f"running (pid {live_pid})",
    }
    sched_mod.save_schedule(state)

    sched_mod._tick_stale_pid_cleanup()
    after = sched_mod.load_schedule()
    assert after["current_pid"] == live_pid


# ---------------------------------------------------------------------------
# #1a — save_schedule must be atomic (no torn write)
# ---------------------------------------------------------------------------

def test_save_schedule_is_atomic(temp_schedule, monkeypatch):
    """
    Simulate a write-to-final-path failure midway through. With atomic write
    (tempfile + os.replace), the final path either has the old contents or the
    new contents — never a torn intermediate.

    Failing today: write_text writes directly to the final path. A simulated
    failure leaves the final path partially written (or empty).
    """
    # Seed a valid file
    original = {"enabled": True, "hour": 2, "minute": 0,
                "last_run_status": "done", "current_pid": None,
                "last_run_ts": None, "next_run_ts": None}
    sched_mod.save_schedule(original)

    # Force os.replace to fail — simulates disk-full at the rename step
    def boom(*args, **kwargs):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(os, "replace", boom)

    new_state = {**original, "enabled": False, "hour": 4}
    with pytest.raises(OSError):
        sched_mod.save_schedule(new_state)

    # File still readable + still has ORIGINAL contents (atomic guarantee)
    reread = json.loads(temp_schedule.read_text())
    assert reread == original


# ---------------------------------------------------------------------------
# #1b — load_schedule must quarantine corrupt JSON, not silently mask it
# ---------------------------------------------------------------------------

def test_load_schedule_quarantines_corrupt_file(temp_schedule):
    """
    Corrupt JSON today causes load_schedule to return DEFAULT_STATE (enabled=False)
    silently. The user's nightly schedule then never fires and they have no signal.

    Contract: on JSONDecodeError, rename the bad file to
    schedule.json.corrupt.<timestamp> and persist DEFAULT_STATE to the canonical
    path. Next load comes back clean, AND the forensic artifact survives for
    debugging.
    """
    temp_schedule.write_text('{"enabled":true,"hour":2,"minu')  # truncated

    state = sched_mod.load_schedule()

    # Returned defaults
    assert state["enabled"] is False
    # Canonical path now contains valid DEFAULT_STATE (not the corrupt bytes)
    rewritten = json.loads(temp_schedule.read_text())
    assert rewritten["enabled"] is False

    # Quarantined copy exists alongside
    parent = temp_schedule.parent
    quarantined = list(parent.glob("schedule.json.corrupt.*"))
    assert len(quarantined) == 1, (
        f"expected exactly one quarantined copy, found {quarantined}"
    )
    # It contains the original corrupt bytes for forensics
    assert quarantined[0].read_text() == '{"enabled":true,"hour":2,"minu'


def test_load_schedule_does_not_quarantine_valid_json(temp_schedule):
    """Sanity guard: a valid file must NOT trigger quarantine."""
    sched_mod.save_schedule({"enabled": True, "hour": 3, "minute": 30})

    # Multiple loads — must remain idempotent
    sched_mod.load_schedule()
    sched_mod.load_schedule()
    sched_mod.load_schedule()

    parent = temp_schedule.parent
    quarantined = list(parent.glob("schedule.json.corrupt.*"))
    assert quarantined == [], "valid file must never be quarantined"


def test_load_schedule_handles_missing_file_no_quarantine(temp_schedule):
    """Missing file path → defaults, no quarantine artifact created."""
    assert not temp_schedule.exists()
    state = sched_mod.load_schedule()
    assert state["enabled"] is False
    # No quarantine sidecar for the absent-file case
    parent = temp_schedule.parent
    assert list(parent.glob("schedule.json.corrupt.*")) == []
