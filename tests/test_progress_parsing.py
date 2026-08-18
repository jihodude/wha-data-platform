"""Progress parsing for the console's live pull bar (2026-07-22).

Shipped untested once and crashed the Control Panel on a missing import —
these tests pin the real runner log formats so the render path can't rot.
"""
from src.scheduler import latest_progress


def test_reads_newest_progress_line(tmp_path):
    log = tmp_path / "run.log"
    log.write_text(
        "===== run started 2026-07-22 (mode=live) =====\n"
        "  [  2%] Connecting to SLX...\n"
        "  [ 12%] Pulling current billable counts for 12 territories...\n"
        "  [ 48%] Pulling new member enrollments across 9 months...\n"
    )
    pct, msg = latest_progress(log)
    assert pct == 48
    assert msg == "Pulling new member enrollments across 9 months..."


def test_handles_three_digit_and_trailing_noise(tmp_path):
    log = tmp_path / "run.log"
    log.write_text("  [100%] Done\n  ✓ Report ready: file.xlsx  (697 KB)\n")
    pct, msg = latest_progress(log)
    assert pct == 100 and msg == "Done"


def test_no_progress_line_yet(tmp_path):
    log = tmp_path / "run.log"
    log.write_text("===== run started =====\n")
    assert latest_progress(log) == (0, "Starting…")


def test_missing_log_returns_none(tmp_path):
    assert latest_progress(tmp_path / "nope.log") == (None, None)
