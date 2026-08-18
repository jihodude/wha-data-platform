"""
audit_v4_output.py — Per-cell explainability sweep of the v4 tracker output.

For every (Year, Month, Territory, Metric) cell that COULD have data, classify:
  EXPECTED     — has a value and it's plausible
  EMPTY-OK     — empty for a known reason (out of scope, admin not set, etc.)
  EMPTY-WHY?   — empty without a known reason  → flag
  ODD-VALUE    — populated but the value looks suspicious           → flag

This is the final sweep before declaring the pipeline trustworthy.

Output:
  • Section per metric with expected vs actual coverage
  • List of every flagged cell with classification reason
  • Summary scorecard

Usage:
    python scripts/audit_v4_output.py
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_XLSX = PROJECT_ROOT / "data" / "output" / "Tracker_v4_2026-03.xlsx"
DEFAULT_CACHE = PROJECT_ROOT / "data" / "cache"  / "scoreboard_2026-03.json"

# Current run scope: Oct 2025 → Mar 2026, 11 territories (WHA FY runs Oct 1 → Sep 30)
ALL_TERRITORIES = [
    "East King", "South King", "North King", "Pierce", "Snohomish",
    "Spokane/NE", "Southwest", "TKP", "Southeast", "NorthCentral", "Majors/NRA",
]

IN_SCOPE: List[Tuple[int, str]] = [
    (2025, "Oct"), (2025, "Nov"), (2025, "Dec"),
    (2026, "Jan"), (2026, "Feb"), (2026, "Mar"),
]

# Territories excluded from retention queries (Majors/NRA pays nationally,
# no standard dues billing)
NO_RETENTION = {"Majors/NRA"}

# Penetration breakdown excludes Majors/NRA (NRA tracked separately)
NO_PENETRATION = {"Majors/NRA"}

# Billables: post-ITD snapshot only for current_month
BILLABLES_MONTH_ONLY = (2026, "Mar")

# Revenue: under WHA FY (Oct → Sep) no month is treated as prior-FY carry-over.
REVENUE_SKIP_MONTHS: set = set()

# Reasonable bound ranges for sanity checks
PLAUSIBLE = {
    "billables_hospitality":   (1, 800),
    "billables_allied":        (0, 60),
    "new_members_per_month":   (0, 50),
    "revenue_per_month_dollars": (0, 50_000),
    "ret_count":               (0, 100),
    "ret_revenue_dollars":     (0, 100_000),
    "drops_count":             (0, 50),
    "drops_revenue":           (-10_000, 50_000),  # can be negative if credits
    "closed_count":            (0, 10),
    "pen_count":               (0, 1500),
    "pen_pct":                 (0.0, 1.0),
    "goal_revenue":            (0, 10_000),
    "goal_retention":          (0.0, 1.0),
}


# Per-metric: (kind, expected scope filter, plausible range key)
#   scope filter is a fn (year, month, territory) -> bool meaning "in scope"
METRIC_SPEC: Dict[str, Tuple[str, callable, str]] = {
    "Goal - New Sales Revenue ($)":            ("admin",  lambda y,m,t: True,                       "goal_revenue"),
    "Goal - New Members (#)":                  ("admin",  lambda y,m,t: True,                       "new_members_per_month"),
    "Goal - Retention %":                      ("admin",  lambda y,m,t: t not in NO_RETENTION,      "goal_retention"),

    "New Sales Revenue - Target ($)":          ("slx",    lambda y,m,t: (y,m) not in REVENUE_SKIP_MONTHS, "revenue_per_month_dollars"),
    "New Sales Revenue - Non-Target ($)":      ("slx",    lambda y,m,t: (y,m) not in REVENUE_SKIP_MONTHS, "revenue_per_month_dollars"),
    "New Members - Target (#)":                ("slx",    lambda y,m,t: True,                       "new_members_per_month"),
    "New Members - Non-Target (#)":            ("slx",    lambda y,m,t: True,                       "new_members_per_month"),

    "Billables - Hospitality Target (#)":      ("slx",    lambda y,m,t: (y,m) == BILLABLES_MONTH_ONLY, "billables_hospitality"),
    "Billables - Hospitality Non-Target (#)":  ("slx",    lambda y,m,t: (y,m) == BILLABLES_MONTH_ONLY, "billables_hospitality"),
    "Billables - Allied (#)":                  ("slx",    lambda y,m,t: (y,m) == BILLABLES_MONTH_ONLY, "billables_allied"),

    "Members Up for Renewal - Target (#)":     ("slx",    lambda y,m,t: t not in NO_RETENTION, "ret_count"),
    "Members Retained - Target (#)":           ("slx",    lambda y,m,t: t not in NO_RETENTION, "ret_count"),
    "Revenue Up for Renewal - Target ($)":     ("slx",    lambda y,m,t: t not in NO_RETENTION, "ret_revenue_dollars"),
    "Revenue Retained - Target ($)":           ("slx",    lambda y,m,t: t not in NO_RETENTION, "ret_revenue_dollars"),
    "Members Up for Renewal - Non-Target (#)": ("slx",    lambda y,m,t: t not in NO_RETENTION, "ret_count"),
    "Members Retained - Non-Target (#)":       ("slx",    lambda y,m,t: t not in NO_RETENTION, "ret_count"),
    "Revenue Up for Renewal - Non-Target ($)": ("slx",    lambda y,m,t: t not in NO_RETENTION, "ret_revenue_dollars"),
    "Revenue Retained - Non-Target ($)":       ("slx",    lambda y,m,t: t not in NO_RETENTION, "ret_revenue_dollars"),

    "Drops - Target (#)":                      ("derived", lambda y,m,t: True, "drops_count"),
    "Drops - Non-Target (#)":                  ("derived", lambda y,m,t: True, "drops_count"),
    "Dropped Revenue - Target ($)":            ("derived", lambda y,m,t: True, "drops_revenue"),
    "Dropped Revenue - Non-Target ($)":        ("derived", lambda y,m,t: True, "drops_revenue"),
    "Closed Businesses - Target (#)":          ("derived", lambda y,m,t: True, "closed_count"),
    "Closed Businesses - Non-Target (#)":      ("derived", lambda y,m,t: True, "closed_count"),

    "Total Target Locations - Restaurant (#)": ("admin",  lambda y,m,t: t not in NO_PENETRATION, "pen_count"),
    "Total Target Locations - Lodging (#)":    ("admin",  lambda y,m,t: t not in NO_PENETRATION, "pen_count"),
    "Target Members - Restaurant (#)":         ("admin",  lambda y,m,t: t not in NO_PENETRATION, "pen_count"),
    "Target Members - Lodging (#)":            ("admin",  lambda y,m,t: t not in NO_PENETRATION, "pen_count"),
    "Penetration - Restaurant %":              ("derived",lambda y,m,t: t not in NO_PENETRATION, "pen_pct"),
    "Penetration - Lodging %":                 ("derived",lambda y,m,t: t not in NO_PENETRATION, "pen_pct"),
    "Penetration - Combined %":                ("slx",    lambda y,m,t: t not in NO_PENETRATION, "pen_pct"),
}


def main() -> int:
    xlsx_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_XLSX
    if not xlsx_path.exists():
        print(f"ERROR: {xlsx_path} not found", file=sys.stderr)
        return 1

    wb = openpyxl.load_workbook(xlsx_path, data_only=False)
    ws = wb["Data - Monthly Metrics"]
    values = read_values(ws)

    print(f"\n=== Auditing: {xlsx_path.name} ===\n")

    sweep_results: List[Dict] = []

    for metric, (kind, scope_fn, bound_key) in METRIC_SPEC.items():
        cell_results = audit_metric(values, metric, scope_fn, bound_key)
        sweep_results.append({"metric": metric, "kind": kind, "cells": cell_results})

    # Per-metric summary
    print(f"{'Metric':<42}  Expect  Actual  Flag")
    print("-" * 72)
    flagged_count = 0
    for entry in sweep_results:
        cells = entry["cells"]
        expect = sum(1 for c in cells if c["status"] != "OUT-OF-SCOPE")
        actual = sum(1 for c in cells if c["status"] == "EXPECTED")
        flagged = [c for c in cells if c["status"] in ("EMPTY-WHY?", "ODD-VALUE")]
        flagged_count += len(flagged)
        flag_str = f"⚠ {len(flagged)}" if flagged else ""
        print(f"{entry['metric']:<42}  {expect:>6}  {actual:>6}  {flag_str}")

    # Detailed flag list
    if flagged_count > 0:
        print(f"\n=== {flagged_count} flagged cells ===\n")
        for entry in sweep_results:
            flagged = [c for c in entry["cells"] if c["status"] in ("EMPTY-WHY?", "ODD-VALUE")]
            if not flagged:
                continue
            print(f"\n{entry['metric']}:")
            for c in flagged[:20]:  # cap per metric
                print(f"  [{c['status']}] {c['year']} {c['month']} {c['territory']}  value={c['value']}  reason={c['reason']}")
            if len(flagged) > 20:
                print(f"  ... and {len(flagged) - 20} more")
    else:
        print("\n✓ No anomalies flagged.")

    return 0


# ---------------------------------------------------------------------------
# Worker functions
# ---------------------------------------------------------------------------

def read_values(ws) -> Dict[Tuple[int, str, str, str], Any]:
    out: Dict[Tuple[int, str, str, str], Any] = {}
    for r in range(5, ws.max_row + 1):
        y = ws.cell(row=r, column=1).value
        m = ws.cell(row=r, column=2).value
        t = ws.cell(row=r, column=3).value
        metric = ws.cell(row=r, column=4).value
        v = ws.cell(row=r, column=5).value
        if metric and y and m and t:
            out[(y, m, t, metric)] = v
    return out


def audit_metric(values, metric, scope_fn, bound_key) -> List[Dict]:
    results = []
    lo, hi = PLAUSIBLE[bound_key]
    for year, month in IN_SCOPE:
        for terr in ALL_TERRITORIES:
            in_scope = scope_fn(year, month, terr)
            v = values.get((year, month, terr, metric))

            if not in_scope:
                status = "OUT-OF-SCOPE"
                reason = "scope excluded"
            elif v is None:
                status, reason = classify_empty(metric, year, month, terr)
            else:
                status, reason = classify_value(v, lo, hi, metric, terr)

            results.append({
                "year": year, "month": month, "territory": terr,
                "metric": metric, "value": v, "status": status, "reason": reason,
            })
    return results


def classify_empty(metric, year, month, territory) -> Tuple[str, str]:
    """Decide why an empty cell is empty."""
    # Goals admin-input rule: Goal - New Members is intentionally null (admin opt-in)
    if metric == "Goal - New Members (#)":
        return "EMPTY-OK", "admin has not set member goals (default null)"
    if metric == "Goal - New Sales Revenue ($)":
        return "EMPTY-WHY?", f"goals.yaml has no value for {territory} {month}"

    # Drops/closed: zero rows for a (territory, month) means no drops/closures that month
    if metric.startswith("Drops") or metric.startswith("Dropped Revenue"):
        return "EMPTY-OK", f"no {metric.split(' -')[0].lower()} found in drops_detail"
    if metric.startswith("Closed Businesses"):
        return "EMPTY-OK", "no closures in this (territory, month)"

    # Revenue: 0 from SLX could be legitimately $0 sales — but our query writes
    # something even for $0 (mapper skips). If value is None it means
    # `revenue_for_period_by_target` returned the territory's row as zeros.
    if metric.startswith("New Sales Revenue"):
        return "EMPTY-WHY?", "engine should have written 0.0 — unexpected None"

    # New members: similar
    if metric.startswith("New Members"):
        return "EMPTY-WHY?", "engine should have written a count (0 or more)"

    # Billables: only current_month
    if metric.startswith("Billables"):
        return "EMPTY-WHY?", "billables expected for current month only"

    # Retention: paid/billed numbers
    if "Renewal" in metric or "Retained" in metric:
        return "EMPTY-OK", "no dues billed this month for this territory (member's billing month differs)"

    return "EMPTY-WHY?", "unclassified"


def classify_value(v, lo, hi, metric, territory) -> Tuple[str, str]:
    """Check if a populated value is plausible."""
    if not isinstance(v, (int, float)):
        return "EXPECTED", "non-numeric value (string/flag)"

    # Most fields can be 0 (means real zero); plausibility is upper bound
    if v < lo:
        if metric.startswith("Dropped Revenue"):
            # Negative drop revenue can happen (credits/refunds)
            return "EXPECTED", "negative — likely credit/refund on last invoice"
        return "ODD-VALUE", f"value {v} below plausible floor {lo}"
    if v > hi:
        return "ODD-VALUE", f"value {v} above plausible ceiling {hi}"
    return "EXPECTED", ""


if __name__ == "__main__":
    sys.exit(main())
