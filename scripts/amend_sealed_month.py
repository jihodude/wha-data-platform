"""amend_sealed_month.py — the ONLY sanctioned way to change a sealed number.

R2, ruled 2026-08-12: the seal never moves on its own. When the CRM's past
changes under a sealed month (an RRO flip, a late accounting correction, a
checkbox), nothing updates automatically — a human runs THIS, with a reason,
and the change is notated forever. SuzAnne's rule, verbatim from the 8/12
walkthrough: "we'll just notate it — it won't actually change, change it."

    python3 scripts/amend_sealed_month.py 2026-07 drops_target TKP Jul 1 \
        --why "Marina Square: CRM flip date corrected to 2026-07-31"

Guarantees, by construction rather than policy:
  · refuses to run without --why
  · touches exactly ONE cell, shows before → after, and asks for confirmation
    (--yes to skip, for scripted use)
  · appends a full amendment record (when / field / cell / old / new / why)
  · writes a .bak beside the close doc before changing anything
  · pushes the amended doc to SharePoint (best-effort; local is authoritative)

The SOP's "revoke the seal and adjust" procedure is this command — there is
no hand-editing of close JSON in any documented workflow.
"""
import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CLOSES = ROOT / "data" / "closes"
HUB_SUBPATH = "Reports/Membership Performance Report/Data/closes"


def amend(period: str, field: str, territory: str, month: str, value: float,
          why: str, closes_dir: Path = CLOSES, assume_yes: bool = False,
          push=None) -> dict:
    if not (why or "").strip():
        raise SystemExit("REFUSED: an amendment without a reason is drift "
                         "with extra steps. Pass --why.")
    path = Path(closes_dir) / f"close_{period}.json"
    if not path.exists():
        raise SystemExit(f"REFUSED: {path.name} does not exist — only a "
                         f"sealed month can be amended.")
    doc = json.loads(path.read_text())
    sealed = doc.get("sealed")
    if not sealed:
        raise SystemExit(f"REFUSED: {period} is closed but not sealed.")
    # TWO WRITERS, ONE CELL (guard added 2026-08-14). This tool SETS an absolute
    # value into the seal; "Adjust a Number" ADDS a delta on top of it at build
    # time. Used together on one cell they stack silently — the operator types
    # the number they want and the overlay moves it again.
    # Only against the REAL store: a caller passing its own closes_dir is
    # sandboxed (tests, a scratch copy) and must not be judged against
    # production corrections — nor reach the network to fetch them.
    from reports.membership_performance_tracker.logic import adjustments as _adj
    _clash = [] if Path(closes_dir) != CLOSES else [
        e for e in _adj.load_fy(_adj.fy_start_of(period))
        if e.get("field") == field and e.get("territory") == territory
        and e.get("month") == month]
    _net = sum(float(e.get("delta") or 0) for e in _clash)
    # Net zero means the corrections cancel out — the cell is back to what the
    # program computed, so there is nothing to stack on. Blocking those would
    # permanently freeze every cell anyone ever corrected and then reversed.
    if _clash and _net:
        raise SystemExit(
            f"REFUSED: {field} {territory} {month} already carries "
            f"{len(_clash)} correction(s) totalling {_net:+g} from Adjust a "
            f"Number. Amending here would stack on top of them. Reverse those "
            f"first, or make this change there instead.")
    if field not in sealed:
        raise SystemExit(f"REFUSED: '{field}' is not a sealed field of "
                         f"{period}. Sealed fields: {sorted(sealed)[:8]}…")
    slot = sealed[field].get(territory)
    if not isinstance(slot, dict) or month not in slot:
        raise SystemExit(f"REFUSED: no sealed cell {field}/{territory}/{month}.")
    old = slot[month]
    print(f"  {period} · {field} · {territory} · {month}:  {old}  →  {value}")
    print(f"  why: {why}")
    if not assume_yes:
        if input("  apply? [y/N] ").strip().lower() != "y":
            raise SystemExit("aborted — nothing changed.")
    shutil.copy2(path, path.with_suffix(path.suffix + ".bak-amend"))
    slot[month] = value
    # THE FROZEN BLOCK TOO (fixed 2026-08-13, found while amending July's
    # allied cells). apply_frozen stamps the sealed slice first and THEN
    # overlays `frozen` — the pre-ITD retention photograph — so every
    # retention amendment landed in the record and was overwritten before it
    # reached the report. Silent since the frozen block existed: the 8/6
    # fee-aware and fee-dollar amendments never took effect either, and the
    # SOP tells the team to amend. An amendment must update wherever the
    # PUBLISHED value lives, which for retention is `frozen`.
    frozen = doc.get("frozen") or {}
    if field in frozen and month == doc.get("month") \
            and isinstance(frozen[field], dict) and territory in frozen[field]:
        frozen[field][territory] = value
        print(f"  ✓ frozen retention block updated too "
              f"({field}/{territory})")
    doc.setdefault("amendments", []).append({
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "what": why, "fields": [field],
        "cell": {"territory": territory, "month": month,
                 "old": old, "new": value},
    })
    path.write_text(json.dumps(doc, indent=2, default=str))
    print(f"  ✓ amended and notated ({len(doc['amendments'])} amendment(s) on record)")
    pushed = False
    try:
        if push is None:
            from src.hub.datahub import DataHub
            hub = DataHub.connect(require_sharepoint=False)
            push = (hub.write_hub_file
                    if getattr(hub, "_sp", None) is not None else None)
        if push is not None:
            push(f"{HUB_SUBPATH}/close_{period}.json", path.read_bytes())
            pushed = True
            print("  ✓ pushed to SharePoint")
    except Exception as exc:
        print(f"  ⚠ SP push failed ({type(exc).__name__}) — the local close "
              f"doc is authoritative; push it when SharePoint is back.")
    return {"old": old, "new": value, "pushed": pushed}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("period"); ap.add_argument("field")
    ap.add_argument("territory"); ap.add_argument("month")
    ap.add_argument("value", type=float)
    ap.add_argument("--why", required=True)
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    amend(a.period, a.field, a.territory, a.month, a.value, a.why,
          assume_yes=a.yes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
