"""Process-level nightly scheduler daemon (cloud entrypoint sidecar).

D2 finding 2 (2026-08-08): the in-session scheduler thread starts only
after a logged-in browser session — on Cloud Run a night-time instance
recycle left NO scheduler until a human logged in, and the 2 AM pull
silently never fired. This daemon runs from the container CMD, before
and independent of any session. It also hydrates close docs first so
period targeting is correct on a fresh disk (finding 11).

Sets WHA_SCHEDULER_DAEMON=1 so the console's in-session starter stays
off — one ticker per instance, never two.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["WHA_SCHEDULER_DAEMON"] = "1"
# The runner module derives its period from MPR_PERIOD at import — unset on
# the cloud, it fell back to a stale default and the boot hydration probed
# the wrong 14 months (8/10: close docs never hydrated, the close panel
# offered to re-close sealed July). Anchor hydration to the clock.
import datetime as _dt
os.environ.setdefault("MPR_PERIOD", _dt.date.today().strftime("%Y-%m"))


def main() -> None:
    try:
        from reports.membership_performance_tracker.runner import _hydrate_sp_inputs
        _hydrate_sp_inputs()
        print("[scheduler-daemon] SP inputs hydrated", flush=True)
    except Exception as exc:
        print(f"[scheduler-daemon] hydration failed (loop continues, runner "
              f"re-hydrates per run): {type(exc).__name__}: {exc}", flush=True)
    from src.scheduler import _scheduler_loop
    print("[scheduler-daemon] ticker started", flush=True)
    _scheduler_loop()


if __name__ == "__main__":
    main()
