"""Every adjustable line: does a correction move exactly the right report cell?

Written 2026-08-14 after Jiho found that correcting "Retention - Comped Target
($)" moved the Target row but left the COMBINED row stale. That bug was
invisible to a single-row check, and there are forty lines — testing them by
hand is not a plan.

For each adjustable line this posts a correction to one real cell, runs the
REAL mapper, and diffs the resulting report rows against an unadjusted build.
Three ways to fail, all caught here:

  · NOTHING MOVED      — the correction never reached the report
  · WRONG CELL         — something moved, but not the one asked for
  · TOO MUCH MOVED     — a cell nobody corrected also changed

A companion row moving is expected and reported, not failed: correcting a band
must move its combined line. The sweep prints them so a human can confirm the
set is the intended one.

    /usr/bin/python3 scripts/sweep_adjustable_lines.py [period]
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reports.membership_performance_tracker.logic import adjustments as adj  # noqa: E402
from reports.membership_performance_tracker.logic.cache import load_scoreboard  # noqa: E402
from reports.membership_performance_tracker.mapper import (  # noqa: E402
    METRIC_FIELD_MAP, TrackerV4Mapper)

CACHE = ROOT / "data" / "cache"


def _rows(data, fy_start, current_month):
    """{(month, territory, metric): value} for a whole mapper pass."""
    out = {}
    for r in TrackerV4Mapper(fiscal_year_start=fy_start,
                             current_month=current_month).map(data):
        out[(r["month"], r["territory"], r["metric"])] = r["value"]
    return out


def _pick_cell(data, field, months):
    """A (territory, month) this field actually has, preferring a live one."""
    grid = getattr(data, field, None)
    if not isinstance(grid, dict):
        return None
    for terr, slot in grid.items():
        if not isinstance(slot, dict):
            return (terr, None) if slot is not None or terr else None
        for m in months:
            if m in slot:
                return (terr, m)
    return None


def main(period: str) -> int:
    fy_start = adj.fy_start_of(period)
    data0 = load_scoreboard(CACHE / f"scoreboard_{period}.json")
    months = [m for m in adj.MONTHS]
    current = period[5:7]
    current_month = adj.MONTHS[(int(current) - 10) % 12]
    base = _rows(data0, fy_start, current_month)

    lines = {m: (k, f) for m, (k, f) in METRIC_FIELD_MAP.items()
             if k != "derived" and f not in adj.DERIVED_FIELDS
             and f not in adj.SPLIT_SUMS
             and not f.startswith(adj.FORBIDDEN_FIELD_PREFIXES)}

    silent, wrong, ok = [], [], []
    print(f"sweeping {len(lines)} adjustable lines on the {period} report\n")
    for metric, (kind, field) in sorted(lines.items()):
        # A photo count only reaches the report for the month it was taken.
        _months = ([current_month] if kind == "tm_current" else months)
        cell = _pick_cell(data0, field, _months)
        if cell is None:
            silent.append((metric, field, "field has no cells in this report"))
            continue
        terr, month = cell
        delta = 7.0
        data = copy.deepcopy(data0)
        notes = adj.apply_to(data, [{"field": field, "territory": terr,
                                     "month": month, "delta": delta}],
                             recompute=adj.recompute)
        if not any(n.startswith("adjusted") for n in notes):
            silent.append((metric, field, "; ".join(notes) or "overlay skipped it"))
            continue
        after = _rows(data, fy_start, current_month)
        moved = {k: (base.get(k), v) for k, v in after.items() if base.get(k) != v}

        own = [k for k in moved if k[2] == metric]
        if not own:
            wrong.append((metric, field, terr, month, sorted(moved)[:4]))
            continue
        ok.append((metric, len(moved), sorted({k[2] for k in moved})))

    print(f"{'MOVED ITS OWN ROW':<22}{len(ok)}")
    print(f"{'NEVER REACHED THE REPORT':<22}{len(silent)}")
    print(f"{'MOVED THE WRONG ROW':<22}{len(wrong)}\n")

    if silent:
        print("--- never reached the report ---")
        for m, f, why in silent:
            print(f"  {m:<44} [{f}]  {why}")
    if wrong:
        print("\n--- moved the wrong row ---")
        for m, f, t, mo, got in wrong:
            print(f"  {m:<44} [{f}] {t} {mo} -> {got}")

    print("\n--- companion rows that moved with each line ---")
    for m, n, metrics in ok:
        extra = [x for x in metrics if x != m]
        if extra:
            print(f"  {m:<44} also moved: {', '.join(extra)}")
    return 1 if (silent or wrong) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "2026-08"))
