#!/usr/bin/env python3
"""
verify_run.py — automated day-plan verification against a scoreboard cache.

Reads the local cache (data/cache/scoreboard_<period>.json) and runs the
six checks the day plan calls for after a fresh SLX refresh. Each check is
either a value range (with tolerance) or an exact-value match. Output is
pass/fail per check + a single summary line.

Designed to be the post-Thread-B verify gate so the human doesn't have to
click through xlsx cells manually:

  cd wha-data-platform
  python3 scripts/verify_run.py             # uses default period 2026-03
  python3 scripts/verify_run.py --period 2026-04
  python3 scripts/verify_run.py --cache /path/to/scoreboard_2026-03.json

Exit code: 0 = all pass, 1 = any fail, 2 = setup error (cache missing etc).
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = PROJECT_ROOT / "data" / "cache" / "scoreboard_2026-03.json"


# ----- Check definitions --------------------------------------------------

@dataclass
class Check:
    name: str
    extract: Callable[[dict], Any]                  # cache["fields"] → value
    expect: Tuple[Any, Any]                          # (low, high) range OR (exact, None)
    fmt: str = "{}"
    note: str = ""

    def evaluate(self, fields: dict) -> Tuple[bool, str]:
        """Return (passed, message)."""
        try:
            actual = self.extract(fields)
        except (KeyError, TypeError, ZeroDivisionError) as exc:
            return False, f"could not extract: {exc}"
        low, high = self.expect
        # Exact-value match path (high is None). Lets us assert exact equality
        # including None — e.g. "this field MUST be None because the engine
        # populates current_month only".
        if high is None:
            ok = actual == low
            disp_actual = "None" if actual is None else self.fmt.format(actual)
            disp_low    = "None" if low is None else self.fmt.format(low)
            return ok, f"got {disp_actual} (expected exactly {disp_low})"
        # Range match path — None can't satisfy a numeric range.
        if actual is None:
            return False, "value is None (engine did not populate this field)"
        ok = low <= actual <= high
        return ok, f"got {self.fmt.format(actual)} (expected {self.fmt.format(low)}–{self.fmt.format(high)})"


def _ratio(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or not den:
        return None
    return num / den * 100


# The six day-plan checks (commit dd77785 / 3ff58ad context, 2026-06-05).
# Adjust EXPECT ranges as confidence grows from re-runs.
CHECKS = [
    Check(
        name="Pierce restaurant penetration",
        extract=lambda f: _ratio(
            f["pen_active_restaurant"]["Pierce"],
            f["pen_market_restaurant"]["Pierce"],
        ),
        expect=(75.0, 85.0),
        fmt="{:.1f}%",
        note="Whitelist fix moved from ~67% → target ~80%.",
    ),
    Check(
        name="Snohomish Feb Target revenue",
        extract=lambda f: f["revenue_target"]["Snohomish"]["Feb"],
        expect=(1400.0, 1700.0),
        fmt="${:,.0f}",
        note="Payment-plan fix; expect ~$1,533 (Maxwell Hotel child location).",
    ),
    Check(
        name="Snohomish Feb new-members Target count (should be 0)",
        extract=lambda f: f["new_members_target"]["Snohomish"]["Feb"],
        expect=(0, 0),
        fmt="{}",
        note="Maxwell Hotel is a child location (not a new member by SOP).",
    ),
    Check(
        name="Billables: Pierce March hospitality target populated",
        extract=lambda f: f["hosp_bills_target"]["Pierce"]["Mar"],
        expect=(1, 10_000),
        fmt="{} billables",
        note="Bug 1 mapper: only current-month emit; Jan/Feb must be None.",
    ),
    Check(
        name="Billables: Pierce January hospitality target should be None",
        extract=lambda f: f["hosp_bills_target"]["Pierce"].get("Jan"),
        expect=(None, None),
        fmt="{}",
        note="Engine populates current_month only; mapper writes only that.",
    ),
    Check(
        name="NRA billables: Pierce March populated",
        extract=lambda f: f["nra_bills"]["Pierce"]["Mar"],
        expect=(0, 10_000),
        fmt="{} NRA bills",
        note="NRA wiring (commit landed pre-session). Just confirms not None.",
    ),
]


# ----- Runner -------------------------------------------------------------

def _load_cache(path: Path) -> dict:
    if not path.exists():
        print(f"ERROR: cache not found at {path}", file=sys.stderr)
        print("Run the engine first to populate it:", file=sys.stderr)
        print(f"  python3 reports/membership_performance_tracker/runner.py", file=sys.stderr)
        sys.exit(2)
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print(f"ERROR: cache file is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(2)
    fields = payload.get("fields")
    if not fields:
        print("ERROR: cache payload missing 'fields' key (corrupt or empty)", file=sys.stderr)
        sys.exit(2)
    saved_at = (payload.get("_meta") or {}).get("saved_at", "?")
    print(f"Cache loaded — saved_at: {saved_at}")
    print(f"  path: {path}")
    print("")
    return fields


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE,
                    help=f"Cache JSON path (default: {DEFAULT_CACHE})")
    ap.add_argument("--period", type=str, default=None,
                    help="Period override (e.g. '2026-03') — picks cache file by name.")
    args = ap.parse_args()

    cache_path = args.cache
    if args.period:
        cache_path = PROJECT_ROOT / "data" / "cache" / f"scoreboard_{args.period}.json"

    fields = _load_cache(cache_path)

    passed = 0
    failed = 0
    for check in CHECKS:
        ok, msg = check.evaluate(fields)
        marker = "✓" if ok else "✗"
        print(f"  {marker} {check.name}")
        print(f"      {msg}")
        if check.note:
            print(f"      ({check.note})")
        if ok:
            passed += 1
        else:
            failed += 1
        print("")

    total = passed + failed
    print("=" * 60)
    if failed == 0:
        print(f"All {total} checks PASSED — safe to publish.")
        return 0
    else:
        print(f"{failed} of {total} checks FAILED — investigate before publishing.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
