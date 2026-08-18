"""
Stale/hung pull handling (2026-07-24 incident: a scheduled live pull hung >10h,
held the SLX lock, and the console showed the PRIOR run's '100% Done' because
progress was read across the append-mode log's run boundaries).

Two fixes:
  1. latest_progress() reads only the CURRENT run (after the last 'run started'
     banner) — a hung run shows its real 0%/Starting, never a stale 100%.
  2. a hung run (pid alive but log not advancing for STALE_SECONDS) is detected
     and cleared: pid reset, SLX lock released, status downgraded.
"""
import os
import time
from pathlib import Path

import src.scheduler as sched


def _write_log(p: Path, text: str, mtime_age_s: float = 0):
    p.write_text(text)
    if mtime_age_s:
        old = time.time() - mtime_age_s
        os.utime(p, (old, old))


def test_latest_progress_ignores_previous_run(tmp_path):
    log = tmp_path / "run.log"
    _write_log(log,
               "===== run started 2026-07-23T02:00 (mode=live) =====\n"
               "[ 50%] pulling billables\n"
               "[100%] done\n"
               "===== run finished 2026-07-23T03:20 (rc=0) =====\n"
               "\n\n===== run started 2026-07-24T02:07 (mode=live) =====\n")
    # current run has NO progress line yet → 0%/Starting, NOT the prior 100%
    assert sched.latest_progress(log) == (0, "Starting…")


def test_latest_progress_reads_current_run(tmp_path):
    log = tmp_path / "run.log"
    _write_log(log,
               "===== run started 2026-07-23T02:00 =====\n[100%] done\n"
               "===== run started 2026-07-24T02:07 =====\n[ 30%] querying SLX\n")
    assert sched.latest_progress(log) == (30, "querying SLX")


def test_run_is_stale_by_log_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setattr(sched, "STALE_SECONDS", 1800)
    fresh = tmp_path / "fresh.log"; _write_log(fresh, "x\n", mtime_age_s=60)
    hung = tmp_path / "hung.log";   _write_log(hung, "x\n", mtime_age_s=3600)
    assert sched.run_is_stale(fresh) is False
    assert sched.run_is_stale(hung) is True
    assert sched.run_is_stale(tmp_path / "missing.log") is False


def test_tick_never_clears_a_live_hung_pid(tmp_path, monkeypatch):
    # A LIVE pid must never be auto-cleared even when the log is stale — clearing
    # it would free the SLX lock mid-pull. Automatic recovery is DEAD-pid only.
    monkeypatch.setattr(sched, "LOG_FILE", tmp_path / "run.log")
    monkeypatch.setattr(sched, "LOCK_PATH", tmp_path / ".runner.pid")
    monkeypatch.setattr(sched, "SCHEDULE_FILE", tmp_path / "schedule.json")
    monkeypatch.setattr(sched, "STALE_SECONDS", 1800)
    _write_log(tmp_path / "run.log", "===== run started =====\n", mtime_age_s=3600)
    sched.save_schedule({**sched.load_schedule(), "current_pid": os.getpid(),
                         "last_run_status": "running (pid X)"})
    assert sched._tick_stale_pid_cleanup() is False        # live pid preserved
    assert sched.load_schedule()["current_pid"] == os.getpid()


def test_force_clear_run_unblocks_manually(tmp_path, monkeypatch):
    # The explicit user action clears state + releases the lock (kill optional).
    monkeypatch.setattr(sched, "LOCK_PATH", tmp_path / ".runner.pid")
    monkeypatch.setattr(sched, "SCHEDULE_FILE", tmp_path / "schedule.json")
    (tmp_path / ".runner.pid").write_text("424242")
    sched.save_schedule({**sched.load_schedule(), "current_pid": 424242,
                         "last_run_status": "running (pid 424242)"})
    sched.force_clear_run(kill=False)
    st = sched.load_schedule()
    assert st["current_pid"] is None
    assert not (tmp_path / ".runner.pid").exists()
    assert "cleared manually" in st["last_run_status"]
