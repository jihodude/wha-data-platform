"""
test_drops_target_column.py — the Data-Drops / Data-Closed "Target (Y/N)" column
must render the tri-state target flag, not blank.

Regression for the bool-vs-string bug: reports.membership_performance_tracker.logic.drops emits ``is_target`` as the
STRING 'Y'/'N'/'?' (and ``was_member_at_closure`` as the string 'Y'), but
writer._yn only recognized bool True/False — so _yn('Y') fell through to '' and
EVERY Target cell rendered blank, silently contradicting the (correct) monthly
drop bucket counts that compare is_target == 'Y'.
"""
from pathlib import Path

import pytest

from reports.membership_performance_tracker.writer import TrackerV4Writer

# Anchor to the report package itself — position-independent (survived one
# tests/ relocation already; a __file__-depth anchor did not).
TEMPLATE = Path(__file__).resolve().parents[1] / "template.xlsx"


# ---------------------------------------------------------------------------
# _yn must accept the string tri-state the data layer actually emits
# ---------------------------------------------------------------------------

def test_yn_handles_string_tristate():
    assert TrackerV4Writer._yn("Y") == "Y"
    assert TrackerV4Writer._yn("N") == "N"
    assert TrackerV4Writer._yn("?") == ""      # unknown → blank, not a literal '?'


def test_yn_string_is_case_insensitive_and_trimmed():
    assert TrackerV4Writer._yn(" y ") == "Y"
    assert TrackerV4Writer._yn("n") == "N"


def test_yn_still_handles_bool_tristate():
    # The penetration/target classifier uses bool tri-state — keep it working.
    assert TrackerV4Writer._yn(True) == "Y"
    assert TrackerV4Writer._yn(False) == "N"
    assert TrackerV4Writer._yn(None) == ""


# ---------------------------------------------------------------------------
# Detail-row prep must surface the flag (the user-visible symptom)
# ---------------------------------------------------------------------------

def _writer():
    return TrackerV4Writer(TEMPLATE)


def test_prep_drops_populates_target_column():
    w = _writer()
    rows = w._prep_drops([
        {"account_id": "1", "account_name": "A", "is_target": "Y"},
        {"account_id": "2", "account_name": "B", "is_target": "N"},
        {"account_id": "3", "account_name": "C", "is_target": "?"},
    ])
    # Column index 6 is "Target (Y/N)" in _prep_drops ordering.
    assert [r[6] for r in rows] == ["Y", "N", ""]


def test_prep_closed_populates_target_and_was_member():
    w = _writer()
    rows = w._prep_closed([
        {"account_id": "1", "is_target": "Y", "was_member_at_closure": "Y"},
        {"account_id": "2", "is_target": "N", "was_member_at_closure": "Y"},
    ])
    # Index 5 = Target (Y/N), index 6 = Was Member at Closure.
    assert [r[5] for r in rows] == ["Y", "N"]
    assert [r[6] for r in rows] == ["Y", "Y"]
