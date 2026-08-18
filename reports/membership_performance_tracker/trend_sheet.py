"""
trend_sheet.py — builds the "Monthly Trends — All TMs" page (exec feedback #3).

A new sheet inserted directly after "Summary Dashboard" and before the first TM
sheet. It shows every metric SUMMED across all territories (statewide) for every
fiscal month, so executives can read month-over-month trends in number format.
Shannon's ask [9:28]: "a year-over-year summary for all of the TMs … the TMs add
up to the summary dashboard, but this is just per month, not every month."

Design — mirrors the formula-driven Summary Dashboard:
  • The page is PURE Excel formulas reading from "Data - Monthly Metrics".
    Nothing here is written by the Python writer — Excel computes it live, the
    same way the Summary Dashboard and TM sheets do. The writer only ever
    populates the data sheets, so this page stays correct on every run.
  • Additive metrics (count / currency) → statewide SUMIFS per month. The
    SUMIFS deliberately OMITS the territory criterion, so each cell sums across
    every TM for that (Year, Month, Metric).
  • Percentage metrics are NOT summed (percentages aren't additive). They are
    recomputed as statewide ratios from the additive component rows already on
    the page — clearly separated in a "Statewide Rates (computed)" section and
    fully auditable (the numerator/denominator rows sit right above).

Year selector: cell B4 (defaults to the latest fiscal year). Change it to roll
the whole page to a different year — exactly like the Summary Dashboard.

The build is idempotent: re-running drops and recreates the sheet, so it can be
baked into the template once AND/or re-applied by the writer without duplicating.

Usage (bake into the template, one-off):
    import openpyxl
    from reports.membership_performance_tracker.trend_sheet import build_monthly_trend_sheet
    wb = openpyxl.load_workbook("…/template.xlsx")
    build_monthly_trend_sheet(wb)
    wb.save("…/template.xlsx")
"""

from typing import Any, Dict, List, Optional, Tuple

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import column_index_from_string, get_column_letter


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TREND_SHEET_NAME = "Monthly Trends — All TMs"
DATA_SHEET = "Data - Monthly Metrics"
REF_METRICS_SHEET = "Ref - Metrics"
SUMMARY_SHEET = "Summary Dashboard"

# WHA fiscal year runs Oct → Sep.
MONTHS_FISCAL = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
                 "Apr", "May", "Jun", "Jul", "Aug", "Sep"]

# Layout
YEAR_CELL = "$B$4"            # the page's own year selector
HEADER_ROW = 6               # column headers (Metric | Oct … Sep | Season Total)
DATA_START_ROW = 7           # first metric row
FIRST_MONTH_COL = 2          # column B
SEASON_TOTAL_COL = 2 + len(MONTHS_FISCAL)   # column N (after the 12 months)

# Category display order + friendly section titles.
CATEGORY_ORDER = ["goal", "sales", "billables", "retention",
                  "drops", "penetration"]   # "closed" removed 8/6 (Jiho:
                  # closed businesses off the face everywhere — the 7/27
                  # ruling's last remnant; her own reports dropped the label)
CATEGORY_TITLES = {
    "goal":        "Goals",
    "sales":       "New Sales",
    "billables":   "Billables",
    "retention":   "Retention",
    "drops":       "Drops",
    "closed":      "Closed Businesses",
    "penetration": "Penetration (counts)",
}

# Styling
_TITLE_FONT    = Font(bold=True, size=14)
_SUBTITLE_FONT = Font(italic=True, size=10, color="666666")
_HEADER_FONT   = Font(bold=True, color="FFFFFF")
_HEADER_FILL   = PatternFill("solid", fgColor="305496")
_SECTION_FONT  = Font(bold=True, color="1F3864")
_SECTION_FILL  = PatternFill("solid", fgColor="D9E1F2")
_RATE_HDR_FONT = Font(bold=True, color="1F3864")
_LABEL_FONT    = Font(bold=False)
_CENTER        = Alignment(horizontal="center")

# Number formats by metric type.
_FMT = {
    "currency": "#,##0",
    "count":    "#,##0",
    "pct":      "0.0%",
}


# ---------------------------------------------------------------------------
# Formula builders (pure — the deterministic core under test)
# ---------------------------------------------------------------------------

def _q(col: str) -> str:
    """Full-column reference into the data sheet, e.g. 'Data - Monthly Metrics'!E:E."""
    return f"'{DATA_SHEET}'!{col}:{col}"


def statewide_sumifs(month: str, metric: str, year_cell: str = YEAR_CELL) -> str:
    """
    Statewide SUMIFS for one (month, metric): sums Value across ALL territories.

    Note the deliberate ABSENCE of a Territory (C:C) criterion — that is what
    makes this a statewide total rather than a per-TM figure.

    Oct/Nov/Dec belong to the fiscal-year START calendar year (year_cell - 1);
    Data-Monthly-Metrics stores them under that prior year, and the TM sheets
    already query $B$4-1 for these columns. Jan-Sep use year_cell as-is.
    """
    yc = f"{year_cell}-1" if month in ("Oct", "Nov", "Dec") else year_cell
    return (
        f"=SUMIFS({_q('E')},"
        f"{_q('A')},{yc},"
        f"{_q('B')},\"{month}\","
        f"{_q('D')},\"{metric}\")"
    )


# A STOCK IS NEVER SUMMED (ruled 8/6; enforced on the TM sheets, missed
# here until the overnight review): billables / locations / penetration
# counts are photographs, so the season cell shows the LATEST photo — not
# twelve monthly rosters added together (a July build read ~2x the roster
# and grew every month).
PHOTO_CATEGORIES = {"billables", "penetration"}


def _season_formula(row: int, is_photo: bool) -> str:
    """Season cell: latest photo for stocks, sum for flows."""
    if is_photo:
        return (f"=IFERROR(LOOKUP(2,1/(B{row}:M{row}<>0),B{row}:M{row}),0)")
    return f"=SUM(B{row}:M{row})"


def _ratio_formula(col_letter: str, num_rows: List[int], den_rows: List[int]) -> str:
    """
    Guarded ratio =IF(Σden=0,0,Σnum/Σden) referencing cells in the given column.

    num_rows / den_rows are sheet row numbers whose cells in `col_letter` are the
    additive components. Used for statewide rates (retention %, penetration %).
    """
    num = "+".join(f"{col_letter}{r}" for r in num_rows)
    den = "+".join(f"{col_letter}{r}" for r in den_rows)
    return f"=IF(({den})=0,0,({num})/({den}))"


# ---------------------------------------------------------------------------
# Ref - Metrics reader
# ---------------------------------------------------------------------------

def _read_metric_catalog(wb) -> List[Tuple[str, str, str]]:
    """
    Read (name, type, category) for every metric from the Ref - Metrics sheet.

    Returns them in the sheet's own order. Header is at row 3; data from row 4.
    """
    ws = wb[REF_METRICS_SHEET]
    out: List[Tuple[str, str, str]] = []
    for r in range(4, ws.max_row + 1):
        name = ws.cell(row=r, column=1).value
        mtype = ws.cell(row=r, column=2).value
        cat = ws.cell(row=r, column=3).value
        if name is None:
            continue
        out.append((str(name), str(mtype or ""), str(cat or "")))
    return out


# ---------------------------------------------------------------------------
# Sheet builder
# ---------------------------------------------------------------------------

def _default_year(wb) -> int:
    """Pick a sensible default year: mirror the Summary Dashboard selector if set,
    else derive from MPR_PERIOD (#24 — was a dead-reckoned hardcoded 2026).

    THE MIRROR IS A CONVERSION, NOT A COPY (fixed 8/11). This page's B4 is the
    fiscal-year END year — that is what makes `$B$4-1` right for Oct/Nov/Dec
    above. The dashboard's B4 is a different quantity: the CALENDAR year of the
    month sitting in its E4. They are equal for Jan-Sep and differ by one for
    Oct-Dec, so copying the cell rendered the FIRST October build as the whole
    of the PRIOR fiscal year — and because the data sheet keeps history, that
    came out as real, fully-populated last-year numbers under this year's
    heading, then healed itself in January. Same off-by-one in the period
    fallback, which read the year and ignored the month.
    """
    try:
        v = wb[SUMMARY_SHEET]["B4"].value
        if isinstance(v, (int, float)):
            month = str(wb[SUMMARY_SHEET]["E4"].value or "").strip()[:3].title()
            return int(v) + (1 if month in ("Oct", "Nov", "Dec") else 0)
    except Exception:
        pass
    import os
    year, _, month_part = os.environ.get("MPR_PERIOD", "2026-03").partition("-")
    fy_rolls = month_part[:2].isdigit() and int(month_part[:2]) >= 10
    return int(year) + (1 if fy_rolls else 0)


def build_monthly_trend_sheet(wb, year_default: Optional[int] = None) -> Dict[str, Any]:
    """
    Create (or rebuild) the "Monthly Trends — All TMs" sheet right after the
    Summary Dashboard. Returns metadata describing the layout (for tests/wiring).

    Idempotent: if the sheet already exists it is removed and recreated, so this
    can be baked into the template once and/or re-applied by the writer.

    Returns:
        {
          "sheet_name":  str,
          "header_row":  int,
          "month_cols":  {month: col_index},
          "metric_rows": {metric_name: row_index},   # additive metrics only
          "rate_rows":   {rate_label: row_index},     # computed pct rows
        }
    """
    if year_default is None:
        year_default = _default_year(wb)

    # --- idempotent: drop any existing copy ---
    if TREND_SHEET_NAME in wb.sheetnames:
        del wb[TREND_SHEET_NAME]

    ws = wb.create_sheet(TREND_SHEET_NAME)

    # Position it immediately after Summary Dashboard (else right after README/first sheet).
    insert_after = SUMMARY_SHEET if SUMMARY_SHEET in wb.sheetnames else wb.sheetnames[0]
    target_index = wb.sheetnames.index(insert_after) + 1
    current_index = wb.sheetnames.index(TREND_SHEET_NAME)
    # move_sheet offset = desired - current
    wb.move_sheet(TREND_SHEET_NAME, offset=target_index - current_index)

    # --- header block ---
    ws["A1"] = "Monthly Trends — All TMs (Statewide)"
    ws["A1"].font = _TITLE_FONT
    ws["A2"] = ("Every metric summed across all territories, month over month. "
                "Change the Year to roll the whole page. Percentages are computed "
                "statewide ratios, not sums. "
                "Billables and Penetration are PHOTOGRAPHS: each month shows that "
                "month's captured roster, and the Season cell shows the latest "
                "photo rather than a sum.")
    ws["A2"].font = _SUBTITLE_FONT
    ws["A4"] = "Year:"
    ws["A4"].font = Font(bold=True)
    ws["B4"] = year_default
    ws["B4"].font = Font(bold=True)
    ws["D4"] = "← change Year to update every figure below"
    ws["D4"].font = _SUBTITLE_FONT

    # --- column header row ---
    month_cols: Dict[str, int] = {}
    ws.cell(row=HEADER_ROW, column=1, value="Metric")
    for i, mon in enumerate(MONTHS_FISCAL):
        col = FIRST_MONTH_COL + i
        month_cols[mon] = col
        c = ws.cell(row=HEADER_ROW, column=col, value=mon)
        c.font = _HEADER_FONT
        c.fill = _HEADER_FILL
        c.alignment = _CENTER
    ws.cell(row=HEADER_ROW, column=1).font = _HEADER_FONT
    ws.cell(row=HEADER_ROW, column=1).fill = _HEADER_FILL
    season = ws.cell(row=HEADER_ROW, column=SEASON_TOTAL_COL, value="Season Total")
    season.font = _HEADER_FONT
    season.fill = _HEADER_FILL
    season.alignment = _CENTER

    # --- catalog, split additive vs percentage ---
    catalog = _read_metric_catalog(wb)
    by_category: Dict[str, List[Tuple[str, str]]] = {}
    for name, mtype, cat in catalog:
        if mtype == "pct":
            continue  # percentages handled in the computed-rates section
        by_category.setdefault(cat, []).append((name, mtype))

    metric_rows: Dict[str, int] = {}
    rate_rows: Dict[str, int] = {}
    rate_dens: Dict[str, List[int]] = {}
    row = DATA_START_ROW

    def _add_sum(label: str, part_metrics: List[str], fmt: str,
                 is_photo: bool = False) -> None:
        """A derived SUM row (e.g. Combined T+NT) referencing metric rows above."""
        nonlocal row
        if any(m not in metric_rows for m in part_metrics):
            return
        parts = [metric_rows[m] for m in part_metrics]
        ws.cell(row=row, column=1, value=label).font = _LABEL_FONT
        for mon in MONTHS_FISCAL:
            col = month_cols[mon]
            cl = get_column_letter(col)
            cell = ws.cell(row=row, column=col,
                           value="=" + "+".join(f"{cl}{r}" for r in parts))
            cell.number_format = _FMT.get(fmt, "#,##0")
        tot = ws.cell(row=row, column=SEASON_TOTAL_COL,
                      value=_season_formula(row, is_photo))
        tot.number_format = _FMT.get(fmt, "#,##0")
        rate_rows[label] = row
        row += 1

    def _add_rate(label: str, num_metrics: List[str], den_metrics: List[str]) -> None:
        nonlocal row
        # Skip gracefully if a component metric is missing from the catalog.
        if any(m not in metric_rows for m in num_metrics + den_metrics):
            return
        num_rows = [metric_rows[m] for m in num_metrics]
        den_rows = [metric_rows[m] for m in den_metrics]
        ws.cell(row=row, column=1, value=label).font = _LABEL_FONT
        for mon in MONTHS_FISCAL:
            col = month_cols[mon]
            cl = get_column_letter(col)
            cell = ws.cell(row=row, column=col,
                           value=_ratio_formula(cl, num_rows, den_rows))
            cell.number_format = _FMT["pct"]
        sl = get_column_letter(SEASON_TOTAL_COL)
        st = ws.cell(row=row, column=SEASON_TOTAL_COL,
                     value=_ratio_formula(sl, num_rows, den_rows))
        st.number_format = _FMT["pct"]
        rate_rows[label] = row
        rate_dens[label] = den_rows
        row += 1

    def _derived_for(cat: str) -> None:
        """Shannon's meeting notes (7/20): the computed rows live INSIDE their
        sections — sums of both + performance-to-goal next to sales, retention
        % (members AND dollars) next to retention, penetration % next to the
        counts — never in a separate block at the bottom."""
        if cat == "sales":
            _add_sum("New Sales Revenue — Combined ($)",
                     ["New Sales Revenue - Target ($)",
                      "New Sales Revenue - Non-Target ($)"], "currency")
            _add_rate("% to Revenue Goal",
                      ["New Sales Revenue - Target ($)",
                       "New Sales Revenue - Non-Target ($)"],
                      ["Goal - New Sales Revenue ($)"])
            _add_sum("New Members — Combined (#)",
                     ["New Members - Target (#)",
                      "New Members - Non-Target (#)"], "count")
            _add_rate("% to New Member Goal",
                      ["New Members - Target (#)",
                       "New Members - Non-Target (#)"],
                      ["Goal - New Members (#)"])
        elif cat == "billables":
            _add_sum("Billables — Total incl. Allied (#)",
                     ["Billables - Hospitality Target (#)",
                      "Billables - Hospitality Non-Target (#)",
                      "Billables - Allied (#)"], "count", is_photo=True)
        elif cat == "retention":
            _add_rate("Retention % — Target (#)",
                      ["Members Retained - Target (#)"],
                      ["Members Up for Renewal - Target (#)"])
            _add_rate("Retention % — Target ($)",
                      ["Revenue Retained - Target ($)"],
                      ["Revenue Up for Renewal - Target ($)"])
            _add_rate("Retention % — T + NT (#)",
                      ["Members Retained - Target (#)",
                       "Members Retained - Non-Target (#)"],
                      ["Members Up for Renewal - Target (#)",
                       "Members Up for Renewal - Non-Target (#)"])
        elif cat == "penetration":
            _add_rate("Penetration - Restaurant %",
                      ["Target Members - Restaurant (#)"],
                      ["Total Target Locations - Restaurant (#)"])
            _add_rate("Penetration - Lodging %",
                      ["Target Members - Lodging (#)"],
                      ["Total Target Locations - Lodging (#)"])
            _add_rate("Penetration - Combined %",
                      ["Target Members - Restaurant (#)",
                       "Target Members - Lodging (#)"],
                      ["Total Target Locations - Restaurant (#)",
                       "Total Target Locations - Lodging (#)"])

    for cat in CATEGORY_ORDER:
        metrics = by_category.get(cat)
        if not metrics:
            continue
        # section header
        sec = ws.cell(row=row, column=1, value=CATEGORY_TITLES.get(cat, cat.title()))
        sec.font = _SECTION_FONT
        for col in range(1, SEASON_TOTAL_COL + 1):
            ws.cell(row=row, column=col).fill = _SECTION_FILL
        row += 1

        for name, mtype in metrics:
            ws.cell(row=row, column=1, value=name).font = _LABEL_FONT
            for mon in MONTHS_FISCAL:
                col = month_cols[mon]
                cell = ws.cell(row=row, column=col, value=statewide_sumifs(mon, name))
                cell.number_format = _FMT.get(mtype, "#,##0")
            tot = ws.cell(row=row, column=SEASON_TOTAL_COL,
                          value=_season_formula(row, cat in PHOTO_CATEGORIES))
            tot.number_format = _FMT.get(mtype, "#,##0")
            metric_rows[name] = row
            row += 1

        _derived_for(cat)

    # --- goal colors (Jiho 8/10): retention + penetration rates against the
    # admin-input goals, same green/yellow/red language as the TM sheets.
    # Dynamic: the goal is AVERAGEIFS over the data sheet (all territories),
    # COUNTIFS-guarded so months with no goal entered stay uncolored, and the
    # month/year criteria ride the header row + Year selector — the colors
    # follow admin-input changes and the year switch on their own.
    from openpyxl.formatting.rule import Rule
    from openpyxl.styles.differential import DifferentialStyle

    _WATCH = 0.05        # amber band below goal, mirrors the TM sheets
    _dxf = {
        "green": DifferentialStyle(font=Font(color="006100"),
                                   fill=PatternFill(bgColor="C6EFCE")),
        "yellow": DifferentialStyle(font=Font(color="9C6500"),
                                    fill=PatternFill(bgColor="FFEB9C")),
        "red": DifferentialStyle(font=Font(color="9C0006"),
                                 fill=PatternFill(bgColor="FFC7CE")),
    }

    def _goal_crit(mon_hdr: str, metric: str, yc: str) -> str:
        return (f"{_q('A')},{yc},{_q('B')},{mon_hdr},"
                f"{_q('D')},\"{metric}\"")

    def _goal_cf(row: int, goal_metric: Optional[str],
                 den_rows: List[int]) -> None:
        """3-rule CF on the 12 month cells of `row`. goal_metric=None means
        the bar is a fixed 100% (the % to goal rows). Months whose
        denominator is empty stay UNCOLORED — a 0% with no data underneath
        is absence, not failure (8/10, penetration photo months)."""
        # two segments: Oct-Dec query Year-1, Jan-Sep query Year (mirrors
        # statewide_sumifs); relative month-header refs walk each segment
        oct_col = get_column_letter(month_cols["Oct"])
        dec_col = get_column_letter(month_cols["Dec"])
        jan_col = get_column_letter(month_cols["Jan"])
        sep_col = get_column_letter(month_cols["Sep"])
        # ONE RULE PER CELL (8/12): SharePoint's Excel Online evaluates only
        # the ANCHOR of a ranged expression rule, so on a B:D + E:M layout
        # exactly Oct and Jan colored and Dec at 97.2% vs a 92% goal stayed
        # bare (Jiho's screenshot). A single-cell rule has nothing to shift,
        # so desktop and Online agree. scripts/fix_pct_cf_per_cell.py applied
        # the same surgery to the static template sheets.
        for c1, c2, yc in ((oct_col, dec_col, f"{YEAR_CELL}-1"),
                           (jan_col, sep_col, YEAR_CELL)):
            for ci in range(column_index_from_string(c1),
                            column_index_from_string(c2) + 1):
                cl = get_column_letter(ci)
                cell = f"{cl}{row}"
                hdr = f"{cl}${HEADER_ROW}"
                if goal_metric is None:
                    goal, present = "1", "TRUE"
                else:
                    crit = _goal_crit(hdr, goal_metric, yc)
                    goal = f"AVERAGEIFS({_q('E')},{crit})"
                    present = f"COUNTIFS({crit})>0"
                den = "+".join(f"{cl}{r}" for r in den_rows)
                base = f"ISNUMBER({cell}),{present},({den})>0"
                ws.conditional_formatting.add(cell, Rule(
                    type="expression", stopIfTrue=True, dxf=_dxf["green"],
                    formula=[f"AND({base},{cell}>={goal})"]))
                ws.conditional_formatting.add(cell, Rule(
                    type="expression", stopIfTrue=True, dxf=_dxf["yellow"],
                    formula=[f"AND({base},{cell}>={goal}-{_WATCH})"]))
                ws.conditional_formatting.add(cell, Rule(
                    type="expression", stopIfTrue=True, dxf=_dxf["red"],
                    formula=[f"AND({base})"]))

    for label, goal_metric in (
            ("Retention % — Target (#)", "Goal - Retention %"),
            ("Retention % — Target ($)", "Goal - Retention %"),
            ("Retention % — T + NT (#)", "Goal - Retention %"),
            ("Penetration - Restaurant %", "Goal - Penetration %"),
            ("Penetration - Lodging %", "Goal - Penetration %"),
            ("Penetration - Combined %", "Goal - Penetration %"),
            ("% to Revenue Goal", None),
            ("% to New Member Goal", None)):
        if label in rate_rows:
            _goal_cf(rate_rows[label], goal_metric, rate_dens.get(label) or [])

    # --- light formatting: widths + freeze panes ---
    ws.column_dimensions["A"].width = 38
    for i in range(len(MONTHS_FISCAL)):
        ws.column_dimensions[get_column_letter(FIRST_MONTH_COL + i)].width = 10
    ws.column_dimensions[get_column_letter(SEASON_TOTAL_COL)].width = 13
    ws.freeze_panes = ws.cell(row=DATA_START_ROW, column=FIRST_MONTH_COL)

    return {
        "sheet_name":  TREND_SHEET_NAME,
        "header_row":  HEADER_ROW,
        "month_cols":  month_cols,
        "metric_rows": metric_rows,
        "rate_rows":   rate_rows,
    }
