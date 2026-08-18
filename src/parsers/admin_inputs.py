"""
admin_inputs.py — Parser for admin_inputs.xlsx.

This file is the human-editable equivalent of the legacy admin_inputs.yaml +
goals.yaml combo. Admins edit cells in Excel; the engine loads structured
values from here every run.

Returns a flat dict shaped like the YAML structure the engine already knows,
so the engine code that calls `_load_admin_inputs` and `_load_goals` doesn't
need to change — only the SOURCE of the values changes.

Returned dict structure:
    {
        "goals":                 {territory: {month: float}},
        "goal_members":          {territory: {month: int}},
        "goal_retention_default": float,
        "goal_retention_overrides": {territory: float},
        "goal_penetration_default": float,
        "goal_penetration_overrides": {territory: float},
    }
    (Penetration COUNTS are no longer admin inputs — they come from SLX.
     YoY Targets / Benefit Reviews / Sales Activities sheets were retired
     2026-07-20 — goals are the only admin inputs.)

Cell layout assumptions (locked in `generate_admin_inputs_xlsx.py`):
    Sales Goals          row 4 header  | row 5+ = territories | cols B-M = months Oct-Sep
    Member Goals         same layout as Sales Goals
    Retention Goal       cell A5 = default | rows 8+ cols A-B = overrides
    Penetration Goal     same layout as Retention Goal
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import openpyxl


# ---------------------------------------------------------------------------
# Layout constants — keep in sync with generate_admin_inputs_xlsx.py
# ---------------------------------------------------------------------------

MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
          "Apr", "May", "Jun", "Jul", "Aug", "Sep"]

TERRITORIES = [
    "EastKing", "SouthKing", "NorthKing", "Pierce", "Snohomish",
    "Spokane/NE", "Southwest", "TKP", "Southeast", "NorthCentral", "Majors/NRA",
]

# Standard "header at row 4, data starts at row 5" layout
HEADER_ROW = 4
DATA_START_ROW = 5


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse(xlsx_path: Path) -> Dict[str, Any]:
    """
    Read admin_inputs.xlsx and return the full admin-input bundle.

    Args:
        xlsx_path: Path to admin_inputs.xlsx.

    Returns:
        Dict with keys: goals, goal_members, goal_retention_default,
        goal_retention_overrides, goal_penetration_default,
        goal_penetration_overrides.
        Penetration counts are NOT loaded from admin inputs anymore — see
        reports/membership_performance_tracker/logic/penetration_override.py
        for the external override path.

    Raises:
        FileNotFoundError if `xlsx_path` doesn't exist.
        KeyError if a required sheet is missing.
    """
    xlsx_path = Path(xlsx_path)
    if not xlsx_path.exists():
        raise FileNotFoundError(f"admin_inputs.xlsx not found at {xlsx_path}")

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)

    result: Dict[str, Any] = {
        "goals":                   _parse_territory_month_grid(wb["Sales Goals"]),
        "goal_members":            _parse_territory_month_grid(wb["Member Goals"]),
        **_parse_retention_goal(wb["Retention Goal"]),
        # Penetration Goal sheet is optional — older xlsx files won't have it.
        **(_parse_penetration_goal(wb["Penetration Goal"])
           if "Penetration Goal" in wb.sheetnames
           else {"goal_penetration_default": 0.75, "goal_penetration_overrides": {}}),
    }
    return result


# ---------------------------------------------------------------------------
# Sheet parsers
# ---------------------------------------------------------------------------

# Strings an admin might type to mean "intentionally no goal" (vs an untouched
# blank cell). These are normalized to 0 — a deliberate zero, not a missing value.
_INTENTIONAL_ZERO_STRINGS = {"-", "—", "–", "0", "n/a", "na", "none"}


def _month_columns(ws, header_row: int) -> Dict[int, str]:
    """Map spreadsheet column → month by READING the header row (handles BOTH the
    legacy SEP-first and the regenerated Oct-first layouts). Falls back to
    positional Oct-first only if no month headers are recognizable.

    Shared by every grid parser (Sales/Member goals grids) so a stray admin
    upload can never shift months. The goals grids were migrated to
    header-name mapping on 2026-07-14.
    """
    col_to_month: Dict[int, str] = {}
    for col in range(2, 2 + len(MONTHS) + 2):
        h = ws.cell(row=header_row, column=col).value
        if isinstance(h, str) and h.strip()[:3].title() in MONTHS:
            col_to_month[col] = h.strip()[:3].title()
    if not col_to_month:
        col_to_month = {2 + i: m for i, m in enumerate(MONTHS)}
    return col_to_month


def _parse_territory_month_grid(ws) -> Dict[str, Dict[str, Optional[float]]]:
    """
    Generic parser for sheets with shape:
        col A = territory name, cols B+ = months Oct..Sep

    Used by Sales Goals and Member Goals.
    Returns {territory: {month: value_or_None}}.

    Value semantics:
        number          → that value (including a literal 0)
        dash / "n/a"    → 0  (admin's deliberate "no goal this month")
        truly blank     → None (cell was never touched)

    This distinction matters: an intentional 0 should NOT be flagged as a
    missing goal by the UI's pre-flight check, but a blank cell can be.
    """
    col_to_month = _month_columns(ws, DATA_START_ROW - 1)

    out: Dict[str, Dict[str, Optional[float]]] = {}
    for row_idx in range(DATA_START_ROW, DATA_START_ROW + len(TERRITORIES)):
        t = ws.cell(row=row_idx, column=1).value
        if t not in TERRITORIES:
            continue
        per_month: Dict[str, Optional[float]] = {}
        for col, month in col_to_month.items():
            v = ws.cell(row=row_idx, column=col).value
            if isinstance(v, (int, float)):
                per_month[month] = v          # includes a literal 0
            elif isinstance(v, str) and v.strip().lower() in _INTENTIONAL_ZERO_STRINGS:
                per_month[month] = 0          # deliberate "no goal"
            else:
                per_month[month] = None       # untouched / blank
        out[t] = per_month
    return out


def _parse_retention_goal(ws) -> Dict[str, Any]:
    """
    Layout:
        A5         = statewide default (e.g. 0.92)
        A8..A18    = territory names
        B8..B18    = per-territory override (or blank)
    """
    default = ws["A5"].value
    if not isinstance(default, (int, float)):
        default = 0.92  # fallback if user clears the default cell

    overrides: Dict[str, float] = {}
    for row_idx in range(8, 8 + len(TERRITORIES)):
        t = ws.cell(row=row_idx, column=1).value
        v = ws.cell(row=row_idx, column=2).value
        if t in TERRITORIES and isinstance(v, (int, float)):
            overrides[t] = float(v)
    return {
        "goal_retention_default":   float(default),
        "goal_retention_overrides": overrides,
    }


def _parse_penetration_goal(ws) -> Dict[str, Any]:
    """
    Same layout as Retention Goal:
        A5         = statewide default (e.g. 0.75)
        A8..A18    = territory names
        B8..B18    = per-territory override (or blank)
    """
    default = ws["A5"].value
    if not isinstance(default, (int, float)):
        default = 0.75  # fallback if user clears the default cell

    overrides: Dict[str, float] = {}
    for row_idx in range(8, 8 + len(TERRITORIES)):
        t = ws.cell(row=row_idx, column=1).value
        v = ws.cell(row=row_idx, column=2).value
        if t in TERRITORIES and isinstance(v, (int, float)):
            overrides[t] = float(v)
    return {
        "goal_penetration_default":   float(default),
        "goal_penetration_overrides": overrides,
    }


# ---------------------------------------------------------------------------
# Change Log — audit trail for admin input mutations
# ---------------------------------------------------------------------------

CHANGE_LOG_SHEET = "Change Log"
CHANGE_LOG_HEADERS = (
    "Timestamp",       # ISO 8601 UTC, populated at call time
    "User",            # Streamlit session operator name (or "admin" fallback)
    "Sheet",           # Source sheet that was edited
    "Cell",            # A1-style cell reference
    "Previous Value",
    "New Value",
)   # No "Reason": it only ever carried a one-time migration note ("Restore
    # Jen's Member Goals…") stamped onto every row, naming a person who has
    # nothing to do with later edits. Removed 2026-08-13 (Jiho). The log
    # answers who/when/what-changed; WHY belongs in the conversation, not in
    # a column that goes stale the moment it is written.


def _now_utc() -> datetime:
    # Indirected through a function so tests can patch it without poking datetime.
    return datetime.now(timezone.utc)


def ensure_change_log(workbook) -> None:
    """Make sure the workbook has a 'Change Log' sheet with the header row.

    Idempotent: if the sheet already exists with correct headers, do nothing.
    """
    if CHANGE_LOG_SHEET in workbook.sheetnames:
        ws = workbook[CHANGE_LOG_SHEET]
        # migrate a pre-8/13 book: drop the retired Reason column in place
        if str(ws.cell(row=1, column=7).value or "").strip() == "Reason":
            ws.delete_cols(7)
        return
    ws = workbook.create_sheet(CHANGE_LOG_SHEET)
    for col_idx, header in enumerate(CHANGE_LOG_HEADERS, start=1):
        ws.cell(row=1, column=col_idx, value=header)


def record_change(
    workbook,
    sheet: str,
    cell: str,
    prev_value,
    new_value,
    user: str,
    reason: str = "",      # accepted and ignored — callers predate the column's removal
) -> bool:
    """Append a row to the 'Change Log' sheet recording an admin input change.

    Idempotent for the same (timestamp_second, user, sheet, cell, new_value):
    a duplicate call within the same UTC second is dedup'd and returns False.
    Returns True if a row was appended.

    Note: timestamp is fetched at call time (not at module load) so test
    fixtures and snapshot harnesses can freeze the clock per-call.
    """
    ensure_change_log(workbook)
    ws = workbook[CHANGE_LOG_SHEET]

    ts = _now_utc().isoformat()
    # Dedup key: compare against last row. Cheap and the common path.
    ts_second = ts.split(".")[0]
    if ws.max_row >= 2:
        last_ts = ws.cell(row=ws.max_row, column=1).value or ""
        last_user = ws.cell(row=ws.max_row, column=2).value
        last_sheet = ws.cell(row=ws.max_row, column=3).value
        last_cell = ws.cell(row=ws.max_row, column=4).value
        last_new = ws.cell(row=ws.max_row, column=6).value
        last_second = str(last_ts).split(".")[0]
        if (
            last_second == ts_second
            and last_user == user
            and last_sheet == sheet
            and last_cell == cell
            and last_new == new_value
        ):
            return False

    ws.append([ts, user, sheet, cell, prev_value, new_value])
    return True


# ---------------------------------------------------------------------------
# Upload-time diff helper
# ---------------------------------------------------------------------------

# Sheets the admin actually edits — diffed cell-by-cell on upload. The Change
# Log sheet itself is never diffed (it's append-only audit history).
# (Retired sheets — Penetration Market/Active, Sales Activities, YoY Targets,
# Benefit Reviews — are absent from current workbooks; diff_workbooks already
# skips sheets absent from both books.)
_DIFFABLE_SHEETS = (
    "Sales Goals",
    "Member Goals",
    "Retention Goal",
    "Penetration Goal",
)


def diff_workbooks(old_wb, new_wb):
    """Yield (sheet, cell, prev_value, new_value) tuples for each changed cell.

    Walks the union of `_DIFFABLE_SHEETS` present in both workbooks. Cells that
    are equal (including both-None) are skipped. Use this on the
    upload path: open old + new with openpyxl, diff, then call
    `record_change()` for each tuple.
    """
    from openpyxl.utils import get_column_letter

    for sheet_name in _DIFFABLE_SHEETS:
        if sheet_name not in old_wb.sheetnames or sheet_name not in new_wb.sheetnames:
            continue
        old_ws = old_wb[sheet_name]
        new_ws = new_wb[sheet_name]
        max_row = max(old_ws.max_row, new_ws.max_row)
        max_col = max(old_ws.max_column, new_ws.max_column)
        for r in range(1, max_row + 1):
            for c in range(1, max_col + 1):
                old_v = old_ws.cell(row=r, column=c).value
                new_v = new_ws.cell(row=r, column=c).value
                if old_v == new_v:
                    continue
                yield sheet_name, f"{get_column_letter(c)}{r}", old_v, new_v
