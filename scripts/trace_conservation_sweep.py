"""Does the Trace page agree with the published report — everywhere?

Trace is the transparency promise: it is what lets an operator answer "where
did this number come from" without the person who built it. Each trace()
already self-checks conservation (do the member rows it shows add up to the
number the workbook publishes?), but nothing had ever swept EVERY cell. A
family/territory/month that silently fails conservation is the feature quietly
not working, and nobody would know.

Read-only. Works from receipts + cache on disk; no SLX, no writes.

    PYTHONPATH=$PWD python3 scripts/trace_conservation_sweep.py [period ...]
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reports.membership_performance_tracker.logic import trace as T   # noqa: E402

FY_MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
             "Apr", "May", "Jun", "Jul", "Aug", "Sep"]


def family_tally(problems) -> Counter:
    """How many problems each family has, worst first.

    Pure and separate so the test suite can prove a print cap cannot hide a
    family — the defect this exists to prevent was invisible to every
    behavioural test because it lived in a `print` slice.
    """
    return Counter(fam for fam, _terr, _mon, _msg in problems)


def sweep(period: str) -> int:
    rec = ROOT / f"data/receipts/receipts_{period}.json"
    if not rec.exists():
        print(f"  {period}: no receipts on disk — skipped")
        return 0
    rows = json.loads(rec.read_text())["rows"]
    families = sorted({r.get("metric") for r in rows if r.get("metric")})
    territories = sorted({r.get("territory") for r in rows if r.get("territory")})
    months = [m for m in FY_MONTHS
              if m in {r.get("month") for r in rows if r.get("month")}]

    print(f"\n=== {period} — {len(families)} families x {len(territories)} "
          f"territories x {len(months)} months ===")
    print(f"    families: {', '.join(families)}")

    checked = failed = errored = 0
    verdicts = Counter()
    problems = []
    for fam in families:
        for terr in territories:
            for mon in months:
                try:
                    out = T.trace(period, fam, terr, mon)
                except Exception as exc:
                    errored += 1
                    problems.append((fam, terr, mon, f"{type(exc).__name__}: {exc}"))
                    continue
                cons = out.get("conservation") or {}
                if not out.get("members") and not any(
                        v not in (None, 0) for v in (out.get("published") or {}).values()):
                    verdicts["empty cell (nothing published, nothing to show)"] += 1
                    continue
                checked += 1
                if cons.get("ok"):
                    verdicts["OK — receipts reconcile to the published number"] += 1
                else:
                    failed += 1
                    verdicts["FAILED conservation"] += 1
                    for p in (cons.get("problems") or [])[:2]:
                        problems.append((fam, terr, mon, str(p)))

    print(f"\n    cells with data checked: {checked}")
    for k, n in verdicts.most_common():
        print(f"      {n:5}  {k}")
    if problems:
        # A CAP MUST NEVER HIDE A FAMILY (2026-08-12). The detail list below is
        # truncated, and `problems` is built family by family in alphabetical
        # order — so on 2026-08 the cap ran out inside Drops and every one of
        # the 69 Retention failures went unprinted. The sweep announced "209
        # PROBLEMS" and then showed none of the ones that mattered, which reads
        # as full coverage. The tally is unconditional for exactly that reason.
        print(f"\n    PROBLEMS ({len(problems)}) by family:")
        for fam, n in family_tally(problems).most_common():
            print(f"      {n:5}  {fam}")
        shown = min(len(problems), 40)
        print(f"\n    first {shown} of {len(problems)}:")
        for fam, terr, mon, msg in problems[:40]:
            print(f"      {fam} / {terr} / {mon}: {msg[:150]}")
        if len(problems) > shown:
            print(f"      … {len(problems) - shown} more not shown — see the "
                  f"tally above for what they are")
    return failed + errored


if __name__ == "__main__":
    periods = sys.argv[1:] or ["2026-08", "2026-07"]
    bad = sum(sweep(p) for p in periods)
    print(f"\n{'=' * 60}\nVERDICT: {'CLEAN' if bad == 0 else f'{bad} FAILING CELL(S)'}")
    raise SystemExit(1 if bad else 0)
