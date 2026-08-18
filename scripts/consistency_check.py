"""
consistency_check.py — mechanical cross-checks on the FINAL rendered xlsx
(Q-FINAL B2+B3, 2026-07-16). Part of the gate battery.

Checks (no LibreOffice needed):
  1. CACHE ↔ SHEET: every per-territory current-month value in the cache
     appears verbatim in 'Data - Monthly Metrics' (writer wrote raw values —
     verifiable without formula evaluation).
  2. STORED-ERROR SCAN: any '#REF!/#DIV/0!/#VALUE!/#N/A/#NAME?' cached in the
     file (template-era baked errors surface here).
  3. STRUCTURE: expected sheets present; drops header intact (col M category);
     dashboard month/year match GATE_PERIOD.
NOTE: full formula RECALC verification needs LibreOffice (not installed on
this Mac — flagged). Until then Excel-open is the recalc check.

Usage: GATE_PERIOD=2026-06 PYTHONPATH=$PWD python3 scripts/consistency_check.py
"""
import json
import os
import sys

import openpyxl

PERIOD = os.environ.get("GATE_PERIOD", "2026-06")
M_INT = int(PERIOD.split("-")[1])
ABB = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun", 7: "Jul",
       8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}[M_INT]
YEAR = int(PERIOD.split("-")[0])
XLSX = f"data/output/Membership_Performance_Report_{PERIOD}.xlsx"
CACHE = f"data/cache/scoreboard_{PERIOD}.json"

# cache field → data-sheet metric name (current-month, per-territory)
FIELD_TO_METRIC = {
    # 2026-07-17 gold-plate fix: these were bill_target / bill_non_target /
    # bill_allied — keys that DON'T EXIST in the cache, so billables silently
    # validated ZERO cells while the gate reported "pass". Real cache keys:
    "hosp_bills_target": "Billables - Hospitality Target (#)",
    "hosp_bills_non_target": "Billables - Hospitality Non-Target (#)",
    "allied_bills": "Billables - Allied (#)",
    "revenue_target": "New Sales Revenue - Target ($)",
    "revenue_non_target": "New Sales Revenue - Non-Target ($)",
    "new_members_target": "New Members - Target (#)",
    "new_members_non_target": "New Members - Non-Target (#)",
}
# data-sheet territory labels differ from cache keys (spaces)
TERR_ALIAS = {"EastKing": "East King", "SouthKing": "South King",
              "NorthKing": "North King", "NorthCentral": "NorthCentral"}

ERRS = ("#REF!", "#DIV/0!", "#VALUE!", "#N/A", "#NAME?", "#NULL!", "#NUM!")


def main() -> int:
    F = json.load(open(CACHE))["fields"]
    wb = openpyxl.load_workbook(XLSX, read_only=True)
    fails = []

    # 3. structure
    need = {"Summary Dashboard", "Data - Monthly Metrics", "Data - Drops",
            "Data - Closed Businesses"}
    missing = need - set(wb.sheetnames)
    if missing:
        fails.append(f"missing sheets: {missing}")
    dash = wb["Summary Dashboard"]
    if dash["E4"].value != ABB or dash["B4"].value != YEAR:
        fails.append(f"dashboard selector {dash['E4'].value}/{dash['B4'].value} != {ABB}/{YEAR}")
    if wb["Data - Drops"]["M3"].value != "Drop Category":
        fails.append("drops col M header missing")

    # 1. cache ↔ sheet — filter by YEAR too (#21): once the 2024/2025 backfill
    # lands, same-month rows from two years would collide last-wins otherwise.
    sheet_vals = {}
    for r in wb["Data - Monthly Metrics"].iter_rows(min_row=2, values_only=True):
        yr, mo, terr, metric, val = r[0], r[1], r[2], r[3], r[4]
        if mo == ABB and yr == YEAR and metric in FIELD_TO_METRIC.values():
            sheet_vals[(str(terr), metric)] = val
    # GOLD-PLATE GUARD (2026-07-17): a mistyped cache field silently skips all of
    # its cells (the bug this fixes). Fail LOUDLY if any configured field is absent
    # from the cache, so a gate can never again "pass" while validating nothing.
    for field in FIELD_TO_METRIC:
        if field not in F:
            fails.append(f"MISCONFIGURED gate: cache field '{field}' not found — "
                         f"it was validating ZERO cells")

    # HAND CORRECTIONS ARE PART OF THE SHEET (8/14). The cache deliberately
    # holds the program's own numbers; the workbook carries the corrections on
    # top. Comparing them raw would report every corrected cell as a defect on
    # every run — so the cache side is adjusted the same way the report is.
    from reports.membership_performance_tracker.logic import adjustments as _adj
    _corr = _adj.by_cell(_adj.for_build(
        _adj.load_fy(_adj.fy_start_of(PERIOD)), PERIOD))
    if _corr:
        print(f"  · {len(_corr)} cell(s) carry a hand correction; the cache "
              f"side is adjusted to match the report")

    checked = 0
    for field, metric in FIELD_TO_METRIC.items():
        data = F.get(field) or {}
        for terr, months in data.items():
            want = (months or {}).get(ABB)
            if want is None:
                continue
            want = float(want) + _corr.get((field, terr, ABB), 0.0)
            label = TERR_ALIAS.get(terr, terr)
            got = sheet_vals.get((label, metric), sheet_vals.get((terr, metric)))
            checked += 1
            if got is None or abs(float(got) - float(want)) > 0.01:
                fails.append(f"{metric} {terr} {ABB}: cache {want} vs sheet {got}")

    # 2. goals-populated sanity (2026-07-17): the engine admin-inputs path bug
    #    shipped ALL-BLANK goals silently (loaded null-goals YAML). Fail if a core
    #    goal metric has ZERO populated cells — the exact symptom, now gated.
    goal_pop = sum(
        1 for r in wb["Data - Monthly Metrics"].iter_rows(min_row=2, values_only=True)
        if r[3] and "Goal" in str(r[3]) and r[4] not in (None, "")
    )
    if goal_pop == 0:
        fails.append("ALL goal cells are BLANK — admin_inputs.xlsx did not load "
                     "(engine path bug / missing file?). Report shipped without goals.")

    # 3. stored-error scan (cheap full sweep) — TWO passes (#21): the default
    # load iterates formula STRINGS (only literal error text is visible); the
    # data_only pass reads Excel's CACHED RESULTS, catching a formula whose
    # cached value is #REF!/#DIV/0!. (If the file was never opened in Excel the
    # cached values are None — recalc_scan/LibreOffice remains the true recalc.)
    err_count = 0
    wb_vals = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    for book, label in ((wb, "literal"), (wb_vals, "cached-result")):
        for ws in book.worksheets:
            for row in ws.iter_rows(values_only=True):
                for v in row:
                    if isinstance(v, str) and v in ERRS:
                        err_count += 1
                        if err_count <= 5:
                            fails.append(f"stored error {v} ({label}) in '{ws.title}'")

    print(f"[consistency] {PERIOD}: {checked} cache↔sheet cells checked, "
          f"{err_count} stored errors, {len(fails)} failure(s)")
    for f in fails[:20]:
        print("  FAIL:", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
