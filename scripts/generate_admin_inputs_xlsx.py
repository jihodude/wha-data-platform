"""
generate_admin_inputs_xlsx.py — One-time migration: build admin_inputs.xlsx
from current YAML config + Hannah's penetration CSV.

The resulting xlsx is what admin staff will edit going forward. After this
runs, the engine reads from data/raw/admin_inputs.xlsx instead of the YAML
files. The YAMLs stay as a fallback / source-of-record until SharePoint is wired.

Output file structure (mirrors the planned SharePoint Data Hub / "Goals & Inputs"
folder; admins can split this into separate files later if they prefer):

    Admin Inputs.xlsx
    ├── README                  ← what each sheet is for, edit rules
    ├── Sales Goals             ← revenue goals per territory per month
    ├── Member Goals            ← new-member goals per territory per month
    ├── Retention Goal          ← retention % target (default 92% statewide)
    └── Penetration Goal        ← restaurant penetration % target (default 75%)

    (YoY Targets / Benefit Reviews / Sales Activities sheets retired 2026-07-20 —
    goals are the only admin inputs.)

Penetration COUNTS come from SLX directly (active members + market), not
admin inputs. Only the penetration GOAL/threshold is admin-configurable
(this file). External research-data overrides for counts: see
src/logic/penetration_override.py + docs/EXTENSION_POINTS.md.

Run once:
    python scripts/generate_admin_inputs_xlsx.py
"""

import sys
from pathlib import Path

import yaml
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT_ROOT / "data" / "raw" / "admin_inputs.xlsx"

# Canonical territory order (matches the rest of the codebase)
TERRITORIES = [
    "EastKing", "SouthKing", "NorthKing", "Pierce", "Snohomish",
    "Spokane/NE", "Southwest", "TKP", "Southeast", "NorthCentral", "Majors/NRA",
]

# FY 2025-26 months in order. Fiscal year = Oct 1 -> Sep 30 (AGENTS.md hard rule
# #2), so the axis starts in October. This MUST stay identical to
# src/parsers/admin_inputs.py MONTHS: the generator writes the headers and seeds
# cells by column position, and the parser reads cells by column position. If the
# two lists drift, every grid (Sales Goals, Member Goals) is mis-read by one
# month. Guarded by tests/test_admin_inputs_month_axis.py.
MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
          "Apr", "May", "Jun", "Jul", "Aug", "Sep"]


HEADER_FILL = PatternFill("solid", start_color="4F4F4F")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
EDIT_FILL = PatternFill("solid", start_color="FFF8DC")  # cornsilk — "edit me"
LOCKED_FILL = PatternFill("solid", start_color="F0F0F0")  # light grey — "don't edit"
NOTE_FONT = Font(italic=True, color="606060", size=10)


def main() -> int:
    # Load existing YAMLs to seed the xlsx
    goals_yaml = yaml.safe_load((PROJECT_ROOT / "config" / "goals.yaml").read_text())
    admin_yaml = yaml.safe_load((PROJECT_ROOT / "config" / "admin_inputs.yaml").read_text())

    fy_goals = (goals_yaml.get("fiscal_years") or {}).get("2025-26", {})
    fy_admin = (admin_yaml.get("fiscal_years") or {}).get("2025-26", {})

    wb = Workbook()
    wb.remove(wb.active)  # drop default "Sheet"

    write_readme_sheet(wb)
    write_sales_goals_sheet(wb, fy_goals.get("territories") or {})
    write_member_goals_sheet(wb, fy_admin.get("goal_members_overrides") or {})
    write_retention_goal_sheet(wb, fy_admin.get("goal_retention_default"),
                               fy_admin.get("goal_retention_overrides") or {})
    write_penetration_goal_sheet(wb, fy_admin.get("goal_penetration_default"),
                                 fy_admin.get("goal_penetration_overrides") or {})
    # NOTE: Penetration Market + Penetration Active sheets removed 2026-06-05 —
    # penetration COUNTS now come from SLX directly. The GOAL/threshold above
    # is the only penetration field still admin-editable in this xlsx.
    # YoY Targets + Benefit Reviews sheets retired 2026-07-20.

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUTPUT)
    print(f"✓ Wrote {OUTPUT}")
    print(f"  Size: {OUTPUT.stat().st_size:,} bytes")
    print(f"  Sheets: {len(wb.sheetnames)}")
    for s in wb.sheetnames:
        print(f"    • {s}")
    return 0


# ---------------------------------------------------------------------------
# Sheet builders
# ---------------------------------------------------------------------------

def write_readme_sheet(wb):
    ws = wb.create_sheet("README")
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 80

    ws["A1"] = "WHA Membership — Admin Inputs"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = ("This workbook is the single source of truth for everything humans "
                "tell the membership data system. Edit cells freely — the engine reads "
                "this file every time it runs.")
    ws["A2"].alignment = Alignment(wrap_text=True)
    ws.merge_cells("A2:B2")
    ws.row_dimensions[2].height = 35

    headers = ["Sheet", "What it does + edit rules"]
    for col, h in enumerate(headers, start=1):
        c = ws.cell(row=4, column=col, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL

    rows = [
        ("Sales Goals",       "Monthly revenue goal per territory. Fill yellow cells with dollar values. Leave blank if no goal set."),
        ("Member Goals",      "Monthly new-member count target per territory. Optional — leave blank if no target is set."),
        ("Retention Goal",    "Retention percentage target. Default 0.92 (92%) statewide. Override per territory if needed."),
        ("Penetration Goal",  "Restaurant penetration percentage target. Default 0.75 (75%) statewide. Override per territory if needed."),
    ]
    for i, (sheet, desc) in enumerate(rows, start=5):
        ws.cell(row=i, column=1, value=sheet).font = Font(bold=True)
        c = ws.cell(row=i, column=2, value=desc)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[i].height = 32

    # Color legend
    ws["A14"] = "Legend:"
    ws["A14"].font = Font(bold=True)
    ws["A15"] = "  Yellow cells"
    ws["A15"].fill = EDIT_FILL
    ws["B15"] = "← Edit these. They feed the engine."
    ws["A16"] = "  Grey cells"
    ws["A16"].fill = LOCKED_FILL
    ws["B16"] = "← Reference labels. Don't change names/headers."


def write_sales_goals_sheet(wb, existing):
    ws = wb.create_sheet("Sales Goals")
    ws["A1"] = "Sales Goals — Monthly Revenue Target ($)"
    ws["A1"].font = Font(bold=True, size=12)
    ws.merge_cells("A1:N1")

    note = ws.cell(row=2, column=1,
        value="Enter the monthly revenue goal in dollars per territory. Blank = no goal set.")
    note.font = NOTE_FONT
    ws.merge_cells("A2:N2")

    # Header row 4
    _header(ws, 4, 1, "Territory")
    for col_idx, month in enumerate(MONTHS, start=2):
        _header(ws, 4, col_idx, month)

    # Data rows 5+
    for row_idx, t in enumerate(TERRITORIES, start=5):
        _locked(ws, row_idx, 1, t)
        for col_idx, m in enumerate(MONTHS, start=2):
            val = (existing.get(t) or {}).get(m)
            _editable(ws, row_idx, col_idx, val)

    _column_widths(ws, first=18, rest=10)


def write_member_goals_sheet(wb, overrides):
    ws = wb.create_sheet("Member Goals")
    ws["A1"] = "Member Goals — Monthly New-Member Target (#)"
    ws["A1"].font = Font(bold=True, size=12)
    ws.merge_cells("A1:N1")

    note = ws.cell(row=2, column=1,
        value="Optional. Enter the monthly new-member count target per territory.")
    note.font = NOTE_FONT
    ws.merge_cells("A2:N2")

    _header(ws, 4, 1, "Territory")
    for col_idx, month in enumerate(MONTHS, start=2):
        _header(ws, 4, col_idx, month)

    for row_idx, t in enumerate(TERRITORIES, start=5):
        _locked(ws, row_idx, 1, t)
        per_month_overrides = overrides.get(t) if isinstance(overrides.get(t), dict) else {}
        for col_idx, m in enumerate(MONTHS, start=2):
            _editable(ws, row_idx, col_idx, per_month_overrides.get(m))

    _column_widths(ws, first=18, rest=10)


def write_retention_goal_sheet(wb, default, overrides):
    ws = wb.create_sheet("Retention Goal")
    ws["A1"] = "Retention Goal — % Target (decimal, e.g. 0.92 = 92%)"
    ws["A1"].font = Font(bold=True, size=12)
    ws.merge_cells("A1:C1")

    note = ws.cell(row=2, column=1,
        value="Default = 0.92 (92%) statewide per SOP. Override per territory if a rep has a different target.")
    note.font = NOTE_FONT
    ws.merge_cells("A2:C2")

    _header(ws, 4, 1, "Statewide Default")
    _editable(ws, 5, 1, default if default is not None else 0.92)
    ws.cell(row=5, column=1).number_format = "0.00%"

    _header(ws, 7, 1, "Territory")
    _header(ws, 7, 2, "Override (decimal)")
    for row_idx, t in enumerate(TERRITORIES, start=8):
        _locked(ws, row_idx, 1, t)
        _editable(ws, row_idx, 2, overrides.get(t))
        ws.cell(row=row_idx, column=2).number_format = "0.00%"

    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 22


def write_penetration_goal_sheet(wb, default, overrides):
    ws = wb.create_sheet("Penetration Goal")
    ws["A1"] = "Penetration Goal — Restaurant % Target (decimal, e.g. 0.75 = 75%)"
    ws["A1"].font = Font(bold=True, size=12)
    ws.merge_cells("A1:C1")

    note = ws.cell(row=2, column=1,
        value="Default = 0.75 (75%) statewide. Override per territory only if a specific market has a different goal. "
              "Counts come from SLX; this sheet sets the on-track/below-threshold line only.")
    note.font = NOTE_FONT
    ws.merge_cells("A2:C2")

    _header(ws, 4, 1, "Statewide Default")
    _editable(ws, 5, 1, default if default is not None else 0.75)
    ws.cell(row=5, column=1).number_format = "0.00%"

    _header(ws, 7, 1, "Territory")
    _header(ws, 7, 2, "Override (decimal)")
    for row_idx, t in enumerate(TERRITORIES, start=8):
        _locked(ws, row_idx, 1, t)
        _editable(ws, row_idx, 2, overrides.get(t))
        ws.cell(row=row_idx, column=2).number_format = "0.00%"

    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 22


# ---------------------------------------------------------------------------
# Cell helpers
# ---------------------------------------------------------------------------

def _header(ws, row, col, text):
    c = ws.cell(row=row, column=col, value=text)
    c.font = HEADER_FONT
    c.fill = HEADER_FILL
    c.alignment = Alignment(horizontal="center")


def _locked(ws, row, col, text):
    c = ws.cell(row=row, column=col, value=text)
    c.fill = LOCKED_FILL
    c.font = Font(bold=True)


def _editable(ws, row, col, value):
    c = ws.cell(row=row, column=col, value=value)
    c.fill = EDIT_FILL


def _column_widths(ws, first=18, rest=10):
    ws.column_dimensions["A"].width = first
    for col_idx in range(2, ws.max_column + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = rest


if __name__ == "__main__":
    sys.exit(main())
