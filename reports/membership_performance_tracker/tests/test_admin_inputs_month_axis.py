"""
test_admin_inputs_month_axis.py — the admin-inputs month axis must be consistent
end to end: a value an admin types under a given month's column must surface in
the engine under that SAME month.

Root cause this guards against (the "off-by-one month" bug): the generator that
builds admin_inputs.xlsx writes the month headers and seeds cells *by column
position*, and the parser reads cells *by column position* (with header-name
mapping as the safety net). The two MUST agree on which calendar month column B
is. Per the Oct-first fiscal year (AGENTS.md hard rule #2) both must start
"Oct". When the generator was Sep-first while the parser was Oct-first, every
value was read one month early — a value typed under "Mar" (generator column H)
was ingested as "Apr" (parser MONTHS[6]).

(Historical note: this file also guarded the Benefit Reviews path until that
sheet was retired on 2026-07-20 — goals are the only admin inputs now.)
"""
import openpyxl

from src.parsers.admin_inputs import MONTHS as PARSER_MONTHS
from reports.membership_performance_tracker.logic.engine import ScoreboardEngine
from reports.membership_performance_tracker.logic.model import empty_scoreboard
from scripts.generate_admin_inputs_xlsx import (
    MONTHS as GENERATOR_MONTHS,
    write_sales_goals_sheet,
    write_member_goals_sheet,
    write_retention_goal_sheet,
    write_penetration_goal_sheet,
)

ADMIN_HEADER_ROW = 4     # month headers in the goal grids
ADMIN_FIRST_DATA_ROW = 5


def _column_for_header(ws, header_row: int, label: str) -> int:
    """Return the 1-based column whose header cell in `header_row` reads `label`."""
    for col in range(1, ws.max_column + 1):
        if ws.cell(row=header_row, column=col).value == label:
            return col
    raise AssertionError(f"header {label!r} not found in row {header_row} of {ws.title!r}")


def test_generator_and_parser_share_one_month_axis():
    """
    The xlsx generator (writes month headers + seeds cells by position) and the
    parser (reads cells by position) must enumerate months in the same order.
    Any divergence shifts every grid — Sales Goals and Member Goals both key
    off this one list — by one month.
    """
    assert GENERATOR_MONTHS == PARSER_MONTHS
    # ...and per the Oct-first fiscal year, that shared axis starts in October.
    assert PARSER_MONTHS[0] == "Oct"


def test_goal_month_preserved_generator_parse_engine(tmp_path):
    """
    A sales goal typed under the 'Mar' column must land in the engine under
    'Mar' — through generator -> parse -> engine ingest, unchanged.
    """
    # --- ARRANGE: build a real admin_inputs.xlsx, type 3205 under "Mar" -------
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # drop the default empty sheet
    write_sales_goals_sheet(wb, {})
    write_member_goals_sheet(wb, {})
    write_retention_goal_sheet(wb, 0.92, {})
    write_penetration_goal_sheet(wb, 0.75, {})

    sg = wb["Sales Goals"]
    mar_col = _column_for_header(sg, ADMIN_HEADER_ROW, "Mar")
    sw_row = None
    for r in range(ADMIN_FIRST_DATA_ROW, ADMIN_FIRST_DATA_ROW + 15):
        if sg.cell(row=r, column=1).value == "Southwest":
            sw_row = r
            break
    assert sw_row, "Southwest row missing from generated Sales Goals sheet"
    sg.cell(row=sw_row, column=mar_col, value=3205)

    admin_path = tmp_path / "admin_inputs.xlsx"
    wb.save(admin_path)

    # --- ACT: parse -> engine (the real ingest path, no SLX needed) -----------
    engine = ScoreboardEngine(
        client=None,
        territory_user_map={},
        fiscal_year_start=2025,
        months=PARSER_MONTHS,
        current_month="Mar",
        rep_name_map={},
    )
    engine.data = empty_scoreboard(PARSER_MONTHS)
    engine.load_admin_inputs_xlsx(admin_path)

    # --- ASSERT: the month label survives (no off-by-one) ---------------------
    assert engine.data.goal["Southwest"]["Mar"] == 3205
    assert engine.data.goal["Southwest"].get("Apr") is None
    # scalar goal defaults also ride along
    assert engine.data.goal_penetration["Southwest"] == 0.75
