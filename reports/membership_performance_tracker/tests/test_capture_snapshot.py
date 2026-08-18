"""test_capture_snapshot.py — the month-end alarm must scream at the right
times and only then (Layer-2: a missed point-in-time month is unrecoverable)."""
from datetime import date
from pathlib import Path

from scripts.capture_snapshot import default_period, monthend_alarm


def test_default_period():
    assert default_period(date(2026, 7, 15)) == "2026-07"


def test_alarm_screams_when_month_closing_uncaptured(tmp_path):
    scream, period, days = monthend_alarm(date(2026, 7, 29), tmp_path)
    assert scream and period == "2026-07" and days == 3


def test_alarm_quiet_when_captured(tmp_path):
    (tmp_path / "scoreboard_2026-07.json").write_text("{}")
    scream, _, _ = monthend_alarm(date(2026, 7, 31), tmp_path)
    assert not scream


def test_alarm_quiet_mid_month(tmp_path):
    scream, _, days = monthend_alarm(date(2026, 7, 15), tmp_path)
    assert not scream and days > 3


def test_alarm_handles_year_end(tmp_path):
    scream, period, days = monthend_alarm(date(2026, 12, 30), tmp_path)
    assert scream and period == "2026-12" and days == 2


def test_save_scoreboard_is_atomic(tmp_path, monkeypatch):
    """P1-7 (7/16): the cache is the contract for ~10 reports — a crash
    mid-write must never leave a corrupt scoreboard json. Write to a temp
    sibling, then os.replace (atomic on POSIX)."""
    import json
    from reports.membership_performance_tracker.logic import cache as cachemod
    from reports.membership_performance_tracker.logic.model import empty_scoreboard

    calls = {}
    real_replace = cachemod.os.replace
    def spy(src, dst):
        calls["src"], calls["dst"] = str(src), str(dst)
        return real_replace(src, dst)
    monkeypatch.setattr(cachemod.os, "replace", spy)

    out = tmp_path / "scoreboard_2026-06.json"
    cachemod.save_scoreboard(empty_scoreboard(["Oct"]), out)
    assert calls, "save must go through os.replace (atomic), not direct write"
    assert calls["dst"] == str(out)
    payload = json.loads(out.read_text())
    assert "_meta" in payload and "fields" in payload
    leftovers = [p for p in tmp_path.iterdir() if p.name != out.name]
    assert not leftovers, f"temp file must not linger: {leftovers}"


def test_pull_lock_blocks_second_runner(tmp_path):
    """P1-7c: ONE SLX session at a time — enforced by the runner itself, not
    just by whoever remembers the rule. Stale locks (dead pid) self-clear."""
    import os
    from reports.membership_performance_tracker.runner import acquire_pull_lock, release_pull_lock

    lock = tmp_path / ".runner.pid"
    assert acquire_pull_lock(lock) is True, "first acquire wins"
    assert acquire_pull_lock(lock) is False, "same-machine second runner refused"
    release_pull_lock(lock)
    assert not lock.exists()

    lock.write_text("999999999")  # dead pid → stale lock self-clears
    assert acquire_pull_lock(lock) is True
    release_pull_lock(lock)


def test_scheduler_monthend_tick_surfaces_alarm(tmp_path, monkeypatch):
    """C3 (7/16): the Railway-hosted scheduler carries the month-end alarm —
    if the closing month has no snapshot, schedule.json gets a screaming
    banner the console can show (and the log gets a line)."""
    from datetime import date
    import src.scheduler as sched

    monkeypatch.setattr(sched, "SCHEDULE_FILE", tmp_path / "schedule.json", raising=False)
    msg = sched._tick_monthend_alarm(today=date(2026, 7, 30), cache_dir=tmp_path)
    assert msg and "2026-07" in msg and "NO SNAPSHOT" in msg.upper()

    (tmp_path / "scoreboard_2026-07.json").write_text("{}")
    assert sched._tick_monthend_alarm(today=date(2026, 7, 30), cache_dir=tmp_path) is None
