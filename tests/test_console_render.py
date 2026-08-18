

# --- honest labels (Jiho, 8/13) -------------------------------------------

def test_live_pull_estimate_quotes_the_last_real_run():
    """The console said "~80 min" for months; a live pull measured 3h05m on
    8/13. The runner records each live run's real duration and the button
    quotes it, so the number can never rot again."""
    from console.app import live_pull_estimate
    assert live_pull_estimate(185) == "~3h05m"
    assert live_pull_estimate(45) == "~45 min"
    # no recording yet (fresh disk) → the measured default, never "80 min"
    assert live_pull_estimate(None) == "~3h05m"
    assert live_pull_estimate(0) == "~3h05m"


def test_admin_badge_reports_the_sharepoint_edit_not_our_copy():
    """The badge read the LOCAL file's mtime: "never" on a fresh container
    (the workbook was safe on SP), and unmoved when someone edited a goal.
    It now reports the SharePoint edit, and says so when that edit has not
    reached a report yet — the workbook is read at the START of a run."""
    from datetime import datetime, timezone, timedelta
    from console.app import format_admin_age
    now = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    edited = "2026-08-13T10:00:00Z"
    synced_before = (now - timedelta(hours=5)).timestamp()   # copy predates the edit
    synced_after = (now - timedelta(minutes=5)).timestamp()  # a run has since read it
    assert format_admin_age(edited, synced_before, now) == \
        "edited 2h ago · not in a report yet"
    assert format_admin_age(edited, synced_after, now) == "edited 2h ago"
    # unknown sync time (fresh container) → state the edit, claim nothing else
    assert format_admin_age(edited, None, now) == "edited 2h ago"
    # SharePoint unreachable → empty, so the caller falls back to local mtime
    assert format_admin_age(None, synced_before, now) == ""
