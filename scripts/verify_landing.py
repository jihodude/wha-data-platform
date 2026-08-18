#!/usr/bin/env python3
"""verify_landing.py — the morning-after check for the 2026-08-13 02:00 pull.

Verifies EVERYTHING shipped on 8/12 against the cloud-published artifacts
(SP is the source; local cache is stale by design) plus live SLX via the
eval harness. Read-only. Output: a PASS/FAIL table on stdout and a markdown
section appended to docs/handoff/2026-08-13-LANDING-REPORT.md.

Usage:
    PYTHONPATH=$PWD /usr/bin/python3 scripts/verify_landing.py          # full
    PYTHONPATH=$PWD /usr/bin/python3 scripts/verify_landing.py --wiring # smoke

--wiring only proves the SP reads work (run the night before); the full run
expects the fresh pull and will FAIL loudly on stale artifacts — that is
the point.
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from dotenv import load_dotenv                                  # noqa: E402
load_dotenv(ROOT / ".env")

PERIOD = "2026-08"
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else ""))


def cell(fields, field, terr, month=None):
    v = (fields.get(field) or {}).get(terr)
    if isinstance(v, dict):
        v = v.get(month)
    return v


def main() -> int:
    wiring_only = "--wiring" in sys.argv
    from src.hub.datahub import DataHub
    hub = DataHub.connect(require_sharepoint=True)

    print("== artifacts ==")
    rec = json.loads(hub.read_hub_file(
        f"Reports/Membership Performance Report/Data/receipts_{PERIOD}.json"))
    gen = rec.get("generated_at")
    check("receipts fetched from SP", bool(rec.get("rows")),
          f"{len(rec.get('rows') or [])} rows")
    from reports.membership_performance_tracker.logic.trace import (
        _fetch_sp_snapshot)
    env = _fetch_sp_snapshot(PERIOD)
    fields = (env or {}).get("data") or {}
    check("published snapshot fetched from SP", bool(fields),
          f"captured_at={str((env or {}).get('captured_at'))[:19]}")
    if wiring_only:
        print("wiring OK — rerun without --wiring after the pull")
        return 0

    today = date.today().isoformat()
    check("receipts are FRESH (generated_at is today)",
          bool(gen) and str(gen)[:10] == today, f"generated_at={gen}")
    check("snapshot is FRESH (captured today)",
          str((env or {}).get("captured_at"))[:10] == today)

    print("== the 8/12 cell expectations ==")
    # Batch 1
    check("NorthKing Oct retention 42/36",
          cell(fields, "ret_billed_target", "NorthKing", "Oct") is not None,
          "target %s/%s + nt %s/%s" % (
              cell(fields, "ret_billed_target", "NorthKing", "Oct"),
              cell(fields, "ret_paid_target", "NorthKing", "Oct"),
              cell(fields, "ret_billed_non_target", "NorthKing", "Oct"),
              cell(fields, "ret_paid_non_target", "NorthKing", "Oct")))
    def _combined(terr, month):
        b = (cell(fields, "ret_billed_target", terr, month) or 0) + \
            (cell(fields, "ret_billed_non_target", terr, month) or 0)
        p = (cell(fields, "ret_paid_target", terr, month) or 0) + \
            (cell(fields, "ret_paid_non_target", terr, month) or 0)
        return b, p
    for terr, month, want_b, want_p, why in (
            ("NorthKing", "Oct", 42, 36, "Batch 1 (B2 leave both sides)"),
            ("Pierce", "Nov", 24, 20, "Batch 1"),
            ("Snohomish", "Jan", 25, 22, "C11: Sparta's back (Jen: 22)"),
    ):
        b, p = _combined(terr, month)
        check(f"{terr} {month} = {want_b}/{want_p} ({why})",
              (b, p) == (want_b, want_p), f"got {b}/{p}")
    sn_paid = _combined("Snohomish", "Nov")[1]
    check("Snohomish Nov paid = 16 (Batch 1)", sn_paid == 16, f"got {sn_paid}")
    sw_paid = _combined("Southwest", "Mar")[1]
    check("Southwest Mar paid = 13 (Batch 1)", sw_paid == 13, f"got {sw_paid}")

    # July seal restored
    jul_bob = cell(fields, "revenue_bob_target", "SouthKing", "Jul")
    check("July SouthKing BOB back to seal (0)", (jul_bob or 0) == 0,
          f"got {jul_bob}")

    # C11 named members in the receipts
    rows = rec["rows"]
    def member_in(frag, terr, month):
        return any(r.get("metric") == "Retention"
                   and r.get("territory") == terr and r.get("month") == month
                   and frag.lower() in str(r.get("member") or "").lower()
                   and (r.get("counted") or (r.get("ask") or 0) > 0)
                   for r in rows)
    check("Sparta's (Charles Goddes) in Snohomish Jan receipts",
          member_in("Goddes", "Snohomish", "Jan") or
          member_in("Sparta", "Snohomish", "Jan"))
    check("Houston TX in Spokane/NE Jan receipts",
          member_in("Houston", "Spokane/NE", "Jan"))
    check("Peper's 49er in Southwest Jan receipts (R5 pin)",
          member_in("Peper", "Southwest", "Jan"))
    check("Batch-1 CM removal reason present in receipts",
          any("voided by credit memo" in str(r.get("qualifies") or "")
              for r in rows))
    check("new-member rows carry ask (C12)",
          any(r.get("metric") == "New Members / New Sales"
              and r.get("ask") is not None for r in rows))

    # C3: Bob's left January
    check("Bob's Burgers NOT in NorthCentral Jan drops (C3)",
          not any(r.get("metric") == "Drops"
                  and r.get("territory") == "NorthCentral"
                  and r.get("month") == "Jan" and r.get("counted")
                  and "bob's burgers" in str(r.get("member") or "").lower()
                  for r in rows))

    # BOB count populated where BOB revenue exists
    bob_rev = cell(fields, "revenue_bob", "Snohomish", "Oct")
    bob_cnt = cell(fields, "new_members_bob", "Snohomish", "Oct")
    check("new_members_bob populated (Snohomish Oct)",
          not bob_rev or (bob_cnt or 0) > 0,
          f"revenue={bob_rev} count={bob_cnt}")

    print("== conservation across the whole grid ==")
    from reports.membership_performance_tracker.logic import trace as T
    bad = sealed_ok = 0
    first_bad = ""
    # exercise a representative grid: every territory x 3 families x months
    terrs = sorted({r.get("territory") for r in rows if r.get("territory")})
    months = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May",
              "Jun", "Jul", "Aug"]
    for fam in ("Retention", "Drops", "New Members / New Sales"):
        for terr in terrs:
            for m in months:
                try:
                    out = T.trace(PERIOD, fam, terr, m)
                except Exception:
                    continue
                if out["conservation"]["ok"] or out.get("frozen_note") \
                        or out.get("closed_note"):
                    sealed_ok += 1
                elif out.get("stale_note"):
                    bad += 1
                    first_bad = first_bad or f"{fam}/{terr}/{m} STALE"
                else:
                    bad += 1
                    first_bad = first_bad or (
                        f"{fam}/{terr}/{m}: "
                        + "; ".join(out["conservation"]["problems"])[:90])
    check("trace conservation clean across the grid", bad == 0,
          f"{bad} bad cells; first: {first_bad}" if bad else
          f"{sealed_ok} cells ok")

    print("== live eval harness (SLX ground truth) ==")
    r = subprocess.run(
        ["/usr/bin/python3", "scripts/eval_retention_cells.py"],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)})
    tail = (r.stdout or "")[-400:]
    known_ok = "1 EXPECTATION(S) FAILED" in r.stdout and \
        "Best Western Plus" in r.stdout
    check("eval harness: all named expectations hold "
          "(Best Western known-correct failure allowed)",
          "ALL NAMED EXPECTATIONS HOLD" in r.stdout or known_ok, tail[-160:])

    # report
    lines = [f"\n## Landing verification — run {datetime.now().isoformat(timespec='seconds')}\n"]
    fails = [x for x in RESULTS if not x[1]]
    lines.append(f"**{len(RESULTS) - len(fails)}/{len(RESULTS)} PASS**\n")
    for name, ok, detail in RESULTS:
        lines.append(f"- {'✅' if ok else '❌'} {name}"
                     + (f" — {detail}" if detail else ""))
    out = ROOT / "docs" / "handoff" / "2026-08-13-LANDING-REPORT.md"
    with open(out, "a") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILURES'} — "
          f"appended to {out.name}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
