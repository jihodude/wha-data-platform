"""A fiscal year with no goals must be LOUD, not silent (item 5, 2026-08-11).

`config/goals.yaml` and `config/admin_inputs.yaml` each carry exactly one key:
`2025-26`. On the first FY2026-27 build `load_goals_for_fy` raises ValueError,
`_load_goals` catches it and emits a `warnings.warn`, and every goal,
attainment and goal-vs-actual cell renders blank. The only signal is a line in
the nightly log that nobody reads.

DELIBERATELY NOT SCAFFOLDED: adding a FY2026-27 block full of nulls would make
this QUIETER, not safer — the loader would find a block, raise nothing, warn
nothing, and still produce no goals. The goal VALUES are leadership's to set
and must not be invented here (hard rule 6: definitions are sourced, not
guessed). So the absence is surfaced where an operator will see it, and filling
it stays a human October chore.
"""
from pathlib import Path

from reports.membership_performance_tracker.logic.engine import ScoreboardEngine
from reports.membership_performance_tracker.logic.model import empty_scoreboard

FY_MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
             "Apr", "May", "Jun", "Jul", "Aug", "Sep"]
GOALS = Path("config/goals.yaml")


def _engine():
    eng = ScoreboardEngine(
        client=None,
        territory_user_map={},
        fiscal_year_start=2026,
        months=FY_MONTHS,
        current_month="Oct",
        rep_name_map={},
    )
    eng.data = empty_scoreboard(FY_MONTHS)
    return eng


def test_a_fiscal_year_with_no_goals_block_raises_a_flag():
    eng = _engine()
    eng._load_goals("2026-27", GOALS)
    rows = eng.flags.get("missing_goals") or []
    assert rows, "a whole fiscal year with no goals must reach the flags tab"
    text = " ".join(str(r) for r in rows)
    assert "2026-27" in text, "the flag names the fiscal year"


def test_the_present_fiscal_year_raises_nothing():
    eng = _engine()
    eng._load_goals("2025-26", GOALS)
    assert not (eng.flags.get("missing_goals") or []), \
        "FY2025-26 is configured — no flag"


def test_the_flag_has_a_section_so_its_rows_render():
    from reports.membership_performance_tracker.logic.receipts_sheet import (
        FLAG_SECTIONS)
    assert "missing_goals" in FLAG_SECTIONS
    title, sev, desc = FLAG_SECTIONS["missing_goals"]
    assert title and desc and sev in ("red", "amber", "gray")


def test_the_admin_inputs_path_flags_too():
    """config/admin_inputs.yaml carries goal_retention_default (0.92) and
    goal_penetration_default (0.75). Those vanish for an unconfigured fiscal
    year exactly like goals.yaml, and were NOT covered by the goals flag."""
    eng = _engine()
    eng._load_admin_inputs("2026-27", Path("config/admin_inputs.yaml"))
    rows = eng.flags.get("missing_goals") or []
    assert any("admin inputs" in str(r) for r in rows), \
        "a fiscal year with no admin inputs must reach the flags tab too"


def test_the_standing_default_targets_carry_forward_to_a_new_fiscal_year():
    """RULED by Jiho 2026-08-11: "the default % can stay". A retention or
    penetration TARGET is standing policy, not a per-year number, so FY2026-27
    inherits FY2025-26's defaults (0.92 / 0.75) rather than rendering the goal
    lines blank. Per-territory overrides and market sizes do NOT carry — those
    are genuinely per-year, and guessing them would invent data."""
    eng = _engine()
    eng._load_admin_inputs("2026-27", Path("config/admin_inputs.yaml"))

    ret = eng.data.goal_retention["EastKing"]["Oct"]
    assert ret == 0.92, f"the standing retention target must carry, got {ret!r}"
    assert any("carried forward" in str(r)
               for r in eng.flags.get("missing_goals") or []), \
        "carrying the default is still disclosed, not silent"
