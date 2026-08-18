"""
model.py — ScoreboardData: the canonical WHA Membership Data Package.

⚠ This dataclass IS the contract between the scraping engine and every output
  consumer.  Both Phase 1 (Scoreboard xlsx) and Phase 2 (UI/API) read from
  this same shape.  Adding a field here = available everywhere downstream.
  Renaming a field = breaks every consumer.  Deprecate, don't rename.

Architecture:
    SLX queries + external files
              │
              ▼
        ScoreboardEngine      ← reports/membership_performance_tracker/logic/engine.py
              │
              ▼
       ┌─ ScoreboardData ─┐   ← THIS FILE
       │  (the package)   │
       └──────────────────┘
              │
       ┌──────┴──────┐
       ▼             ▼
   xlsx writer   UI / API
   (Phase 1)     (Phase 2)

Computation layers (all live in this single dataclass):
  L0 atomic        — raw values from SLX + external files
  L1 elementwise   — per-cell derived values (no aggregation)
  L2 aggregations  — sums/means across territory or month
  L3 season-level  — ratios, status flags, cross-month comparisons

Axes:
  t ∈ TERRITORY_ORDER     11 canonical territory names
  m ∈ months              month abbreviations, order set at runtime

Two-axis variables  → Dict[territory, Dict[month, value]]
Single-axis (terr.) → Dict[territory, value]
Single-axis (month) → Dict[month, value]

Usage:
    from reports.membership_performance_tracker.logic.model import ScoreboardData, empty_scoreboard
    data = empty_scoreboard(months=["Oct","Nov","Dec","Jan","Feb","Mar"])
    data.revenue["Pierce"]["Mar"] = 12000.0
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Canonical territory ordering (matches Scoreboard row order exactly)
# ---------------------------------------------------------------------------
TERRITORY_ORDER: List[str] = [
    "EastKing",
    "SouthKing",
    "NorthKing",
    "Pierce",
    "Snohomish",
    "Spokane/NE",
    "Southwest",
    "TKP",
    "Southeast",
    "NorthCentral",
    "Majors/NRA",
]


@dataclass
class ScoreboardData:
    """
    Typed container for all Scoreboard variables across four computation layers.

    All fields are mutable dicts populated in-place by ScoreboardEngine.
    Fields default to empty dicts; call empty_scoreboard() for pre-seeded None-filled
    structures when you need explicit None sentinels for missing data.
    """

    # ------------------------------------------------------------------
    # LAYER 0 — Atomic (direct SLX queries or external file parsers)
    # ------------------------------------------------------------------

    # revenue[t][m]: new-sales revenue (PAID dues) for the month, computed from SLX
    #   invoices (dlInvoiceHistoryHeader) — NOT from sales_goals.xlsx (that is the GOAL).
    revenue: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)

    # goal[t][m]: monthly sales goal, from the admin Sales Goals sheet (admin_inputs.xlsx)
    goal: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)

    # hosp_bills[t][m]: hospitality billable count (post-ITD snapshot). Ratified
    #   2026-07-14: an ACTIVE account CARRYING A MEMBERSHIP BILL; Hospitality vs
    #   Allied is decided by the membership PRODUCT (see billables.py), NOT the old
    #   'Type != Allied AND ParentId eq null' rule.
    hosp_bills: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)

    # allied_bills[t][m]: allied billable count (post-ITD snapshot)
    #   accounts WHERE Status=Active AND Type=Allied
    allied_bills: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)


    # ret_paid[t][m]: unique accounts with Balance=0.0 in dlInvoiceHistoryHeader
    #   for bill_month=m, within tight date window
    ret_paid: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)

    # ret_billed[t][m]: total unique accounts billed (any Balance) for bill_month=m
    ret_billed: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)

    # new_members[t][m]: accounts enrolled within [month_start, month_end]
    #   excludes reinstatements (Salescode='510', ReinstatedDate set)
    new_members: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Target / Non-Target split fields (for v4 tracker long-form output)
    # ------------------------------------------------------------------
    # Each metric below mirrors its total counterpart but split by T/NT classification
    # (from reports.membership_performance_tracker.logic.target.build_target_map). 'unknown' accounts (missing FTE/rooms
    # data) are typically merged into non_target for reporting purposes.

    # Revenue
    revenue_target:     Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    revenue_non_target: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)

    # revenue_bob[t][m]: the FACE-VALUE portion of revenue that is BOB/promo
    #   credit (comped — counted as sales per Jen's convention but never
    #   collected as cash). Surfaced so readers can subtract it (Jiho 7/20).
    revenue_bob: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    # Comp lines (ruled 2026-08-04): visibility only — the retention calc is
    # unchanged (comps retained at $0/$0). ret_comped[t][m] = members comped
    # that cycle; ret_comped_dollars = face $ "we could have collected";
    # revenue_comped_new = comped NEW sales (policy: always 0 — a tripwire).
    ret_comped: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)
    ret_comped_dollars: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    # band split (ruled 8/5): combined comp traces to its band; T+NT == combined
    ret_comped_target: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)
    ret_comped_non_target: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)
    ret_comped_dollars_target: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    ret_comped_dollars_non_target: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    revenue_comped_new: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    # BOB renewals (ruled 2026-08-04): count IN retention at face, own line.
    ret_bob: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)
    ret_bob_dollars: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    # Band-scoped BOB face (Jiho 2026-07-22: the single BOB row can't tell the
    # reader WHICH band holds the comped members — Snohomish Oct's $2,225 was
    # 1 Corporate + 3 Allied). Split so band math is possible by inspection.
    revenue_bob_target: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    revenue_bob_non_target: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)

    # New members
    new_members_target:     Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)
    new_members_non_target: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)
    # new-BOB joins (#) — Anthony's count ask, 8/12 demo 22:53
    new_members_bob:        Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)

    # Billables (hospitality only; Allied is always non-target so allied_bills covers it)
    hosp_bills_target:     Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)
    hosp_bills_non_target: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)

    # Retention members
    ret_paid_target:       Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)
    ret_paid_non_target:   Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)
    ret_billed_target:     Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)
    ret_billed_non_target: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)

    # Retention revenue (dollars from dlInvoiceHistoryHeader)
    rev_retained_target:     Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    rev_retained_non_target: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    rev_up_target:           Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    rev_up_non_target:       Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)

    # Drops (counts and dollars)
    drops_target:             Dict[str, Dict[str, Optional[int]]]   = field(default_factory=dict)
    drops_non_target:         Dict[str, Dict[str, Optional[int]]]   = field(default_factory=dict)
    drops_revenue_target:     Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    drops_revenue_non_target: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)

    # Drop counts by CATEGORY (B10, 7/16): {category: {territory: {month: n}}}
    # — Closed/Sold/Non-Payment/Voluntary; Admin+Retro excluded like everywhere.
    drops_by_category: Dict[str, Dict[str, Dict[str, Optional[int]]]] = field(default_factory=dict)

    # Closed businesses
    closed_target:     Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)
    closed_non_target: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)

    # Per-account detail lists (feed Data - Drops and Data - Closed Businesses sheets)
    drops_detail:  List[Dict] = field(default_factory=list)
    closed_detail: List[Dict] = field(default_factory=list)

    # Penetration breakdown by segment (Restaurant / Lodging) — SLX-computed by
    # _query_penetration, optionally substituted by a PenetrationOverride adapter
    # (see reports/membership_performance_tracker/logic/penetration_override.py
    #  + docs/EXTENSION_POINTS.md).
    pen_market_restaurant: Dict[str, Optional[int]] = field(default_factory=dict)
    pen_market_lodging:    Dict[str, Optional[int]] = field(default_factory=dict)
    pen_active_restaurant: Dict[str, Optional[int]] = field(default_factory=dict)
    pen_active_lodging:    Dict[str, Optional[int]] = field(default_factory=dict)

    # Non-Target pool penetration — same math, applied to the sub-threshold
    # population (FTE < 10 for restaurant; rooms < 40 for lodging). Lets the
    # Penetration Report show: of the small-business market, what's our share?
    pen_market_nt_restaurant: Dict[str, Optional[int]] = field(default_factory=dict)
    pen_market_nt_lodging:    Dict[str, Optional[int]] = field(default_factory=dict)
    pen_active_nt_restaurant: Dict[str, Optional[int]] = field(default_factory=dict)
    pen_active_nt_lodging:    Dict[str, Optional[int]] = field(default_factory=dict)

    # Per-(territory, segment) provenance for the penetration counts above:
    # "slx" if the cell came from compute_penetration_by_segment, or
    # "override:<adapter_name>" if a PenetrationOverride supplied it.
    # Shape: {territory: {"restaurant": "slx" | "override:...", "lodging": ...}}
    penetration_source: Dict[str, Dict[str, str]] = field(default_factory=dict)

    # Goals — additional admin-input goal types (revenue goal already in `goal[t][m]`)
    goal_members:   Dict[str, Dict[str, Optional[int]]]   = field(default_factory=dict)
    goal_retention: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)

    # Restaurant penetration goal (statewide default + per-territory overrides).
    # Stored as decimal (0.75 = 75%). Per-territory scalar — does NOT vary by month.
    goal_penetration: Dict[str, Optional[float]] = field(default_factory=dict)


    # rep_name[t]: territory manager display name, from territory_map.yaml
    rep_name: Dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # LAYER 1 — First-Level Derived (elementwise, no aggregation)
    # ------------------------------------------------------------------

    # combined_bills[t][m] = hosp_bills[t][m] + allied_bills[t][m]
    combined_bills: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)

    # attainment_pct[t][m] = revenue / goal, stored as a FRACTION (e.g. 0.95), not %.
    # None when revenue or goal is None, OR when goal == 0 (the % cell stays blank —
    # engine._attainment returns None; it does NOT store raw revenue).
    attainment_pct: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)

    # retention_pct[t][m] = ret_paid / ret_billed
    # Stored as fraction (e.g. 0.917). None for Majors/NRA (no standard billing).
    retention_pct: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)

    # retention_str[t][m]: display string "paid/billed" (e.g. "22/24")
    # "—" for Majors/NRA or months with no billing data
    retention_str: Dict[str, Dict[str, str]] = field(default_factory=dict)

    # pen_pct[t] = combined active / combined market, a FRACTION (e.g. 0.72), where
    # combined = restaurant + lodging from the segment fields above (P1-5: a missing
    # segment contributes zero). Computed in engine._compute_layer1.
    # Scalar per territory; same value repeated across all month columns in Scoreboard
    pen_pct: Dict[str, Optional[float]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # LAYER 2 — Aggregations (linear; see plan for LA notation)
    # ------------------------------------------------------------------

    # ytd_revenue[t] = Σ_m revenue[t][m]  (row sum of R_revenue)
    ytd_revenue: Dict[str, Optional[float]] = field(default_factory=dict)

    # ytd_goal[t] = Σ_m goal[t][m]
    ytd_goal: Dict[str, Optional[float]] = field(default_factory=dict)

    # ytd_members[t] = Σ_m new_members[t][m]
    ytd_members: Dict[str, Optional[int]] = field(default_factory=dict)

    # statewide_revenue[m] = Σ_t revenue[t][m]  (col sum of R_revenue)
    statewide_revenue: Dict[str, Optional[float]] = field(default_factory=dict)

    # statewide_goal[m] = Σ_t goal[t][m]
    statewide_goal: Dict[str, Optional[float]] = field(default_factory=dict)

    # statewide_members[m] = Σ_t new_members[t][m]
    statewide_members: Dict[str, Optional[int]] = field(default_factory=dict)

    # avg_retention[t] = count-WEIGHTED rate Σpaid / Σbilled across billed months
    #   (NOT the unweighted mean of monthly ratios — R4; see engine._compute_layer2).
    avg_retention: Dict[str, Optional[float]] = field(default_factory=dict)

    # statewide_avg_pen = aggregate Σactive / Σmarket across territories (volume-
    #   weighted, NOT the mean of territory rates; P1-5: a missing segment contributes
    #   zero — see engine._compute_layer2).
    statewide_avg_pen: Optional[float] = None

    # ------------------------------------------------------------------
    # LAYER 3 — Season-Level Ratios & Classifications
    # ------------------------------------------------------------------

    # season_attainment[t] = ytd_revenue[t] / ytd_goal[t]  (fraction)
    # None when ytd_goal == 0 (engine._attainment; blank cell, NOT raw revenue).
    season_attainment: Dict[str, Optional[float]] = field(default_factory=dict)

    # dollars_per_member[t] = ytd_revenue[t] / ytd_members[t]
    # None if ytd_members == 0
    dollars_per_member: Dict[str, Optional[float]] = field(default_factory=dict)

    # ret_status[t]: "On Track" (≥92%) / "Watch" (<92%) / "N/A" (no data)
    ret_status: Dict[str, str] = field(default_factory=dict)

    # pen_status[t]: "Above Avg" / "Near Avg" / "Below Avg" / "N/A"
    # Thresholds: ±5% of statewide_avg_pen
    pen_status: Dict[str, str] = field(default_factory=dict)

    # statewide_attainment[m] = statewide_revenue[m] / statewide_goal[m]  (fraction)
    statewide_attainment: Dict[str, Optional[float]] = field(default_factory=dict)

    # mom_change[m] = (sw_revenue[m] - sw_revenue[m-1]) / sw_revenue[m-1]  (fraction)
    # None for the first month (no prior month)
    mom_change: Dict[str, Optional[float]] = field(default_factory=dict)

    # latest_billables[t] = combined_bills[t][last_available_month]
    latest_billables: Dict[str, Optional[int]] = field(default_factory=dict)

    # delta_oct_to_mar[t] = combined_bills[t]["Mar"] - combined_bills[t]["Oct"]
    delta_oct_to_mar: Dict[str, Optional[int]] = field(default_factory=dict)

    # best_month[t]: month abbreviation with highest revenue (e.g. "Mar")
    best_month: Dict[str, Optional[str]] = field(default_factory=dict)

    # trend[t]: revenue direction based on last 3 vs prior 3 months
    # "↑" / "→" / "↓" / "—" (insufficient data)
    trend: Dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # AUDIT — Database-Change events (from src/slx/audit.py)
    # ------------------------------------------------------------------
    # Lists of dicts (engine fills via audit.changes_to_dict).  Each entry has
    # account_id, account_name, field, old_value, new_value, when, by_user_id.
    # The lists span the full reporting window — consumers filter as needed.

    bill_month_changes:     List[Dict] = field(default_factory=list)
    billing_account_changes: List[Dict] = field(default_factory=list)
    status_flips:           List[Dict] = field(default_factory=list)

    # ------------------------------------------------------------------
    # EDGE CASE FLAGS — Events that affect numbers but need admin review
    # ------------------------------------------------------------------

    # bob_new_accounts[t]: BOB (Black-Owned Business) accounts that enrolled
    #   this reporting month, per territory.
    #   BOB accounts are comped ($0 dues in SLX) but count toward rep goal and
    #   as new billables. Admin must apply manual revenue credit for the rep.
    #   Source: accounts WHERE CDiverseOwnership ne null AND enrolled this month.
    #   Each entry: {"account_id": str, "account_name": str, "enrolled_date": str}
    bob_new_accounts: Dict[str, List[Dict]] = field(default_factory=dict)

    # consolidation_events: Accounts that were consolidated this period.
    #   When N accounts merge into 1 corporate parent, billable count drops by N-1.
    #   Surfaces as context for admins when a territory's billable count drops
    #   unexpectedly between months.
    #   Source: Cheryl's SLX "dues adjustment note code" group (field name TBD).
    #   Each entry: {"account_id": str, "account_name": str, "territory": str,
    #                "consolidated_date": str, "accounts_merged": int}
    #   NOTE: field name unconfirmed — consult Cheryl before enabling this query.
    consolidation_events: List[Dict] = field(default_factory=list)


def empty_scoreboard(months: List[str]) -> ScoreboardData:
    """
    Return a ScoreboardData with all T×M fields pre-seeded to None.

    This makes it safe to write partial data: any cell that ScoreboardEngine
    couldn't fill will be None, and scoreboard_writer skips None values.

    Args:
        months: List of month abbreviations in season order, e.g.
                ["Oct","Nov","Dec","Jan","Feb","Mar"]

    Returns:
        ScoreboardData with empty dicts pre-populated for all territories × months.
    """
    territories = TERRITORY_ORDER

    def tm() -> Dict[str, Dict[str, None]]:
        return {t: {m: None for m in months} for t in territories}

    def t_none() -> Dict[str, None]:
        return {t: None for t in territories}

    def t_str(default: str = "—") -> Dict[str, str]:
        return {t: default for t in territories}

    def m_none() -> Dict[str, None]:
        return {m: None for m in months}

    return ScoreboardData(
        # L0
        revenue=tm(),
        goal=tm(),
        hosp_bills=tm(),
        allied_bills=tm(),
        ret_paid=tm(),
        ret_billed=tm(),
        new_members=tm(),
        # T/NT splits — all initialised to None across territory × month
        revenue_target=tm(),
        revenue_non_target=tm(),
        new_members_target=tm(),
        new_members_non_target=tm(),
        new_members_bob=tm(),
        hosp_bills_target=tm(),
        hosp_bills_non_target=tm(),
        ret_paid_target=tm(),
        ret_paid_non_target=tm(),
        ret_billed_target=tm(),
        ret_billed_non_target=tm(),
        rev_retained_target=tm(),
        rev_retained_non_target=tm(),
        rev_up_target=tm(),
        rev_up_non_target=tm(),
        drops_target=tm(),
        drops_non_target=tm(),
        drops_revenue_target=tm(),
        drops_revenue_non_target=tm(),
        closed_target=tm(),
        closed_non_target=tm(),
        # Per-account detail lists
        drops_detail=[],
        closed_detail=[],
        # Penetration breakdown (SLX-computed, optionally overridden)
        pen_market_restaurant=t_none(),
        pen_market_lodging=t_none(),
        pen_active_restaurant=t_none(),
        pen_active_lodging=t_none(),
        pen_market_nt_restaurant=t_none(),
        pen_market_nt_lodging=t_none(),
        pen_active_nt_restaurant=t_none(),
        pen_active_nt_lodging=t_none(),
        penetration_source={t: {} for t in territories},
        goal_penetration=t_none(),
        # Additional goals
        goal_members=tm(),
        goal_retention=tm(),
        revenue_bob=tm(),
        ret_comped=tm(),
        ret_comped_dollars=tm(),
        revenue_comped_new=tm(),
        ret_bob=tm(),
        ret_bob_dollars=tm(),
        revenue_bob_target=tm(),
        revenue_bob_non_target=tm(),
        rep_name=t_str(""),
        # L1
        combined_bills=tm(),
        attainment_pct=tm(),
        retention_pct=tm(),
        retention_str={t: {m: "—" for m in months} for t in territories},
        pen_pct=t_none(),
        # L2
        ytd_revenue=t_none(),
        ytd_goal=t_none(),
        ytd_members=t_none(),
        statewide_revenue=m_none(),
        statewide_goal=m_none(),
        statewide_members=m_none(),
        avg_retention=t_none(),
        statewide_avg_pen=None,
        # L3
        season_attainment=t_none(),
        dollars_per_member=t_none(),
        ret_status=t_str("N/A"),
        pen_status=t_str("N/A"),
        statewide_attainment=m_none(),
        mom_change=m_none(),
        latest_billables=t_none(),
        delta_oct_to_mar=t_none(),
        best_month=t_none(),
        trend=t_str("—"),
        # Edge case flags
        bob_new_accounts={t: [] for t in territories},
        consolidation_events=[],
    )
