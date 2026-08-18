"""
period.py — reporting-period engine.

Single source of truth for "which month are we reporting." Turns a 'YYYY-MM'
period string into the fiscal-year-derived values the report needs, so the
period is one input instead of constants hardcoded across runner/app/datahub.

WHA fiscal year = Oct 1 → Sep 30. `months` is the FY-to-date list (Oct → the
reporting month), which is the set of columns a report through that month covers.
"""
from dataclasses import dataclass
from typing import List

# Canonical fiscal-year month order (Oct = FY start).
FY_MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
             "Apr", "May", "Jun", "Jul", "Aug", "Sep"]

_INT_TO_ABB = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
               7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}


@dataclass(frozen=True)
class Period:
    period: str            # "2026-03"
    year: int              # 2026 (calendar year of the reporting month)
    month: int             # 3
    current_month: str     # "Mar"
    fy_start: int          # 2025 (calendar year the fiscal year began)
    fiscal_year: str       # "2025-26"
    months: List[str]      # FY-to-date, e.g. ["Oct","Nov","Dec","Jan","Feb","Mar"]


def parse_period(period: str) -> Period:
    """Parse a 'YYYY-MM' reporting period into FY-derived values.

    Examples:
        "2026-03" → Mar, FY 2025-26, months Oct..Mar (the current pinned behavior)
        "2026-05" → May, FY 2025-26, months Oct..May
        "2025-10" → Oct, FY 2025-26, months [Oct]
        "2026-09" → Sep, FY 2025-26, months Oct..Sep (full year)
    """
    try:
        y_str, m_str = period.split("-")
        year, month = int(y_str), int(m_str)
    except (ValueError, AttributeError):
        raise ValueError(f"period must be 'YYYY-MM', got {period!r}")
    if not 1 <= month <= 12:
        raise ValueError(f"month out of range in period {period!r}")

    current_month = _INT_TO_ABB[month]
    # Oct-Dec belong to the FY that started this calendar year; Jan-Sep to the
    # FY that started the previous calendar year.
    fy_start = year if month >= 10 else year - 1
    fiscal_year = f"{fy_start}-{str(fy_start + 1)[-2:]}"
    idx = FY_MONTHS.index(current_month)
    months = FY_MONTHS[: idx + 1]  # Oct → reporting month (FY-to-date)

    return Period(
        period=f"{year:04d}-{month:02d}",
        year=year,
        month=month,
        current_month=current_month,
        fy_start=fy_start,
        fiscal_year=fiscal_year,
        months=months,
    )


def list_available_periods(cache_dir) -> List[str]:
    """Periods that actually have data, NEWEST first (Phase C console default).

    Scans `cache_dir` for scoreboard_YYYY-MM.json files. The console opens on
    the first entry instead of a pinned month — the structural fix for the
    March-download incident (a hardcoded default served stale-but-fresh-looking
    data). YYYY-MM sorts lexicographically, so plain sort is chronological.
    """
    import re
    from pathlib import Path
    d = Path(cache_dir)
    if not d.is_dir():
        return []
    pat = re.compile(r"^scoreboard_(\d{4}-\d{2})\.json$")
    found = [m.group(1) for p in d.iterdir() if (m := pat.match(p.name))]
    return sorted(found, reverse=True)
