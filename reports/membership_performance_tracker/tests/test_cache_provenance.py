"""The cache file must say what it holds — pre-overlay SData or the published
(post-overlay) numbers.

Why this exists (2026-07-30): the same filename `scoreboard_<period>.json` was
written by TWO writers meaning different things — a live pull saves SData's
own numbers BEFORE the Crystal overlay (deliberate: the SData cross-check and
the replay contract), while materializing from the SharePoint snapshot writes
the PUBLISHED post-overlay data. Nothing marked which. Comparing two caches of
different provenance produced a false regression alarm (drops 179 → 430 with
negative dollars) that took an hour of forensics to clear — and
`_cache_source()` in runner.py, built to answer exactly this, read a
`_meta.source` key that no writer ever set, so it silently answered 'slx'
always.
"""
import json
from pathlib import Path

from reports.membership_performance_tracker.logic.cache import save_scoreboard
from reports.membership_performance_tracker.logic.model import ScoreboardData


def test_save_records_provenance(tmp_path):
    p = save_scoreboard(ScoreboardData(), tmp_path / "sb.json", source="slx-preoverlay")
    meta = json.loads(Path(p).read_text())["_meta"]
    assert meta["source"] == "slx-preoverlay"


def test_save_without_source_says_so_instead_of_lying(tmp_path):
    """An unmarked save must be readable as 'unknown', never mistaken for a
    definite pipeline — the silent-'slx' default is what hid the ambiguity."""
    p = save_scoreboard(ScoreboardData(), tmp_path / "sb.json")
    meta = json.loads(Path(p).read_text())["_meta"]
    assert meta.get("source") == "unknown"
