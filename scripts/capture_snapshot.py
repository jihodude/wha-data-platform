"""
capture_snapshot.py — the month-end capture ritual as ONE portable command.
Layer-2 ("stays correct without heroics"). Works from anywhere (SLX is
internet-reachable, proven 2026-07-15); loud on every failure; never silent.

Usage:
  PYTHONPATH=$PWD python3 scripts/capture_snapshot.py                # current month
  PYTHONPATH=$PWD python3 scripts/capture_snapshot.py 2026-07        # explicit
  PYTHONPATH=$PWD python3 scripts/capture_snapshot.py --check-monthend
      # for cron/launchd: exits 3 + screams if the closing month has no
      # snapshot yet and month-end is within ALARM_DAYS — never pulls by itself.

Steps (normal mode):
  1. Refuse if another runner is already going (one-SLX-session rule).
  2. Reachability probe: HTTPS to the SData endpoint must answer 401.
  3. Run the pull (streams runner output; the [drops] progress lines show life).
  4. Run the gate battery with GATE_PERIOD=<period>.
  5. One-line PASS/FAIL verdict; nonzero exit on any failure.
NOTE: gates compare against data/truth/*.csv — refresh those exports for the
period being gated (see docs/handoff/2026-07-31-parallel-month-checklist.md).
"""
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SDATA_URL = "https://crm.wrahome.com/sdata/slx/dynamic/-/"
ALARM_DAYS = 3  # scream this many days before a month closes uncaptured


def default_period(today: date) -> str:
    return f"{today.year:04d}-{today.month:02d}"


def monthend_alarm(today: date, cache_dir: Path, alarm_days: int = ALARM_DAYS):
    """Return (should_scream, period, days_left). Screams when the CURRENT
    month ends within alarm_days and data/cache holds no snapshot for it."""
    nxt = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    days_left = (nxt - today).days
    period = default_period(today)
    captured = (cache_dir / f"scoreboard_{period}.json").exists()
    return (days_left <= alarm_days and not captured), period, days_left


def runner_alive() -> bool:
    r = subprocess.run(["pgrep", "-f", "membership_performance_tracker/runner"],
                       capture_output=True)
    return r.returncode == 0


def reachable() -> bool:
    r = subprocess.run(
        ["curl", "-sk", "--connect-timeout", "8", "-o", "/dev/null",
         "-w", "%{http_code}", SDATA_URL], capture_output=True, text=True)
    return r.stdout.strip() == "401"


def main() -> int:
    args = sys.argv[1:]
    today = date.today()

    if "--check-monthend" in args:
        scream, period, days_left = monthend_alarm(today, ROOT / "data" / "cache")
        if scream:
            print(f"🚨 [capture] MONTH {period} CLOSES IN {days_left} DAY(S) AND HAS "
                  f"NO SNAPSHOT. Penetration/paid-revenue are point-in-time — run "
                  f"scripts/capture_snapshot.py {period} TODAY.", flush=True)
            return 3
        print(f"[capture] month-end check ok ({period}, {days_left}d left)")
        return 0

    period = next((a for a in args if not a.startswith("-")), default_period(today))

    if runner_alive():
        print("🚨 [capture] another pull is already running (one SLX session rule). "
              "Refusing.", flush=True)
        return 2
    if not reachable():
        print(f"🚨 [capture] SLX unreachable ({SDATA_URL} did not answer 401). "
              f"Check network / the CRM migration. NOT captured.", flush=True)
        return 2

    env = {**os.environ, "MPR_PERIOD": period, "PYTHONPATH": str(ROOT)}
    print(f"[capture] pulling {period} (60-150 min; [drops] lines = heartbeat)")
    pull = subprocess.run(
        [sys.executable, "-u",
         str(ROOT / "reports/membership_performance_tracker/runner.py")],
        cwd=ROOT, env=env)
    if pull.returncode != 0:
        print(f"🚨 [capture] PULL FAILED (exit {pull.returncode}) — no snapshot "
              f"for {period}.", flush=True)
        return 1

    print(f"[capture] gating {period}")
    gates = subprocess.run(
        ["bash", str(ROOT / "scripts/run_gates.sh")],
        cwd=ROOT, env={**env, "GATE_PERIOD": period})
    verdict = "PASS" if gates.returncode == 0 else "GATES ERRORED — read output above"
    print(f"[capture] {period} captured. Gate run: {verdict}", flush=True)
    return 0 if gates.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
