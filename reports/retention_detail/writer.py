"""
writer.py — Single-sheet xlsx writer for the retention drilldown report.

Layout (intentionally simple, replaces Jennifer's hand-built reference):
    Row 1 — title + bill month + generated-at
    Row 2 — frozen
    Row 3 — column headers (bold)
    Rows 4+ — per-territory section:
        section header row (bold + fill)
        one row per member (light red fill if unpaid)
        subtotal block (labeled, bold)
        one blank row
    Final block — statewide totals (bold + fill)

Number formatting:
    Currency: $#,##0;($#,##0);"-"
    %        : 0.0%
    MID      : text (preserves leading zeros)

This is the MVP. No multi-sheet workbook, no autofilter, no hyperlinks,
no conditional borders. Looks like a real report; doesn't pretend to be a
collections platform.
"""

from datetime import date
from pathlib import Path
from typing import Dict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side


# ---------- styles ----------

TITLE_FONT      = Font(name="Calibri", size=14, bold=True)
SECTION_FONT    = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
HEADER_FONT     = Font(name="Calibri", size=10, bold=True)
SUBTOTAL_FONT   = Font(name="Calibri", size=10, bold=True)
META_FONT       = Font(name="Calibri", size=9, italic=True, color="606060")

SECTION_FILL    = PatternFill("solid", start_color="305496")   # dark blue
UNPAID_FILL     = PatternFill("solid", start_color="FCE4D6")   # light red
SUBTOTAL_FILL   = PatternFill("solid", start_color="F2F2F2")   # light grey
STATEWIDE_FILL  = PatternFill("solid", start_color="D9E1F2")   # light blue

CURRENCY_FMT = '"$"#,##0;("$"#,##0);"-"'
PCT_FMT      = '0.0%'

THIN_BORDER = Border(bottom=Side(style="thin", color="BFBFBF"))


# ---------- columns ----------

COLUMNS = [
    ("MID",         12, "text"),
    ("Member Name", 38, "text"),
    ("TM",          14, "text"),
    ("Billed",      14, "currency"),
    ("Paid",        14, "currency"),
    ("Balance",     14, "currency"),
    ("Last Note",   60, "text"),
]


# ---------- public entry point ----------

def write_drilldown(
    drilldown: Dict[str, dict],
    output_path: Path,
    bill_month: int,
    fiscal_year_label: str = "",
) -> Path:
    """
    Write the retention drilldown to a single-sheet xlsx.

    Args:
        drilldown:         {territory: {"rows": [...], "summary": {...}}} from
                           reports.retention_detail.data.collect_drilldown.
        output_path:       Where to save the xlsx.
        bill_month:        1-12; included in the title.
        fiscal_year_label: e.g. "2025-26" — included in the title.

    Returns:
        The output_path (so callers can chain).
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Retention Detail Report"

    # Set column widths
    for i, (_, width, _) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = width

    # ---- Title row (row 1) ----
    bm_name = _month_name(bill_month)
    fy_part = f" — FY {fiscal_year_label}" if fiscal_year_label else ""
    ws.cell(row=1, column=1,
            value=f"Hospitality Retention Detail Report — Bill Month {bill_month} ({bm_name}){fy_part}"
            ).font = TITLE_FONT
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(COLUMNS))

    # ---- Generated-at meta (row 2) ----
    meta = ws.cell(row=2, column=1,
                   value=f"Generated {date.today().isoformat()} — Balance is current as of this run; not point-in-time.")
    meta.font = META_FONT
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(COLUMNS))

    # ---- Column headers (row 3) ----
    for col, (label, _, _) in enumerate(COLUMNS, start=1):
        c = ws.cell(row=3, column=col, value=label)
        c.font = HEADER_FONT
        c.border = THIN_BORDER

    # Freeze rows 1-3
    ws.freeze_panes = "A4"

    # ---- Per-territory sections ----
    row = 4
    state_billed = state_paid = 0.0
    state_count_billed = state_count_paid = 0

    for territory in sorted(drilldown.keys()):
        section = drilldown[territory]
        rows_data = section["rows"]
        summary   = section["summary"]

        # Section header row
        ws.cell(row=row, column=1, value=f"{territory} Territory").font = SECTION_FONT
        ws.cell(row=row, column=2, value=f"Bill Month: {bill_month}").font = SECTION_FONT
        for col in range(1, len(COLUMNS) + 1):
            ws.cell(row=row, column=col).fill = SECTION_FILL
        row += 1

        # Data rows
        for r in rows_data:
            unpaid = r["balance"] > 0
            cells = [
                r["mid"],
                r["name"],
                r["tm"],
                r["billed"],
                r["paid"],
                r["balance"],
                r["last_note"],
            ]
            for col, (val, (_, _, fmt)) in enumerate(zip(cells, COLUMNS), start=1):
                c = ws.cell(row=row, column=col, value=val)
                if fmt == "currency":
                    c.number_format = CURRENCY_FMT
                elif fmt == "text":
                    c.number_format = "@"
                if col == 7:                      # Last Note column wraps
                    c.alignment = Alignment(wrap_text=True, vertical="top")
                if unpaid:
                    c.fill = UNPAID_FILL
            ws.row_dimensions[row].height = 18 if not unpaid else 24
            row += 1

        # Subtotal block (3 LABELED rows — not Jennifer's bare numbers)
        _write_subtotal_row(ws, row, "Total billed / paid",
                            summary["billed_total"], summary["paid_total"],
                            num_format=CURRENCY_FMT)
        row += 1
        _write_subtotal_row(ws, row, "Collection rate (Paid/Billed)",
                            summary["collection_rate"], None,
                            num_format=PCT_FMT)
        row += 1
        _write_subtotal_row(ws, row, "Members billed / paid",
                            summary["count_billed"], summary["count_paid"],
                            num_format="0")
        row += 1

        # Blank spacer
        row += 1

        # Accumulate statewide
        state_billed       += summary["billed_total"]
        state_paid         += summary["paid_total"]
        state_count_billed += summary["count_billed"]
        state_count_paid   += summary["count_paid"]

    # ---- Statewide totals ----
    state_summary = {
        "billed_total":    state_billed,
        "paid_total":      state_paid,
        "collection_rate": (state_paid / state_billed) if state_billed else None,
        "count_billed":    state_count_billed,
        "count_paid":      state_count_paid,
        "retention_rate":  (state_count_paid / state_count_billed) if state_count_billed else None,
    }
    _write_statewide(ws, row, state_summary)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path


# ---------- helpers ----------

def _write_subtotal_row(ws, row, label, val_a, val_b, *, num_format):
    """Write a labeled subtotal row: label in col C, value in col D (and E if val_b)."""
    ws.cell(row=row, column=3, value=label).font = SUBTOTAL_FONT
    a = ws.cell(row=row, column=4, value=val_a)
    a.font = SUBTOTAL_FONT
    a.number_format = num_format
    if val_b is not None:
        b = ws.cell(row=row, column=5, value=val_b)
        b.font = SUBTOTAL_FONT
        b.number_format = num_format
    for col in range(1, len(COLUMNS) + 1):
        ws.cell(row=row, column=col).fill = SUBTOTAL_FILL


def _write_statewide(ws, row, summary):
    """Write the statewide-rollup block at the very end."""
    ws.cell(row=row, column=1, value="STATEWIDE").font = SECTION_FONT
    for col in range(1, len(COLUMNS) + 1):
        ws.cell(row=row, column=col).fill = STATEWIDE_FILL
    row += 1

    _write_subtotal_row(ws, row, "Total billed / paid",
                        summary["billed_total"], summary["paid_total"],
                        num_format=CURRENCY_FMT)
    row += 1
    _write_subtotal_row(ws, row, "Collection rate (Paid/Billed)",
                        summary["collection_rate"], None,
                        num_format=PCT_FMT)
    row += 1
    _write_subtotal_row(ws, row, "Members billed / paid",
                        summary["count_billed"], summary["count_paid"],
                        num_format="0")
    row += 1
    _write_subtotal_row(ws, row, "Retention rate (paid members / billed)",
                        summary["retention_rate"], None,
                        num_format=PCT_FMT)


_MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"]


def _month_name(bill_month: int) -> str:
    if 1 <= bill_month <= 12:
        return _MONTH_NAMES[bill_month]
    return f"BM {bill_month}"
