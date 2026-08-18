"""The nightly must survive Cloud Run replacing the container.

2026-08-15: the 02:00 pull did not run. The container was alive through the
slot, the logs were silent, and the console showed the next run as TOMORROW.
Root cause is structural, not a fluke: the firing rule asked "is the clock
within 10 minutes of `next_run_ts`?", `next_run_ts` lives on Cloud Run's
ephemeral disk, and Google replaces containers whenever it likes —
`--min-instances 1` guarantees *an* instance, not the *same* one. A wiped disk
recomputes the next slot as tomorrow, so the night is lost silently.

`due_now` asks the daily question instead: has today's pull happened, and are
we still inside the safe window? These tests pin that.
"""
from datetime import datetime, timedelta

from src import scheduler as S

ON = {"enabled": True, "hour": 2, "minute": 0}


def at(h, m=0):
    return datetime(2026, 8, 15, h, m)


def test_the_normal_case_still_fires_on_time():
    fire, why = S.due_now(at(2, 0), ON, already_ran=False)
    assert fire and why == "on time"


def test_a_container_born_after_the_slot_still_runs_todays_pull():
    """THE 8/15 FAILURE. A fresh instance at 03:06 has an empty disk, so its
    `next_run_ts` already points at tomorrow. The old rule lost the night here;
    the daily question does not."""
    fire, why = S.due_now(at(3, 6), ON, already_ran=False)
    assert fire, "a replacement container inside the window must still run today"
    assert "catch-up" in why and "66m late" in why


def test_it_will_not_run_twice():
    assert S.due_now(at(3, 6), ON, already_ran=True)[0] is False
    assert S.due_now(at(2, 0), ON, already_ran=True)[1] == "already ran today"


def test_the_window_closes_before_business_hours():
    """The 2026-07-20 ruling survives: a catch-up must never surprise anyone
    mid-morning against a CRM people are actively editing."""
    assert S.due_now(at(5, 59), ON, already_ran=False)[0] is True
    assert S.due_now(at(6, 0), ON, already_ran=False)[0] is False
    assert "window" in S.due_now(at(9, 30), ON, already_ran=False)[1]


def test_nothing_runs_before_the_slot_or_when_disabled():
    assert S.due_now(at(1, 59), ON, already_ran=False) == (False, "before today's slot")
    assert S.due_now(at(2, 30), {**ON, "enabled": False}, already_ran=False)[0] is False


def test_a_custom_hour_moves_the_whole_window():
    late = {"enabled": True, "hour": 22, "minute": 30}
    assert S.due_now(datetime(2026, 8, 15, 22, 30), late, already_ran=False)[0] is True
    assert S.due_now(datetime(2026, 8, 15, 22, 29), late, already_ran=False)[0] is False


def test_ran_today_reads_the_cache_when_the_disk_was_wiped(tmp_path):
    """`last_run_ts` is erasable; `pulled_at` in the scoreboard cache is
    written by every live pull and restored from SharePoint at boot. A fresh
    container must be able to tell that today's pull already happened."""
    (tmp_path / "scoreboard_2026-08.json").write_text(
        '{"_meta": {"pulled_at": "2026-08-15T02:04:11", "source": "slx-live"}}')
    now = datetime(2026, 8, 15, 3, 6)
    assert S.ran_today({}, now, cache_dir=tmp_path) is True, \
        "an empty schedule.json must not hide a pull that already ran"

    (tmp_path / "scoreboard_2026-08.json").write_text(
        '{"_meta": {"pulled_at": "2026-08-14T02:04:11", "source": "slx-live"}}')
    assert S.ran_today({}, now, cache_dir=tmp_path) is False


def test_ran_today_survives_junk_without_blocking_the_nightly():
    """Fail OPEN: unreadable state must not be able to suppress a pull."""
    now = datetime(2026, 8, 15, 3, 0)
    assert S.ran_today({"last_run_ts": "not-a-date"}, now, cache_dir="/nope") is False
