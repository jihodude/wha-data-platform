"""
test_console_period_resolution.py — Phase C: the console must default to the
NEWEST period that actually has data, never a pinned month (the March-download
incident: a hardcoded default served stale March data that LOOKED fresh).

`list_available_periods` is the testable core the console builds on: scan the
cache dir for scoreboard_YYYY-MM.json, newest first, ignoring junk.
"""
from src.config.period import list_available_periods


def _touch(d, name):
    (d / name).write_text("{}")


def test_lists_periods_newest_first(tmp_path):
    for n in ("scoreboard_2026-03.json", "scoreboard_2026-06.json", "scoreboard_2025-12.json"):
        _touch(tmp_path, n)
    assert list_available_periods(tmp_path) == ["2026-06", "2026-03", "2025-12"]


def test_ignores_junk_and_non_period_files(tmp_path):
    for n in ("scoreboard_2026-06.json", "scoreboard_2026-06.json.tmp",
              "scoreboard_backup.json", "notes.txt", "scoreboard_2026-6.json"):
        _touch(tmp_path, n)
    assert list_available_periods(tmp_path) == ["2026-06"]


def test_empty_or_missing_dir_returns_empty(tmp_path):
    assert list_available_periods(tmp_path) == []
    assert list_available_periods(tmp_path / "nope") == []
