"""One SLX session at a time — and never announce a run that won't happen.

Hard rule #5 is enforced mechanically by the runner's file lock, so the DATA
was never at risk from two people clicking at once: the second pull exits on
arrival. What was wrong was the telling. `trigger_refresh` wrote the "run
started" banner BEFORE spawning, so the loser of a race got a success message
and a log entry for a pull that had already died, and waited three hours for
it. Two people clicking within a few seconds is all it takes — no UI can
refresh fast enough to hide the button from both.
"""


# ── One SLX session: don't announce a run that won't happen (8/13) ───────────
# The runner takes the single-session lock and a second live pull exits on
# arrival, so the DATA was never at risk. But the "run started" banner was
# written before the spawn, so the loser of a race saw a success message and a
# log entry, then waited three hours for a pull that had already died.

def test_a_second_live_pull_is_refused_and_never_announced(tmp_path, monkeypatch):
    import os
    from src import scheduler as sch

    lock = tmp_path / ".runner.pid"
    lock.write_text(str(os.getpid()))          # a live pull owns the lock
    monkeypatch.setattr(sch, "LOCK_PATH", lock)
    log = tmp_path / "run.log"
    monkeypatch.setattr(sch, "LOG_FILE", log)

    def _boom(*a, **k):
        raise AssertionError("a second live pull must never be spawned")
    monkeypatch.setattr(sch.subprocess, "Popen", _boom)

    assert sch.live_pull_in_progress() is True
    assert sch.trigger_refresh("live") == 0, "caller must learn it did not start"
    assert not log.exists(), "a refused pull must not write a started banner"


def test_a_dead_lock_does_not_block_the_next_pull(tmp_path, monkeypatch):
    from src import scheduler as sch
    lock = tmp_path / ".runner.pid"
    lock.write_text("999999")                  # crashed run, pid long gone
    monkeypatch.setattr(sch, "LOCK_PATH", lock)
    assert sch.live_pull_in_progress() is False, (
        "a stale lock must not wedge the schedule — the runner clears it")


def test_no_lock_file_means_nothing_is_running(tmp_path, monkeypatch):
    from src import scheduler as sch
    monkeypatch.setattr(sch, "LOCK_PATH", tmp_path / "absent.pid")
    assert sch.live_pull_in_progress() is False
