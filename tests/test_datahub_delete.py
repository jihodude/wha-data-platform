"""
delete_hub_file directory bug (task #17, found during the 2026-07-22 SP
folder cleanup): the leftover 'dues_analysis' FOLDER could not be removed —
Path.unlink() raises on directories. Deleting a hub path must handle files
AND directories on the local mirror, and stay silent on already-absent paths.
"""
import pytest

import src.hub.datahub as dh
from src.hub.datahub import DataHub


@pytest.fixture
def local_hub(tmp_path, monkeypatch):
    monkeypatch.setattr(dh, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(dh, "HUB_LOCAL_DIR", tmp_path / "hub")
    return DataHub(sharepoint_client=None)


def test_delete_hub_file_removes_a_file(local_hub, tmp_path):
    f = tmp_path / "hub" / "Reports" / "X" / "old.json"
    f.parent.mkdir(parents=True)
    f.write_text("{}")
    local_hub.delete_hub_file("Reports/X/old.json")
    assert not f.exists()


def test_delete_hub_file_removes_a_directory_tree(local_hub, tmp_path):
    d = tmp_path / "hub" / "Reports" / "dues_analysis"
    (d / "Data").mkdir(parents=True)
    (d / "Data" / "stale.json").write_text("{}")
    local_hub.delete_hub_file("Reports/dues_analysis")
    assert not d.exists()


def test_delete_hub_file_absent_path_is_silent(local_hub):
    local_hub.delete_hub_file("Reports/never_existed.json")
