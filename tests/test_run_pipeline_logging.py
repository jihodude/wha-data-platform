"""
test_run_pipeline_logging.py — close the QA observability gap (task_f770f709).

Before this contract, only `scheduler.trigger_refresh` (the detached "Trigger Full
Refresh Now" button + nightly cron) wrote to `data/output/scheduled_run.log`.
Cache-mode AND live refreshes triggered through the Streamlit "Generate Selected
Reports" button (`run_pipeline_sync`) captured stdout into `session_state.log_lines`
only — those messages died with the Streamlit session, leaving no persistent disk
audit of console-initiated runs.

These tests pin the new behavior:

  • `run_pipeline_sync` appends a `===== run started ... mode=<m>, source=console =====`
    banner before subprocess.run and a `===== run finished ... rc=<n> =====` banner
    after, plus the full captured stdout so SP-push lines land on disk.
  • `scheduler.trigger_refresh` writes the same banner format with `source=scheduler`
    for log-parser parity.

The `source=` discriminator lets the recent-runs UI (and any future log scraper)
attribute every entry to its origin.
"""

import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_V4_PATH = PROJECT_ROOT / "console" / "app.py"


# ---------------------------------------------------------------------------
# Streamlit shim — app_v4 calls st.set_page_config() and renders pages at
# module-import time. We pre-install a MagicMock so the import does not require
# a real Streamlit runtime. session_state behaves like a real dict so the
# function-under-test's `st.session_state.log_lines = []` style writes work.
# ---------------------------------------------------------------------------

class _DictSessionState(dict):
    """Dict that also supports attribute access (matches Streamlit's API)."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key, value):
        self[key] = value


def _install_streamlit_shim():
    """Replace `streamlit` in sys.modules with a MagicMock that won't crash
    app_v4's module-level UI calls. Idempotent — safe across test reruns."""
    if isinstance(sys.modules.get("streamlit"), MagicMock):
        # Reset session_state between import-time renders
        sys.modules["streamlit"].session_state.clear()
        return
    fake_st = MagicMock()
    fake_st.session_state = _DictSessionState({
        "nav": "_no_route_",
        # Bypass the password gate at module load — _check_password() short-
        # circuits on `session_state.get("authenticated")`.
        "authenticated": True,
    })
    # Context managers (st.sidebar, st.container, etc.) need __enter__/__exit__
    fake_st.sidebar.__enter__ = lambda self=None: None
    fake_st.sidebar.__exit__ = lambda *a, **k: None
    # st.columns(n) — real signature returns a list of column handles. The
    # default MagicMock returns a single MagicMock, which breaks tuple unpacking
    # like `c1, c2, c3 = st.columns(3)`.
    def _columns(spec, **_):
        n = spec if isinstance(spec, int) else len(spec)
        return [MagicMock() for _ in range(n)]
    fake_st.columns.side_effect = _columns
    # st.button defaults to a truthy MagicMock, which makes every sidebar
    # nav_button "fire" on import and mutate session_state.nav. Force False.
    fake_st.button.return_value = False
    sys.modules["streamlit"] = fake_st
    sys.modules["streamlit.components.v1"] = MagicMock()


def _load_app_v4():
    """Load app_v4 as a module, tolerating any module-tail UI crash. By the
    time the tail (page dispatcher, sidebar rendering) runs, all function and
    constant defs we care about are bound — we discard the failure."""
    _install_streamlit_shim()
    # Make sure `src.scheduler.start_scheduler` is a no-op so the import does
    # not spawn a real daemon polling thread (would leak across the suite).
    from src import scheduler as sched_mod
    sched_mod.start_scheduler = lambda: None

    spec = importlib.util.spec_from_file_location("app_v4_under_test", APP_V4_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["app_v4_under_test"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        # Page dispatch or some UI primitive choked on a MagicMock — ignore.
        # The function we want to test (`run_pipeline_sync`) is already bound.
        pass
    return module


# Load once for the suite (cheap to re-import a second time, but pointless).
app_v4 = _load_app_v4()
from src import scheduler as sched_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _StubCompleted:
    """Lightweight stand-in for subprocess.CompletedProcess."""

    def __init__(self, stdout="OUTPUT: /tmp/x.xlsx\n✓ Report ready\n", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    """Point BOTH app_v4 and scheduler at the same per-test log path so the
    source= discriminator is the only thing distinguishing entries."""
    path = tmp_path / "scheduled_run.log"
    monkeypatch.setattr(app_v4, "SCHEDULED_RUN_LOG", path, raising=False)
    monkeypatch.setattr(sched_mod, "LOG_FILE", path)
    return path


@pytest.fixture(autouse=True)
def _reset_session_state():
    """Streamlit's session_state is a single shared shim across the suite —
    reset between tests so run_pipeline_sync doesn't see stale state."""
    fake_st = sys.modules.get("streamlit")
    if fake_st is not None and isinstance(fake_st.session_state, _DictSessionState):
        fake_st.session_state.clear()
        fake_st.session_state["nav"] = "_no_route_"
    yield


@pytest.fixture
def stub_sharepoint(monkeypatch):
    """Skip the SharePoint pull step — no client, no admin-bytes side effects."""
    monkeypatch.setattr(app_v4, "get_sharepoint_client", lambda: None)


# ---------------------------------------------------------------------------
# Tests — run_pipeline_sync
# ---------------------------------------------------------------------------

def test_run_pipeline_sync_writes_run_started_banner(log_file, stub_sharepoint, monkeypatch):
    """Cache-mode console refresh must leave a `run started` banner with the
    mode AND `source=console` discriminator on disk. Without `source=`, the
    recent-runs parser can't tell console runs from scheduler runs."""
    monkeypatch.setattr(app_v4.subprocess, "run",
                        lambda *a, **kw: _StubCompleted())

    app_v4.run_pipeline_sync("cache")

    text = log_file.read_text()
    assert "===== run started" in text
    assert "mode=cache" in text
    assert "source=console" in text


def test_run_pipeline_sync_writes_finished_banner(log_file, stub_sharepoint, monkeypatch):
    """The finished banner closes the audit block. The captured stdout from
    the subprocess must also land on disk so the "SP push succeeded" /
    "✓ Report ready" lines survive the Streamlit session dying."""
    stdout = ("OUTPUT: /tmp/x.xlsx\n"
              "Pushed report to SharePoint.\n"
              "✓ Report ready\n")
    monkeypatch.setattr(app_v4.subprocess, "run",
                        lambda *a, **kw: _StubCompleted(stdout=stdout))

    app_v4.run_pipeline_sync("live")

    text = log_file.read_text()
    assert "===== run finished" in text
    assert "rc=0" in text
    # The full subprocess stdout must be persisted — that is the entire point
    # of closing this gap.
    assert "Pushed report to SharePoint." in text
    assert "OUTPUT: /tmp/x.xlsx" in text


def test_run_pipeline_sync_records_nonzero_returncode(log_file, stub_sharepoint, monkeypatch):
    """A failed run must still get a banner — the finished marker carries the
    rc so a later parser can spot the failure even if Streamlit was closed."""
    monkeypatch.setattr(app_v4.subprocess, "run",
                        lambda *a, **kw: _StubCompleted(returncode=2))

    app_v4.run_pipeline_sync("cache")

    text = log_file.read_text()
    assert "===== run finished" in text
    assert "rc=2" in text


# ---------------------------------------------------------------------------
# Tests — scheduler.trigger_refresh (parity)
# ---------------------------------------------------------------------------

def test_trigger_refresh_writes_source_scheduler_banner(log_file, monkeypatch):
    """Parity check: scheduler-side trigger writes the same banner format with
    `source=scheduler`, so a single recent-runs parser can handle both code
    paths without bespoke heuristics."""
    fake_proc = MagicMock(pid=42424)
    monkeypatch.setattr(sched_mod.subprocess, "Popen",
                        lambda *a, **kw: fake_proc)

    pid = sched_mod.trigger_refresh("live")

    assert pid == 42424
    text = log_file.read_text()
    assert "===== run started" in text
    assert "mode=live" in text
    assert "source=scheduler" in text
