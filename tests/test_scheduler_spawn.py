"""Spawn interpreter — the 8/6 02:00 casualty.

The scheduler launched pulls with bare "python3", which resolves through
PATH — and since the 8/4 gcloud install put Homebrew's dependency-less
python first, the August 6 scheduled pull died at import ("No module named
'yaml'") and left a zombie marked "running". Every spawn must use the
interpreter the spawning process itself runs on (sys.executable): if the
console imports its deps, its children can too — PATH never gets a vote.
"""
import sys


def test_scheduler_spawns_with_its_own_interpreter():
    from src import scheduler
    cmd = scheduler.build_runner_cmd()
    assert cmd[0] == sys.executable, \
        f"spawn must pin sys.executable, got {cmd[0]!r}"


def test_console_spawns_with_its_own_interpreter():
    text = open("console/app.py").read()
    assert '["python3"' not in text and '"python3",' not in text, \
        "console must not spawn bare python3 (PATH-dependent)"
