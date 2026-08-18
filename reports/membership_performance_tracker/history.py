"""
history.py — the history assembler (Jiho, 2026-07-22).

Point-in-time ("photo") metrics — penetration counts and percentages,
billables — are only true for the day they were pulled. Each monthly pull
already preserves its photo in that period's cache file
(data/cache/scoreboard_YYYY-MM.json) and in the official SharePoint snapshot.
Without assembly, a report only shows the CURRENT pull's photo and every
prior month reads blank — so trends aren't analyzable.

The assembler walks each PRIOR fiscal month at report time, loads that
month's own cache (SharePoint official snapshot as fallback), runs the SAME
mapper over it, and keeps only that month's photo rows. The writer's normal
upsert places them. One source of truth per month, each month photographed
by its own pull.

Honesty rule: a month with no stored photo stays blank on the report — the
capture history starts June 2026 (earlier photos were never taken and are
not fabricated).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from reports.membership_performance_tracker.logic import adjustments as _adjustments
from reports.membership_performance_tracker.mapper import (
    METRIC_FIELD_MAP, TrackerV4Mapper)

# Metric kinds that are photographs of the pull day (vs. transactional
# history, which every pull recomputes correctly for all months).
PHOTO_KINDS = frozenset({"t", "derived", "tm_current"})

PHOTO_METRICS = frozenset(
    name for name, (kind, _f) in METRIC_FIELD_MAP.items() if kind in PHOTO_KINDS
)

# Fiscal-year month order (Oct start — AGENTS.md hard rule 2)
_FY_ORDER = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
             "Apr", "May", "Jun", "Jul", "Aug", "Sep"]


def _period_for(month_abb: str, fiscal_year_start: int) -> str:
    """'Jun' + fy_start 2025 → '2026-06' (Oct–Dec belong to fy_start)."""
    month_int = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                 "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}[month_abb]
    year = fiscal_year_start if month_int >= 10 else fiscal_year_start + 1
    return f"{year}-{month_int:02d}"


# A photo is only honest if taken NEAR its month: within this many days after
# the period ends (Shannon's cadence photographs on the 1st; slack for late
# runs). A March-period cache pulled in July is JULY's state wearing a March
# label — rejected, month stays blank.
PHOTO_FRESHNESS_DAYS = 35


def _photo_is_fresh(period: str, saved_at: str) -> bool:
    """saved_at MUST be the photograph's own clock (pulled_at), not the
    file-write clock — see _snapshot_taken_at (S6, overnight review 8/10)."""
    from datetime import datetime, timedelta
    try:
        y, m = int(period[:4]), int(period[5:7])
        period_end = (datetime(y + (m == 12), (m % 12) + 1, 1))
        taken = datetime.fromisoformat(str(saved_at)[:19])
        return taken <= period_end + timedelta(days=PHOTO_FRESHNESS_DAYS)
    except (ValueError, TypeError):
        return False   # unknown capture time — never guess


def _load_snapshot(period: str, cache_dir: Path, sp_fallback: bool = False):
    """That period's saved numbers: local cache first; official SharePoint
    snapshot only when the caller opts in (production runs do; tests don't).
    Snapshots whose capture date is too far past their period are REJECTED
    (their photo shows a later month's state)."""
    import json
    from reports.membership_performance_tracker.logic.cache import (
        load_scoreboard, scoreboard_from_dict)
    local = cache_dir / f"scoreboard_{period}.json"
    if local.exists():
        meta = (json.loads(local.read_text()).get("_meta") or {})
        # S6 (overnight review 8/10): saved_at is the FILE-WRITE clock and
        # every rebuild re-stamps it, so a sealed month rebuilt >35 days
        # after it ended failed its own freshness test and its photo went
        # blank in every later edition. pulled_at is the PHOTOGRAPH's clock
        # (carried forward untouched by non-live saves) — the honest one.
        # Both stamps are candidate capture times; reject only when EVERY
        # one says "too late". pulled_at survives rebuilds, saved_at does
        # not — requiring both to be fresh is what blanked sealed months.
        stamps = [meta.get("pulled_at"), meta.get("saved_at")]
        taken = next((t for t in stamps if t), None)
        if not any(_photo_is_fresh(period, t) for t in stamps if t):
            print(f"  [history] {period}: snapshot exists but was captured "
                  f"{taken!r} — too late to be {period}'s photo; skipped")
            return None
        return load_scoreboard(local)
    if not sp_fallback:
        return None
    try:
        from src.hub.datahub import DataHub  # optional SP fallback
        hub = DataHub.connect(require_sharepoint=True)
        import json
        raw = hub.read_hub_file(
            f"Audit & History Log/Snapshots/{period}/snapshot_{period}_official.json")
        payload = json.loads(raw)
        return scoreboard_from_dict(payload.get("data") or payload.get("fields") or {})
    except Exception:
        return None


def assemble_photo_history(
    current_month: str,
    fiscal_year_start: int,
    cache_dir: Path,
    sp_fallback: bool = False,
) -> List[Dict[str, Any]]:
    """
    Photo-metric rows for every PRIOR fiscal month that has a stored snapshot.

    Args:
        current_month:      This run's month ('Jul') — prior months only.
        fiscal_year_start:  e.g. 2025 for FY 2025-26.
        cache_dir:          data/cache directory holding scoreboard_*.json.

    Returns:
        Mapper-shaped rows (year, month, territory, metric, value, notes)
        restricted to PHOTO_METRICS × each snapshot's own month. Months with
        no snapshot contribute nothing (blank on the report — honest).
    """
    rows: List[Dict[str, Any]] = []
    if current_month not in _FY_ORDER:
        return rows
    # Once, not once per month: this reads up to twelve stores.
    _fy_entries = _adjustments.load_fy(fiscal_year_start)
    for month_abb in _FY_ORDER[:_FY_ORDER.index(current_month)]:
        period = _period_for(month_abb, fiscal_year_start)
        data = _load_snapshot(period, cache_dir, sp_fallback=sp_fallback)
        if data is None:
            continue
        # THE SECOND APPLY DOOR (2026-08-14). A past month's photo metrics —
        # billables, member locations, penetration — reach a later report
        # through here, re-mapped from that month's OWN cache. The cache is
        # deliberately the program's own numbers, so without this a hand
        # correction to a photo metric would show on its own month's report
        # and then silently revert in every later month's column. Each month
        # carries its own corrections, hence load(period) inside the loop.
        _entries = _adjustments.for_build(_fy_entries, period)
        if _entries:
            for note in _adjustments.apply_to(data, _entries,
                                              recompute=_adjustments.recompute):
                print(f"  [history] {month_abb}: {note}")
        mapper = TrackerV4Mapper(fiscal_year_start=fiscal_year_start,
                                 current_month=month_abb)
        for row in mapper.map(data):
            if row["metric"] in PHOTO_METRICS and row["month"] == month_abb:
                rows.append(row)
        print(f"  [history] {month_abb}: photo metrics assembled from "
              f"scoreboard_{period}.json")
    return rows
