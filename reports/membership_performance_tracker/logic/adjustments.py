"""adjustments.py — hand corrections as first-class, replayable data.

Designed with Jiho 2026-08-14; see
docs/superpowers/specs/2026-08-14-adjustments-design.md.

THE SHAPE OF THE IDEA. A number is never overwritten. A correction is an
ENTRY posted on top of it, the way a closed accounting period takes an
adjusting journal entry rather than an eraser:

    published cell = computed value + Σ adjustments(field, territory, month)

Removal is the same entry with a negative amount. Moving a member between
months, territories or bands is two entries posted together under one
`group` — so a one-sided move, which is what silently double-counted or lost
members on 2026-08-13, cannot be expressed.

WHY THE CACHE MUST STAY CLEAN (verified in runner.py, 8/14). The build order
is: save cache (`slx-preoverlay`) → seal() → apply_frozen() → save cache again
(`frozen-stamped`) → mapper → writer. For a SEALED month apply_frozen does
`target.clear(); target.update(sealed)`, which resets the field before any
overlay lands. For an OPEN month nothing resets it — so if adjustments were
written into the cache file, every `--from-cache` rebuild would load its own
previous output, add the adjustment again, and compound it silently.

Therefore: **adjustments are never persisted into the scoreboard cache.** The
cache stays the program's own computation, and this overlay is applied at each
point that READS it — the report build and the Trace page — which is
idempotent by construction and keeps "what the program said" separable from
"what we corrected" forever.

STORAGE IS A SIDECAR, NOT THE CLOSE DOC (corrected 8/14 after the dependency
investigation). Putting entries in `close_<period>.json` looked natural, but
`is_closed()` is literally "does that file exist" (month_close.py) — so writing
one for an OPEN month would make the month report as closed, auto-seal it on
the next live pull while it was still collecting, and then refuse to ever close
it properly (`freeze()` raises AlreadyClosed). It would also rewrite a 302 KB
document containing the only copy of the seal on every append, and race the
close doc's own writers.

So adjustments live in `data/adjustments/adjustments_<period>.json`, which
works identically for open and closed months, cannot disturb a seal, and keeps
this mechanism separate from the older `amendments` log that SETS values while
this one ADDS. Append-only: undo is a reversing entry, never a delete.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from uuid import uuid4
from pathlib import Path
from typing import Dict, Iterable, List, Optional

_ROOT = Path(__file__).resolve().parents[3]
ADJUSTMENTS_DIR = _ROOT / "data" / "adjustments"

KEY = "entries"

# SharePoint is the record; local disk is a working copy. Cloud Run wipes a
# container on every deploy, so a correction that exists only locally dies at
# the next deploy and the number silently reverts to what the program computed.
HUB_SUBPATH = "Reports/Membership Performance Report/Data/adjustments"

# Penetration counts are per-territory with no month axis (mapper's "t" kind):
# ScoreboardData holds `field[territory]`, not `field[territory][month]`. They
# are adjustable, but they are addressed without a month.
MONTHLESS_FIELDS = frozenset({
    "pen_market_restaurant", "pen_market_lodging",
    "pen_active_restaurant", "pen_active_lodging",
    "pen_market_nt_restaurant", "pen_market_nt_lodging",
    "pen_active_nt_restaurant", "pen_active_nt_lodging",
})

MONTHS = ("Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
          "Apr", "May", "Jun", "Jul", "Aug", "Sep")

# Goals are edited in Admin Inputs and deliberately recompute past months'
# percentages from current goals (ruled 8/14). An adjustment must never touch
# them, or the two mechanisms would fight over the same cell.
FORBIDDEN_FIELD_PREFIXES = ("goal", "statewide_goal", "ytd_goal")

# Derived values recompute from adjusted bases; adjusting them directly would
# let a ratio contradict its own terms ("48/58" saying one thing, the % another).
DERIVED_FIELDS = frozenset({
    "retention_pct", "retention_str", "ret_status",
    "pen_pct", "pen_status", "attainment_pct", "season_attainment",
    "statewide_attainment", "mom_change", "trend", "avg_retention",
    "best_month", "delta_oct_to_mar", "dollars_per_member",
})

_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


class AdjustmentRefused(Exception):
    """The entry was rejected. The message says what to fix."""


class AdjustmentSavedLocallyOnly(Exception):
    """Written locally, but SharePoint would not take it.

    Not a refusal — the entry exists and applies on this machine. It is a
    warning that the only copy is somewhere a deploy can erase.
    """


def _path(period: str, store_dir: Optional[Path] = None) -> Path:
    return (store_dir or ADJUSTMENTS_DIR) / f"adjustments_{period}.json"


def _hub():
    """The SharePoint hub, or None when unreachable. Never raises."""
    try:
        from src.hub.datahub import DataHub
        hub = DataHub.connect(require_sharepoint=False)
        return hub if getattr(hub, "_sp", None) is not None else None
    except Exception:
        return None


# Most periods of a fiscal year have no corrections at all, and load_fy asks
# for twelve of them. Without this, every build (and every Trace render) paid
# a dozen SharePoint round-trips to be told "no such file" twelve times.
_PULL_MISSES: set = set()


def _pull(period: str, dest: Path) -> bool:
    """Fetch this period's corrections from SharePoint into `dest`. Quiet."""
    if period in _PULL_MISSES:
        return False
    hub = _hub()
    if hub is None:
        return False
    try:
        raw = hub.read_hub_file(f"{HUB_SUBPATH}/adjustments_{period}.json")
    except Exception:
        _PULL_MISSES.add(period)
        return False
    try:
        json.loads(raw)                      # refuse to cache a corrupt copy
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return True
    except Exception:
        _PULL_MISSES.add(period)
        return False


def load(period: str, store_dir: Optional[Path] = None) -> List[dict]:
    """Every adjustment posted against `period`, oldest first. [] when none."""
    p = _path(period, store_dir)
    if not p.exists():
        # A fresh container has no local copy — the record lives on SharePoint.
        # Only heal the default store; a caller passing store_dir (tests, or a
        # deliberate sandbox) must not reach the network.
        if store_dir is not None or not _pull(period, p):
            return []
    try:
        doc = json.loads(p.read_text())
    except (OSError, ValueError):
        return []
    entries = doc.get(KEY)
    if not isinstance(entries, list):
        return []
    # Stamp which file this came from (in memory only). A month-less
    # correction — the per-territory penetration counts — belongs to ONE
    # period's photograph, and once entries from twelve files are pooled
    # there is otherwise no way to tell which.
    return [{**e, "_period": period} for e in entries]


def validate(field: str, territory: str, month: str, delta,
             why: str, who: str) -> float:
    """Raise AdjustmentRefused unless this entry is postable. Returns the delta."""
    if not (why or "").strip():
        raise AdjustmentRefused(
            "An adjustment needs a reason — it is the only record of why this "
            "number is not what the program computed.")
    if not (who or "").strip():
        raise AdjustmentRefused("An adjustment needs a name — who is making it.")
    if not (field or "").strip():
        raise AdjustmentRefused("An adjustment needs a field.")
    if field in SPLIT_SUMS:
        a, b = SPLIT_SUMS[field]
        raise AdjustmentRefused(
            f"'{field}' is the Target and Non-Target lines added together. "
            f"Correcting it directly does nothing — it is rebuilt from "
            f"'{a}' and '{b}' every time the report runs. Correct whichever "
            f"band the change belongs to and this follows.")
    if field in DERIVED_FIELDS:
        raise AdjustmentRefused(
            f"'{field}' is calculated from other numbers. Adjust those and it "
            f"follows — adjusting it directly would let it contradict them.")
    if field.startswith(FORBIDDEN_FIELD_PREFIXES):
        raise AdjustmentRefused(
            f"'{field}' is a goal. Goals are edited in Admin Inputs, which "
            f"already applies to closed months.")
    if not (territory or "").strip():
        raise AdjustmentRefused("An adjustment needs a territory.")
    if territory == "Total":
        raise AdjustmentRefused(
            "'Total' is every territory added together, not a place to post to. "
            "Adjust the territory the correction actually belongs to.")
    if field in MONTHLESS_FIELDS:
        # Per-territory photo counts have no month axis at all.
        return _as_number(delta)
    if month not in MONTHS:
        raise AdjustmentRefused(
            f"'{month}' is not a month of the fiscal year ({', '.join(MONTHS)}).")
    return _as_number(delta)


def _as_number(delta) -> float:
    try:
        value = float(delta)
    except (TypeError, ValueError):
        raise AdjustmentRefused(f"'{delta}' is not a number.")
    if value == 0:
        raise AdjustmentRefused("An adjustment of zero would change nothing.")
    return value


def post(period: str, field: str, territory: str, month: str, delta,
         why: str, who: str, member_id: Optional[str] = None,
         member: Optional[str] = None, group: Optional[str] = None,
         store_dir: Optional[Path] = None, now: Optional[str] = None) -> dict:
    """Append one adjustment to `period` and return the stored entry.

    Append-only: nothing is ever rewritten or removed, so the history of a
    number is complete. Reversing an entry means posting its negative.
    """
    if not _PERIOD_RE.match(period or ""):
        raise AdjustmentRefused(f"'{period}' is not a period like '2026-07'.")
    value = validate(field, territory, month, delta, why, who)

    p = _path(period, store_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        try:
            doc = json.loads(p.read_text())
        except ValueError:
            raise AdjustmentRefused(
                f"{p.name} is unreadable. Do not post over it — it holds "
                f"corrections that are not recorded anywhere else.")
    else:
        # Works the same for an open month: this file is the record, and
        # creating it says nothing about whether the month is closed.
        doc = {"period": period, KEY: []}

    entry = {
        "at": now or datetime.now().astimezone().isoformat(timespec="seconds"),
        "who": who.strip(),
        "field": field,
        "territory": territory,
        "month": None if field in MONTHLESS_FIELDS else month,
        "delta": value,
        "member_id": member_id or None,
        "member": member or None,
        "why": why.strip(),
        "group": group or None,
    }
    doc.setdefault(KEY, []).append(entry)
    # default=str matches every other writer of a record in this codebase; a
    # stray date object must not be the thing that loses a correction.
    payload = json.dumps(doc, indent=2, default=str)
    p.write_text(payload)
    _PULL_MISSES.discard(period)

    # FAIL LOUD (8/14). Every other close-doc writer swallows a failed push;
    # here that would mean a correction the operator watched succeed, living on
    # one container until the next deploy erases it. If SharePoint is reachable
    # and the write fails, say so — the local copy stays, so nothing is lost,
    # but nobody is told it is safe when it is not.
    if store_dir is None:
        hub = _hub()
        if hub is not None:
            try:
                hub.write_hub_file(f"{HUB_SUBPATH}/adjustments_{period}.json",
                                   payload.encode("utf8"))
            except Exception as exc:
                raise AdjustmentSavedLocallyOnly(
                    f"Saved on this machine, but SharePoint refused it "
                    f"({type(exc).__name__}). The correction is NOT safe yet — "
                    f"tell whoever maintains the report before relying on it.")
    return entry


def post_move(period: str, field: str, territory: str, from_month: str,
              to_month: str, amount, why: str, who: str,
              member_id: Optional[str] = None, member: Optional[str] = None,
              store_dir: Optional[Path] = None,
              now: Optional[str] = None) -> List[dict]:
    """Move an amount between two months as ONE action: out of, and into.

    Both entries share a `group`, so the pair is visible as a pair. A move is
    never two independent posts — that is the shape of the 8/13 near-miss,
    where taking a member out of one month without putting them in another
    (or the reverse) silently lost or doubled them.
    """
    if from_month == to_month:
        raise AdjustmentRefused("A move needs two different months.")
    size = abs(float(amount))
    stamp = now or datetime.now().astimezone().isoformat(timespec="seconds")
    # uuid, not a timestamp: two moves on the same cell in the same second
    # would otherwise merge into one group and read as a single action.
    group = f"mv-{uuid4().hex[:12]}"
    out = post(period, field, territory, from_month, -size, why, who,
               member_id, member, group, store_dir, stamp)
    into = post(period, field, territory, to_month, size, why, who,
                member_id, member, group, store_dir, stamp)
    return [out, into]


def total_for(entries: Iterable[dict], field: str, territory: str,
              month: str) -> float:
    """Net adjustment for one cell."""
    return float(sum(e.get("delta") or 0 for e in entries
                     if e.get("field") == field
                     and e.get("territory") == territory
                     and e.get("month") == month))


def by_cell(entries: Iterable[dict]) -> Dict[tuple, float]:
    """{(field, territory, month): net delta} — every cell an overlay touches."""
    out: Dict[tuple, float] = {}
    for e in entries:
        key = (e.get("field"), e.get("territory"), e.get("month"))
        # month is legitimately None for the per-territory penetration counts,
        # so only a missing field or territory disqualifies an entry.
        if key[0] is None or key[1] is None:
            continue
        out[key] = out.get(key, 0.0) + float(e.get("delta") or 0)
    return out


def for_cell(entries: Iterable[dict], field: str, territory: str,
             month: str) -> List[dict]:
    """Every entry behind one cell, oldest first — what Trace shows."""
    return [e for e in entries
            if e.get("field") == field
            and e.get("territory") == territory
            and e.get("month") == month]


def apply_to(data, entries: Iterable[dict],
             recompute=None) -> List[str]:
    """Add every adjustment onto `data`'s base fields. Returns notes for the log.

    `data` is a ScoreboardData (attribute dicts: `data.<field>[territory][month]`)
    or anything shaped like one. Only fields the object already carries are
    touched — an adjustment naming a field this build does not have is reported
    and skipped rather than inventing an attribute.

    CALL THIS AFTER `apply_frozen`. Earlier and it is either photographed into
    the seal (then re-applied forever) or wiped by apply_frozen's
    `target.clear()`. See this module's docstring for the verified order.

    `recompute(data, touched)` is the derived-value pass — percentages,
    "48/58" strings, status colours, rollups. It is a REQUIRED argument in
    practice: base numbers moving while their percentages sit stale is exactly
    the 2026-08-13 frozen-block defect. Passing None is allowed only for
    testing the mechanical layer in isolation.
    """
    notes: List[str] = []
    touched: List[tuple] = []
    for (field, territory, month), delta in sorted(by_cell(entries).items()):
        if not delta:
            continue
        grid = getattr(data, field, None)
        if not isinstance(grid, dict):
            notes.append(f"adjustment skipped — this build has no '{field}'")
            continue
        # Two shapes live side by side: month grids (field[territory][month])
        # and the per-territory penetration counts (field[territory]), which
        # have no month axis at all.
        if month is None:
            if territory not in grid:
                notes.append(
                    f"adjustment skipped — no cell {field} {territory}")
                continue
            before = grid[territory]
        else:
            slot = grid.get(territory)
            if not isinstance(slot, dict) or month not in slot:
                notes.append(
                    f"adjustment skipped — no cell {field} {territory} {month}")
                continue
            before = slot[month]
        base = 0.0 if before is None else float(before)
        after = base + delta
        if after < 0:
            # A correction may not drive a cell below zero: that is arithmetic
            # nobody can explain to a reader, and it always means the entry (or
            # its sign) is wrong.
            notes.append(
                f"adjustment REFUSED — {field} {territory} {month} would go "
                f"{base:g} → {after:g}")
            continue
        if month is None:
            grid[territory] = after
        else:
            grid[territory][month] = after
        touched.append((field, territory, month))
        notes.append(f"adjusted {field} {territory} {month}: {base:g} → {after:g}")

    if recompute is not None and touched:
        notes.extend(recompute(data, touched) or [])
    return notes


# ── the derivation pass ──────────────────────────────────────────────────────
# Verified 2026-08-14 against the live cache: pen_pct is a FRACTION (EastKing
# 0.5166 = (251+29)/(489+53)), not a percentage. Same for retention_pct.
#
# Most of the report's percentages, combined totals, quarter and YTD columns
# are EXCEL formulas over the Data sheet — they recompute for free as long as
# this overlay lands before the mapper. The Python-side derived fields are a
# different matter, and only two things here actually need doing.

# The combined L0 fields come straight from SLX, independently of their
# Target/Non-Target splits — so adjusting a split leaves them disagreeing with
# their own parts. (Verified: EastKing Jul ret_paid 11 = 8 + 3.)
SPLIT_SUMS = {
    "ret_paid":     ("ret_paid_target", "ret_paid_non_target"),
    "ret_billed":   ("ret_billed_target", "ret_billed_non_target"),
    "revenue":      ("revenue_target", "revenue_non_target"),
    "new_members":  ("new_members_target", "new_members_non_target"),
    "hosp_bills":   ("hosp_bills_target", "hosp_bills_non_target"),
    # Added 8/14 after Jiho checked more than one row: correcting
    # "Retention - Comped Target ($)" moved the Target line (TM row 58) while
    # the COMBINED line (row 24) stayed stale, because that row reads its own
    # stored field. Any family with a stored combined AND a T/NT pair belongs
    # here — the report shows both, so both must agree.
    "ret_comped":         ("ret_comped_target", "ret_comped_non_target"),
    "ret_comped_dollars": ("ret_comped_dollars_target",
                           "ret_comped_dollars_non_target"),
    "revenue_bob":        ("revenue_bob_target", "revenue_bob_non_target"),
}

PEN_TERMS = {
    "pen_pct": (("pen_active_restaurant", "pen_active_lodging"),
                ("pen_market_restaurant", "pen_market_lodging")),
}


def _cell(data, field, territory, month):
    grid = getattr(data, field, None)
    if not isinstance(grid, dict):
        return None
    slot = grid.get(territory)
    if month is None:
        return slot if not isinstance(slot, dict) else None
    return slot.get(month) if isinstance(slot, dict) else None


def recompute(data, touched: Iterable[tuple]) -> List[str]:
    """Bring the values derived from an adjusted base back into line.

    Deliberately narrow. The report's own percentages, statuses, combined
    lines, quarter and YTD columns are Excel formulas over the Data sheet, so
    they follow automatically once the mapper sees adjusted counts. What Python
    still owes:

      · the COMBINED counts, which SLX supplies independently of the splits;
      · `pen_pct`, the one derived field the mapper actually reads.

    The wider aggregates (`ytd_*`, `statewide_*`, `avg_retention`, `trend`,
    `mom_change`, …) are computed, cached and sealed but read by NOTHING in the
    report — verified by grepping mapper, writer, trend_sheet and the console.
    They are left alone rather than half-reimplemented here; the seal
    photographs them pre-adjustment on purpose, which is what keeps "what the
    program computed" recoverable.
    """
    notes: List[str] = []
    cells = {(t, m) for _f, t, m in touched if m is not None}
    terrs = {t for _f, t, _m in touched}

    for combined, (a, b) in SPLIT_SUMS.items():
        grid = getattr(data, combined, None)
        if not isinstance(grid, dict):
            continue
        for territory, month in sorted(cells):
            slot = grid.get(territory)
            if not isinstance(slot, dict) or month not in slot:
                continue
            left, right = (_cell(data, a, territory, month),
                           _cell(data, b, territory, month))
            if left is None and right is None:
                continue
            total = (left or 0) + (right or 0)
            if slot[month] != total:
                notes.append(f"recomputed {combined} {territory} {month}: "
                             f"{slot[month]} → {total}")
                slot[month] = total

    # combined_bills sits one level up: hospitality (itself a split sum) + allied
    grid = getattr(data, "combined_bills", None)
    if isinstance(grid, dict):
        for territory, month in sorted(cells):
            slot = grid.get(territory)
            if not isinstance(slot, dict) or month not in slot:
                continue
            hosp = _cell(data, "hosp_bills", territory, month)
            allied = _cell(data, "allied_bills", territory, month)
            if hosp is None and allied is None:
                continue
            total = (hosp or 0) + (allied or 0)
            if slot[month] != total:
                notes.append(f"recomputed combined_bills {territory} {month}: "
                             f"{slot[month]} → {total}")
                slot[month] = total

    for target, (actives, markets) in PEN_TERMS.items():
        grid = getattr(data, target, None)
        if not isinstance(grid, dict):
            continue
        for territory in sorted(terrs):
            if territory not in grid:
                continue
            act = [_cell(data, f, territory, None) for f in actives]
            mkt = [_cell(data, f, territory, None) for f in markets]
            if all(v is None for v in act):
                continue
            denom = sum(v or 0 for v in mkt)
            value = None if not denom else sum(v or 0 for v in act) / denom
            if grid[territory] != value:
                notes.append(f"recomputed {target} {territory}: "
                             f"{grid[territory]} → {value}")
                grid[territory] = value
    return notes


def periods_of_fy(fy_start: int) -> List[str]:
    """Every period of one fiscal year, Oct(fy_start) → Sep(fy_start + 1)."""
    out = []
    for i in range(12):
        m = (10 + i - 1) % 12 + 1
        y = fy_start if m >= 10 else fy_start + 1
        out.append(f"{y}-{m:02d}")
    return out


def load_fy(fy_start: int, store_dir: Optional[Path] = None) -> List[dict]:
    """Every correction made anywhere in one fiscal year, oldest first.

    THE REPORT IS THE FISCAL YEAR, NOT THE MONTH (found 8/14 by Jiho). A
    correction is filed under the period whose report was open when it was
    made — correct July's column from the August report and it lands in
    August's file. But every later report shows that same July column, so
    loading only the built period's file made the correction visible on the
    August report and invisible on September's. Corrections are collected
    across the fiscal year and applied by the month each one names.

    The fiscal-year bound is the guard `apply_frozen` needs explicitly: a
    FY25-26 correction is unreachable from a FY26-27 build because that year's
    periods are never read.
    """
    out: List[dict] = []
    for period in periods_of_fy(fy_start):
        out.extend(load(period, store_dir))
    out.sort(key=lambda e: str(e.get("at") or ""))
    return out


def fy_start_of(period: str) -> int:
    """Fiscal year a 'YYYY-MM' period belongs to (FY runs Oct → Sep)."""
    year, month = int(period[:4]), int(period[5:7])
    return year if month >= 10 else year - 1


def for_build(entries: Iterable[dict], period: str) -> List[dict]:
    """The corrections that apply when building `period`'s report.

    Two different keys, because the data has two shapes:

      · A correction naming a MONTH applies to that column on every report of
        the fiscal year — the August report and the September report show the
        same July column, so a July fix must appear on both.
      · A correction with NO month (the per-territory penetration counts) has
        no column to follow. Each period's snapshot IS one photograph, so it
        belongs to the period it was filed under and nowhere else. Without
        this, a June penetration fix also moved May's photo — caught by
        test_a_correction_to_one_month_does_not_touch_another, 8/14.
    """
    return [e for e in entries
            if e.get("month") or e.get("_period") in (None, period)]
