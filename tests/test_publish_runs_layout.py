"""Output layout (Jiho 8/10): every generation lands in
Output/<period>/Runs/<run-date>/, and a CLOSED month refreshes FINAL —
closed-ness read from Data/closes/ (the restructure home; the old Closes/
probe silently disabled FINAL self-healing)."""
import datetime
import json

import pytest

import src.hub.datahub as dh
from src.hub.datahub import DataHub


@pytest.fixture
def local_hub(tmp_path, monkeypatch):
    monkeypatch.setattr(dh, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(dh, "HUB_LOCAL_DIR", tmp_path / "hub")
    monkeypatch.setattr(dh, "OUTPUT_DIR", tmp_path / "output")
    return DataHub(sharepoint_client=None)


def test_runs_nest_under_run_date_folders(local_hub, tmp_path):
    local_hub.publish_report_versioned(
        "Membership Performance Report", "Report_2026-08.xlsx", b"x")
    today = datetime.date.today().strftime("%Y-%m-%d")
    day = (tmp_path / "hub" / "Reports" / "Membership Performance Report"
           / "Output" / "2026-08" / "Runs" / today)
    files = list(day.glob("*.xlsx"))
    assert len(files) == 1, f"run must land in Runs/{today}/: {day}"
    assert files[0].name.startswith("Report_2026-08_")


def test_closed_month_refreshes_final_from_data_closes(local_hub, tmp_path):
    close = (tmp_path / "hub" / "Reports" / "Membership Performance Report"
             / "Data" / "closes" / "close_2026-07.json")
    close.parent.mkdir(parents=True, exist_ok=True)
    close.write_text(json.dumps({"period": "2026-07"}))
    local_hub.publish_report_versioned(
        "Membership Performance Report", "Report_2026-07.xlsx", b"y")
    final = (tmp_path / "hub" / "Reports" / "Membership Performance Report"
             / "Output" / "2026-07" / "FINAL" / "Report_2026-07.xlsx")
    assert final.exists(), "sealed month must refresh FINAL (self-healing)"


def test_new_month_gets_its_own_period_and_day_folders(local_hub, tmp_path,
                                                       monkeypatch):
    """Jiho 8/10: on Sept 1 the first run must create Output/2026-09/ and
    land in Runs/2026-09-01/ — period from the report's filename, day from
    the clock at publish time."""
    class _FakeDT(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 1, 2, 5, 0)
    # publish does `from datetime import datetime` at call time, so patching
    # the module attribute reaches it
    monkeypatch.setattr(datetime, "datetime", _FakeDT)

    local_hub.publish_report_versioned(
        "Membership Performance Report", "Report_2026-09.xlsx", b"z")
    day = (tmp_path / "hub" / "Reports" / "Membership Performance Report"
           / "Output" / "2026-09" / "Runs" / "2026-09-01")
    assert list(day.glob("*.xlsx")), "Sept 1 run must open 2026-09/Runs/2026-09-01/"
