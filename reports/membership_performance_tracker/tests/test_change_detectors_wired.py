"""C2 — the four change detectors exist, are implemented, and were NEVER run.

`bill_month_changes`, `billing_account_changes`, `status_flips` and
`consolidation_events` are declared on ScoreboardData (model.py:322-346) and
implemented in src/slx/audit.py (:119) — and a repo-wide check on 8/12 found
ZERO call sites. Every scoreboard ever published carries them as [].

The cost of that silence is measured: 6 members sit under a different bill
month in the live CRM than the cycle we filed them under (four SpokaneNE
hotels four months off, Hilton Seattle Airport $5,940, B&C Preston with no
retention row at all) — the exact class the first detector was built to
surface, invisible for want of one call.

The collector is a standalone function so it is testable without the engine,
and best-effort by design: the audit history is a SECONDARY surface, so its
failure flags loudly but never kills a run.
"""
from datetime import date

from reports.membership_performance_tracker.logic.engine import (
    collect_change_detectors)


class _FC:
    """the FieldChange dataclass shape, minus the import"""
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_collects_all_four_families(monkeypatch):
    from reports.membership_performance_tracker.logic import engine as eng
    fc = _FC(account_id="A1", account_name="Stokes", field="Duesbillmonth",
             old_value="9", new_value="2", when=None)
    monkeypatch.setattr(eng._audit, "bill_month_changes", lambda c, since, until=None: [fc])
    monkeypatch.setattr(eng._audit, "billing_account_changes", lambda c, since, until=None: [fc])
    monkeypatch.setattr(eng._audit, "status_flips_within", lambda c, since, until=None: [
        {"account_id": "A2", "gap_days": 3}])
    flags = {}
    out = collect_change_detectors(object(), 2025, flags)
    assert set(out) == {"bill_month_changes", "billing_account_changes",
                        "status_flips", "consolidation_events"}
    # plain dicts, never dataclasses — the cache is JSON
    assert isinstance(out["bill_month_changes"][0], dict)
    assert out["bill_month_changes"][0]["old_value"] == "9"
    # consolidation events ARE the CBillingAccount changes (audit.py:128:
    # "consolidation activity") — one source, two names kept for the model
    assert out["consolidation_events"] == out["billing_account_changes"]
    assert out["status_flips"] == [{"account_id": "A2", "gap_days": 3}]
    # a human-visible summary lands on the flags surface
    assert "change_detectors" in flags


def test_detector_failure_flags_loudly_and_returns_empty(monkeypatch):
    from reports.membership_performance_tracker.logic import engine as eng
    def boom(*a, **k):
        raise RuntimeError("audit surface down")
    monkeypatch.setattr(eng._audit, "bill_month_changes", boom)
    monkeypatch.setattr(eng._audit, "billing_account_changes", boom)
    monkeypatch.setattr(eng._audit, "status_flips_within", boom)
    flags = {}
    out = collect_change_detectors(object(), 2025, flags)
    assert all(v == [] for v in out.values())
    assert flags.get("change_detectors_failed"), "silent absorption is the defect class this repo keeps re-finding"


def test_window_is_the_fiscal_year(monkeypatch):
    from reports.membership_performance_tracker.logic import engine as eng
    seen = {}
    def spy(c, since, until=None):
        seen["since"] = since
        return []
    monkeypatch.setattr(eng._audit, "bill_month_changes", spy)
    monkeypatch.setattr(eng._audit, "billing_account_changes", lambda *a, **k: [])
    monkeypatch.setattr(eng._audit, "status_flips_within", lambda *a, **k: [])
    collect_change_detectors(object(), 2025, {})
    assert seen["since"] == date(2025, 10, 1), "FY = Oct 1 start, hard rule 2"
