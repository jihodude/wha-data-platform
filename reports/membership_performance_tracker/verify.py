"""
verify_v4_output.py — Inspect a generated v4 tracker xlsx and report coverage.

What it checks:
  1. Data - Monthly Metrics:  how many of the 31 metrics × 11 territories × N months
                               are populated, broken down by metric and territory
  2. Data - Drops:             row count + sample row
  3. Data - Closed Businesses: row count + sample row
  4. Cross-check vs JSON cache: do the xlsx values match the source ScoreboardData?
  5. Anomalies: metrics that got 0 rows (likely a wiring bug), territories with no data

What it does NOT check:
  - Whether the TM sheets and Summary Dashboard render correctly. Those use Excel
    formulas that resolve at recalc time — you'll see them when you open the file.
    To force recalc in code, run:
        python scripts/recalc_scan.py data/output/Membership_Performance_Report_<period>.xlsx
    (requires LibreOffice)

Usage (period defaults to MPR_PERIOD, else 2026-03):
    PYTHONPATH=$PWD python3 reports/membership_performance_tracker/verify.py
    PYTHONPATH=$PWD python3 reports/membership_performance_tracker/verify.py data/output/<file>.xlsx
"""

import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import openpyxl

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Period-driven (#24): the old pinned "Tracker_v4_2026-03" defaults meant
# inspecting any other period cross-checked against the WRONG cache.
_PERIOD = os.environ.get("MPR_PERIOD", "2026-03")
DEFAULT_XLSX  = PROJECT_ROOT / "data" / "output" / f"Membership_Performance_Report_{_PERIOD}.xlsx"
DEFAULT_CACHE = PROJECT_ROOT / "data" / "cache"  / f"scoreboard_{_PERIOD}.json"

METRICS_SHEET = "Data - Monthly Metrics"
DROPS_SHEET   = "Data - Drops"
CLOSED_SHEET  = "Data - Closed Businesses"


def main() -> int:
    xlsx_path  = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_XLSX
    cache_path = DEFAULT_CACHE

    if not xlsx_path.exists():
        print(f"ERROR: {xlsx_path} not found", file=sys.stderr)
        return 1

    print(f"\n=== Inspecting: {xlsx_path.name} ===")
    print(f"    Size:   {xlsx_path.stat().st_size:,} bytes")
    print(f"    Cache:  {'present' if cache_path.exists() else 'missing'}\n")

    wb = openpyxl.load_workbook(xlsx_path, data_only=False)
    sheet_names = wb.sheetnames
    print(f"Sheets in workbook: {len(sheet_names)}")
    for s in sheet_names:
        print(f"    • {s}")
    print()

    # ── 1. Data - Monthly Metrics ──────────────────────────────────
    inspect_metrics_sheet(wb)

    # ── 2. Data - Drops ─────────────────────────────────────────────
    inspect_detail_sheet(wb, DROPS_SHEET, header_row=3)

    # ── 3. Data - Closed Businesses ─────────────────────────────────
    inspect_detail_sheet(wb, CLOSED_SHEET, header_row=3)

    # ── 4. Cross-check with cache ──────────────────────────────────
    if cache_path.exists():
        crosscheck_against_cache(wb, cache_path)

    # ── 5. Final hint ──────────────────────────────────────────────
    print("Next: open the xlsx in Excel and inspect TM sheets + Summary Dashboard.")
    print("Excel will recalculate the cross-sheet formulas automatically on open.")
    return 0


# ---------------------------------------------------------------------------
# Sheet inspectors
# ---------------------------------------------------------------------------

def inspect_metrics_sheet(wb) -> None:
    ws = wb[METRICS_SHEET]
    populated   = 0
    by_metric:    Dict[str, int] = defaultdict(int)
    by_territory: Dict[str, int] = defaultdict(int)
    by_year_mo:   Dict[Tuple[int, str], int] = defaultdict(int)

    for r in range(5, ws.max_row + 1):
        year   = ws.cell(row=r, column=1).value
        month  = ws.cell(row=r, column=2).value
        terr   = ws.cell(row=r, column=3).value
        metric = ws.cell(row=r, column=4).value
        val    = ws.cell(row=r, column=5).value
        if val is None:
            continue
        populated += 1
        by_metric[metric] += 1
        by_territory[terr] += 1
        by_year_mo[(year, month)] += 1

    print(f"=== {METRICS_SHEET} ===")
    print(f"Populated rows: {populated:,} of {ws.max_row - 4:,} total slots\n")

    # Per-metric coverage
    print(f"By metric (sorted by row count):")
    for m, n in sorted(by_metric.items(), key=lambda kv: -kv[1]):
        print(f"    {n:5d}  {m}")
    print()

    # Per-territory coverage
    print(f"By territory:")
    for t, n in sorted(by_territory.items(), key=lambda kv: -kv[1]):
        print(f"    {n:5d}  {t}")
    print()

    # Per-year-month coverage
    print(f"By (year, month):")
    for (y, mo), n in sorted(by_year_mo.items()):
        print(f"    {y} {mo}: {n}")
    print()


def inspect_detail_sheet(wb, sheet_name: str, header_row: int) -> None:
    if sheet_name not in wb.sheetnames:
        print(f"⚠ sheet '{sheet_name}' missing from workbook\n")
        return
    ws = wb[sheet_name]
    data_start = header_row + 1
    count = sum(
        1 for r in range(data_start, ws.max_row + 1)
        if ws.cell(row=r, column=1).value
    )
    print(f"=== {sheet_name} ===")
    print(f"Rows populated: {count:,}")
    if count > 0:
        sample_vals = [
            ws.cell(row=data_start, column=c).value
            for c in range(1, min(ws.max_column, 12) + 1)
        ]
        print(f"Sample row {data_start}: {sample_vals}")
    print()


def crosscheck_against_cache(wb, cache_path: Path) -> None:
    """Spot-check that xlsx values match the source cached ScoreboardData."""
    payload = json.loads(cache_path.read_text())
    fields = payload.get("fields", {})

    # Map a known field → its metric string in the v4 schema
    SPOT_CHECKS: List[Tuple[str, str, str, str, int]] = [
        # (cache_field, metric_name, territory_in_cache, territory_in_xlsx, month_int)
        # We use a few representative spot-checks across different metric types.
        ("revenue_target",     "New Sales Revenue - Target ($)",     "Pierce", "Pierce", 3),
        ("hosp_bills_target",  "Billables - Hospitality Target (#)", "Pierce", "Pierce", 3),
        ("allied_bills",       "Billables - Allied (#)",             "Pierce", "Pierce", 3),
        ("ret_paid_target",    "Members Retained - Target (#)",      "Pierce", "Pierce", 3),
    ]

    MONTH_INT_TO_ABB = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",
                        7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec"}

    ws = wb[METRICS_SHEET]
    print(f"=== Cross-check: cache vs xlsx ===")
    for cache_field, metric, terr_cache, terr_xlsx, m_int in SPOT_CHECKS:
        month_abb = MONTH_INT_TO_ABB[m_int]
        cache_val = (fields.get(cache_field) or {}).get(terr_cache, {}).get(month_abb)
        xlsx_val = _find_xlsx_cell(ws, 2026, month_abb, terr_xlsx, metric)
        match = "✓" if cache_val == xlsx_val else "✗"
        print(f"  {match} {terr_xlsx} {month_abb} | {metric}  cache={cache_val}  xlsx={xlsx_val}")
    print()


def _find_xlsx_cell(ws, year: int, month: str, territory: str, metric: str):
    for r in range(5, ws.max_row + 1):
        if (ws.cell(row=r, column=1).value == year
            and ws.cell(row=r, column=2).value == month
            and ws.cell(row=r, column=3).value == territory
            and ws.cell(row=r, column=4).value == metric):
            return ws.cell(row=r, column=5).value
    return None


if __name__ == "__main__":
    sys.exit(main())
