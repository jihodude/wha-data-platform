"""Console render smoke tests (2026-07-22).

Why: the live-progress bar shipped WITHOUT a render-path test and crashed the
Control Panel with a NameError the moment a pull was running — the one state
nobody had exercised. These run the real app through Streamlit's AppTest in
both states and assert a clean render.

Run in a SUBPROCESS: app_v4 has module-level side effects (scheduler thread,
SharePoint, file I/O). Inside the shared pytest process those leave state that
deadlocks a second AppTest run (diagnosed 2026-07-22 — a true hang, not
slowness). A clean child interpreter is the only reliable isolation.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHILD = Path(__file__).parent / "_console_smoke_child.py"


def _render(mode: str):
    r = subprocess.run(
        [sys.executable, str(CHILD), mode],
        cwd=str(ROOT), env={**__import__("os").environ, "PYTHONPATH": str(ROOT)},
        capture_output=True, text=True, timeout=120,
    )
    return r


def test_console_renders_with_no_pull_running():
    r = _render("idle")
    assert r.returncode == 0 and "OK" in r.stdout, \
        f"console failed to render:\n{r.stdout}\n{r.stderr[-800:]}"


def test_console_renders_while_a_pull_is_running():
    r = _render("running")
    assert r.returncode == 0 and "OK" in r.stdout, \
        f"progress path failed to render:\n{r.stdout}\n{r.stderr[-800:]}"


def test_adjust_a_number_renders():
    """The third MPR view. Added 2026-08-14 with the page itself — the console
    router runs at module level, so a page defined after it raises NameError
    the first time somebody clicks the button, and only then."""
    _render("nav:mpr.adjust")
