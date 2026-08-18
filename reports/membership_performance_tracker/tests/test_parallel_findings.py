"""
test_parallel_findings.py — regression tests for the correctness findings from
docs/review/parallel-quality-findings.md (2026-07-17 INVESTIGATE phase). One
test group per finding number; each pins the fixed behavior so the superseded
bug can't return.
"""
import os
import warnings

import pytest


def _raise(exc):
    def _f(*a, **k):
        raise exc
    return _f


# --- #5: goals_loader.get_goal falsy-zero (an explicit 0 goal became default) ---

def test_finding5_get_goal_preserves_explicit_zero():
    from src.config.goals_loader import get_goal
    goals = {"Pierce": {"Mar": 0}}
    # A deliberate 0 goal must stay 0, not be replaced by the default.
    assert get_goal(goals, "Pierce", "Mar", default=500) == 0


def test_finding5_get_goal_uses_default_only_when_missing():
    from src.config.goals_loader import get_goal
    goals = {"Pierce": {"Mar": 0}}
    assert get_goal(goals, "Pierce", "Apr", default=500) == 500  # month absent
    assert get_goal(goals, "King", "Mar", default=500) == 500    # territory absent


# --- #15: drops._get_renewal_info read Duesbillmonth from records[0] only ---

class _RenewalFakeClient:
    """cMemberGens returns two rows (Sage-dup pattern); the FIRST lacks
    Duesbillmonth, a LATER one has it — like Membernum/product already scan for."""

    def _fetch_all(self, entity, where="", select=None, page_size=200):
        if entity == "cMemberGens":
            return [
                {"Membernum": "M1", "MembershipProduct": {"$key": "P1"}},  # no billmonth
                {"Membernum": "M1", "Duesbillmonth": 6},                    # 2nd row has it
            ]
        return []  # dlInvoiceHistoryHeader → no invoices (renewal_year None)


def test_finding15_renewal_billmonth_found_on_non_first_row():
    from reports.membership_performance_tracker.logic.drops import _get_renewal_info
    _year, month_name, member_id, _product, _wra = _get_renewal_info(_RenewalFakeClient(), "A1")
    assert month_name == "June", "Duesbillmonth on a duplicate (non-first) row must still resolve"
    assert member_id == "M1"


# --- #25: acquire_pull_lock treated a live-but-other-user process as stale ---

def test_finding25_lock_refuses_on_permission_error(tmp_path, monkeypatch):
    """os.kill(pid,0) raising PermissionError = the process EXISTS but is another
    user's (the exact 'someone else's live pull' case). Must REFUSE + keep the
    lock, not clear it as stale (hard rule 5: one SLX session at a time)."""
    import reports.membership_performance_tracker.runner as runner
    lock = tmp_path / "pull.lock"
    lock.write_text("99999")
    monkeypatch.setattr(runner.os, "kill", _raise(PermissionError()))
    assert runner.acquire_pull_lock(lock) is False
    assert lock.exists(), "a live other-user lock must NOT be cleared"


def test_finding25_lock_clears_stale_dead_pid(tmp_path, monkeypatch):
    import reports.membership_performance_tracker.runner as runner
    lock = tmp_path / "pull.lock"
    lock.write_text("99999")
    monkeypatch.setattr(runner.os, "kill", _raise(ProcessLookupError()))
    assert runner.acquire_pull_lock(lock) is True  # dead pid → clear + acquire
    assert lock.read_text().strip() == str(os.getpid())


# --- #14: engine bob_new_accounts last-user-wins for multi-user territories ---

_FY = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"]


def test_finding14_bob_new_accounts_merges_across_users():
    """Majors/NRA has two seat users since 7/13; bob_new_accounts must SUM across
    them like every other per-territory metric, not last-user-wins overwrite."""
    from reports.membership_performance_tracker.logic.engine import ScoreboardEngine
    from reports.membership_performance_tracker.logic.model import empty_scoreboard

    class FakeSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            return []  # no new members — isolate the BOB loop

        def get_bob_new_accounts(self, user_id, start, end):
            return {"U1": [{"id": "A1"}], "U2": [{"id": "A2"}]}.get(user_id, [])

    eng = ScoreboardEngine(
        client=FakeSLX(),
        territory_user_map={"U1": "Majors/NRA", "U2": "Majors/NRA"},
        fiscal_year_start=2025, months=_FY, current_month="Mar", rep_name_map={},
    )
    eng.data = empty_scoreboard(_FY)
    eng._query_new_members()
    got = eng.data.bob_new_accounts["Majors/NRA"]
    assert {a["id"] for a in got} == {"A1", "A2"}, "both users' BOB accounts must be kept"


# --- #7 (R3b): _merge_retention_rows summed the 'pct' key + left 'string' stale ---

def test_finding7_merge_recomputes_pct_and_string_not_sum():
    from reports.membership_performance_tracker.logic.retention import _merge_retention_rows
    a = {"pct": 90.0, "paid": 9, "billed": 10, "string": "9/10",
         "revenue_up_for_renewal": 100.0, "revenue_retained": 90.0, "revenue_retention_pct": 90.0}
    b = {"pct": 80.0, "paid": 8, "billed": 10, "string": "8/10",
         "revenue_up_for_renewal": 100.0, "revenue_retained": 80.0, "revenue_retention_pct": 80.0}
    m = _merge_retention_rows(a, b)
    assert m["paid"] == 17 and m["billed"] == 20
    assert m["pct"] == 85.0, "pct must be RECOMPUTED 17/20, not summed 90+80"
    assert m["string"] == "17/20", "string must be rebuilt from merged counts, not stale '9/10'"


# --- #6 (R3a): compute_retention_all_months overwrote multi-user territories ---

def _ms(y, mo, d):
    from datetime import datetime, timezone
    return f"/Date({int(datetime(y, mo, d, tzinfo=timezone.utc).timestamp() * 1000)})/"


class _TwoUserRetentionSLX:
    """Two seat users of one territory, each owning one distinct paid+billed
    account, enrolled 2+ yrs prior (first-cycle rule keeps them in)."""
    _acct = {"U_A": "A1", "U_B": "A2"}

    def _fetch_all(self, entity, where="", select=None, page_size=200):
        if entity == "dlInvoiceHistoryHeader":
            uid = next((u for u in self._acct if u in where), None)
            if not uid:
                return []
            # Comment anchors cohort membership since 2026-07-28 (the fetch is
            # no longer comment-filtered server-side, so fixtures carry it).
            return [{"Accountid": self._acct[uid], "Balance": 0.0,
                     "Net_invoice": 500.0, "Invoice_Type": "IN", "Comment": "12",
                     "Invoice_number": self._acct[uid], "Invoice_Date": _ms(2025, 11, 1)}]
        if entity == "cMemberGens":
            aid = next((a for a in ("A1", "A2") if a in where), None)
            return [{"Account": {"$key": aid}, "EnrolledDate": _ms(2023, 1, 1)}] if aid else []
        return []


def test_finding6_all_months_sums_multiuser_not_overwrite():
    from reports.membership_performance_tracker.logic.retention import compute_retention_all_months
    tmap = {"U_A": "Majors/NRA", "U_B": "Majors/NRA"}
    res = compute_retention_all_months(_TwoUserRetentionSLX(), tmap, bill_months=[12],
                                       fiscal_year_start=2025, request_delay=0.0)
    assert res[12]["Majors/NRA"]["billed"] == 2, "second user must not erase the first (last-user-wins)"


# --- #4/#8: BOB (Black-Owned Business) query must scope to the reported month ---

def test_finding4_bob_query_scopes_to_month():
    """BOB = comped Black-Owned Business; the alert flags accounts enrolled THIS
    month for manual revenue credit (training PDF: 'all the Bobs for the month').
    The query used to IGNORE its date window and return every diverse-owned
    account, every month. Scope by CDiverseEnrollDate, exclusive next-day end."""
    from src.slx.client import SLXClient

    class _Stub(SLXClient):
        def __init__(self):
            self.where = None

        def _fetch_all(self, entity, where="", select=None, page_size=200):
            self.where = where
            return []

    c = _Stub()
    c.get_bob_new_accounts("U1", "2026-03-01", "2026-03-31")
    assert "CDiverseOwnership ne null" in c.where
    assert "CDiverseEnrollDate ge @2026-03-01@" in c.where
    assert "CDiverseEnrollDate lt @2026-04-01@" in c.where  # exclusive next-day boundary


# --- #11: unrecognized FTE band must be Unknown (not silent Non-Target); tables shared ---

def test_finding11_unrecognized_fte_band_is_unknown():
    from reports.membership_performance_tracker.logic.target import (
        _classify_one, TARGET, NON_TARGET, UNKNOWN)
    assert _classify_one("Restaurant", None, "5 to 9") == NON_TARGET   # recognized < 10 FTE
    assert _classify_one("Restaurant", None, "10 to 19") == TARGET     # recognized target
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert _classify_one("Restaurant", None, "42 to 88") == UNKNOWN  # unrecognized
    assert any("42 to 88" in str(x.message) for x in w), "unrecognized band must warn"


def test_finding11_drops_parse_fte_range_unknown_for_unrecognized():
    from reports.membership_performance_tracker.logic.drops import _parse_fte_range
    assert _parse_fte_range("5 to 9") == (7, False)     # recognized below-threshold → N
    assert _parse_fte_range("10 to 19") == (14, True)   # recognized target → Y
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert _parse_fte_range("42 to 88") == (None, None)  # unrecognized → Unknown (blank)
    assert any("42 to 88" in str(x.message) for x in w), "unrecognized band must warn"


def test_finding11_classification_tables_are_shared_not_duplicated():
    from reports.membership_performance_tracker.logic import target, drops
    assert drops._TARGET_RANGES is target._TARGET_RANGES
    assert drops._RANGE_MIDPOINTS is target._RANGE_MIDPOINTS


# --- FTE band normalization (7/18 live-pull discovery): the CRM holds 1,198
# variant-FORMAT band strings ('10-19', '1,000-4,999', '10  to 19'…) — same bands,
# different formatting (import drift). Canonicalize before lookup so a format
# variant never lands in Unknown (or, pre-guard, silent Non-Target). ---

def test_fte_variant_formats_classify_canonically():
    from reports.membership_performance_tracker.logic.target import (
        _classify_one, TARGET, NON_TARGET)
    assert _classify_one("Restaurant", None, "10-19") == TARGET        # hyphen form
    assert _classify_one("Restaurant", None, "10  to 19") == TARGET    # double space
    assert _classify_one("Restaurant", None, "1,000-4,999") == TARGET  # comma+hyphen
    assert _classify_one("Restaurant", None, "5,000 to 9,999") == TARGET
    assert _classify_one("Restaurant", None, "5-9") == NON_TARGET      # below threshold
    assert _classify_one("Restaurant", None, "1-4") == NON_TARGET


def test_fte_variant_formats_parse_in_drops():
    from reports.membership_performance_tracker.logic.drops import _parse_fte_range
    assert _parse_fte_range("10-19") == (14, True)
    assert _parse_fte_range("1,000-4,999") == (2999, True)
    assert _parse_fte_range("5-9") == (7, False)


def test_fte_all_live_band_formats_classify_no_unknown():
    """Every format present in the live CRM (sourced 2026-07-22 from cRestProfiles:
    45,042 rows, 23 distinct formats, 0 falling to Unknown) classifies to a real
    bucket. Locks the complete format space so a normalize/table regression can't
    silently reopen the 745-target-sized-Unknown hole. New live format → add it
    here AND to target._RANGE_MIDPOINTS."""
    from reports.membership_performance_tracker.logic.target import (
        _classify_one, TARGET, NON_TARGET, UNKNOWN)
    from reports.membership_performance_tracker.logic.drops import _parse_fte_range
    live = {
        "1 to 4": NON_TARGET, "1-4": NON_TARGET,
        "5 to 9": NON_TARGET, "5-9": NON_TARGET,
        "10 to 19": TARGET, "10-19": TARGET, "10  to 19": TARGET,
        "20 to 49": TARGET, "20-49": TARGET,
        "50 to 99": TARGET, "50-99": TARGET,
        "100 to 249": TARGET, "100-249": TARGET,
        "250 to 499": TARGET, "250-499": TARGET,
        "500 to 999": TARGET, "500-999": TARGET,
        "1000 to 4999": TARGET, "1,000 to 4,999": TARGET, "1,000-4,999": TARGET,
        "5000 to 9999": TARGET, "5,000 to 9,999": TARGET,
    }
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a stray Unknown-warn would fail here
        for raw, expected in live.items():
            assert _classify_one("Restaurant", None, raw) == expected, f"target: {raw!r}"
            assert _classify_one("Restaurant", None, raw) != UNKNOWN
            _emp, is_target = _parse_fte_range(raw)
            assert is_target is (expected == TARGET), f"drops: {raw!r}"


def test_fte_truly_unknown_band_still_warns():
    from reports.membership_performance_tracker.logic.target import _classify_one, UNKNOWN
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert _classify_one("Restaurant", None, "42 to 88") == UNKNOWN
    assert any("42 to 88" in str(x.message) for x in w)


# --- #16: retention status/alert must honor the admin Retention Goal, not hardcode 0.92 ---

_FY16 = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"]


def test_finding16_retention_alert_uses_admin_goal_not_hardcoded_92():
    from reports.membership_performance_tracker.runner import build_alerts_dict
    from reports.membership_performance_tracker.logic.model import empty_scoreboard
    d = empty_scoreboard(_FY16)
    d.avg_retention["Pierce"] = 0.88
    d.avg_retention["Snohomish"] = 0.88
    for m in _FY16:
        d.goal_retention["Pierce"][m] = 0.85     # admin LOWERED Pierce's goal
        d.goal_retention["Snohomish"][m] = 0.92  # Snohomish at default
    alerts = build_alerts_dict(d, "Mar", "2025-2026", {})
    watched = {r["territory"] for r in alerts["retention_watch"]}
    assert "Snohomish" in watched, "0.88 < 0.92 goal must alert"
    assert "Pierce" not in watched, "0.88 >= 0.85 admin goal must NOT alert (goal was lowered)"


def test_finding16_retention_goal_helper_falls_back_to_default():
    from reports.membership_performance_tracker.logic.retention import (
        retention_goal_for, DEFAULT_RETENTION_GOAL)
    assert retention_goal_for({"Pierce": {"Mar": 0.80}}, "Pierce") == 0.80  # admin goal
    assert retention_goal_for({}, "Pierce") == DEFAULT_RETENTION_GOAL        # unset → fallback
    assert retention_goal_for({"Pierce": {"Mar": None}}, "Pierce") == DEFAULT_RETENTION_GOAL


# --- drops $ (7/21: CMP fallback REVERTED — CMP fees are not dues) ---

def test_drops_amount_never_uses_cmp_fees():
    """REVERSAL of the 7/20 fallback: CMP = Claims Management Program fees
    (Jen 7/21), not dues — showing them as lost membership revenue was wrong.
    An account with no WRA dues invoice reports NO lost-$ (blank beats wrong)."""
    from reports.membership_performance_tracker.logic.drops import _get_last_invoice_amount

    class FakeSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            if "Comp_code eq 'WRA'" in where:
                return []
            if "Comp_code eq 'MSC'" in where:
                return [
                    {"Accountid": "A1", "Net_invoice": 700.0,
                     "Invoice_Date": "/Date(1770000000000)/", "Po_number": "2026 CMP Fee BM 6-12"},
                ]
            return []

    assert _get_last_invoice_amount(FakeSLX(), "A1") is None, \
        "no WRA dues → no lost-$; claims fees must never fill the gap"


# --- retention: partial payers count as retained (Jen's convention, 7/21) ---

def test_partial_payer_counts_as_retained():
    """Jennifer's convention, ratified by Jiho 7/21: a partial payer STAYED —
    they count as retained. Decoded from her HCB file (EK 5 full + 2 partial
    = her published 7/9). Zero-paid and unknown-balance members still don't."""
    from reports.membership_performance_tracker.logic.retention import _member_retained

    full    = [{"balance": 0.0,   "amount": 510.0}]
    partial = [{"balance": 169.72, "amount": 510.0}]   # paid 340.28
    unpaid  = [{"balance": 510.0, "amount": 510.0}]
    unknown = [{"balance": None,  "amount": 510.0}]
    assert _member_retained(full) is True
    assert _member_retained(partial) is True, "partial payer stayed — retained"
    assert _member_retained(unpaid) is False
    assert _member_retained(unknown) is False
