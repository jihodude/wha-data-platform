"""Child process for the console render smoke test (run via subprocess so the
full pytest suite's global state can never pollute the AppTest run).

argv[1] = "idle" | "running". Prints "OK" and exits 0 on a clean render;
prints the exception and exits 1 otherwise.
"""
import os
import sys

os.environ["WHA_OFFLINE"] = "1"   # no network in a render smoke test


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "idle"
    from streamlit.testing.v1 import AppTest

    if mode == "running":
        import src.scheduler as sched
        real = sched.load_schedule
        sched.load_schedule = lambda: {**real(), "current_pid": os.getpid()}

    at = AppTest.from_file("console/app.py", default_timeout=60)
    at.session_state["authenticated"] = True
    if mode.startswith("nav:"):
        at.session_state["nav"] = mode.split(":", 1)[1]
    at.run()
    if at.exception:
        for e in at.exception:
            print("EXC:", e.value)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
