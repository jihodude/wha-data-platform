"""
test_runner_publish_to_hub.py — runner pushes cache + xlsx to SP (2026-06-05 PM).

Pins the contract for the new `_publish_to_hub` helper in runner.py. This is
the wiring that makes the architecture the user asked for work:

  • Any SLX refresh (scheduled, console "Trigger Full Refresh Now", console
    "Generate Selected Reports") pushes the freshly-pulled cache to SP at
    `Audit & History Log/Snapshots/<period>/snapshot_<period>_official.json`
    PLUS a timestamped per-run record for audit history.
  • The finished xlsx report ALSO uploads to the versioned Reports folder,
    so the detached "Trigger Full Refresh" path stops being SP-blind.
  • Both writes are best-effort — if SP is unavailable (dev env, missing
    creds), the runner silently skips and still produces local output.
  • A partial failure (cache lands but xlsx upload fails, or vice versa)
    must not propagate as a process error; report both outcomes so the
    caller can log.

The helper is the seam — runner.main() calls it once at the end. The Streamlit
"Generate Selected Reports" path can stop carrying its own SP upload code
(deferred cleanup; not in this commit).
"""

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from reports.membership_performance_tracker import runner as runner_mod
from reports.membership_performance_tracker.logic.model import empty_scoreboard


FY_MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
             "Apr", "May", "Jun", "Jul", "Aug", "Sep"]


@pytest.fixture
def stub_data():
    """Minimal ScoreboardData with a couple of populated cells."""
    data = empty_scoreboard(FY_MONTHS)
    data.revenue["Pierce"]["Mar"] = 12345.67
    data.hosp_bills_target["Pierce"]["Mar"] = 42
    return data


@pytest.fixture
def fake_xlsx(tmp_path):
    """A real on-disk xlsx-named file so output_path.exists() + read_bytes() work."""
    p = tmp_path / "Membership_Performance_Report_2026-03.xlsx"
    p.write_bytes(b"PK\x03\x04fake-xlsx-bytes")  # ZIP magic so this looks xlsx-ish
    return p


@pytest.fixture
def fake_hub():
    """
    A DataHub-shaped mock. SP-connected by default; tests override via attribute.
    Tracks every call so assertions can check ordering + arguments.
    """
    hub = MagicMock()
    hub._sp = MagicMock(name="sp_client")  # truthy → "SP available"
    hub.archive_snapshot = MagicMock(
        side_effect=lambda period, data, is_official=False, run_ts=None: (
            f"Audit & History Log/Snapshots/{period}/"
            f"snapshot_{period}_{'official' if is_official else (run_ts or 'run123')}.json"
        )
    )
    hub.publish_report_versioned = MagicMock(
        return_value="Reports/Membership Performance Report/Output/2026-06-05/file.xlsx"
    )
    return hub


# ---------------------------------------------------------------------------
# Cache snapshot uploads
# ---------------------------------------------------------------------------

def test_publish_uploads_official_snapshot_on_live_slx(stub_data, fake_xlsx, fake_hub, monkeypatch):
    """Live SLX runs (is_live_slx=True, default): write the canonical official snapshot."""
    monkeypatch.setattr(runner_mod, "_datahub_factory", lambda: fake_hub)

    result = runner_mod._publish_to_hub(
        data=stub_data, output_path=fake_xlsx, period="2026-03",
        is_live_slx=True,
    )

    # Exactly one archive_snapshot call with is_official=True
    official_calls = [c for c in fake_hub.archive_snapshot.call_args_list
                      if c.kwargs.get("is_official") is True]
    assert len(official_calls) == 1
    assert official_calls[0].args[0] == "2026-03"
    assert result["cache_snapshot_path"] is not None
    assert "_official" in result["cache_snapshot_path"]


def test_publish_skips_official_snapshot_on_cache_mode(stub_data, fake_xlsx, fake_hub, monkeypatch):
    """
    Structural fix 2026-06-06: cache-mode runs (is_live_slx=False) must NOT
    overwrite the canonical _official snapshot. Otherwise re-processing a
    materialized-from-SP cache cements partial data as canonical, creating a
    feedback loop where bad SP → bad cache → bad SP.
    """
    monkeypatch.setattr(runner_mod, "_datahub_factory", lambda: fake_hub)

    result = runner_mod._publish_to_hub(
        data=stub_data, output_path=fake_xlsx, period="2026-03",
        is_live_slx=False,
    )

    # Zero archive_snapshot calls with is_official=True
    official_calls = [c for c in fake_hub.archive_snapshot.call_args_list
                      if c.kwargs.get("is_official") is True]
    assert official_calls == [], "cache-mode run must NOT touch the official snapshot"
    assert result["cache_snapshot_path"] is None

    # Per-run audit entry still written
    per_run_calls = [c for c in fake_hub.archive_snapshot.call_args_list
                     if c.kwargs.get("is_official") is False]
    assert len(per_run_calls) == 1, "per-run audit entry must still be written in cache-mode"

    # Xlsx NOT uploaded (contract changed 2026-08-03 — cache-mode builds are
    # local verification artifacts; publishing needs MPR_PUBLISH=1. See
    # test_cache_mode_does_not_upload_xlsx_unless_asked.)
    assert result["xlsx_sp_path"] is None


def test_publish_also_writes_per_run_audit_entry(stub_data, fake_xlsx, fake_hub, monkeypatch):
    """Audit trail: archive_snapshot(period, data, is_official=False)."""
    monkeypatch.setattr(runner_mod, "_datahub_factory", lambda: fake_hub)

    runner_mod._publish_to_hub(data=stub_data, output_path=fake_xlsx, period="2026-03")

    per_run_calls = [c for c in fake_hub.archive_snapshot.call_args_list
                     if c.kwargs.get("is_official") is False]
    assert len(per_run_calls) == 1


def test_publish_uses_same_run_ts_for_official_and_per_run(
    stub_data, fake_xlsx, fake_hub, monkeypatch
):
    """
    Audit-trail integrity: the official snapshot and the per-run snapshot from
    a single _publish_to_hub call must share one run_id. Otherwise the
    discrepancy-checker can't trace 'which per-run file produced the current
    official'. Verify Med #8 from the 2026-06-05 adversarial pass; proven in
    practice by QA chip task_f770f709 (run_id 22b3Z official, 52d8Z per-run).

    Format pin: must match src/hub/audit.py:_now_ts —
        YYYY-MM-DDTHH-MM-SS-mmmmmm-XXXXZ
    where XXXX is 4 lowercase hex chars (secrets.token_hex(2)).
    """
    monkeypatch.setattr(runner_mod, "_datahub_factory", lambda: fake_hub)

    runner_mod._publish_to_hub(data=stub_data, output_path=fake_xlsx, period="2026-03")

    official = [c for c in fake_hub.archive_snapshot.call_args_list
                if c.kwargs.get("is_official") is True]
    per_run = [c for c in fake_hub.archive_snapshot.call_args_list
               if c.kwargs.get("is_official") is False]
    assert len(official) == 1 and len(per_run) == 1

    official_ts = official[0].kwargs.get("run_ts")
    per_run_ts = per_run[0].kwargs.get("run_ts")

    assert official_ts is not None, "official call must receive run_ts kwarg"
    assert per_run_ts is not None, "per-run call must receive run_ts kwarg"
    assert official_ts == per_run_ts, (
        f"run_ts must match between official ({official_ts!r}) and "
        f"per-run ({per_run_ts!r}) — audit trail depends on this"
    )

    pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{6}-[0-9a-f]{4}Z$"
    )
    assert pattern.match(official_ts), (
        f"run_ts {official_ts!r} does not match audit.py:_now_ts format"
    )


# ---------------------------------------------------------------------------
# Xlsx upload
# ---------------------------------------------------------------------------

def test_publish_uploads_xlsx_to_versioned_path(stub_data, fake_xlsx, fake_hub, monkeypatch):
    """The finished xlsx lands under Reports/<REPORT_NAME>/Output/<date>/."""
    monkeypatch.setattr(runner_mod, "_datahub_factory", lambda: fake_hub)

    result = runner_mod._publish_to_hub(
        data=stub_data, output_path=fake_xlsx, period="2026-03",
    )

    assert fake_hub.publish_report_versioned.called
    call = fake_hub.publish_report_versioned.call_args
    # The bytes are the xlsx file contents
    args_and_kwargs = {**dict(zip(["data", "report_name", "filename"], call.args)), **call.kwargs}
    assert args_and_kwargs.get("data") == fake_xlsx.read_bytes() or \
           call.kwargs.get("data") == fake_xlsx.read_bytes()
    assert result["xlsx_sp_path"] is not None


# ---------------------------------------------------------------------------
# Graceful skip + partial failure
# ---------------------------------------------------------------------------

def test_publish_silent_when_no_sp(stub_data, fake_xlsx, monkeypatch):
    """No SP client (dev env) → silent no-op, no error, no calls attempted."""
    hub = MagicMock()
    hub._sp = None     # falsy → "no SP"
    hub.archive_snapshot = MagicMock()
    hub.publish_report_versioned = MagicMock()
    monkeypatch.setattr(runner_mod, "_datahub_factory", lambda: hub)

    result = runner_mod._publish_to_hub(data=stub_data, output_path=fake_xlsx, period="2026-03")

    assert hub.archive_snapshot.call_count == 0
    assert hub.publish_report_versioned.call_count == 0
    assert result["cache_snapshot_path"] is None
    assert result["xlsx_sp_path"] is None
    assert result["errors"] == []  # not an error condition


def test_publish_continues_when_snapshot_fails_but_xlsx_succeeds(
    stub_data, fake_xlsx, fake_hub, monkeypatch
):
    """Partial failure: snapshot upload throws, xlsx still gets attempted."""
    fake_hub.archive_snapshot.side_effect = RuntimeError("SP timeout on snapshot")
    monkeypatch.setattr(runner_mod, "_datahub_factory", lambda: fake_hub)

    result = runner_mod._publish_to_hub(data=stub_data, output_path=fake_xlsx, period="2026-03")

    assert fake_hub.publish_report_versioned.called
    assert result["xlsx_sp_path"] is not None
    assert any("snapshot" in e.lower() for e in result["errors"])


def test_publish_handles_missing_xlsx(stub_data, tmp_path, fake_hub, monkeypatch):
    """If the xlsx wasn't written (writer failed), don't crash — record error."""
    monkeypatch.setattr(runner_mod, "_datahub_factory", lambda: fake_hub)
    nonexistent = tmp_path / "does_not_exist.xlsx"

    result = runner_mod._publish_to_hub(data=stub_data, output_path=nonexistent, period="2026-03")

    # Snapshot still uploads (the cache exists in memory)
    assert fake_hub.archive_snapshot.called
    # Xlsx upload skipped (file missing)
    assert not fake_hub.publish_report_versioned.called
    assert result["xlsx_sp_path"] is None


def test_cache_mode_does_not_upload_xlsx_unless_asked(monkeypatch, tmp_path):
    """2026-08-03 (Jiho, after a stray March workbook appeared in the SP
    Output folder during the Jen-comparison hold): a --from-cache build is a
    LOCAL verification artifact — publishing is a deliberate act. Cache-mode
    runs must NOT upload the xlsx to SharePoint unless MPR_PUBLISH=1. The
    per-run audit snapshot still writes (immutable history, lives in Data/,
    not user-visible Output). Live SLX runs are unchanged."""
    from reports.membership_performance_tracker import runner

    out = tmp_path / "report.xlsx"
    out.write_bytes(b"x")

    class Hub:
        def __init__(self):
            self.published = []
            self._sp = object()
        def archive_snapshot(self, *a, **k):
            return "snap"
        def publish_report_versioned(self, **k):
            self.published.append(k["filename"])
            return "sp/path"

    hub = Hub()
    monkeypatch.setattr(runner, "_datahub_factory", lambda: hub)

    monkeypatch.delenv("MPR_PUBLISH", raising=False)
    res = runner._publish_to_hub(object(), out, "2026-07", is_live_slx=False)
    assert hub.published == [], "cache-mode must not upload the xlsx"
    assert res["xlsx_sp_path"] is None

    monkeypatch.setenv("MPR_PUBLISH", "1")
    runner._publish_to_hub(object(), out, "2026-07", is_live_slx=False)
    assert hub.published == ["report.xlsx"], "MPR_PUBLISH=1 opts in"

    monkeypatch.delenv("MPR_PUBLISH", raising=False)
    runner._publish_to_hub(object(), out, "2026-07", is_live_slx=True)
    assert hub.published == ["report.xlsx", "report.xlsx"], "live runs unchanged"


def test_mpr_publish_zero_holds_even_live_runs(monkeypatch, tmp_path):
    """MPR_PUBLISH=0 = explicit hold: a live verification pull keeps its
    untested workbook off the SP Output folder (2026-08-04)."""
    from reports.membership_performance_tracker import runner
    out = tmp_path / "r.xlsx"
    out.write_bytes(b"x")
    class Hub:
        _sp = object()
        def __init__(self): self.published = []
        def archive_snapshot(self, *a, **k): return "snap"
        def publish_report_versioned(self, **k):
            self.published.append(1); return "p"
    hub = Hub()
    monkeypatch.setattr(runner, "_datahub_factory", lambda: hub)
    monkeypatch.setenv("MPR_PUBLISH", "0")
    runner._publish_to_hub(object(), out, "2026-07", is_live_slx=True)
    assert hub.published == [], "hold must keep even live runs off Output"
