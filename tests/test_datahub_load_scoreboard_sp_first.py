"""
test_datahub_load_scoreboard_sp_first.py — DataHub reads cache from SP first
(2026-06-05 PM).

Pins the user's architectural ask: any report engine asking DataHub for the
period cache must get the latest SLX snapshot from SharePoint if available,
falling back to the local mirror only when SP is unreachable. This is the
read-side of the cache-in-SP flow; the write-side is exercised by
test_runner_publish_to_hub.py.

Today `DataHub.load_scoreboard(period)` reads `data/cache/scoreboard_<period>.json`
local-only. After this change it tries:
  1. SP: latest snapshot via _load_latest_snapshot (prefers official, falls back
     to newest per-run)
  2. Local: `data/cache/scoreboard_<period>.json` (legacy save_scoreboard format)
  3. Raises FileNotFoundError citing both paths

The two payload formats differ — snapshot envelope vs legacy `{_meta, fields}` —
so the implementation must unwrap envelopes correctly when going through the
SP path.
"""

import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.hub.datahub import DataHub
from reports.membership_performance_tracker.logic.cache import save_scoreboard
from reports.membership_performance_tracker.logic.model import ScoreboardData, empty_scoreboard


FY_MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
             "Apr", "May", "Jun", "Jul", "Aug", "Sep"]


@pytest.fixture
def populated_scoreboard():
    """Distinctive scoreboard so we can tell SP-loaded data apart from local."""
    sd = empty_scoreboard(FY_MONTHS)
    sd.revenue["Pierce"]["Mar"] = 99_999.99
    sd.hosp_bills_target["Pierce"]["Mar"] = 777
    return sd


def _make_snapshot_envelope(period: str, sd: ScoreboardData, *, is_official: bool) -> bytes:
    """Build the on-the-wire snapshot bytes archive_snapshot writes."""
    envelope = {
        "schema_version": 1,
        "period": period,
        "captured_at": "2026-06-05T22:00:00Z",
        "is_official": is_official,
        "run_id": "official" if is_official else "2026-06-05T22-00-00Z",
        "data": asdict(sd),
    }
    return json.dumps(envelope, default=str).encode("utf-8")


# ---------------------------------------------------------------------------
# SP-first behavior
# ---------------------------------------------------------------------------

def test_load_scoreboard_prefers_sp_official_snapshot(populated_scoreboard, tmp_path, monkeypatch):
    """When SP has an official snapshot for the period, load it (not local)."""
    # Stub out local cache to something WRONG — proves SP path wins
    monkeypatch.setattr("src.hub.datahub.CACHE_DIR", tmp_path)
    wrong_local = empty_scoreboard(FY_MONTHS)
    wrong_local.revenue["Pierce"]["Mar"] = 0.0  # ≠ 99999.99
    save_scoreboard(wrong_local, tmp_path / "scoreboard_2026-03.json")

    hub = DataHub()
    hub._sp = MagicMock(name="sp_client")
    # SP folder listing: one official snapshot
    hub._sp.list_folder = MagicMock(return_value=[
        {"name": "snapshot_2026-03_official.json"},
    ])
    hub._sp.read_file = MagicMock(
        return_value=_make_snapshot_envelope("2026-03", populated_scoreboard, is_official=True)
    )

    sd = hub.load_data("2026-03")

    # Asserts the SP envelope was the winner
    assert sd.revenue["Pierce"]["Mar"] == 99_999.99
    assert sd.hosp_bills_target["Pierce"]["Mar"] == 777


def test_load_scoreboard_uses_newest_per_run_when_no_official(populated_scoreboard, tmp_path, monkeypatch):
    """No official snapshot → fall back to newest per-run snapshot in SP."""
    monkeypatch.setattr("src.hub.datahub.CACHE_DIR", tmp_path)

    hub = DataHub()
    hub._sp = MagicMock(name="sp_client")
    hub._sp.list_folder = MagicMock(return_value=[
        {"name": "snapshot_2026-03_2026-06-05T20-00-00Z.json"},
        {"name": "snapshot_2026-03_2026-06-05T22-00-00Z.json"},  # ← newest
    ])
    hub._sp.read_file = MagicMock(
        return_value=_make_snapshot_envelope("2026-03", populated_scoreboard, is_official=False)
    )

    sd = hub.load_data("2026-03")
    assert sd.revenue["Pierce"]["Mar"] == 99_999.99
    # Verify the read call targeted the newest filename, not the older one
    read_path = hub._sp.read_file.call_args.args[0]
    assert "T22-00-00Z" in read_path


# ---------------------------------------------------------------------------
# Local fallback
# ---------------------------------------------------------------------------

def test_load_scoreboard_falls_back_to_local_when_sp_unreachable(populated_scoreboard, tmp_path, monkeypatch):
    """SP throws on list_folder → use the local cache file."""
    monkeypatch.setattr("src.hub.datahub.CACHE_DIR", tmp_path)
    save_scoreboard(populated_scoreboard, tmp_path / "scoreboard_2026-03.json")

    hub = DataHub()
    hub._sp = MagicMock(name="sp_client")
    hub._sp.list_folder = MagicMock(side_effect=ConnectionError("SP offline"))

    sd = hub.load_data("2026-03")
    assert sd.revenue["Pierce"]["Mar"] == 99_999.99


def test_load_scoreboard_falls_back_to_local_when_sp_has_no_snapshot(populated_scoreboard, tmp_path, monkeypatch):
    """SP reachable but folder empty → use local cache."""
    monkeypatch.setattr("src.hub.datahub.CACHE_DIR", tmp_path)
    save_scoreboard(populated_scoreboard, tmp_path / "scoreboard_2026-03.json")

    hub = DataHub()
    hub._sp = MagicMock(name="sp_client")
    hub._sp.list_folder = MagicMock(return_value=[])

    sd = hub.load_data("2026-03")
    assert sd.revenue["Pierce"]["Mar"] == 99_999.99


def test_load_scoreboard_falls_back_to_local_when_sp_is_none(populated_scoreboard, tmp_path, monkeypatch):
    """No SP client at all (dev env) → local cache."""
    monkeypatch.setattr("src.hub.datahub.CACHE_DIR", tmp_path)
    save_scoreboard(populated_scoreboard, tmp_path / "scoreboard_2026-03.json")

    hub = DataHub()
    hub._sp = None

    sd = hub.load_data("2026-03")
    assert sd.revenue["Pierce"]["Mar"] == 99_999.99


def test_load_scoreboard_raises_when_neither_sp_nor_local_has_data(tmp_path, monkeypatch):
    """Last resort: SP empty + no local file → FileNotFoundError."""
    monkeypatch.setattr("src.hub.datahub.CACHE_DIR", tmp_path)

    hub = DataHub()
    hub._sp = MagicMock(name="sp_client")
    hub._sp.list_folder = MagicMock(return_value=[])

    with pytest.raises(FileNotFoundError):
        hub.load_data("2026-03")


# ---------------------------------------------------------------------------
# Fail-loud on SP errors (2026-07-17 gold-plate)
# A SharePoint error must NOT silently downgrade the read to a possibly-staler
# local cache. A listing/read error is loud; a genuinely-empty folder (no
# snapshot yet — the normal pre-publish case) stays quiet. Fallback itself is
# still correct either way — same fail-loud class as read_admin_inputs.
# ---------------------------------------------------------------------------

def test_sp_listing_error_warns_loudly_then_falls_back(populated_scoreboard, tmp_path, monkeypatch, capsys):
    """SP listing throws (network/auth) → WARN loudly, then use local cache."""
    monkeypatch.setattr("src.hub.datahub.CACHE_DIR", tmp_path)
    save_scoreboard(populated_scoreboard, tmp_path / "scoreboard_2026-03.json")

    hub = DataHub()
    hub._sp = MagicMock(name="sp_client")
    hub._sp.list_folder = MagicMock(side_effect=ConnectionError("SP down"))

    sd = hub.load_data("2026-03")
    assert sd.revenue["Pierce"]["Mar"] == 99_999.99  # local fallback still works
    out = capsys.readouterr().out
    assert "WARNING" in out and "2026-03" in out


def test_sp_empty_folder_falls_back_quietly(populated_scoreboard, tmp_path, monkeypatch, capsys):
    """No snapshot yet (empty folder) is NORMAL pre-publish → fall back QUIETLY."""
    monkeypatch.setattr("src.hub.datahub.CACHE_DIR", tmp_path)
    save_scoreboard(populated_scoreboard, tmp_path / "scoreboard_2026-03.json")

    hub = DataHub()
    hub._sp = MagicMock(name="sp_client")
    hub._sp.list_folder = MagicMock(return_value=[])

    sd = hub.load_data("2026-03")
    assert sd.revenue["Pierce"]["Mar"] == 99_999.99
    assert "WARNING" not in capsys.readouterr().out


def test_sp_corrupt_official_snapshot_warns_then_uses_local(populated_scoreboard, tmp_path, monkeypatch, capsys):
    """A snapshot file that won't parse must WARN (not be silently skipped)."""
    monkeypatch.setattr("src.hub.datahub.CACHE_DIR", tmp_path)
    save_scoreboard(populated_scoreboard, tmp_path / "scoreboard_2026-03.json")

    hub = DataHub()
    hub._sp = MagicMock(name="sp_client")
    hub._sp.list_folder = MagicMock(return_value=[{"name": "snapshot_2026-03_official.json"}])
    hub._sp.read_file = MagicMock(return_value=b"{ this is not valid json")

    sd = hub.load_data("2026-03")
    assert sd.revenue["Pierce"]["Mar"] == 99_999.99  # local fallback
    out = capsys.readouterr().out
    assert "WARNING" in out
