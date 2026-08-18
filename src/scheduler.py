"""
scheduler.py — In-console scheduler for the nightly SLX refresh (F1).

Design (deliberately simple, no APScheduler):

  • Schedule state lives in `data/schedule.json` (enabled, time, last/next run).
  • A daemon thread in the Streamlit app process polls every 60s. When the
    scheduled time arrives and `enabled=True`, it spawns the tracker runner
    in detached mode (Popen with stdout to a log file), updates the schedule
    file, and goes back to sleep.
  • The console displays + edits the schedule by reading/writing the JSON.

Why a thread (not APScheduler):
  Streamlit reruns the script on every interaction — APScheduler with state
  in memory gets confused. A plain JSON file + a single daemon thread (guarded
  by `start_scheduler()`'s idempotent flag) survives reruns cleanly.

Deployment caveat:
  The scheduler thread runs inside the Streamlit process. On Railway hobby/
  free tiers the container sleeps when idle, so the scheduler effectively
  stops until traffic wakes the app. For reliable nightly runs in production,
  either (a) keep the container always-on (pro tier or pinger) or (b) replace
  this with Railway's cron jobs feature pointing at the runner.
"""

import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEDULE_FILE = PROJECT_ROOT / "data" / "schedule.json"
LOG_FILE      = PROJECT_ROOT / "data" / "output" / "scheduled_run.log"
RUNNER_PATH   = PROJECT_ROOT / "reports" / "membership_performance_tracker" / "runner.py"


def build_runner_cmd() -> list:
    """The runner spawn command — ALWAYS the interpreter this process runs
    on, never bare "python3" (8/6 02:00 casualty: the brew-gcloud PATH shim
    resolved first, its python has no deps, the August pull died at import
    and left a zombie marked running). If this process imports its
    dependencies, its children can too — PATH never gets a vote."""
    import sys
    return [sys.executable, str(RUNNER_PATH)]
# The single SLX-session lock (shared with the runner's acquire_pull_lock).
LOCK_PATH     = PROJECT_ROOT / "data" / "cache" / ".runner.pid"
# A run whose log has not advanced in this long is treated as hung (2026-07-24:
# a scheduled pull stalled >10h holding the lock; SLX requests time out at
# 60-90s, so 30m of TOTAL log silence unambiguously means hung, never slow).
STALE_SECONDS = 30 * 60

DEFAULT_STATE = {
    # Cloud Run's disk resets on restart, wiping schedule.json — with a
    # hard False default an instance recycle silently killed the nightly
    # (8/8 deploy verification). The cloud deploy sets
    # WHA_SCHEDULE_DEFAULT_ENABLED=1 so a MISSING file defaults to ON;
    # an existing schedule.json always wins (default, not override).
    "enabled":        os.environ.get("WHA_SCHEDULE_DEFAULT_ENABLED") == "1",
    "hour":           2,        # 2 AM by default
    "minute":         0,
    "last_run_ts":    None,
    "last_run_status": None,
    "next_run_ts":    None,
    "current_pid":    None,     # set while a scheduled run is in-flight
}


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------


# First period managed by the month-close system. Months before this are
# closed history (FY25-26 capture-and-freeze) — they never drag the nightly
# period backwards.
CLOSE_ANCHOR = "2026-07"


def period_for_run(now) -> str:
    """Which month a scheduled run reports on.

    CLOSE-AWARE since 2026-08-03 (designed with Jiho, confirmed against the
    leadership transcript — "whatever he's exporting from SLX excludes the
    next month… that would also affect accounting too, so they don't have
    to hold"): the nightly pull keeps targeting the CLOSING month until its
    close file exists, then advances. A month's ITD close happens INSIDE
    the next calendar month (July's ITD runs ~Aug 5-7), so the old rule
    (prior month on the 1st only) abandoned July on Aug 2 whether or not
    it ever closed.
    """
    from datetime import timedelta
    from reports.membership_performance_tracker.logic import month_close as _mc
    prev = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    if prev >= CLOSE_ANCHOR and not _mc.is_closed(prev):
        return prev
    return now.strftime("%Y-%m")


def _quarantine_corrupt_schedule() -> Optional[Path]:
    """
    Rename a corrupt schedule.json aside with a unix timestamp so the user has
    a forensic copy explaining what broke. Returns the quarantine path on
    success, None if the rename itself failed (logged-and-swallowed).
    """
    ts = int(time.time())
    quarantine_path = SCHEDULE_FILE.parent / f"schedule.json.corrupt.{ts}"
    try:
        os.replace(str(SCHEDULE_FILE), str(quarantine_path))
        return quarantine_path
    except Exception:
        logger.exception("failed to quarantine corrupt schedule.json")
        return None


def load_schedule() -> dict:
    """
    Return the schedule state dict (filled with defaults for any missing key).

    Corruption handling (Bug 1, 2026-06-05): if schedule.json fails to parse,
    we quarantine the bad file (schedule.json.corrupt.<ts>) and persist
    DEFAULT_STATE to the canonical path. This makes the next read clean AND
    keeps a forensic artifact so we can debug what truncated the file —
    without that, a single SIGKILL or disk-full mid-write would silently
    disable the nightly schedule with zero user signal.
    """
    if not SCHEDULE_FILE.exists():
        return dict(DEFAULT_STATE)
    try:
        state = json.loads(SCHEDULE_FILE.read_text())
        for k, v in DEFAULT_STATE.items():
            state.setdefault(k, v)
        return state
    except json.JSONDecodeError:
        logger.warning(
            "schedule.json is corrupt — quarantining and resetting to defaults"
        )
        _quarantine_corrupt_schedule()
        defaults = dict(DEFAULT_STATE)
        try:
            save_schedule(defaults)
        except Exception:
            logger.exception("could not write defaults after quarantine")
        return defaults
    except Exception:
        # Unexpected read error (permissions, encoding) — return defaults but
        # do NOT quarantine. The file might be recoverable; humans can inspect.
        logger.exception("unexpected error reading schedule.json")
        return dict(DEFAULT_STATE)


def save_schedule(state: dict) -> None:
    """
    Atomic write: serialize to a same-directory tempfile, fsync, then
    os.replace() onto the canonical path. POSIX guarantees os.replace() is
    atomic within a single filesystem, so a reader either sees the previous
    contents or the new contents — never a torn intermediate.

    This is the substrate for the Bug 1 / 3 schedule.json reliability story:
    runner._update_schedule_status, the UI Save button, and the scheduler
    polling thread all funnel through save_schedule; making it atomic protects
    every writer at once.
    """
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2)

    # mkstemp gives us an FD, not just a path, so no race between create and write
    fd, tmp_path = tempfile.mkstemp(
        prefix=".schedule.",
        suffix=".tmp",
        dir=str(SCHEDULE_FILE.parent),
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(SCHEDULE_FILE))
    except Exception:
        # If anything failed before the replace landed, scrub the temp file.
        # Suppress the unlink error so we don't mask the original exception.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Schedule math
# ---------------------------------------------------------------------------

# The nightly's designed slot. 2 AM is not arbitrary and not cosmetic:
#   * the month close needs a clean BEFORE-ITD photo from each night, and
#   * the day's Crystal export must already have landed.
# A later run time breaks both, and breaks them QUIETLY — which is why the
# console used to force the time back to 2:00 on every save.
SAFE_HOUR, SAFE_MINUTE = 2, 0


def schedule_time_warning(hour: int, minute: int) -> Optional[str]:
    """What moving the nightly off 2:00 AM costs. None when it is on 2:00.

    Restored as a WARNING rather than a lock (Jiho 2026-08-12): WHA needs the
    time adjustable for GL/Sage posting timing, and we needed it that day to
    prove the scheduler self-fires. The earlier fix for the same problem was to
    hardcode the hour in the console's save handler, which meant the stored
    value could never differ — and the page still claimed "2:00 AM" even when
    it did. Warn, never refuse, and never change silently.

    Pure by design: `scheduler.py:325` established that render-path decisions
    live here, not in the console, so the test suite can exercise them.
    """
    if (hour, minute) == (SAFE_HOUR, SAFE_MINUTE):
        return None
    return (f"{hour:02d}:{minute:02d} is outside the designed 02:00 slot. "
            f"The month close relies on a clean before-ITD photo from each "
            f"night, and the day's Crystal export must already have landed — "
            f"a later time can break both, and it breaks them silently. "
            f"Move it only for a deliberate reason (GL/Sage timing, or a "
            f"scheduler test), and put it back to 02:00 afterwards.")


def compute_next_run(hour: int, minute: int, after: Optional[datetime] = None) -> datetime:
    """Next occurrence of HH:MM strictly after `after` (or now)."""
    after = after or datetime.now()
    candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= after:
        candidate += timedelta(days=1)
    return candidate


def refresh_next_run() -> dict:
    """Recompute and persist next_run_ts based on current enabled + time."""
    state = load_schedule()
    if state.get("enabled"):
        state["next_run_ts"] = compute_next_run(state["hour"], state["minute"]).isoformat()
    else:
        state["next_run_ts"] = None
    save_schedule(state)
    return state


# ---------------------------------------------------------------------------
# Manual / scheduled trigger
# ---------------------------------------------------------------------------

def write_run_started_banner(log_file: Path, mode: str, source: str,
                             report: str = "") -> None:
    """
    Append the canonical `run started` banner to `log_file`.

    Format: `===== run started <ISO ts> (mode=<mode>, source=<source>) =====`

    `report` (optional, 2026-07-27) names which report ran. The log predates
    the platform being multi-report, so entries without it are assumed to be
    the MPR — which is what they were. Dues runs pass it, so Recent Activity
    stops labelling every run "Membership Performance Report".

    `source` is the discriminator that lets the recent-runs parser tell
    console-initiated runs (run_pipeline_sync, source="console") from
    scheduler-initiated runs (trigger_refresh, source="scheduler") apart on
    disk. Without it, the two paths produced indistinguishable banners and a
    user-triggered cache refresh left no persistent audit trail.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    tag = f", report={report}" if report else ""
    banner = (f"\n\n===== run started {datetime.now().isoformat()} "
              f"(mode={mode}, source={source}{tag}) =====\n")
    with open(log_file, "ab") as fh:
        fh.write(banner.encode())


def parse_recent_runs(text: str, default_report: str) -> list:
    """Run summaries (newest LAST) parsed from a run log's banners.

    Lives beside the writer above so the format has exactly one definition.
    `default_report` labels pre-2026-07-27 entries, which carry no `report=`
    because the MPR was the only thing that wrote here.
    """
    runs, cur = [], None
    for line in text.splitlines():
        if line.startswith("===== run started"):
            if cur:
                runs.append(cur)
            ts = line.replace("===== run started", "").strip(" =")
            # Read the mode generically: the MPR writes live|cache, dues
            # writes "report" (its source of record is the CRM export). A
            # fixed live/cache test rendered every dues run as "?".
            mm = re.search(r"mode=([^,)=\s]+)", line)
            mode = mm.group(1) if mm else "?"
            # `source=` is post-2026-06-05; older entries default to scheduler
            # since that path was the only writer historically.
            source = ("console" if "source=console" in line
                      else "scheduler" if "source=scheduler" in line
                      else "scheduler")
            m = re.search(r"report=([^,)=]+)", line)
            cur = {"timestamp": ts.split(" (")[0].strip(),
                   "mode": mode,
                   "source": source,
                   "report": m.group(1).strip() if m else default_report,
                   "status": "running"}
        elif line.startswith("===== run finished") and cur:
            # rc=0 → done, anything else → error. Catches Streamlit-console
            # runs where there's no "✓ Report ready" marker on failure.
            cur["status"] = "done" if "rc=0" in line else "error"
        elif "✓ Report ready" in line:
            if cur:
                cur["status"] = "done"
        elif "ERROR" in line and cur:
            cur["status"] = "error"
    if cur:
        runs.append(cur)
    return runs


def write_run_finished_banner(log_file: Path, rc: int, stdout: str = "") -> None:
    """
    Append a `run finished` banner to `log_file`, optionally preceded by the
    full captured stdout from the subprocess.

    Used by run_pipeline_sync (which calls subprocess.run with stdout=PIPE);
    trigger_refresh streams stdout directly through Popen, so it does NOT
    write a finished banner — the runner's own output marks completion.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "ab") as fh:
        if stdout:
            payload = stdout if stdout.endswith("\n") else stdout + "\n"
            fh.write(payload.encode())
        banner = f"===== run finished {datetime.now().isoformat()} (rc={rc}) =====\n"
        fh.write(banner.encode())


def should_fire(now: datetime, next_run: datetime, grace_minutes: int = 10) -> bool:
    """Fire only within the grace window AFTER the scheduled time.

    2026-07-20 incident: the console's scheduler thread starts when the console
    is OPENED; a missed 2:00 slot then fired at 6:42 the moment Jiho opened
    localhost. A missed slot must be SKIPPED (rolled to the next one), never
    caught up — opening a dashboard can never be what launches an 80-minute pull.

    Kept for the display path and for `due_now`, which now owns the decision.
    """
    late = (now - next_run).total_seconds()
    return 0 <= late <= grace_minutes * 60


# How long after the scheduled time a missed pull may still start. Four hours
# keeps every catch-up before business hours (a 02:00 slot can run until 06:00),
# which was the other half of the 2026-07-20 concern.
CATCH_UP_HOURS = 4


def ran_today(state: dict, now: datetime, cache_dir=None) -> bool:
    """Has a live pull already completed today?

    Two sources, because the first one is erasable. `last_run_ts` lives in
    schedule.json on Cloud Run's ephemeral disk. The scoreboard cache's
    `pulled_at` is stamped by every live pull AND restored from SharePoint by
    boot hydration, so it survives the disk being wiped — which is exactly the
    case this whole function exists for.
    """
    last = state.get("last_run_ts")
    if last:
        try:
            if datetime.fromisoformat(last).date() == now.date():
                return True
        except (ValueError, TypeError):
            pass
    cache_dir = Path(cache_dir) if cache_dir else PROJECT_ROOT / "data" / "cache"
    try:
        for p in cache_dir.glob("scoreboard_*.json"):
            m = re.search(r'"pulled_at":\s*"([^"]+)"', p.open().read(400))
            if not m:
                continue
            when = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
            if when.tzinfo is not None:
                when = when.astimezone().replace(tzinfo=None)
            if when.date() == now.date():
                return True
    except (OSError, ValueError):
        pass
    return False


def due_now(now: datetime, state: dict, already_ran: bool,
            grace_minutes: int = 10,
            catch_up_hours: int = CATCH_UP_HOURS):
    """(should_start, why) — the nightly decision, as a pure function.

    THE 2026-08-15 MISS. The old rule asked "is the clock within 10 minutes of
    `next_run_ts`?" That fails for a reason no amount of care prevents: Cloud
    Run replaces containers whenever it likes (`--min-instances 1` guarantees
    *an* instance, not the *same* one), the replacement wipes schedule.json,
    and `compute_next_run` then quietly points at TOMORROW. A ten-minute target
    plus an erasable memory of it lost the night of 2026-08-15 with nothing
    reported anywhere.

    So the question changed from "is it 02:00 right now?" to "has today's pull
    happened, and are we still inside the safe window?" That is idempotent: a
    container born at 03:06 with an empty disk asks it, finds no pull today,
    and runs. Losing the state stops mattering, because the state is no longer
    what is being asked.

    The 2026-07-20 ruling still holds. It was that OPENING A DASHBOARD must
    never launch a three-hour pull — and the daemon is process-level now
    (`console/scheduler_boot.py`), so no browser can trigger anything. The
    window is bounded so a catch-up still lands before business hours, never
    mid-morning against a CRM people are editing.
    """
    if not state.get("enabled"):
        return False, "disabled"
    try:
        slot = now.replace(hour=int(state.get("hour", 2)),
                           minute=int(state.get("minute", 0)),
                           second=0, microsecond=0)
    except (TypeError, ValueError):
        return False, "unreadable schedule time"
    if now < slot:
        return False, "before today's slot"
    if now >= slot + timedelta(hours=catch_up_hours):
        return False, f"past today's {catch_up_hours}h window"
    if already_ran:
        return False, "already ran today"
    return True, ("on time" if should_fire(now, slot, grace_minutes)
                  else f"catch-up ({int((now - slot).total_seconds() // 60)}m late)")



# Progress parsing (2026-07-22) — lives HERE, not in the console, so it is a
# pure function the test suite can exercise. The console's progress bar was
# shipped untested and crashed the page on a missing import; the lesson is
# that render-path code must be testable.
_PROGRESS_RE = re.compile(r"\[\s*(\d+)%\]\s*(.*)")


def _current_run_start_index(lines) -> int:
    """Index just AFTER the last 'run started' banner (0 if none). Progress must
    be read only within the current run — the log is append-mode, so scanning
    across boundaries surfaces a PRIOR run's 100% while this run hangs
    (2026-07-24 incident)."""
    for i in range(len(lines) - 1, -1, -1):
        if "run started" in lines[i]:
            return i + 1
    return 0


def latest_progress(log_path: Path, tail: int = 200):
    """Newest '[ NN%] message' from the CURRENT run → (percent, message).

    Returns (0, "Starting…") when the current run has no progress line yet, and
    (None, None) when the log does not exist.
    """
    try:
        lines = Path(log_path).read_text(errors="ignore").splitlines()
    except (OSError, FileNotFoundError):
        return None, None
    for line in reversed(lines[_current_run_start_index(lines):]):
        m = _PROGRESS_RE.search(line)
        if m:
            return int(m.group(1)), m.group(2).strip()
    return 0, "Starting…"


def log_heartbeat_age(log_path=None):
    """Seconds since the run log was last written (a run's heartbeat), or None
    if the log is missing."""
    p = Path(log_path) if log_path is not None else LOG_FILE
    try:
        return time.time() - p.stat().st_mtime
    except (OSError, FileNotFoundError):
        return None


def run_is_stale(log_path=None, stale_seconds=None) -> bool:
    """True when the run log has not advanced in > STALE_SECONDS — i.e. the pull
    is hung, not merely slow (SLX requests time out at 60-90s)."""
    age = log_heartbeat_age(log_path)
    thresh = STALE_SECONDS if stale_seconds is None else stale_seconds
    return age is not None and age > thresh


def force_clear_run(kill: bool = False) -> dict:
    """Manually unblock a stalled/ghost run (EXPLICIT user action only — never
    called automatically). Clears current_pid, releases the SLX lock, and marks
    the status. With kill=True, SIGTERMs the pid first (the console 'force clear'
    button passes this) — the ONE sanctioned place a pull may be killed."""
    import signal
    state = load_schedule()
    pid = state.get("current_pid")
    if kill and pid and is_pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
    state["current_pid"] = None
    state["last_run_status"] = f"cleared manually (was pid {pid})"
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass
    save_schedule(state)
    return state


def live_pull_in_progress() -> bool:
    """True when a live pull already owns the single SLX-session lock.

    Reads the same lock file the runner writes (`acquire_pull_lock`), so this
    answers the same question the runner will — before we tell anyone their
    pull started. A dead pid means a crashed run: the lock is stale, the
    runner clears it on the next acquire, and this reports not-running.
    """
    try:
        pid = int(LOCK_PATH.read_text().strip())
    except (OSError, ValueError):
        return False
    return is_pid_alive(pid)


def trigger_refresh(mode: str = "live", period: str = None) -> int:
    """
    Fire the tracker runner as a detached subprocess. Returns the PID so the
    caller can record it. Non-blocking — the runner takes ~3 hours for live.

    Returns 0 WITHOUT starting anything when a live pull is already running —
    the caller must tell the user their pull did not start.

    Output (stdout + stderr) is appended to data/output/scheduled_run.log so
    the console can show recent activity.
    """
    # DON'T ANNOUNCE A RUN THAT WON'T HAPPEN (8/13). The runner takes the
    # single-SLX-session lock and a second live pull exits immediately — the
    # data was never at risk. But the banner was written BEFORE the spawn, so
    # the loser of a race saw "run started", saw it in the log, and waited
    # three hours for a pull that died on arrival. Two people clicking within
    # the same few seconds is all it takes; the UI can't refresh fast enough
    # to hide the button from both. Check the lock first and say so.
    if mode == "live" and live_pull_in_progress():
        return 0
    write_run_started_banner(LOG_FILE, mode, source="scheduler")
    cmd = build_runner_cmd()
    if mode == "cache":
        cmd.append("--from-cache")
    # Pin the CURRENT month explicitly (2026-07-20 incident: with no period in
    # the env the runner fell back to its default and pulled March). A nightly
    # refresh means "refresh the month we are in" — always.
    import os as _os
    env = _os.environ.copy()
    # explicit period wins (D2 finding 12: the post-close "after-ITD
    # capture" pull must target the month JUST CLOSED, not the current one
    # — with the default, the runner's auto-seal never fired from that flow)
    env["MPR_PERIOD"] = period or period_for_run(datetime.now())
    # Scheduled runs publish (Jiho 8/3) — the cache-mode SP guard is only for
    # bare CLI verification builds.
    env["MPR_PUBLISH"] = "1"
    # Append mode so successive runs don't clobber each other's logs
    log_handle = open(LOG_FILE, "ab")
    proc = subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    # Persist the pid (2026-07-22): the console's progress bar and the
    # schedule page both read current_pid from the schedule state — a
    # returned-but-unrecorded pid left them blind to console-triggered pulls.
    try:
        sched = load_schedule()
        sched["current_pid"] = proc.pid
        save_schedule(sched)
    except Exception:
        pass
    return proc.pid


def is_pid_alive(pid: Optional[int]) -> bool:
    """Cheap check whether a PID is still running. None → False."""
    if not pid:
        return False
    try:
        # Signal 0 is a no-op that raises if the process is gone
        import os
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# ---------------------------------------------------------------------------
# Background polling loop
# ---------------------------------------------------------------------------

_scheduler_started = False
_scheduler_lock = threading.Lock()


def _tick_stale_pid_cleanup() -> bool:
    """
    One pass of stale-PID detection: if schedule.json's current_pid points at
    a dead process, clear it and downgrade an obsolete 'running …' status to
    'finished'. Returns True if state was modified.

    Extracted from _scheduler_loop so callers (UI, tests) can invoke it on
    demand. None-safe on last_run_status — finding #4 (2026-06-05) showed the
    previous inline check did `None.startswith()` which silently raised
    AttributeError and was swallowed by the loop's bare except, leaving the
    dead PID in schedule.json forever.
    """
    # SAFETY INVARIANT (test_stale_pid_cleanup_preserves_running_pid): only a
    # DEAD pid is cleared automatically. A hung-but-alive run is NOT auto-cleared
    # — clearing a live run's pid/lock from a background thread would free the
    # SLX lock mid-pull (two sessions) or, keyed off a shared stale log, kill the
    # wrong process (2026-07-24: it SIGTERM'd the test runner). Hung runs are
    # SURFACED in the UI and cleared by an explicit user action (force_clear_run).
    state = load_schedule()
    pid = state.get("current_pid")
    if not pid:
        return False
    if is_pid_alive(pid):
        return False
    state["current_pid"] = None
    # `or ""` because the value may be None (DEFAULT_STATE), and None.startswith raises
    status = state.get("last_run_status") or ""
    if status.startswith("running"):
        state["last_run_status"] = "finished"
    # A dead run's lock is stale — safe to release so a fresh pull isn't blocked.
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass
    save_schedule(state)
    return True


def _tick_monthend_alarm(today=None, cache_dir=None):
    """Month-end capture alarm (C3, 7/16): penetration/paid-revenue are
    point-in-time — a month that closes uncaptured is unrecoverable. Reuses
    scripts/capture_snapshot.monthend_alarm; stamps the banner into
    schedule.json (consumed by the console) and the log. Returns the banner
    text, or None when all clear."""
    from datetime import date as _date
    from scripts.capture_snapshot import monthend_alarm
    from pathlib import Path as _Path
    today = today or _date.today()
    cache_dir = _Path(cache_dir) if cache_dir else _Path(__file__).resolve().parent.parent / "data" / "cache"
    scream, period, days_left = monthend_alarm(today, cache_dir)
    msg = (f"MONTH {period} CLOSES IN {days_left} DAY(S) AND HAS NO SNAPSHOT — "
           f"run the capture TODAY (point-in-time metrics are unrecoverable)."
           if scream else None)
    try:
        state = load_schedule()
        if state.get("monthend_alarm") != msg:
            state["monthend_alarm"] = msg
            save_schedule(state)
            if msg:
                logger.warning("month-end alarm: %s", msg)
    except Exception:
        logger.exception("monthend alarm tick failed")
    return msg


def _scheduler_loop():
    while True:
        try:
            _tick_stale_pid_cleanup()
            _tick_monthend_alarm()
            state = load_schedule()
            now = datetime.now()

            # SELF-HEAL (8/8 cloud sweep): a fresh instance with the env
            # default gets enabled=True but next_run_ts=None — and this
            # loop's guard then never fires. "Enabled" with no next run is
            # a lie; stamp one so an instance restart can never silently
            # skip the nightly.
            if state.get("enabled") and not state.get("next_run_ts"):
                state = refresh_next_run()

            # Fire on the DAILY question, not the instant one — see `due_now`.
            already_running = is_pid_alive(state.get("current_pid"))
            fire, why = due_now(now, state, ran_today(state, now))
            if fire and not already_running:
                pid = trigger_refresh("live")
                state["last_run_ts"]     = now.isoformat()
                state["last_run_status"] = f"running (pid {pid})"
                state["current_pid"]     = pid
                state["next_run_ts"]     = compute_next_run(
                    state["hour"], state["minute"], now).isoformat()
                save_schedule(state)
                # SAY WHAT IT DECIDED (2026-08-15). The daemon logged when it
                # started and never again, so when the 8/15 nightly failed to
                # run there was no way to tell whether it had ticked, skipped,
                # or died — the container was alive and the logs were silent.
                # One line per decision that matters costs nothing and makes
                # the next failure diagnosable instead of a guess.
                print(f"[scheduler-daemon] started the nightly pull ({why}), "
                      f"pid {pid}", flush=True)
            elif fire and already_running:
                print(f"[scheduler-daemon] due ({why}) but a pull is already "
                      f"running (pid {state.get('current_pid')}) — standing down",
                      flush=True)
            # Keep next_run_ts honest for the console's display even when
            # nothing fires; the decision above no longer depends on it.
            elif state.get("enabled") and state.get("next_run_ts"):
                if now >= datetime.fromisoformat(state["next_run_ts"]):
                    state["next_run_ts"] = compute_next_run(
                        state["hour"], state["minute"], now).isoformat()
                    save_schedule(state)
        except Exception:
            # Log rather than silently swallow — silent absorption was the
            # mechanism that hid finding #4 in production.
            logger.exception("scheduler tick failed")
        time.sleep(60)


def start_scheduler() -> None:
    """
    Start the background polling thread once. Safe to call repeatedly — subsequent
    calls are no-ops. Use this from app startup.

    No-op under pytest or WHA_OFFLINE (2026-07-22): a lingering daemon thread
    started at module import polluted the test process and made the console
    render smoke test time out. The scheduler is a production-runtime concern,
    not a test one — tests that import app_v4 must not spawn it.
    """
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("WHA_OFFLINE") == "1":
        return
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="wha-scheduler")
    t.start()
