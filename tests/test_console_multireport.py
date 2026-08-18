"""
The console is a MULTI-REPORT platform; six places still assumed one report
(Jiho's list, 2026-07-27). These pin the ones that are logic rather than CSS.

1. Viewing month offered only months with an MPR cache — "March, June, July".
2. A Dues run showed up in Recent Activity as "Membership Performance Report".
"""
from pathlib import Path

from src.config.period import list_available_periods
from src.scheduler import parse_recent_runs, write_run_started_banner

MPR = "Membership Performance Report"
DUES = "Dues Analysis"


# ── 1. the month picker spans every report, not just the MPR's cache ────

def _console_periods(cache_dir, dues_months):
    """Mirror of console.app._console_periods (app.py imports streamlit at
    module scope, so the union rule is pinned on its two inputs)."""
    return sorted(set(list_available_periods(cache_dir)) | set(dues_months),
                  reverse=True)


def test_month_picker_includes_months_only_dues_can_serve(tmp_path):
    # The MPR happens to have three cache files; the dues FY has nine months.
    for n in ("scoreboard_2026-07.json", "scoreboard_2026-06.json",
              "scoreboard_2026-03.json"):
        (tmp_path / n).write_text("{}")
    dues = [f"2025-{m:02d}" for m in (10, 11, 12)] + \
           [f"2026-{m:02d}" for m in range(1, 7)]
    got = _console_periods(tmp_path, dues)
    assert got[0] == "2026-07"                 # MPR-only month still offered
    assert "2025-10" in got and "2026-01" in got   # dues-only months appear
    assert got == sorted(got, reverse=True)        # newest first


def test_a_month_both_reports_have_is_not_duplicated(tmp_path):
    (tmp_path / "scoreboard_2026-06.json").write_text("{}")
    assert _console_periods(tmp_path, ["2026-06"]) == ["2026-06"]


def test_picker_survives_a_report_that_cannot_list_its_months(tmp_path):
    (tmp_path / "scoreboard_2026-06.json").write_text("{}")
    assert _console_periods(tmp_path, []) == ["2026-06"]


# ── 2. Recent Activity names the report that actually ran ───────────────

def test_a_dues_run_is_labelled_dues(tmp_path):
    log = tmp_path / "run.log"
    write_run_started_banner(log, "report", "console", report=DUES)
    runs = parse_recent_runs(log.read_text(), default_report=MPR)
    assert len(runs) == 1
    assert runs[0]["report"] == DUES
    assert runs[0]["source"] == "console"


def test_older_entries_without_a_report_tag_stay_mpr(tmp_path):
    # The log predates multi-report; those runs WERE the MPR, so labelling
    # them so is a fact about history, not a default.
    log = tmp_path / "run.log"
    log.write_text("===== run started 2026-07-26T02:00:00 "
                   "(mode=live, source=scheduler) =====\n"
                   "  ✓ Report ready: x.xlsx\n")
    runs = parse_recent_runs(log.read_text(), default_report=MPR)
    assert runs[0]["report"] == MPR and runs[0]["status"] == "done"


def test_two_reports_in_one_click_produce_two_distinct_entries(tmp_path):
    log = tmp_path / "run.log"
    write_run_started_banner(log, "report", "console", report=DUES)
    log.write_text(log.read_text() + "===== run finished rc=0 =====\n")
    write_run_started_banner(log, "cache", "console", report=MPR)
    log.write_text(log.read_text() + "===== run finished rc=0 =====\n")
    runs = parse_recent_runs(log.read_text(), default_report=MPR)
    assert [r["report"] for r in runs] == [DUES, MPR]
    assert [r["status"] for r in runs] == ["done", "done"]
    assert [r["mode"] for r in runs] == ["report", "cache"]


def test_a_failed_dues_run_is_labelled_dues_and_errored(tmp_path):
    log = tmp_path / "run.log"
    write_run_started_banner(log, "report", "console", report=DUES)
    log.write_text(log.read_text() + "===== run finished rc=1 =====\n")
    runs = parse_recent_runs(log.read_text(), default_report=MPR)
    assert runs[0]["report"] == DUES and runs[0]["status"] == "error"


def test_report_name_with_spaces_is_not_truncated(tmp_path):
    log = tmp_path / "run.log"
    write_run_started_banner(log, "cache", "scheduler", report=MPR)
    runs = parse_recent_runs(log.read_text(), default_report="fallback")
    assert runs[0]["report"] == MPR


# ── the progress bar belongs to the MPR's pull, nobody else's ───────────

def test_pull_probe_matches_only_the_mpr_runner():
    """'runner.py' alone matches every report's runner, so running Dues made
    the console announce an 80-minute live SLX pull that was not happening
    (Jiho, 2026-07-28)."""
    import re
    src = (Path(__file__).resolve().parents[1] / "console" / "app.py").read_text()
    probe = re.search(r'pgrep",\s*"-f",\s*"([^"]+)"', src)
    assert probe, "process probe not found"
    pattern = probe.group(1)
    assert "membership_performance_tracker" in pattern, pattern
    # the pattern must NOT match another report's runner
    assert not re.search(pattern.replace("/", r"/"),
                         "reports/dues_analysis/runner.py")
