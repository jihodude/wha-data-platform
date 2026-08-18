"""
P6 decoupling: report registry — the console discovers report nodes via
src.base.registry instead of hardcoding runner paths.
"""
from pathlib import Path

from src.base.registry import available_reports, runner_path


def test_known_reports_discovered():
    names = {r.name for r in available_reports()}
    assert {"membership_performance_tracker", "retention_detail"} <= names


def test_runner_paths_resolve_to_real_files():
    by_name = {r.name: r for r in available_reports()}
    for name in ("membership_performance_tracker", "retention_detail"):
        node = by_name[name]
        assert node.runner is not None and node.runner.exists(), name


def test_runner_path_helper_matches_console_expectations():
    root = Path(__file__).resolve().parent.parent
    assert runner_path("membership_performance_tracker") == (
        root / "reports" / "membership_performance_tracker" / "runner.py")
    assert runner_path("retention_detail") == (
        root / "reports" / "retention_detail" / "runner.py")


def test_runner_path_missing_raises_keyerror():
    import pytest
    with pytest.raises(KeyError):
        runner_path("nonexistent_report")
