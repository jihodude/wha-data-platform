"""
mapper.py — TrackerV4Mapper: ScoreboardData → long-form metric rows.

Produces rows for the v4 tracker's `Data - Monthly Metrics` sheet. Each row is a
single (Year, Month, Territory, Metric, Value) tuple matching the long-form
schema confirmed from the v4 template:

    Row 4 (headers): Year | Month | Territory | Metric | Value | Notes
    Row 5+: data rows

This mapper does NOT write to a file — it returns a list of dicts that the
writer consumes. Keeping the two layers separate means we can:
  • Test the mapper in isolation (no Excel dependency)
  • Reuse mapped rows for other targets (SharePoint cache, JSON export, etc.)
  • Swap output formats without touching the data-shape logic

Metric naming:
    Every key in METRIC_FIELD_MAP corresponds to an exact metric string in the
    v4 template's `Ref - Metrics` sheet (col A). Mismatches mean broken lookups
    in the TM sheet formulas — these strings must NOT drift from the template.

Territory naming:
    Internal canonical names ('EastKing', 'SouthKing', 'NorthKing') get
    translated to v4 display names ('East King', 'South King', 'North King').
    Other territories pass through unchanged. Uses CANONICAL_TO_TRACKER from
    reports.membership_performance_tracker.logic.drops as the single source of truth.

Year resolution:
    Oct/Nov/Dec belong to fiscal_year_start (e.g. 2025 for FY 2025-26)
    Jan-Sep belong to fiscal_year_start + 1
    The tracker stores data across multiple calendar years so the mapper accepts
    a `year` parameter overridable per call for historical backfills.

Penetration + billables metrics:
    These are point-in-time (current-month only). The engine queries them once for
    `current_month`; prior months have no data. The mapper writes them only for
    `current_month` so the trend sheet shows the actual snapshot month rather than
    repeating the same value (or 0) across Jan/Feb/Mar. Historical months will
    populate once the 2024/2025 backfill runs.

Percentages stored as decimals:
    Per v4 README — store 0.917, not 91.7 (the template formats as %).

Usage:
    from reports.membership_performance_tracker.mapper import TrackerV4Mapper
    mapper = TrackerV4Mapper(fiscal_year_start=2025)
    rows = mapper.map(data)
    # rows is list[dict] with keys: year, month, territory, metric, value, notes
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from reports.membership_performance_tracker.logic.drops import CANONICAL_TO_TRACKER
from reports.membership_performance_tracker.logic.model import ScoreboardData, TERRITORY_ORDER


# ---------------------------------------------------------------------------
# Metric name → ScoreboardData field lookup
# ---------------------------------------------------------------------------
# Each entry: v4 metric string → (kind, field_name)
#   kind = "tm"         → field is data.<field>[territory][month]  (every month)
#   kind = "tm_current" → field is data.<field>[territory][month]  (snapshot month only)
#   kind = "t"          → field is data.<field>[territory]  (constant across months)
#   kind = "derived"    → handled in _emit_derived_rows()
#
# "tm_current" exists for point-in-time-with-T/M-shape fields like billables:
# the engine writes only current_month today, but the field SHAPE is [t][m]. If
# the engine ever backfills prior months (intentionally or by accident), the
# "tm" path would emit them and the trend sheet would surface stale data as
# real history. "tm_current" guarantees the snapshot-month-only contract at the
# mapper layer, independent of engine behavior.

# Goals — admin input (currently in goal[t][m] for revenue; others pending wiring)
METRIC_FIELD_MAP: Dict[str, tuple] = {
    # Goals
    "Goal - New Sales Revenue ($)":             ("tm", "goal"),
    "Goal - New Members (#)":                   ("tm", "goal_members"),
    "Goal - Retention %":                       ("tm", "goal_retention"),
    # admin per-territory penetration goal (8/6): drives the status colors —
    # emitted per build month so each month's % colors against its own goal
    "Goal - Penetration %":                     ("t", "goal_penetration"),
    # New sales
    "New Sales Revenue - Target ($)":           ("tm", "revenue_target"),
    "BOB - Target ($)":                         ("tm", "revenue_bob_target"),
    "BOB - Non-Target ($)":                     ("tm", "revenue_bob_non_target"),
    "New Sales Revenue - Non-Target ($)":       ("tm", "revenue_non_target"),
    "New Sales Revenue - BOB/Promo ($)":        ("tm", "revenue_bob"),
    # Comp lines (ruled 2026-08-04) — visibility, outside the % calc
    "New Sales - Comped ($)":                   ("tm", "revenue_comped_new"),
    "Retention - Comped (#)":                   ("tm", "ret_comped"),
    "Retention - Comped ($)":                   ("tm", "ret_comped_dollars"),
    # band split (ruled 8/5) — the T3/N3 comp rows; T+NT == combined
    "Retention - Comped Target (#)":            ("tm", "ret_comped_target"),
    "Retention - Comped Non-Target (#)":        ("tm", "ret_comped_non_target"),
    "Retention - Comped Target ($)":            ("tm", "ret_comped_dollars_target"),
    "Retention - Comped Non-Target ($)":        ("tm", "ret_comped_dollars_non_target"),
    "Retention - BOB (#)":                      ("tm", "ret_bob"),
    "Retention - BOB ($)":                      ("tm", "ret_bob_dollars"),
    "New Members - Target (#)":                 ("tm", "new_members_target"),
    "New Members - Non-Target (#)":             ("tm", "new_members_non_target"),
    "New Members - BOB (#)":                    ("tm", "new_members_bob"),
    # Billables — point-in-time (engine populates current_month only)
    "Billables - Hospitality Target (#)":       ("tm_current", "hosp_bills_target"),
    "Billables - Hospitality Non-Target (#)":   ("tm_current", "hosp_bills_non_target"),
    "Billables - Allied (#)":                   ("tm_current", "allied_bills"),
    # NOTE: "Billables - NRA (#)" removed 2026-07-17 (meaning audit) — the
    # bm>12 NRA marker was disproven 2026-07-14; NRA chain accounts are counted
    # inside the Majors/NRA territory column, so a dedicated NRA row was a
    # permanent, misleading 0. (The nra_bills field was fully removed 2026-07-19.)
    # Retention — members
    "Members Up for Renewal - Target (#)":      ("tm", "ret_billed_target"),
    "Members Retained - Target (#)":            ("tm", "ret_paid_target"),
    "Members Up for Renewal - Non-Target (#)":  ("tm", "ret_billed_non_target"),
    "Members Retained - Non-Target (#)":        ("tm", "ret_paid_non_target"),
    # Retention — revenue
    "Revenue Up for Renewal - Target ($)":      ("tm", "rev_up_target"),
    "Revenue Retained - Target ($)":            ("tm", "rev_retained_target"),
    "Revenue Up for Renewal - Non-Target ($)":  ("tm", "rev_up_non_target"),
    "Revenue Retained - Non-Target ($)":        ("tm", "rev_retained_non_target"),
    # Drops
    "Drops - Target (#)":                       ("tm", "drops_target"),
    "Drops - Non-Target (#)":                   ("tm", "drops_non_target"),
    "Dropped Revenue - Target ($)":             ("tm", "drops_revenue_target"),
    "Dropped Revenue - Non-Target ($)":         ("tm", "drops_revenue_non_target"),
    # NOTE: "Closed Businesses - Target/Non-Target (#)" removed 2026-07-27
    # (the Crystal pivot). The legacy MPR reported drops and never closures:
    # Jennifer's March 2026 edition carries a bare "Closed/Sold" label with no
    # data and June drops the label entirely. The population was also 73% chain
    # locations (Starbucks stores, Jack in the Box #8324…) whose dues live on a
    # parent record — a closed location, not a lost member — and Crystal's drop
    # reports already carry the dues-carrying closures under Status Reason
    # "Out of Business", so a separate row would double-count them. The
    # closed_* fields and the template's Closed sheet/dashboard cells still
    # exist; they come out in the template pass.
    # Penetration — static per territory (mapper repeats value across all months)
    "Total Target Locations - Restaurant (#)":  ("t", "pen_market_restaurant"),
    "Total Target Locations - Lodging (#)":     ("t", "pen_market_lodging"),
    "Target Members - Restaurant (#)":          ("t", "pen_active_restaurant"),
    "Target Members - Lodging (#)":             ("t", "pen_active_lodging"),
    "Penetration - Restaurant %":               ("derived", "pen_restaurant_pct"),
    "Penetration - Lodging %":                  ("derived", "pen_lodging_pct"),
    "Penetration - Combined %":                 ("t", "pen_pct"),
    # Non-Target penetration — sub-threshold hospitality (smaller restaurants
    # / smaller hotels). Engine populates pen_active_nt_* and pen_market_nt_*
    # via compute_penetration_by_segment; the % is divided at map-time using
    # the same Active / (Active + Inactive) formula as the Target pool.
    "Non-Target Locations - Restaurant (#)":    ("t", "pen_market_nt_restaurant"),
    "Non-Target Locations - Lodging (#)":       ("t", "pen_market_nt_lodging"),
    "Non-Target Members - Restaurant (#)":      ("t", "pen_active_nt_restaurant"),
    "Non-Target Members - Lodging (#)":         ("t", "pen_active_nt_lodging"),
    # Member Locations (ruled 8/5 — Anthony's consolidation check: billables
    # drop + locations flat = a consolidation, not a loss). Per band, summed
    # restaurant + lodging actives from the penetration sweep; the TM sheets
    # place one line under each section's billables row. Consolidation is not
    # target-by-definition (a franchise of small units is a non-target
    # corporate), hence a line per band.
    "Member Locations - Target (#)":            ("derived", "member_locations_target"),
    "Member Locations - Non-Target (#)":        ("derived", "member_locations_nt"),
    "Penetration - Restaurant Non-Target %":    ("derived", "pen_nt_restaurant_pct"),
    "Penetration - Lodging Non-Target %":       ("derived", "pen_nt_lodging_pct"),
    "Penetration - Combined Non-Target %":      ("derived", "pen_nt_combined_pct"),
}

# Fiscal-year month sequence — Oct starts the WHA fiscal year (Oct 1 → Sep 30)
FY_MONTH_ORDER: List[str] = [
    "Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
    "Apr", "May", "Jun", "Jul", "Aug", "Sep",
]

MONTH_TO_INT: Dict[str, int] = {
    "Jan": 1,  "Feb": 2,  "Mar": 3,  "Apr": 4,
    "May": 5,  "Jun": 6,  "Jul": 7,  "Aug": 8,
    "Sep": 9,  "Oct": 10, "Nov": 11, "Dec": 12,
}


# ---------------------------------------------------------------------------
# Mapper
# ---------------------------------------------------------------------------

@dataclass
class TrackerV4Mapper:
    """
    Maps ScoreboardData → long-form metric rows for the v4 tracker.

    Args:
        fiscal_year_start: Calendar year when fiscal year begins (e.g. 2025 for FY 2025-26).
                           Used to assign each month abbreviation to the correct
                           calendar year (Oct-Dec → fy_start; Jan-Sep → fy_start+1).
        current_month:     The month this run was executed for (e.g. "Mar"). Point-in-time
                           metrics (billables, penetration) are only written for this month;
                           they are not repeated across all months (that would be misleading).
    """
    fiscal_year_start: int = 2025
    current_month: Optional[str] = None

    def map(self, data: ScoreboardData) -> List[Dict[str, Any]]:
        """
        Walk every (metric × territory × month) cell and emit one row each.

        Skips None values — the v4 sheet treats empty cells as "no data". This
        means a partial run (e.g. only current_month populated for billables)
        only writes rows for the months that actually have data.

        Returns:
            List of dicts shaped:
                {
                    "year":      int,    # e.g. 2026
                    "month":     str,    # 3-char abbreviation, e.g. "Mar"
                    "territory": str,    # v4 display name, e.g. "East King"
                    "metric":    str,    # exact v4 metric string
                    "value":     number, # numeric value (decimals for %)
                    "notes":     str,    # always "" for now; reserved for flags
                }
        """
        rows: List[Dict[str, Any]] = []

        # Find which months are populated in this run by inspecting a known field
        # (revenue is populated for every month we queried). Falls back to FY order.
        sample_field = data.revenue
        populated_months: List[str]
        if sample_field:
            any_territory = next(iter(sample_field.keys()), None)
            if any_territory and sample_field[any_territory]:
                populated_months = list(sample_field[any_territory].keys())
            else:
                populated_months = FY_MONTH_ORDER
        else:
            populated_months = FY_MONTH_ORDER

        # Point-in-time metrics only emit for current_month (not all months).
        # If current_month is unset, fall back to the last populated month.
        snapshot_month = self.current_month or (populated_months[-1] if populated_months else None)

        for metric_name, (kind, field_name) in METRIC_FIELD_MAP.items():
            if kind == "tm":
                self._emit_tm_rows(rows, data, metric_name, field_name, populated_months)
            elif kind == "tm_current":
                # Point-in-time [t][m] fields (billables) — current month only.
                # Same emitter as "tm", restricted to a single month so prior-month
                # cells in the trend sheet stay empty regardless of engine behavior.
                if snapshot_month:
                    self._emit_tm_rows(rows, data, metric_name, field_name, [snapshot_month])
            elif kind == "t":
                # Static-per-territory (penetration counts) — current month only
                if snapshot_month:
                    self._emit_t_rows(rows, data, metric_name, field_name, [snapshot_month])
            elif kind == "derived":
                # Derived from static fields (pen %) — current month only
                if snapshot_month:
                    self._emit_derived_rows(rows, data, metric_name, field_name, [snapshot_month])

        # B10 (7/16): per-category drop rollups — one metric per category so
        # the data sheet answers "WHY did we lose members" month by month.
        # Field shape: {category: {territory: {month: n}}}.
        for cat, terr_grid in (getattr(data, "drops_by_category", None) or {}).items():
            metric_name = f"Drops - {cat} (#)"
            for territory, months in terr_grid.items():
                display = CANONICAL_TO_TRACKER.get(territory, territory)
                for month_abb, val in (months or {}).items():
                    if val is None or month_abb not in FY_MONTH_ORDER:
                        continue
                    rows.append({
                        "year": self._year_for_month(month_abb),
                        "month": month_abb,
                        "territory": display,
                        "metric": metric_name,
                        "value": val,
                        "notes": "",
                    })

        return rows

    # ------------------------------------------------------------------
    # Emitters
    # ------------------------------------------------------------------

    def _emit_tm_rows(
        self,
        rows: List[Dict[str, Any]],
        data: ScoreboardData,
        metric_name: str,
        field_name: str,
        months: List[str],
    ) -> None:
        """Emit one row per territory × month for a [t][m] field."""
        field = getattr(data, field_name, None)
        if not isinstance(field, dict):
            return
        for canonical in TERRITORY_ORDER:
            per_month = field.get(canonical) or {}
            tracker_name = CANONICAL_TO_TRACKER.get(canonical, canonical)
            for month in months:
                value = per_month.get(month)
                if value is None:
                    continue
                rows.append({
                    "year":      self._year_for_month(month),
                    "month":     month,
                    "territory": tracker_name,
                    "metric":    metric_name,
                    "value":     value,
                    "notes":     "",
                })

    def _emit_t_rows(
        self,
        rows: List[Dict[str, Any]],
        data: ScoreboardData,
        metric_name: str,
        field_name: str,
        months: List[str],
    ) -> None:
        """Emit identical value across all months for a [t] (static-per-territory) field."""
        field = getattr(data, field_name, None)
        if not isinstance(field, dict):
            return
        for canonical in TERRITORY_ORDER:
            value = field.get(canonical)
            if value is None:
                continue
            tracker_name = CANONICAL_TO_TRACKER.get(canonical, canonical)
            for month in months:
                rows.append({
                    "year":      self._year_for_month(month),
                    "month":     month,
                    "territory": tracker_name,
                    "metric":    metric_name,
                    "value":     value,
                    "notes":     "",
                })

    def _emit_derived_rows(
        self,
        rows: List[Dict[str, Any]],
        data: ScoreboardData,
        metric_name: str,
        field_name: str,
        months: List[str],
    ) -> None:
        """
        Derived metrics computed at map-time (segment-level penetration %).

        These aren't stored as fields on the model — the underlying numerator
        and denominator are, so we divide here.
        """
        if field_name == "pen_restaurant_pct":
            num_field = data.pen_active_restaurant
            den_field = data.pen_market_restaurant
        elif field_name == "pen_lodging_pct":
            num_field = data.pen_active_lodging
            den_field = data.pen_market_lodging
        elif field_name == "pen_nt_restaurant_pct":
            num_field = data.pen_active_nt_restaurant
            den_field = data.pen_market_nt_restaurant
        elif field_name == "pen_nt_lodging_pct":
            num_field = data.pen_active_nt_lodging
            den_field = data.pen_market_nt_lodging
        elif field_name in ("member_locations_target", "member_locations_nt"):
            if field_name == "member_locations_target":
                rest, lodg = data.pen_active_restaurant, data.pen_active_lodging
            else:
                rest, lodg = data.pen_active_nt_restaurant, data.pen_active_nt_lodging
            for canonical in TERRITORY_ORDER:
                r_val, l_val = rest.get(canonical), lodg.get(canonical)
                if r_val is None and l_val is None:
                    continue        # never photographed ≠ zero locations
                tracker_name = CANONICAL_TO_TRACKER.get(canonical, canonical)
                for month in months:
                    rows.append({
                        "year":      self._year_for_month(month),
                        "month":     month,
                        "territory": tracker_name,
                        "metric":    metric_name,
                        "value":     (r_val or 0) + (l_val or 0),
                        "notes":     "",
                    })
            return
        elif field_name == "pen_nt_combined_pct":
            # Combined NT is computed at map-time from the two segments because
            # the engine does not store a precomputed pen_pct_nt — keeping the
            # numerator/denominator split avoids drift if one segment is missing
            # for a territory.
            self._emit_nt_combined_rows(rows, data, metric_name, months)
            return
        else:
            return  # unknown derived metric

        for canonical in TERRITORY_ORDER:
            num = num_field.get(canonical)
            den = den_field.get(canonical)
            if num is None or not den:
                continue
            value = num / den
            tracker_name = CANONICAL_TO_TRACKER.get(canonical, canonical)
            for month in months:
                rows.append({
                    "year":      self._year_for_month(month),
                    "month":     month,
                    "territory": tracker_name,
                    "metric":    metric_name,
                    "value":     value,
                    "notes":     "",
                })

    def _emit_nt_combined_rows(
        self,
        rows: List[Dict[str, Any]],
        data: ScoreboardData,
        metric_name: str,
        months: List[str],
    ) -> None:
        """Combined NT % = (rest_active + lodging_active) / (rest_market + lodging_market).

        Missing segments contribute 0 so a territory with only restaurant NT data
        still emits a sensible % (matches Target Combined's handling in engine
        _compute_layer1, which uses 0-coalescing when one segment is absent).
        """
        for canonical in TERRITORY_ORDER:
            active_r = data.pen_active_nt_restaurant.get(canonical) or 0
            active_l = data.pen_active_nt_lodging.get(canonical) or 0
            market_r = data.pen_market_nt_restaurant.get(canonical) or 0
            market_l = data.pen_market_nt_lodging.get(canonical) or 0
            combined_active = active_r + active_l
            combined_market = market_r + market_l
            if not combined_market:
                continue
            value = combined_active / combined_market
            tracker_name = CANONICAL_TO_TRACKER.get(canonical, canonical)
            for month in months:
                rows.append({
                    "year":      self._year_for_month(month),
                    "month":     month,
                    "territory": tracker_name,
                    "metric":    metric_name,
                    "value":     value,
                    "notes":     "",
                })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _year_for_month(self, month_abb: str) -> int:
        """
        Map a 3-char month abbreviation to its calendar year given the fiscal year.

        WHA FY runs Oct → Sep. For FY 2025-26:
            Oct, Nov, Dec → 2025
            Jan, Feb, ..., Sep → 2026
        """
        m_int = MONTH_TO_INT.get(month_abb)
        if m_int is None:
            return self.fiscal_year_start
        return self.fiscal_year_start if m_int >= 10 else self.fiscal_year_start + 1
