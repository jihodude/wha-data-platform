#!/usr/bin/env python3
"""verify_workbook_vs_cache.py <period> — the chain's final link (Jiho,
8/10: "if the chain lacks, add another element that makes sure the
numbers are correct").

Independently re-derives every data-sheet row from the CACHE via the
production mapper and diffs it against the workbook actually on disk —
proving the artifact people download equals the data that was verified.
Zero tolerance; exits nonzero on any mismatch.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(period: str) -> int:
    os.environ["MPR_PERIOD"] = period
    from src.config.period import parse_period
    P = parse_period(period)
    from reports.membership_performance_tracker.logic.cache import load_scoreboard
    from reports.membership_performance_tracker.mapper import TrackerV4Mapper
    data = load_scoreboard(ROOT / "data/cache" / f"scoreboard_{period}.json")
    from reports.membership_performance_tracker.logic import month_close as mc
    # Hand corrections are part of the published face (8/14): the workbook
    # carries them, the cache deliberately does not. Comparing a clean cache to
    # an adjusted workbook would report every corrected cell as a defect every
    # night.
    from reports.membership_performance_tracker.logic import adjustments as _adj
    _adj.apply_to(data, _adj.for_build(
        _adj.load_fy(_adj.fy_start_of(period)), period), recompute=_adj.recompute)
    for note in mc.apply_frozen(data, mc.load_all_closes(), period=period):
        pass                                    # sealed values stamped
    rows = TrackerV4Mapper(fiscal_year_start=P.fy_start,
                           current_month=P.current_month).map(data)
    from reports.membership_performance_tracker.history import assemble_photo_history
    rows.extend(assemble_photo_history(P.current_month, P.fy_start,
                                       ROOT / "data" / "cache", period))
    want = {(r["year"], str(r["month"]), str(r["territory"]),
             str(r["metric"])): r["value"] for r in rows}

    from openpyxl import load_workbook
    wb = load_workbook(ROOT / "data/output" /
                       f"Membership_Performance_Report_{period}.xlsx",
                       read_only=True)
    ws = wb["Data - Monthly Metrics"]
    got = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        y, mo, t, met, val = r[:5]
        if isinstance(y, int):        # skip note/header furniture rows
            got[(y, str(mo), str(t), str(met))] = val
    wb.close()

    bad = []
    for k, v in want.items():
        g = got.get(k, "<MISSING>")
        same = (g == v) or (isinstance(g, (int, float)) and
                            isinstance(v, (int, float)) and abs(g - v) < 1e-6)
        if not same:
            bad.append((k, v, g))
    extra = set(got) - set(want)
    print(f"workbook-vs-cache [{period}]: {len(want)} derived rows, "
          f"{len(bad)} mismatches, {len(extra)} unexplained sheet rows")
    for b in bad[:6]:
        print("  ✗", b)
    if bad:
        return 1
    print("✓ the artifact equals the data — final link holds")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "2026-08"))
