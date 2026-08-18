"""Cloud Run's disk resets on every instance restart, so schedule.json
vanishes and the nightly silently reverts to DEFAULT_STATE — which was
enabled=False. WHA_SCHEDULE_DEFAULT_ENABLED=1 (set only in the cloud
deploy's env) makes a *missing* schedule file default to ON at 2:00 AM,
so an instance recycle can never quietly kill the nightly. A schedule
file that EXISTS always wins — the env var is a default, not an override
(found in the 8/8 first-deploy verification)."""
import importlib
import json
import os

import pytest


@pytest.fixture(autouse=True)
def _reload_clean_after():
    """reload() bakes the env default into DEFAULT_STATE at import time —
    without this, the last test here leaked enabled=True into every later
    test file (caught 8/8: robustness tests failed only in the full run)."""
    yield
    os.environ.pop("WHA_SCHEDULE_DEFAULT_ENABLED", None)
    import src.scheduler as sched
    importlib.reload(sched)


def _fresh_scheduler(tmp_path, monkeypatch, env_val):
    import src.scheduler as sched
    if env_val is None:
        monkeypatch.delenv("WHA_SCHEDULE_DEFAULT_ENABLED", raising=False)
    else:
        monkeypatch.setenv("WHA_SCHEDULE_DEFAULT_ENABLED", env_val)
    importlib.reload(sched)
    monkeypatch.setattr(sched, "SCHEDULE_FILE", tmp_path / "schedule.json")
    return sched


def test_missing_file_defaults_on_when_env_set(tmp_path, monkeypatch):
    sched = _fresh_scheduler(tmp_path, monkeypatch, "1")
    st = sched.load_schedule()
    assert st["enabled"] is True
    assert (st["hour"], st["minute"]) == (2, 0)


def test_missing_file_stays_off_without_env(tmp_path, monkeypatch):
    sched = _fresh_scheduler(tmp_path, monkeypatch, None)
    assert sched.load_schedule()["enabled"] is False


def test_existing_file_beats_env_default(tmp_path, monkeypatch):
    sched = _fresh_scheduler(tmp_path, monkeypatch, "1")
    (tmp_path / "schedule.json").write_text(json.dumps({"enabled": False}))
    assert sched.load_schedule()["enabled"] is False


def test_enabled_without_next_run_self_heals(tmp_path, monkeypatch):
    # The cloud ticker guard is `enabled and next_run_ts` — a fresh
    # env-defaulted instance had enabled=True, next_run_ts=None and never
    # fired (8/8 sweep). refresh_next_run must stamp a real next run.
    sched = _fresh_scheduler(tmp_path, monkeypatch, "1")
    st = sched.load_schedule()
    assert st["enabled"] is True and st["next_run_ts"] is None
    healed = sched.refresh_next_run()
    assert healed["next_run_ts"] is not None
