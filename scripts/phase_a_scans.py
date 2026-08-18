#!/usr/bin/env python3
"""phase_a_scans.py — dress-rehearsal Phase A: contradiction scans.

Every scan hunts a class of error we have actually caught at least once by
eye; the point is that no instance of these classes can exist UNKNOWINGLY.
A hit is either a defect to fix or a named, explained exception for the
dossier — never silence.

  S1 paid-but-zero      count-lens vs dollar-lens (the Thai Ginger nine)
  S2 value sanity       retained>ask, negative asks/dollars, counted<=0
  S3 band lens          retention band vs the month's billables band (Epulo)
  S4 counted nowhere    left members in no drop row + no active account
  S5 duplicate rows     same member twice in one cell
  S6 three copies       cache vs seal vs SP-official pointer, every cell
  S7 render gates       Σ member rows == every published cell, 4 families

Usage: PYTHONPATH=. python3 scripts/phase_a_scans.py 2026-07
Writes data/output/phase_a_scan_<period>.json and prints a summary.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(period: str) -> int:
    rows = json.loads(
        (ROOT / "data/receipts" / f"receipts_{period}.json").read_text())["rows"]
    cache = json.loads(
        (ROOT / "data/cache" / f"scoreboard_{period}.json").read_text())["fields"]
    close_p = ROOT / "data/closes" / f"close_{period}.json"
    sealed = (json.loads(close_p.read_text()).get("sealed")
              if close_p.exists() else None)
    off_p = (ROOT / "data/hub/Audit & History Log/Snapshots" / period /
             f"snapshot_{period}_official.json")

    ret = [r for r in rows if r["metric"] == "Retention"]
    bil = [r for r in rows if r["metric"] == "Billables"]
    drp = [r for r in rows if r["metric"] == "Drops"]
    new = [r for r in rows if r["metric"].startswith("New")]
    out = {}

    # S1 — paid in window but $0 (BOB/comped are branch-valued, not this)
    out["S1_paid_but_zero"] = [
        {"member": r["member"], "cell": f'{r["territory"]} {r["month"]} {r["band"]}',
         "ask": r["ask"]}
        for r in ret if r["counted"] and r["qualifies"] == "paid in window"
        and r["ask"] > 0 and r["retained"] == 0]

    # S2 — value sanity
    s2 = []
    for r in ret:
        if r["retained"] - r["ask"] > 0.01:
            s2.append(f'{r["member"]}: retained {r["retained"]} > ask {r["ask"]}')
        if r["ask"] < 0 or r["retained"] < 0:
            s2.append(f'{r["member"]}: negative ask/retained')
    for r in bil + new + drp:
        v = r.get("amount", r.get("face", 0))
        if r.get("counted") and isinstance(v, (int, float)) and v < 0:
            s2.append(f'{r["metric"]} {r["member"]}: negative value {v}')
    out["S2_value_sanity"] = s2

    # S3 — band-lens disagreement (photo month's billables vs retention rows).
    # T/NT rows only: a member can hold BOTH a hospitality and an allied
    # line, and the allied roster row must not shadow their real band
    # (first run: 143 false hits, all dual-line members shadowed to Allied).
    bb = {r["member_id"]: r["band"] for r in bil
          if r["band"] in ("Target", "Non-Target")}
    out["S3_band_disagreement"] = [
        {"member": r["member"], "cell": f'{r["territory"]} {r["month"]}',
         "retention_band": r["band"], "billables_band": bb[r["member_id"]]}
        for r in ret if r["member_id"] in bb and r["band"] != bb[r["member_id"]]]

    # S4 — departed members counted nowhere (drop-side completeness)
    drop_ids = {r["member_id"] for r in drp}
    active_ids = {r["member_id"] for r in bil if r["counted"]}
    new_ids = {r["member_id"] for r in new}
    names_by_norm = defaultdict(set)
    for r in bil:
        names_by_norm[str(r["member"]).lower().strip()[:18]].add(r["member_id"])
    s4 = []
    for r in ret:
        if r["qualifies"] not in ("left mid-cycle", "bill rescinded"):
            continue
        aid = r["member_id"]
        if aid in drop_ids or aid in active_ids or aid in new_ids:
            continue
        rejoin = bool(names_by_norm.get(str(r["member"]).lower().strip()[:18]))
        s4.append({"member": r["member"], "cell": f'{r["territory"]} {r["month"]}',
                   "why_excluded": r["qualifies"],
                   "same_name_active_account": rejoin})
    out["S4_counted_nowhere"] = s4

    # S5 — duplicate member rows in one cell
    keys = Counter((r["metric"], r.get("month"), r["territory"],
                    r.get("segment"), r["member_id"]) for r in rows
                   if r.get("member_id"))
    out["S5_duplicates"] = [
        {"key": " ".join(str(x) for x in k), "count": n}
        for k, n in keys.items() if n > 1]

    # S6 — three copies of the truth must agree cell-for-cell
    s6 = []
    if sealed is not None:
        containers = {"cache": cache}
        if off_p.exists():
            env = json.loads(off_p.read_text())
            d = env.get("data", {})
            containers["official"] = d.get("fields", d)
        for cname, cont in containers.items():
            for f, grid in sealed.items():
                if not isinstance(grid, dict) or f not in cont:
                    continue
                for t, months in grid.items():
                    if not isinstance(months, dict):
                        continue
                    for m, v in months.items():
                        got = (cont[f].get(t) or {}).get(m) \
                            if isinstance(cont[f].get(t), dict) else None
                        same = (got == v) or (
                            isinstance(got, (int, float))
                            and isinstance(v, (int, float))
                            and abs(got - v) < 1e-6)
                        if not same:
                            s6.append(f"{cname}: {f} {t} {m}: seal={v} got={got}")
    out["S6_copy_drift"] = s6

    # S7 — render gates (Σ member rows == published cells)
    from reports.membership_performance_tracker.logic import receipts_render as RR
    fy_start = int(period[:4]) if int(period[5:7]) >= 10 else int(period[:4]) - 1
    import reports.membership_performance_tracker.logic.receipts_sheet as rs
    snapshot_month = rs.MONTH_ORDER[(int(period[5:7]) - 10) % 12]
    gates = []
    gates += RR.gate_retention(ret, cache)
    gates += RR.gate_new_members(new, cache)
    try:
        gates += RR.gate_billables(bil, cache, snapshot_month)
    except TypeError:
        gates += RR.gate_billables(bil, cache)
    gates += RR.gate_drops(drp, cache)
    out["S7_gate_errors"] = gates

    outp = ROOT / "data/output" / f"phase_a_scan_{period}.json"
    outp.write_text(json.dumps(out, indent=2, default=str))
    print(f"═══ Phase A scans · {period} ═══")
    for k, v in out.items():
        print(f"  {k:22} {'PASS (0 hits)' if not v else f'{len(v)} hits'}")
        for hit in list(v)[:4]:
            print(f"     · {json.dumps(hit, default=str)[:110]}")
    print(f"→ {outp}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "2026-07"))
