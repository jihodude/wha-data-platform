"""Crystal export ingestion for the MPR — fetch, staleness, archive, arrival gate.

Independent of the dues report's own report layer by direction (Jiho
2026-07-27: "develop the two reports independently and merge them later once
both are validated"). Shared promotion into src/ happens after both validate.
"""
import hashlib
import json
from datetime import date

import pytest

from reports.membership_performance_tracker.logic import crystal


class FakeClient:
    """Minimal stand-in for SLXClient: serves attachment rows and file bytes."""

    def __init__(self, rows, files=None, base_url="https://slx/sdata/slx/dynamic/-/"):
        self.rows = rows
        self.files = files or {}
        self.base_url = base_url
        self.calls = []

    def _get(self, entity, params):
        self.calls.append((entity, params))
        return {"$resources": self.rows}

    def _get_bytes(self, path):
        key = path.split("('")[1].split("')")[0]
        return self.files[key]


def _row(key, name, size=1000, exists=True):
    return {"$key": key, "fileName": name, "fileSize": size, "fileExists": exists}


def test_parse_stamp_handles_both_interactive_and_scheduled_filenames():
    """SLX stamps scheduled exports WITHOUT the separator after the year.

    Matching only the interactive form would silently ignore every scheduled
    run — the pipeline would serve last month's file forever without erroring.
    """
    interactive = crystal.parse_export_stamp("NewMemberSalesReport_JihoB_2026_07_26_0921.xls")
    scheduled = crystal.parse_export_stamp("NewMemberSalesReport_JihoB_202608_01_0930.xls")

    assert interactive == (date(2026, 7, 26), "JihoB", "xls", "NewMemberSalesReport")
    assert scheduled == (date(2026, 8, 1), "JihoB", "xls", "NewMemberSalesReport")


def test_latest_export_prefers_parsable_and_honors_since():
    """A PDF of the same report is useless to the parsers even when newer, and
    an export older than the period must never masquerade as this month's run."""
    rows = [
        _row("k_pdf", "DroppedMembersByType_KyleG_2026_08_02_0500.pdf"),
        _row("k_new", "DroppedMembersByType_JihoB_202608_01_0930.xls"),
        _row("k_old", "DroppedMembersByType_JihoB_2026_07_26_0922.xls"),
    ]
    client = FakeClient(rows)

    newest = crystal.latest_export(client, "DroppedMembersByType")
    in_period = crystal.latest_export(client, "DroppedMembersByType", since=date(2026, 8, 1))
    stale = crystal.latest_export(client, "DroppedMembersByType", since=date(2026, 9, 1))

    assert newest.file_name.endswith("202608_01_0930.xls")
    assert in_period.run_date == date(2026, 8, 1)
    assert stale is None


def test_download_refuses_a_truncated_export():
    """A short read parses to FEWER rows — i.e. it silently undercounts."""
    rows = [_row("k1", "BillablesByTerritorySummaryByBm_JihoB_202608_01_0930.xls", size=5000)]
    client = FakeClient(rows, files={"k1": b"partial"})

    export = crystal.latest_export(client, "BillablesByTerritorySummaryByBm")
    with pytest.raises(ValueError, match="truncated"):
        crystal.download_export(client, export)


def test_archive_writes_bytes_and_records_provenance(tmp_path):
    """The archived file IS the provenance: the report the org would have opened."""
    payload = b"\xd0\xcf\x11\xe0 fake workbook bytes"
    export = crystal.ReportExport(
        key="k1", file_name="NewMemberSalesReport_JihoB_202608_01_0930.xls",
        run_date=date(2026, 8, 1), user="JihoB", ext="xls", size=len(payload),
    )

    path = crystal.archive_export("2026-08", "new_member_sales", export, payload, root=tmp_path)

    assert path.read_bytes() == payload
    manifest = json.loads((tmp_path / "2026-08" / "manifest.json").read_text())
    entry = manifest["new_member_sales"]
    assert entry["file_name"] == export.file_name
    assert entry["run_date"] == "2026-08-01"
    assert entry["sha256"] == hashlib.sha256(payload).hexdigest()
    assert entry["size"] == len(payload)


def test_fetch_period_blocks_and_names_every_missing_report(tmp_path):
    """Arrival gate: a silently-dead schedule must fail the run, not degrade it.

    Only two of the required reports have in-period runs here; the raised
    error must name the rest so the fix is 'check these schedules'.
    """
    rows = [
        _row("k1", "NewMemberSalesReport_JihoB_202608_01_0930.xls"),
        _row("k2", "DroppedMembersByType_JihoB_202608_01_0930.xls"),
    ]
    files = {"k1": b"x" * 1000, "k2": b"y" * 1000}
    client = FakeClient(rows, files=files)

    with pytest.raises(crystal.MissingExports) as err:
        crystal.fetch_period(client, "2026-08", root=tmp_path)

    missing = err.value.missing
    assert "retention" in missing and "billables" in missing
    assert "new_member_sales" not in missing


def test_fetch_period_archives_every_required_report(tmp_path):
    """Happy path: each report lands once, keyed by its cache-facing name."""
    rows, files = [], {}
    for i, (key, (_name, prefix)) in enumerate(crystal.REPORTS.items()):
        k = f"k{i}"
        rows.append(_row(k, f"{prefix}_JihoB_202608_01_0930.xls", size=100))
        files[k] = b"z" * 100
    client = FakeClient(rows, files=files)

    got = crystal.fetch_period(client, "2026-08", root=tmp_path)

    assert set(got) == set(crystal.REPORTS)
    manifest = json.loads((tmp_path / "2026-08" / "manifest.json").read_text())
    assert set(manifest) == set(crystal.REPORTS)


def test_stale_export_is_flagged_distinctly_from_a_missing_one(tmp_path):
    """"Use last night's run; if it isn't there, flag it for the employee."

    A schedule that ran once and then stopped firing leaves an export in the
    archive forever. Serving it would be silent staleness, so it must fail —
    and the message must say the run is OLD (schedule stopped) rather than
    ABSENT (schedule never created), because those are different fixes.
    """
    rows = [_row("k1", "NewMemberSalesReport_JihoB_2026_07_26_0921.xls")]
    client = FakeClient(rows, files={"k1": b"x" * 1000})

    with pytest.raises(crystal.MissingExports) as err:
        crystal.fetch_period(client, "2026-08", root=tmp_path,
                             required=["new_member_sales"],
                             min_run_date=date(2026, 8, 1))

    reason = err.value.missing["new_member_sales"]
    assert "2026-07-26" in reason, "must name the last run it DID find"
    assert "stale" in reason.lower()


def test_closed_business_rows_are_not_emitted():
    """Dropped 2026-07-27 (Jiho): the legacy MPR reported drops, never closures.

    Jennifer's own editions carry no closed-business number — March 2026 has a
    bare "Closed/Sold" label with no data and June drops the label entirely.
    The closure population is also 73% chain locations (Starbucks stores et al)
    whose dues live on a parent record, so they were never member losses. Under
    the Crystal pivot the report shows what the org's reports show: drops only.
    """
    from reports.membership_performance_tracker.mapper import METRIC_FIELD_MAP, TrackerV4Mapper
    from reports.membership_performance_tracker.logic.model import ScoreboardData

    assert not [m for m in METRIC_FIELD_MAP if "Closed" in m]

    data = ScoreboardData()
    data.revenue = {"EastKing": {"Oct": 100}}
    data.closed_target = {"EastKing": {"Oct": 5}}
    data.closed_non_target = {"EastKing": {"Oct": 3}}

    rows = TrackerV4Mapper(fiscal_year_start=2025, current_month="Oct").map(data)

    assert not [r for r in rows if "Closed" in r["metric"]]


def test_prefix_never_matches_a_longer_report_name():
    """Suzanne runs BM-scoped exports beside the full report.

    The archive holds DroppedMembersHospitalityBM8_suzannes_… next to
    DroppedMembersHospitality_…. A startswith() match would happily hand a
    single-bill-month export to the parser expecting the whole report —
    a plausible-looking file, a badly wrong number, no error anywhere.
    """
    rows = [
        _row("k_bm", "DroppedMembersHospitalityBM8_suzannes_202608_02_0400.xls"),
        _row("k_full", "DroppedMembersHospitality_suzannes_202608_01_0930.xls"),
    ]
    client = FakeClient(rows)

    got = crystal.list_exports(client, "DroppedMembersHospitality")

    assert [e.file_name for e in got] == ["DroppedMembersHospitality_suzannes_202608_01_0930.xls"]


class FakeSchedulingClient:
    """Serves trigger records shaped like the live scheduling service."""

    def __init__(self, windows):
        self.windows = windows
        self.base_url = "https://slx/sdata/slx/dynamic/-/"

    def _get(self, path, params=""):
        if path == "triggers":
            return {"$resources": [{"$key": n} for n in self.windows]}
        key = path.split("('")[1].split("')")[0]
        start, end = self.windows[key]
        return {"parameters": [
            {"name": "ScheduleName", "value": key},
            {"name": "ReportParameters",
             "value": '[{"currentValues":[{"rangeDateValue":"'
                      f'{start}T07:00:00Z;{end}T18:55:00Z"' + '}]}]'},
        ]}


def test_drops_window_is_read_from_the_live_schedule_not_from_memory():
    """A drops row cannot say its year, so the schedule's window IS the year.

    Moving that window every October used to rest on a human remembering. The
    CRM exposes the range it is actually scheduled with, so the program checks
    it instead.
    """
    names = ["Dropped Members - Hospitality", "Dropped Members By Type", "Dropped Allied Report"]
    good = FakeSchedulingClient({n: ("2025-10-01", "2030-12-31") for n in names})

    crystal.assert_drops_window_matches_fy(good, 2025)

    with pytest.raises(RuntimeError, match="window starts 2025-10-01, expected 2026-10-01"):
        crystal.assert_drops_window_matches_fy(good, 2026)


def test_a_missing_drops_schedule_is_reported_by_name():
    partial = FakeSchedulingClient({"Dropped Members - Hospitality": ("2025-10-01", "2030-12-31")})

    with pytest.raises(RuntimeError, match="Dropped Allied Report: no live schedule found"):
        crystal.assert_drops_window_matches_fy(partial, 2025)


# ---------------------------------------------------------------------------
# S3 hole 1, RULED 2026-08-11 (Jiho): the window guard becomes a FLAG, not a
# compile refusal.
#
# `assert_drops_window_matches_fy` was written, tested, and called by NOTHING —
# while the comment above it claimed the program "refuses to compile" a
# mis-windowed drops grid. Wiring the assert as written would hard-refuse every
# build from Oct 1 2026 (the live schedules start 2025-10-01, per the test
# above) on a date when nobody who built this is still here, and the remedy
# needs CRM access. So the annual obligation goes into the artifact where
# Suzanne can see it, not into a traceback nobody can clear.
# ---------------------------------------------------------------------------
_DROPS_SCHEDULES = ["Dropped Members - Hospitality", "Dropped Members By Type",
                    "Dropped Allied Report"]


def test_the_window_check_reports_problems_instead_of_refusing_to_build():
    good = FakeSchedulingClient({n: ("2025-10-01", "2030-12-31")
                                 for n in _DROPS_SCHEDULES})

    assert crystal.check_drops_window(good, 2025) == [], "matching FY is silent"

    problems = crystal.check_drops_window(good, 2026)
    assert len(problems) == 3, "every mis-windowed schedule is named"
    assert all("window starts 2025-10-01, expected 2026-10-01" in p
               for p in problems)


def test_the_window_check_names_a_missing_schedule_too():
    partial = FakeSchedulingClient(
        {"Dropped Members - Hospitality": ("2025-10-01", "2030-12-31")})
    problems = crystal.check_drops_window(partial, 2025)
    assert any("Dropped Allied Report: no live schedule found" in p
               for p in problems)


def test_the_window_check_reports_its_own_failure_rather_than_killing_the_run():
    """It runs inside the nightly's live pull. A check that can abort the build
    is exactly what was ruled against — but silence is not the alternative."""
    class Unreachable:
        base_url = "https://slx/sdata/slx/dynamic/-/"

        def _get(self, *a, **k):
            raise RuntimeError("scheduling service unavailable")

    problems = crystal.check_drops_window(Unreachable(), 2026)
    assert len(problems) == 1 and "could not be read" in problems[0]


def test_the_window_flag_has_a_section_so_its_rows_render():
    """An unregistered key renders without title, severity or description."""
    from reports.membership_performance_tracker.logic.receipts_sheet import (
        FLAG_SECTIONS)
    assert crystal.DROPS_WINDOW_FLAG in FLAG_SECTIONS
    title, sev, desc = FLAG_SECTIONS[crystal.DROPS_WINDOW_FLAG]
    assert title and desc and sev in ("red", "amber", "gray")
