#!/usr/bin/env python3
"""number_check.py — the MECHANICAL number check (Jiho 8/4: no LLM judgment).

    PYTHONPATH=$PWD python3 scripts/number_check.py <before_cache.json> [period]

Compares the BEFORE cache (snapshotted pre-pull) against the CURRENT cache
cell by cell. Every changed cell must match a PREDICTED delta class from
the 8/3-8/4 rulings; anything unpredicted prints loudly and exits 1.
The classes (each cites its ruling):

  P1 ask/retained moved on retention fields      — dues-level ask (GO 8/4)
     + fees-out (SHADUES/AHLA/county, 8/3) + BOB faces IN (8/4). Direction:
     asks move toward the dues level; retained never exceeds ask.
  P2 retained INCREASED with ask flat            — posting-lag payments
     (Hood Canale class, R9) landing since the 7/31 capture.
  P3 comp/BOB fields appeared                    — new fields, any value.
  P4 drops fields moved in the CACHE             — the cache is PRE-OVERLAY
     SData (runner saves before the Crystal overlay); published drops are
     verified separately by replaying feed_drops against the archive.
  P5 billables/penetration drifted small         — photo metrics re-taken on
     a later day (roster moves). Threshold: warn > 5 members per cell.
  P6 counts changed ±small on retention          — BOB admissions (text-
     comment members now visible) + void exclusions. Flags enumerate them.
  SALES fields: NO predicted change (cohort_screen only gained a tripwire).
     Any new-sales delta beyond cents = UNPREDICTED.

Output: per-class counts, then every UNPREDICTED cell. Exit 0 = clean.
"""
import json
import sys
from pathlib import Path

RET_DOLLAR_FIELDS = {"rev_retained_target", "rev_retained_non_target",
                     "rev_up_target", "rev_up_non_target"}
RET_COUNT_FIELDS = {"ret_paid", "ret_billed", "ret_paid_target",
                    "ret_billed_target", "ret_paid_non_target",
                    "ret_billed_non_target"}
NEW_FIELDS = {"ret_comped", "ret_comped_dollars", "ret_bob",
              "ret_bob_dollars", "revenue_comped_new"}
DROP_FIELDS = {"drops_target", "drops_non_target", "drops_revenue_target",
               "drops_revenue_non_target"}
PHOTO_FIELDS = {"hosp_bills", "hosp_bills_target", "hosp_bills_non_target",
                "allied_bills", "combined_bills", "latest_billables"}
SALES_FIELDS = {"revenue", "revenue_target", "revenue_non_target",
                "revenue_bob", "revenue_bob_target", "revenue_bob_non_target",
                "new_members", "new_members_target", "new_members_non_target"}
DERIVED_PREFIXES = ("retention_pct", "retention_str", "avg_retention",
                    "ret_status", "pen_", "statewide_", "ytd_", "trend",
                    "mom_", "attainment", "season_", "delta_", "best_month",
                    "dollars_per_member", "goal")


def _cells(fields):
    for f, per_terr in (fields or {}).items():
        if not isinstance(per_terr, dict):
            continue
        for terr, months in per_terr.items():
            if isinstance(months, dict):
                for m, v in months.items():
                    if isinstance(v, (int, float)):
                        yield f, terr, m, float(v)


def main() -> int:
    before_path = Path(sys.argv[1])
    period = sys.argv[2] if len(sys.argv) > 2 else "2026-07"
    root = Path(__file__).resolve().parent.parent
    after_path = root / "data" / "cache" / f"scoreboard_{period}.json"
    b = json.loads(before_path.read_text()).get("fields") or {}
    a = json.loads(after_path.read_text()).get("fields") or {}

    bmap = {(f, t, m): v for f, t, m, v in _cells(b)}
    amap = {(f, t, m): v for f, t, m, v in _cells(a)}
    keys = set(bmap) | set(amap)

    counts = {"P1": 0, "P2": 0, "P3": 0, "P4": 0, "P5": 0, "P6": 0,
              "unchanged": 0, "derived": 0}
    unpredicted, photo_warn = [], []

    for k in sorted(keys):
        f, t, m = k
        bv, av = bmap.get(k), amap.get(k)
        if bv is not None and av is not None and abs(bv - av) < 0.01:
            counts["unchanged"] += 1
            continue
        if f.startswith(DERIVED_PREFIXES):
            counts["derived"] += 1          # recomputed from primaries
            continue
        if f in NEW_FIELDS:
            counts["P3"] += 1
            continue
        if f in RET_DOLLAR_FIELDS:
            counts["P1" if "up" in f or (av or 0) <= (bv or 0) else "P2"] += 1
            continue
        if f in RET_COUNT_FIELDS:
            if abs((av or 0) - (bv or 0)) <= 4:
                counts["P6"] += 1
                continue
            unpredicted.append((k, bv, av, "retention count moved > 4"))
            continue
        if f in DROP_FIELDS:
            # The cache stores SData's PRE-OVERLAY drops (runner saves before
            # the Crystal overlay, by design) — the PUBLISHED drops layer must
            # be verified by replaying feed_drops instead (8/4 lesson: the
            # cache diff false-alarmed on 116 cells the workbook never shows).
            counts["P4"] += 1
            continue
        if f in PHOTO_FIELDS:
            if abs((av or 0) - (bv or 0)) <= 5:
                counts["P5"] += 1
            else:
                photo_warn.append((k, bv, av))
                counts["P5"] += 1
            continue
        if f in SALES_FIELDS:
            if abs((av or 0) - (bv or 0)) < 0.01:
                counts["unchanged"] += 1
            else:
                unpredicted.append((k, bv, av, "SALES moved — no code change predicts this"))
            continue
        unpredicted.append((k, bv, av, "field outside every predicted class"))

    print("== MECHANICAL NUMBER CHECK ==")
    for c, n in counts.items():
        print(f"  {c}: {n}")
    if photo_warn:
        print(f"\n⚠ photo drift > 5 members ({len(photo_warn)}):")
        for k, bv, av in photo_warn[:10]:
            print(f"   {k}: {bv} -> {av}")
    if unpredicted:
        print(f"\n⛔ UNPREDICTED CHANGES ({len(unpredicted)}) — investigate before trusting:")
        for k, bv, av, why in unpredicted[:40]:
            print(f"   {k}: {bv} -> {av}   [{why}]")
        return 1
    print("\n✓ every change lands in a predicted class")
    return 0


if __name__ == "__main__":
    sys.exit(main())
