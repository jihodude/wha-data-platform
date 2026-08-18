"""
test_cache_schema_version.py — the local cache is the contract for ~10 reports,
so load_scoreboard must FAIL LOUD on a schema it can't safely interpret rather
than silently loading wrong-shaped data (2026-07-17 gold-plate). Before this,
load_scoreboard only ever *warned* on ANY mismatch — despite a docstring that
promised `ValueError` on an incompatible schema. Ratified contract:

  - version == code version  → load, no schema warning
  - version OLDER than code  → load with a warning (forward-compatible:
                               scoreboard_from_dict defaults the missing fields)
  - version NEWER than code  → ValueError (fields written by newer code that
                               this code cannot safely interpret)
  - version missing/non-int  → ValueError (unversioned/corrupt; shape unknowable)
"""
import json
import warnings

import pytest

from reports.membership_performance_tracker.logic.cache import (
    CACHE_SCHEMA_VERSION,
    load_scoreboard,
    save_scoreboard,
)
from reports.membership_performance_tracker.logic.model import ScoreboardData


def _write(path, meta):
    path.write_text(json.dumps({"_meta": meta, "fields": {}}))
    return path


def test_matching_version_loads_without_schema_warning(tmp_path):
    p = save_scoreboard(ScoreboardData(), tmp_path / "match.json")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        data = load_scoreboard(p)
    assert isinstance(data, ScoreboardData)
    assert not [w for w in caught if "schema version" in str(w.message)]


def test_older_version_loads_with_warning(tmp_path):
    p = _write(tmp_path / "old.json", {"schema_version": CACHE_SCHEMA_VERSION - 1})
    with pytest.warns(UserWarning, match="schema version"):
        data = load_scoreboard(p)
    assert isinstance(data, ScoreboardData)


def test_newer_version_hard_fails(tmp_path):
    p = _write(tmp_path / "new.json", {"schema_version": CACHE_SCHEMA_VERSION + 1})
    with pytest.raises(ValueError, match="schema"):
        load_scoreboard(p)


def test_missing_version_hard_fails(tmp_path):
    p = (tmp_path / "nover.json")
    p.write_text(json.dumps({"fields": {}}))  # no _meta at all
    with pytest.raises(ValueError, match="schema"):
        load_scoreboard(p)


def test_save_scoreboard_preserves_given_saved_at(tmp_path):
    """The SP re-sync must not re-stamp the pull time (badge honesty, 7/20):
    save_scoreboard accepts the ORIGINAL snapshot timestamp."""
    p = save_scoreboard(ScoreboardData(), tmp_path / "s.json",
                        saved_at="2026-07-20T03:11:09")
    meta = json.loads(p.read_text())["_meta"]
    assert meta["saved_at"] == "2026-07-20T03:11:09"
