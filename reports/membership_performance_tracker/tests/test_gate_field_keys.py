"""Gate-hardening regression (2026-07-17): consistency_check's FIELD_TO_METRIC
referenced cache keys that don't exist (bill_target/bill_non_target/bill_allied),
so billables silently validated ZERO cells while the gate reported "pass". This
test asserts every configured key is a REAL ScoreboardData field — it would have
caught that bug, and guards against any future mistyped key.
"""
import importlib.util
from dataclasses import fields

from reports.membership_performance_tracker.logic.model import ScoreboardData


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_consistency_check_keys_are_real_cache_fields():
    cc = _load_module("scripts/consistency_check.py", "consistency_check")
    valid = {f.name for f in fields(ScoreboardData)}
    bad = [k for k in cc.FIELD_TO_METRIC if k not in valid]
    assert not bad, f"consistency_check references non-existent cache fields: {bad}"
