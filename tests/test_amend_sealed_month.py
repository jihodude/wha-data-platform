"""The R2 amend tool: one cell, one reason, notated forever, refuses drift."""
import json

import pytest

from scripts.amend_sealed_month import amend


def _seed(tmp_path, sealed=True):
    doc = {"period": "2026-07", "month": "Jul", "frozen": {},
           "amendments": [{"at": "2026-08-05", "what": "earlier fix"}]}
    if sealed:
        doc["sealed"] = {"drops_target": {"TKP": {"Jul": 0.0, "Apr": 1.0}}}
    (tmp_path / "close_2026-07.json").write_text(json.dumps(doc))
    return tmp_path


def test_amends_one_cell_and_notates(tmp_path):
    d = _seed(tmp_path)
    out = amend("2026-07", "drops_target", "TKP", "Jul", 1.0,
                why="Marina Square flip corrected", closes_dir=d,
                assume_yes=True, push=lambda *a: None)
    doc = json.loads((d / "close_2026-07.json").read_text())
    assert doc["sealed"]["drops_target"]["TKP"]["Jul"] == 1.0
    assert doc["sealed"]["drops_target"]["TKP"]["Apr"] == 1.0   # untouched
    rec = doc["amendments"][-1]
    assert rec["cell"] == {"territory": "TKP", "month": "Jul",
                           "old": 0.0, "new": 1.0}
    assert "Marina Square" in rec["what"]
    assert (d / "close_2026-07.json.bak-amend").exists()
    assert out["old"] == 0.0


def test_refuses_without_reason(tmp_path):
    d = _seed(tmp_path)
    with pytest.raises(SystemExit, match="without a reason"):
        amend("2026-07", "drops_target", "TKP", "Jul", 1.0, why="  ",
              closes_dir=d, assume_yes=True, push=lambda *a: None)


def test_refuses_unknown_cell_and_unsealed_month(tmp_path):
    d = _seed(tmp_path)
    with pytest.raises(SystemExit, match="no sealed cell"):
        amend("2026-07", "drops_target", "TKP", "Sep", 1.0, why="x",
              closes_dir=d, assume_yes=True, push=lambda *a: None)
    d2 = _seed(tmp_path / "u", sealed=False) if (tmp_path / "u").mkdir() is None else None
    with pytest.raises(SystemExit, match="not sealed"):
        amend("2026-07", "drops_target", "TKP", "Jul", 1.0, why="x",
              closes_dir=tmp_path / "u", assume_yes=True, push=lambda *a: None)
