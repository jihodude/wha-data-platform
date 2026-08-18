"""
P6 decoupling: DataHub generic per-(report, period) cache.

Contract (2026-07-22, reconstruction P6 — design decision confirmed:
shared SLX client + GENERIC per-report cache):

  hub.save_report_data(report, period, payload)  → data/cache/<report>_<period>.json
     envelope {"_meta": {saved_at, report, period}, "data": payload}
     + hub mirror Reports/<report>/Data/<report>_<period>.json
  hub.load_report_data(report, period)           → payload (SP/hub-first, local fallback)
     raises FileNotFoundError naming both locations when absent.

ScoreboardData never appears in this path — it is MPR-internal.
"""
import json

import pytest

import src.hub.datahub as dh
from src.hub.datahub import DataHub


@pytest.fixture
def local_hub(tmp_path, monkeypatch):
    monkeypatch.setattr(dh, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(dh, "HUB_LOCAL_DIR", tmp_path / "hub")
    return DataHub(sharepoint_client=None)


def test_save_then_load_roundtrip(local_hub, tmp_path):
    payload = {"territories": {"Pierce": {"collected": 123.45}}, "months": ["2026-06"]}
    local_hub.save_report_data("dues_analysis", "2026-06", payload)

    # local cache file exists with the envelope convention
    f = tmp_path / "cache" / "dues_analysis_2026-06.json"
    assert f.exists()
    env = json.loads(f.read_text())
    assert env["_meta"]["report"] == "dues_analysis"
    assert env["_meta"]["period"] == "2026-06"
    assert env["_meta"]["saved_at"]  # freshness guard convention
    assert env["data"] == payload

    # roundtrip returns the payload, not the envelope
    assert local_hub.load_report_data("dues_analysis", "2026-06") == payload


def test_save_writes_hub_mirror(local_hub, tmp_path):
    local_hub.save_report_data("dues_analysis", "2026-06", {"x": 1})
    mirror = (tmp_path / "hub" / "Reports" / "dues_analysis" / "Data"
              / "dues_analysis_2026-06.json")
    assert mirror.exists()


def test_load_missing_raises_with_both_paths(local_hub):
    with pytest.raises(FileNotFoundError) as e:
        local_hub.load_report_data("dues_analysis", "1999-01")
    msg = str(e.value)
    assert "dues_analysis_1999-01.json" in msg
    assert "Reports/dues_analysis/Data" in msg


def test_load_prefers_hub_mirror_over_local_cache(local_hub, tmp_path):
    # hub mirror (the shared source of truth when SP is offline it's the local
    # mirror of it) says 2, stale local cache says 1 → hub mirror wins
    local_hub.save_report_data("dues_analysis", "2026-06", {"v": 2})
    stale = {"_meta": {"saved_at": "2020-01-01T00:00:00Z",
                       "report": "dues_analysis", "period": "2026-06"},
             "data": {"v": 1}}
    (tmp_path / "cache" / "dues_analysis_2026-06.json").write_text(json.dumps(stale))
    assert local_hub.load_report_data("dues_analysis", "2026-06") == {"v": 2}


def test_hub_folder_display_name_avoids_duplicate_folders(local_hub, tmp_path):
    # code-name cache file locally, display-name folder in the hub mirror —
    # so one report never spawns two SP folders (dues_analysis vs Dues Analysis)
    local_hub.save_report_data("dues_analysis", "2026-06", {"v": 1},
                               hub_folder="Dues Analysis")
    assert (tmp_path / "cache" / "dues_analysis_2026-06.json").exists()
    mirror = (tmp_path / "hub" / "Reports" / "Dues Analysis" / "Data"
              / "dues_analysis_2026-06.json")
    assert mirror.exists()
    assert not (tmp_path / "hub" / "Reports" / "dues_analysis").exists()
    # round-trips only when the same hub_folder is given
    assert local_hub.load_report_data("dues_analysis", "2026-06",
                                      hub_folder="Dues Analysis") == {"v": 1}


def test_load_falls_back_to_local_cache(local_hub, tmp_path):
    only_local = {"_meta": {"saved_at": "2026-07-22T00:00:00Z",
                            "report": "dues_analysis", "period": "2026-05"},
                  "data": {"v": "local"}}
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cache" / "dues_analysis_2026-05.json").write_text(json.dumps(only_local))
    assert local_hub.load_report_data("dues_analysis", "2026-05") == {"v": "local"}
