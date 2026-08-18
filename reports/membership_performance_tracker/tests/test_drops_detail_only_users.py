"""
test_drops_detail_only_users.py — program/house reps (Retro Coordinator) in drops.

Their DroppedMembersHospitality export includes 119 retro-program member drops
under 'Retro Coordinator' (the bm-13-16 special-cycle set). The MPR's universe
rule: those are neither Target nor Non-Target, so they contribute to NO count —
but the team wants the information, so they ride the detail sheet only
(same pattern as the Admin category, ratified 2026-07-14).

Mechanism: engine merges `drops_detail_only_users` into the map passed to
fetch_drops_and_closed ONLY (billables/penetration/retention never see it);
bucket aggregation already skips territories outside the canonical set.
"""
import reports.membership_performance_tracker.logic.engine as engine_module
from reports.membership_performance_tracker.logic.engine import ScoreboardEngine
from reports.membership_performance_tracker.logic.model import empty_scoreboard

FY_MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
             "Apr", "May", "Jun", "Jul", "Aug", "Sep"]


def _engine(**kw):
    eng = ScoreboardEngine(
        client=None,
        territory_user_map={"U1": "Pierce"},
        fiscal_year_start=2025,
        months=FY_MONTHS,
        current_month="Jun",
        rep_name_map={},
        **kw,
    )
    eng.data = empty_scoreboard(FY_MONTHS)
    return eng


def test_detail_only_users_flow_into_drops_fetch_only(monkeypatch):
    seen = {}

    def fake_fetch(client, territory_user_map, rep_map, min_status_date=None,
                   **kw):
        seen["map"] = dict(territory_user_map)
        return [], []

    monkeypatch.setattr(engine_module, "fetch_drops_and_closed", fake_fetch)
    eng = _engine(drops_detail_only_users={"URETRO": "Retro Program"})
    eng._query_drops_and_closed()

    assert seen["map"]["URETRO"] == "Retro Program", "retro user reaches drops fetch"
    assert seen["map"]["U1"] == "Pierce"
    assert "URETRO" not in eng.territory_user_map, \
        "the shared territory map must stay untouched (universe rule)"


def test_retro_program_rows_never_reach_buckets():
    eng = _engine()
    eng.data.drops_detail = [{
        "account_id": "A9", "account_name": "Retro-Only Diner",
        "territory": "Retro Program", "territory_manager": "",
        "business_type": "Restaurant", "employee_count": 12,
        "is_target": "Y", "renewal_year": 2026, "renewal_month": "Jun",
        "drop_reason": "Out of Business", "drop_category": "Closed",
        "amount_billed": 500.0, "drop_date": "2026-06-10",
    }]
    eng.aggregate_drops_buckets()
    for terr, months in eng.data.drops_target.items():
        assert not any(months.values()), f"retro row leaked into {terr} buckets"


def test_detail_rows_carry_the_account_status_and_mark_rro():
    """The DETAIL sheet must obey the same rule as the counts.

    2026-07-30 (Jen, recorded): "RRO is not a dropped" — the counts exclude RRO,
    but the detail path scopes `Account.Status ne 'Active'`, which INCLUDES RRO
    (Sold splits Closed/RRO). One workbook cannot carry two rules: an auditor
    tracing a headline number to the detail sheet would find members the count
    never had.

    Fix: the detail keeps the row (it IS the FYI list Jen describes) but the
    category says so, so nobody mistakes it for a counted loss.
    """
    from reports.membership_performance_tracker.logic.drops import _drop_category

    assert _drop_category("Sold", status="RRO") == "RRO — not a drop (FYI)"
    assert _drop_category("Out of Business", status="RRO LNI Active") == "RRO — not a drop (FYI)"
    # ordinary statuses are untouched
    assert _drop_category("Sold", status="Closed") == "Sold"
    assert _drop_category("Non-Payment", status="Inactive") == "Non-Payment"
    assert _drop_category("Sold") == "Sold"          # status optional
