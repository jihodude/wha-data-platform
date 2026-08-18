"""
engine.py — ScoreboardEngine: queries SLX + parses external files + computes
            all ScoreboardData fields in correct topological order (L0→L1→L2→L3).

Computation pipeline:
    Phase 1: L0 — Query SLX (billables, retention, new_members)
                  Parse external files (sales_goals, penetration)
    Phase 2: L1 — Elementwise derived (combined_bills, attainment_pct,
                                        retention_pct, retention_str, pen_pct)
    Phase 3: L2 — Aggregations (ytd sums, statewide sums, avg_retention,
                                 statewide_avg_pen)
    Phase 4: L3 — Season-level (attainment, status flags, MoM, trend, $/member)

Usage:
    from src.slx.client import SLXClient
    from reports.membership_performance_tracker.logic.engine import ScoreboardEngine

    client = SLXClient(username, password)
    engine = ScoreboardEngine(
        client=client,
        territory_user_map={"U6UJ9A00009Z": "Pierce", ...},
        fiscal_year_start=2025,
        months=["Oct", "Nov", "Dec", "Jan", "Feb", "Mar"],
        current_month="Mar",         # the month being reported this run
        rep_name_map={"Pierce": "Tamorro", ...},
    )
    data = engine.run(
        territory_map=territory_map_yaml,
        fiscal_year="2025-26",
        goals_config_path=Path("config/goals.yaml"),
        # Optional: penetration_override=HannahCsvOverride(...)
        # (see docs/EXTENSION_POINTS.md)
    )
"""

import warnings
from calendar import monthrange
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from reports.membership_performance_tracker.logic.billables import (
    compute_billables_by_target,
)
from reports.membership_performance_tracker.logic.drops import fetch_drops_and_closed
from reports.membership_performance_tracker.logic.model import ScoreboardData, empty_scoreboard
from reports.membership_performance_tracker.logic.retention import compute_retention_all_months, DEFAULT_RETENTION_GOAL
from src.slx.client import SLXClient
from src.slx import audit as _audit


def collect_change_detectors(client, fiscal_year_start: int,
                             flags: Dict[str, list]) -> Dict[str, list]:
    """Run the four change detectors that were declared, implemented, and
    NEVER CALLED (found 8/12: zero call sites; every published scoreboard
    carried them as []). The measured cost of that silence: 6 members filed
    under a different bill month than the live CRM's — four SpokaneNE hotels
    four months off, Hilton Seattle Airport $5,940 — exactly the class
    `bill_month_changes` exists to surface.

    Best-effort by design: the audit history is a secondary surface, so a
    failure here flags loudly (`change_detectors_failed`) and returns empty
    lists rather than killing an 80-minute run. Silent absorption is the
    defect class this repo keeps re-finding — hence the flag, not a pass.

    `consolidation_events` and `billing_account_changes` are one query:
    audit.py defines CBillingAccount changes AS consolidation activity; the
    model keeps both names, so both fields carry the same rows.
    """
    since = date(fiscal_year_start, 10, 1)          # FY = Oct 1 (hard rule 2)
    out = {"bill_month_changes": [], "billing_account_changes": [],
           "status_flips": [], "consolidation_events": []}
    try:
        def _dicts(items):
            return [dict(getattr(i, "__dict__", None) or i) for i in items]
        out["bill_month_changes"] = _dicts(
            _audit.bill_month_changes(client, since=since))
        out["billing_account_changes"] = _dicts(
            _audit.billing_account_changes(client, since=since))
        out["consolidation_events"] = out["billing_account_changes"]
        out["status_flips"] = _dicts(
            _audit.status_flips_within(client, since=since, until=None))
        flags.setdefault("change_detectors", []).append({
            "bill_month_changes": len(out["bill_month_changes"]),
            "billing_account_changes": len(out["billing_account_changes"]),
            "status_flips": len(out["status_flips"]),
            "note": "counts this fiscal year — details ride in the cache"})
    except Exception as exc:
        flags.setdefault("change_detectors_failed", []).append({
            "error": f"{type(exc).__name__}: {exc}",
            "defect": "audit history unavailable — bill-month moves and "
                      "consolidations are INVISIBLE this run"})
        out = {k: [] for k in out}
    return out


# ---------------------------------------------------------------------------
# Month name <-> bill month integer mapping
# ---------------------------------------------------------------------------
MONTH_ABB_TO_INT: Dict[str, int] = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
    "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
    "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
MONTH_INT_TO_ABB: Dict[int, str] = {v: k for k, v in MONTH_ABB_TO_INT.items()}

def _month_date_range(month: str, fiscal_year_start: int):
    """
    Return (start_date, end_date) for a month abbreviation within a fiscal year.

    WHA FY runs Oct → Sep:
        Months Oct-Dec fall in fiscal_year_start calendar year.
        Months Jan-Sep fall in fiscal_year_start + 1 calendar year.
    """
    m_int = MONTH_ABB_TO_INT[month]
    year = fiscal_year_start if m_int >= 10 else fiscal_year_start + 1
    last_day = monthrange(year, m_int)[1]
    return date(year, m_int, 1), date(year, m_int, last_day)


class ScoreboardEngine:
    """
    Queries SLX and external files then computes all ScoreboardData in order.

    Design principles:
    - Each _query_* and _compute_layer* method is independently testable
    - All mutations happen on the single ScoreboardData instance (`self.data`)
    - None values propagate cleanly — no crash on missing data
    - Majors/NRA is handled as a special case for retention (no standard billing)
    """

    NO_RETENTION_TERRITORY = "Majors/NRA"  # excluded from retention queries

    def __init__(
        self,
        client: SLXClient,
        territory_user_map: Dict[str, str],
        fiscal_year_start: int,
        months: List[str],
        current_month: str,
        rep_name_map: Dict[str, str],
        drops_detail_only_users: Optional[Dict[str, str]] = None,
        drops_extra_users: Optional[Dict[str, str]] = None,
    ):
        """
        Args:
            client:              Authenticated SLXClient instance.
            territory_user_map:  {slx_user_id: canonical_territory_name}
                                 Source: territory_map.yaml slx_user_to_territory.
            fiscal_year_start:   Calendar year when fiscal year begins (e.g. 2025).
            months:              Ordered list of month abbreviations to process,
                                 e.g. ["Oct","Nov","Dec","Jan","Feb","Mar"].
            current_month:       The month being reported in this run (e.g. "Mar").
                                 Billables are queried live for this month only.
            rep_name_map:        {canonical_territory: rep_display_name}
                                 Source: territory_map.yaml rep_to_territory (inverted).
            drops_detail_only_users: {slx_user_id: label} program/house reps (e.g.
                                 Retro Coordinator) whose drops ride the DETAIL
                                 sheet only. Merged into the DROPS fetch alone —
                                 never billables/penetration/retention — and their
                                 label is outside the canonical territory set, so
                                 bucket aggregation skips them (universe rule).
                                 Source: territory_map.yaml drops_detail_only_users.
        """
        self.client = client
        # The exceptions queue (Jen endorsed in-call 2026-07-30; Shannon's
        # summary step 10): rows a rule excluded that a HUMAN must still see.
        # Collected during the passes, written beside the cache by the runner.
        self.flags: Dict[str, list] = {}
        self.territory_user_map = territory_user_map
        self.fiscal_year_start = fiscal_year_start
        self.months = months
        self.current_month = current_month
        self.rep_name_map = rep_name_map
        self.drops_detail_only_users = drops_detail_only_users or {}
        # Open-territory users (2026-07-23, Todd's Crab Cracker class): accounts
        # managed by an UNASSIGNED territory user were invisible to every drop
        # sweep. These users' drops COUNT, mapped to their canonical territory.
        self.drops_extra_users = drops_extra_users or {}
        self.data: Optional[ScoreboardData] = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        territory_map: dict,
        fiscal_year: str = "2025-26",
        goals_config_path: Path = Path("config/goals.yaml"),
        admin_inputs_path: Path = Path("config/admin_inputs.yaml"),
        penetration_override=None,   # optional PenetrationOverride adapter — see reports.membership_performance_tracker.logic.penetration_override
        progress_callback=None,
    ) -> ScoreboardData:
        """
        Execute the full computation pipeline.

        Args:
            territory_map:       Parsed territory_map.yaml dict.
            fiscal_year:         FY label matching a key in goals.yaml (e.g. "2025-26").
            goals_config_path:   Path to goals.yaml.
            admin_inputs_path:   Path to admin_inputs.yaml (legacy fallback source).
            penetration_override: Optional adapter (reports.membership_performance_tracker.logic.penetration_override.PenetrationOverride)
                                  that substitutes per-(territory, segment) penetration
                                  counts AFTER the SLX pass. None (default) → SLX only.
                                  See docs/EXTENSION_POINTS.md for the worked example.
            progress_callback:   Optional callable(pct: int, message: str). Called at
                                 each pipeline phase so callers (CLI, Streamlit) can
                                 display a progress bar. pct is 0-100.

        Returns:
            Fully populated ScoreboardData instance.

        Data sources:
            • SLX SData               — billables, retention, new members, revenue,
                                        pen_active (all active member locations)
            • config/goals.yaml       — admin-set monthly revenue targets
            • admin_inputs.xlsx       — goal grids and rate defaults (goals are
                                        the only admin inputs as of 2026-07-20)
        """
        def _progress(pct: int, msg: str):
            if progress_callback:
                progress_callback(pct, msg)

        self.data = empty_scoreboard(self.months)
        self.penetration_override = penetration_override

        n_territories = len([v for v in self.territory_user_map.values() if v])

        # Phase 1 — L0: raw data from all sources
        _progress(5,  "Loading territory and rep configuration...")
        self._populate_rep_names()

        _progress(12, f"Pulling current billable counts for {n_territories} territories...")
        self._query_billables()

        _progress(28, f"Computing Target-filtered penetration for {n_territories} territories...")
        self._query_penetration()
        self._flag_billables_without_invoices()

        _progress(32, f"Pulling retention data across {len(self.months)} months...")
        self._query_retention()

        _progress(48, f"Pulling new member enrollments across {len(self.months)} months...")
        self._query_new_members()

        _progress(60, "Pulling revenue data from the membership database...")
        self._query_revenue()

        _progress(65, "Pulling drops and closed-business detail...")
        self._query_drops_and_closed()
        _progress(70, "Drops and closed-business detail loaded.")

        # Prefer the unified Excel file if present (admins edit this directly);
        # fall back to the legacy YAMLs only when the xlsx is missing.
        # PATH FIX (2026-07-17, parallel-review find): repo root is 4 levels up
        # (logic → membership_performance_tracker → reports → <repo>). Was 3
        # (.parent×3 = 'reports/data/raw', a non-existent dir) — so every LIVE run
        # silently took the else-branch and loaded NULL goals from goals.yaml.
        admin_xlsx = Path(__file__).resolve().parents[3] / "data" / "raw" / "admin_inputs.xlsx"
        if admin_xlsx.exists():
            _progress(74, "Loading admin inputs from admin_inputs.xlsx...")
            self.load_admin_inputs_xlsx(admin_xlsx)
        else:
            # Loud: a MISSING xlsx now means genuinely-absent (path is correct), and
            # the YAML fallback ships blank goals — surface it, don't hide it.
            warnings.warn(f"[admin_inputs] xlsx NOT found at {admin_xlsx} — falling back "
                          f"to legacy YAML; goals will be blank. Verify the file/path.")
            _progress(74, "Loading monthly goals from goals.yaml...")
            self._load_goals(fiscal_year, goals_config_path)
            _progress(76, "Loading admin inputs from admin_inputs.yaml...")
            self._load_admin_inputs(fiscal_year, admin_inputs_path)

        # Phase 2 — L1: elementwise derived values
        _progress(80, "Computing per-territory metrics...")
        self._compute_layer1()

        # Phase 3 + 4 — L2 + L3: aggregations and season-level ratios
        _progress(85, "Aggregating statewide totals and finalizing season-level calculations...")
        self._compute_layer2()
        self._compute_layer3()

        # C2 (2026-08-12): the change detectors, wired at last — see
        # collect_change_detectors. Live-pull only: a cache replay has no
        # client, and stale detector output would be worse than none.
        if self.client is not None:
            _progress(88, "Scanning the CRM audit history for changes...")
            detected = collect_change_detectors(
                self.client, self.fiscal_year_start, self.flags)
            self.data.bill_month_changes = detected["bill_month_changes"]
            self.data.billing_account_changes = detected["billing_account_changes"]
            self.data.status_flips = detected["status_flips"]
            self.data.consolidation_events = detected["consolidation_events"]

        return self.data

    # ------------------------------------------------------------------
    # Phase 1 — Layer 0: raw data queries and file parsing
    # ------------------------------------------------------------------

    def _populate_rep_names(self):
        """Fill rep_name[t] from the rep_name_map provided at init."""
        for territory, name in self.rep_name_map.items():
            self.data.rep_name[territory] = name

    def _query_billables(self):
        """
        Query SLX for current-month billables (post-ITD snapshot) + T/NT split.

        Queries the live state of SLX — run only AFTER ITD has executed.
        Populates hosp_bills, allied_bills (totals) and
        hosp_bills_target, hosp_bills_non_target for current_month. All other
        months remain None (captured in prior runs).
        """
        # Scope to the reported month: an early-next-month activation must not
        # land in this month's snapshot (Jen, 2026-07-30; Shannon's step 8).
        _, _period_end = _month_date_range(self.current_month, self.fiscal_year_start)
        self._product_carriers: Dict[str, str] = {}
        billables = compute_billables_by_target(
            self.client, self.territory_user_map, period_end=_period_end,
            carriers_out=self._product_carriers)
        m = self.current_month
        for territory, counts in billables.items():
            if territory in self.data.hosp_bills:
                self.data.hosp_bills[territory][m]   = counts.get("hospitality")
                self.data.allied_bills[territory][m] = counts.get("allied")
                # T/NT splits — merge 'unknown' into non_target for cleaner reporting
                t_count  = counts.get("hospitality_target")
                nt_count = counts.get("hospitality_non_target")
                u_count  = counts.get("hospitality_unknown") or 0
                self.data.hosp_bills_target[territory][m]     = t_count
                self.data.hosp_bills_non_target[territory][m] = (
                    (nt_count or 0) + u_count if nt_count is not None else None
                )

    def _query_retention(self):
        self._invoiced_accounts = set()
        """
        Query dlInvoiceHistoryHeader for retention across all bill months in `months`.

        Uses compute_retention_all_months with per-month server-side Comment filter
        (avoids the SLX pagination bug from broad unfiltered fetches).

        Maps bill_month_int → month_abbreviation to populate ret_paid[t][m] and
        ret_billed[t][m]. Majors/NRA is excluded (no standard dues billing).
        """
        # Build user map without Majors/NRA (no standard billing)
        retention_user_map = {
            uid: territory
            for uid, territory in self.territory_user_map.items()
            if territory != self.NO_RETENTION_TERRITORY
        }

        # RATIFIED CONVENTION (2026-07-14, from the team's own archived sheets):
        # month-M's retention column shows bill-month M−1 — "the cycle that
        # CLOSED in M" (3rd notice lands in M). Decisive evidence: handmade June
        # TKP 12/14 = BM5 (BM6 was 29/35). Oct's column shows BM9 of the PRIOR
        # fiscal year (Sep cohort closing in Oct).
        bill_months = sorted({
            (MONTH_ABB_TO_INT[m] - 1) or 12
            for m in self.months if m in MONTH_ABB_TO_INT
        })

        # FY-EDGE (2026-07-14, historical-gate bug): the Oct column shows BM9 —
        # September of the PRIOR fiscal year (e.g. Sep-2025 for FY25-26). The
        # window helper maps BM9 to fy_start+1 (Sep-2026, the future) unless we
        # evaluate it against fiscal_year_start−1. Query it separately and merge.
        main_bms = [b for b in bill_months if b != 9]
        retention_all = compute_retention_all_months(
            flags_out=self.flags,
            client=self.client,
            territory_user_map=retention_user_map,
            bill_months=main_bms,
            fiscal_year_start=self.fiscal_year_start,
            include_target_split=True,
        ) if main_bms else {}
        if 9 in bill_months:
            prior_fy = compute_retention_all_months(
                client=self.client,
                territory_user_map=retention_user_map,
                bill_months=[9],
                fiscal_year_start=self.fiscal_year_start - 1,
                include_target_split=True,
            )
            retention_all.update(prior_fy)

        # retention_all: {bill_month_int: {territory: {pct, paid, billed, ...,
        #   paid_target, billed_target, revenue_retained_target, revenue_up_target,
        #   paid_non_target, billed_non_target, revenue_retained_non_target,
        #   revenue_up_non_target}}}
        for bill_month_int, territory_data in retention_all.items():
            # Display shift: a bill month is reported in the FOLLOWING month's
            # column because that is when its collection window closes — BM M's
            # 3rd (final) notice lands in M+1 (Jennifer 2026-07-22). So the June
            # column holds BM5: June is when BM5 stopped collecting.
            display_month = bill_month_int + 1 if bill_month_int < 12 else 1
            month_abb = MONTH_INT_TO_ABB.get(display_month)
            if month_abb not in self.months:
                continue
            for territory, r in territory_data.items():
                if territory not in self.data.ret_paid:
                    continue
                # Totals
                self.data.ret_paid[territory][month_abb]   = r.get("paid")
                self.data.ret_billed[territory][month_abb] = r.get("billed")
                # T/NT member splits
                self.data.ret_paid_target[territory][month_abb]       = r.get("paid_target")
                self.data.ret_billed_target[territory][month_abb]     = r.get("billed_target")
                self.data.ret_paid_non_target[territory][month_abb]   = r.get("paid_non_target")
                self.data.ret_billed_non_target[territory][month_abb] = r.get("billed_non_target")
                # T/NT revenue splits (in dollars)
                self.data.rev_retained_target[territory][month_abb]     = r.get("revenue_retained_target")
                self.data.rev_up_target[territory][month_abb]           = r.get("revenue_up_target")
                self.data.rev_retained_non_target[territory][month_abb] = r.get("revenue_retained_non_target")
                self.data.rev_up_non_target[territory][month_abb]       = r.get("revenue_up_non_target")
                # Comp line (ruled 2026-08-04): visibility only, outside the % calc
                self.data.ret_comped.setdefault(territory, {})[month_abb] = r.get("comped_count")
                self.data.ret_comped_dollars.setdefault(territory, {})[month_abb] = r.get("comped_dollars")
                self.data.ret_comped_target.setdefault(territory, {})[month_abb] = r.get("comped_target_count")
                self.data.ret_comped_non_target.setdefault(territory, {})[month_abb] = r.get("comped_non_target_count")
                self.data.ret_comped_dollars_target.setdefault(territory, {})[month_abb] = r.get("comped_target_dollars")
                self.data.ret_comped_dollars_non_target.setdefault(territory, {})[month_abb] = r.get("comped_non_target_dollars")
                self.data.ret_bob.setdefault(territory, {})[month_abb] = r.get("bob_count")
                self.data.ret_bob_dollars.setdefault(territory, {})[month_abb] = r.get("bob_dollars")

    def _query_new_members(self):
        """
        Query cMemberGens for new members enrolled in each month's date window.

        Uses compute_new_members_for_period per month. Excludes within-window
        reinstatements (ReinstatedDate / Salescode 510).

        ⚠️ Add-on child locations are NOT excluded — the old `ParentId eq null`
        filter was removed, and 2026-07-30 confirmed the rule: a separately
        billed location IS a new member (Jen; and her own CRM report lists
        them). A location that merely raises the corporate's dues is a dues
        adjustment and never enters this cohort, because the parent's enroll
        date is old.

        Also queries for BOB (Black-Owned Business) accounts enrolled in the
        current_month date window. BOB accounts are comped ($0 dues) but count
        toward the rep goal — surfaced in bob_new_accounts[t] for admin review.
        """
        # PAID-ONLY COUNTS (Jiho ratified 2026-07-22): new-member counts are no
        # longer computed here from the enrollment cohort — they derive from the
        # SAME paid amounts as the dollars, inside _query_revenue (single source,
        # single API sweep). This eliminated the count-without-revenue class
        # (present in EVERY era: 17 cells on 7/13, 7 on 7/21, 21 post-reversion).
        # BOB (comped) still counts, visible in the BOB row.

        # BOB accounts: query only for the current_month (the month being reported).
        # We flag these for admin review so they know to apply manual revenue credit.
        start, end = _month_date_range(self.current_month, self.fiscal_year_start)
        start_str = start.strftime("%Y-%m-%d")
        end_str   = end.strftime("%Y-%m-%d")

        for user_id, territory in self.territory_user_map.items():
            if territory is None or territory not in self.data.bob_new_accounts:
                continue
            bob_list = self.client.get_bob_new_accounts(user_id, start_str, end_str)
            if bob_list:
                # SUM across a territory's seat users, not last-user-wins
                # (finding #14): Majors/NRA has two users since 7/13 — every other
                # per-territory metric accumulates; this one silently overwrote.
                self.data.bob_new_accounts[territory] = (
                    self.data.bob_new_accounts.get(territory, []) + bob_list
                )

    def _query_revenue(self):
        """
        Query SLX for new-sales revenue per territory per month.

        Source:  dlInvoiceHistoryHeader.Net_invoice (the actual billed dues amount)
                 filtered to WRA dues invoices for accounts that enrolled in the
                 same month — captures only the initial sign-up invoice, not renewals.

        Under the WHA FY (Oct 1 → Sep 30), Oct is the FY's first month and is
        queried live. No month is treated as a prior-FY carry-over.
        """
        from reports.membership_performance_tracker.logic.revenue import (
            revenue_and_counts_by_first_pay)

        # OPTION 2 (Jiho ratified 2026-07-22): one sweep, FIRST-PAYMENT-MONTH
        # anchoring — each member + all their first-year dollars land in the
        # month their first dues payment arrived. Counts derive from the same
        # paid amounts (paid-only rule), so count ⟺ dollars per cell, both
        # directions, with BOB anchored at enrollment and visible in its row.
        windows = [(m, *(_month_date_range(m, self.fiscal_year_start)))
                   for m in self.months]
        per_terr = revenue_and_counts_by_first_pay(
            client=self.client,
            territory_user_map=self.territory_user_map,
            month_windows=windows,
            flags_out=self.flags,
        )
        for territory, by_month in per_terr.items():
            if territory not in self.data.revenue:
                continue
            for month, b in by_month.items():
                self.data.revenue[territory][month] = b.get("total")
                self.data.revenue_target[territory][month] = b.get("target")
                self.data.revenue_non_target[territory][month] = (
                    (b.get("non_target") or 0.0) + (b.get("unknown") or 0.0))
                self.data.revenue_bob[territory][month] = b.get("bob")
                self.data.revenue_bob_target.setdefault(territory, {})[month] = b.get("bob_target")
                self.data.revenue_bob_non_target.setdefault(territory, {})[month] = b.get("bob_non_target")
                self.data.revenue_comped_new.setdefault(territory, {})[month] = b.get("comped_new")
                if b.get("comped_new"):
                    self.flags.setdefault("comped_new_sales", []).append(
                        {"territory": territory, "month": month,
                         "face_dollars": b.get("comped_new"),
                         "accounts": [f"{a} (${v:,.0f})" for a, v in
                                      (b.get("comped_new_accounts") or {}).items()],
                         "defect": "a NEW membership was comped — banned "
                                   "outside BOB (ruled 8/4, policy active "
                                   "from that date; earlier comps are "
                                   "pre-policy). Investigate."})
                self.data.new_members[territory][month] = b.get("count_total")
                self.data.new_members_target[territory][month] = b.get("count_target")
                self.data.new_members_non_target[territory][month] = (
                    (b.get("count_non_target") or 0) + (b.get("count_unknown") or 0))
                self.data.new_members_bob.setdefault(territory, {})[month] = b.get("count_bob")

    def _query_drops_and_closed(self):
        """
        Fetch drop and closed-business detail rows from SLX and aggregate buckets.

        Populates:
            data.drops_detail   — per-account drop rows (for Data - Drops sheet)
            data.closed_detail  — per-account closed-biz rows (for Data - Closed Businesses)
            ... and the aggregated bucket fields (see aggregate_drops_buckets)
        """
        # StatusDate floor = July 1 preceding the FY (3 months before the Oct 1 FY
        # start). StatusDate lags the real drop date, so this buffer guarantees a
        # genuine in-FY drop can't be excluded; aggregation is FY-windowed anyway.
        # Mirrors the retention safe-window convention (retention.py). This bounds
        # the fetch so drops stops pulling every inactive account back to ~2001.
        drops_status_floor = date(self.fiscal_year_start, 7, 1)
        drops, closed = fetch_drops_and_closed(
            client=self.client,
            territory_user_map={**self.territory_user_map,
                                **self.drops_extra_users,
                                **self.drops_detail_only_users},
            rep_map=self.rep_name_map,
            min_status_date=drops_status_floor,
        )
        self.data.drops_detail  = drops
        self.data.closed_detail = closed
        self.aggregate_drops_buckets()

    def aggregate_drops_buckets(self):
        """
        Rebuild monthly drops/closed bucket fields from `drops_detail` and `closed_detail`.

        Public method (callable independently of SLX) so the cache-replay path can
        re-aggregate after a bug fix without needing to re-query SLX.

        Drops are bucketed into the month matching their drop_date / date_closed.
        `is_target` from drops.py is a string flag: 'Y' → Target, anything else
        ('N', '?', None) → Non-Target. Unknowns fall into Non-Target to avoid
        silently dropping records.
        """
        from reports.membership_performance_tracker.logic.drops import CANONICAL_TO_TRACKER
        tracker_to_canonical = {v: k for k, v in CANONICAL_TO_TRACKER.items()}

        self.data.drops_by_category = {}   # rebuilt below (B10)

        # Zero out existing buckets before re-aggregating (avoids double-count when
        # called after a partial cache load)
        for field in (self.data.drops_target, self.data.drops_non_target,
                      self.data.drops_revenue_target, self.data.drops_revenue_non_target,
                      self.data.closed_target, self.data.closed_non_target):
            for t in field:
                for m in field[t]:
                    field[t][m] = None

        # Aggregate monthly counts + revenue from per-account detail
        for d in (self.data.drops_detail or []):
            if d.get("drop_category") == "Admin":
                continue  # housekeeping, not a member loss (ratified 2026-07-14)
            if d.get("dues_carrying") is False:
                # BILLABLE GATE (Jiho ratified 2026-07-23): no own dues anywhere
                # (no Dues Level, no positive WRA invoice, no ledger dues) —
                # never a dues-carrying member; rides the detail sheet only.
                # Records not yet swept (flag absent) keep legacy behavior.
                continue
            tracker_terr = d.get("territory")
            canonical = tracker_to_canonical.get(tracker_terr)
            if not canonical or canonical not in self.data.drops_target:
                continue

            drop_date = d.get("drop_date")
            month_abb = None
            if drop_date and len(drop_date) >= 7:
                # drop_date is "YYYY-MM-DD"; require both year and month to
                # match this FY's calendar window for that month abbreviation.
                # Prevents (e.g.) a 2024-03 drop from being counted into FY 2025-26 March.
                try:
                    drop_year = int(drop_date[0:4])
                    m_int = int(drop_date[5:7])
                    expected_year = (
                        self.fiscal_year_start if m_int >= 10
                        else self.fiscal_year_start + 1
                    )
                    if drop_year == expected_year:
                        month_abb = MONTH_INT_TO_ABB.get(m_int)
                except (ValueError, IndexError):
                    # GOLD-PLATE (2026-07-17): an unparseable drop_date silently
                    # drops the record from monthly buckets — surface it loudly.
                    warnings.warn(f"[drops] unparseable drop_date {drop_date!r} — "
                                  f"record skipped from monthly buckets")
            if month_abb not in self.months:
                continue

            # B10: per-category monthly rollup (Admin already skipped above;
            # non-canonical territories — Retro Program — never reach here).
            cat = d.get("drop_category")
            if cat:
                bucket = self.data.drops_by_category.setdefault(cat, {})                              .setdefault(canonical, {})
                bucket[month_abb] = (bucket.get(month_abb) or 0) + 1

            # drops.py emits is_target as 'Y' / 'N' / '?' strings.
            # 'Y' → Target bucket; everything else (N, ?, None) → Non-Target.
            is_target = d.get("is_target")
            amount    = d.get("amount_billed") or 0.0

            if is_target == "Y":
                self.data.drops_target[canonical][month_abb] = (
                    (self.data.drops_target[canonical][month_abb] or 0) + 1
                )
                self.data.drops_revenue_target[canonical][month_abb] = (
                    (self.data.drops_revenue_target[canonical][month_abb] or 0.0) + amount
                )
            else:
                self.data.drops_non_target[canonical][month_abb] = (
                    (self.data.drops_non_target[canonical][month_abb] or 0) + 1
                )
                self.data.drops_revenue_non_target[canonical][month_abb] = (
                    (self.data.drops_revenue_non_target[canonical][month_abb] or 0.0) + amount
                )

        # Closed businesses — bucket by date_closed if available
        for c in (self.data.closed_detail or []):
            tracker_terr = c.get("territory")
            canonical = tracker_to_canonical.get(tracker_terr)
            if not canonical or canonical not in self.data.closed_target:
                continue

            date_closed = c.get("date_closed")
            month_abb = None
            if date_closed and len(date_closed) >= 7:
                # Year-aware: a 2024-03 close must not fall into FY 2025-26 March.
                try:
                    closed_year = int(date_closed[0:4])
                    m_int = int(date_closed[5:7])
                    expected_year = (
                        self.fiscal_year_start if m_int >= 10
                        else self.fiscal_year_start + 1
                    )
                    if closed_year == expected_year:
                        month_abb = MONTH_INT_TO_ABB.get(m_int)
                except (ValueError, IndexError):
                    # GOLD-PLATE (2026-07-17): an unparseable date_closed silently
                    # drops the record from monthly buckets — surface it loudly.
                    warnings.warn(f"[closed] unparseable date_closed {date_closed!r} — "
                                  f"record skipped from monthly buckets")
            if month_abb not in self.months:
                continue

            # drops.py emits is_target as 'Y' / 'N' / '?' for closed too
            is_target = c.get("is_target")
            if is_target == "Y":
                self.data.closed_target[canonical][month_abb] = (
                    (self.data.closed_target[canonical][month_abb] or 0) + 1
                )
            else:
                self.data.closed_non_target[canonical][month_abb] = (
                    (self.data.closed_non_target[canonical][month_abb] or 0) + 1
                )

        # ──────────────────────────────────────────────────────────────────
        # None → 0 coercion for months we actually processed.
        # 2026-06-05 PM verify-fix (mapper audit finding #3): the loops above
        # only WRITE a cell when a drop / closed event lands in that bucket.
        # Cells stay None for (territory, month) pairs with zero events —
        # ambiguous between "no data" and "real zero". The mapper skips None
        # → trend sheet shows blank → executive reads it as "no data" when
        # the truth is "zero drops". For months we know the engine processed
        # (self.months), coerce None → 0 so the trend sheet correctly shows
        # 0 instead of empty. Months outside self.months stay None (we
        # genuinely don't have data for them yet — historical backfill territory).
        count_fields = (self.data.drops_target, self.data.drops_non_target,
                        self.data.closed_target, self.data.closed_non_target)
        revenue_fields = (self.data.drops_revenue_target,
                          self.data.drops_revenue_non_target)
        for field in count_fields:
            for t in field:
                for m in self.months:
                    if m in field[t] and field[t][m] is None:
                        field[t][m] = 0
        for field in revenue_fields:
            for t in field:
                for m in self.months:
                    if m in field[t] and field[t][m] is None:
                        field[t][m] = 0.0

    def _load_goals(self, fiscal_year: str, goals_config_path: Path):
        """
        Load monthly goals per territory from goals.yaml.

        Goals are admin-set (not in SLX). Under the WHA FY (Oct → Sep), the full
        12-month sequence is loaded. If a month is null in the YAML, goal[t][m]
        stays None.
        """
        from src.config.goals_loader import goals_as_engine_dict

        try:
            goals = goals_as_engine_dict(
                fiscal_year=fiscal_year,
                months=self.months,
                config_path=goals_config_path,
            )
        except (FileNotFoundError, ValueError) as exc:
            warnings.warn(f"[goals] Could not load goals for FY '{fiscal_year}': {exc}")
            # LOUD, NOT SILENT (2026-08-11). Both config files carry only
            # FY2025-26, so the first October build loses every goal,
            # attainment and goal-vs-actual cell with nothing but a log line
            # to say so. Scaffolding a null FY block would make this quieter,
            # not safer — the loader would find a block and warn about
            # nothing. The values are leadership's to set, so the absence is
            # surfaced where an operator sees it instead.
            self.flags.setdefault("missing_goals", []).append(
                f"No goals are configured for fiscal year {fiscal_year} in "
                f"{goals_config_path}. Every goal, attainment and "
                f"goal-vs-actual cell will be blank until they are entered "
                f"({exc})")
            return

        for territory, per_month in goals.items():
            if territory not in self.data.goal:
                continue
            for m, val in per_month.items():
                self.data.goal[territory][m] = val

    def _flag_billables_without_invoices(self):
        """Jen's "that is a no-no" check — a dues-carrying member holding no
        invoice all year (the RRO-conversion duplicate, or the Four Points
        class). Runs only when both passes supplied their sets; costs nothing.
        """
        from reports.membership_performance_tracker.logic.run_timing import (
            billables_without_invoices)
        carriers = getattr(self, "_product_carriers", None)
        invoiced = getattr(self, "_invoiced_accounts", None)
        if not carriers or invoiced is None:
            return
        rows = billables_without_invoices(carriers, invoiced)
        if rows:
            self.flags.setdefault("billable_without_invoice", []).extend(rows)
            print(f"  [flags] {len(rows)} member(s) carry a dues product but "
                  f"no invoice this FY — listed for review")

    def _query_penetration(self):
        """
        Compute Target-filtered penetration per territory, split Restaurant/Lodging.

        Confirmed definition (2026-05-29): Target restaurant = >=10 FTE, Target
        lodging = >=40 rooms. Numerator = active Target members; denominator
        (market) = active + inactive Target locations (the total known market).

        Populates from SLX:
            pen_active_restaurant[t], pen_active_lodging[t]   — active Target
            pen_market_restaurant[t], pen_market_lodging[t]   — active + inactive Target
        pen_pct[t] (combined) is then derived in _compute_layer1.

        Optional external override: if `self.penetration_override` is set
        (PenetrationOverride adapter — see `reports.membership_performance_tracker.logic.penetration_override`),
        per-(territory, segment) cells can be replaced by the override AFTER
        the SLX pass. The chosen source is recorded in `self.data.penetration_source`
        as "slx" or "override:<name>". The default (None) leaves SLX untouched.
        """
        from reports.membership_performance_tracker.logic.billables import compute_penetration_by_segment
        from reports.membership_performance_tracker.logic.penetration_override import apply_override

        pen = compute_penetration_by_segment(self.client, self.territory_user_map)
        merged, sources = apply_override(pen, getattr(self, "penetration_override", None))

        for territory, seg in merged.items():
            if territory not in self.data.pen_active_restaurant:
                continue
            self.data.pen_active_restaurant[territory] = seg["restaurant"]["active"]
            self.data.pen_market_restaurant[territory] = seg["restaurant"]["market"]
            self.data.pen_active_lodging[territory]    = seg["lodging"]["active"]
            self.data.pen_market_lodging[territory]    = seg["lodging"]["market"]
            # Non-Target pool (same math on the sub-threshold population).
            # Older overrides may not surface this — defaults to None.
            nt_r = seg.get("restaurant_nt") or {}
            nt_l = seg.get("lodging_nt") or {}
            self.data.pen_active_nt_restaurant[territory] = nt_r.get("active")
            self.data.pen_market_nt_restaurant[territory] = nt_r.get("market")
            self.data.pen_active_nt_lodging[territory]    = nt_l.get("active")
            self.data.pen_market_nt_lodging[territory]    = nt_l.get("market")

        # Record provenance of each cell for audit / display.
        if hasattr(self.data, "penetration_source"):
            self.data.penetration_source.update(sources)

    def _load_admin_inputs(self, fiscal_year: str, config_path: Path):
        """
        Load admin-entered values from admin_inputs.yaml.

        Populates:
            goal_retention[t][m]       — retention target per (territory, month)
            goal_members[t][m]         — new-member count target per (territory, month)
            goal_penetration[t]        — penetration target per territory

        Goal fields use a default + per-territory override pattern:
            goal_retention_default          → applied to every (t, m)
            goal_retention_overrides[t]     → static override across all months
            goal_members_default            → applied to every (t, m)
            goal_members_overrides[t][m]    → per-month override

        Missing or null values stay as None in the data package — the mapper
        skips None cells so empty admin inputs simply leave gaps in the output.
        """
        try:
            raw = yaml.safe_load(config_path.read_text())
        except Exception as exc:
            warnings.warn(f"[admin_inputs] Failed to load {config_path}: {exc}")
            return

        _all_fys = (raw or {}).get("fiscal_years", {}) or {}
        fy_data = _all_fys.get(fiscal_year, {})
        if not fy_data:
            # DEFAULTS CARRY FORWARD (ruled by Jiho 2026-08-11: "the default %
            # can stay"). A retention/penetration TARGET is standing policy,
            # not a per-year number, so a new fiscal year inherits the most
            # recent one rather than rendering the goal lines blank. Only the
            # two defaults carry — per-territory overrides and market sizes do
            # NOT, because those are genuinely per-year and guessing them would
            # invent data. The flag below still fires either way.
            _prev = _all_fys.get(max(_all_fys), {}) if _all_fys else {}
            fy_data = {k: _prev[k] for k in
                       ("goal_retention_default", "goal_penetration_default",
                        "goal_members_default")
                       if _prev.get(k) is not None}
            warnings.warn(
                f"[admin_inputs] No entry for fiscal year '{fiscal_year}' in "
                f"{config_path}"
                + (f" — carrying forward the default targets from "
                   f"FY '{max(_all_fys)}'" if fy_data else ""))
            # Flagged either way (found 2026-08-11 sweeping the rollover; the
            # goals.yaml flag did NOT cover this file). Carrying the defaults
            # keeps the goal LINES populated; the per-territory overrides are
            # still missing, and that is what the flag is telling the operator.
            self.flags.setdefault("missing_goals", []).append(
                f"No admin inputs are configured for fiscal year "
                f"{fiscal_year} in {config_path}. "
                + (f"The standing default targets were carried forward from "
                   f"FY {max(_all_fys)}, but any per-territory overrides are "
                   f"missing until this year's inputs are entered."
                   if fy_data else
                   "The retention and penetration goal lines will be blank "
                   "until they are entered."))
            if not fy_data:
                return

        # NOTE: penetration segment fields (pen_market/active_restaurant/lodging)
        # are NOT loaded here anymore — they are computed from SLX by
        # _query_penetration (Target-filtered). Goals are the only admin inputs.

        # Goal fields — default + override pattern
        self._apply_goal_field(
            field=self.data.goal_retention,
            default=fy_data.get("goal_retention_default"),
            overrides=fy_data.get("goal_retention_overrides") or {},
        )
        self._apply_goal_field(
            field=self.data.goal_members,
            default=fy_data.get("goal_members_default"),
            overrides=fy_data.get("goal_members_overrides") or {},
        )
        self._apply_scalar_goal(
            field=self.data.goal_penetration,
            default=fy_data.get("goal_penetration_default"),
            overrides=fy_data.get("goal_penetration_overrides") or {},
        )

    def load_admin_inputs_xlsx(self, xlsx_path: Path) -> None:
        """
        Load all admin-entered values from admin_inputs.xlsx in one pass.

        Replaces the two separate YAML loaders (_load_admin_inputs + _load_goals)
        with a single xlsx-driven path. Admins now edit the xlsx directly; the
        engine reads from it.

        Falls back to no-op (with a warning) if the file is missing or unreadable.

        Args:
            xlsx_path: Path to admin_inputs.xlsx (typically data/raw/admin_inputs.xlsx).
        """
        from src.parsers.admin_inputs import parse as parse_admin_xlsx
        try:
            data = parse_admin_xlsx(xlsx_path)
        except FileNotFoundError:
            # A genuinely-absent admin file is a legitimate mode (blank goals);
            # keep it a warning, not a hard failure.
            warnings.warn(f"[admin_inputs] xlsx not found at {xlsx_path} — leaving fields blank")
            return
        except Exception as exc:
            # GOLD-PLATE (2026-07-17): a PRESENT-but-corrupt admin file silently
            # blanked ALL goals + attainment. That's a wrong report shipped quietly.
            # Fail LOUD — the file exists, so a parse failure is a real problem.
            raise RuntimeError(
                f"[admin_inputs] failed to parse {xlsx_path}: {type(exc).__name__}: "
                f"{exc} — refusing to ship a report with silently-blank goals"
            ) from exc

        # Sales Goals (revenue) — month grid per territory
        for t, by_m in (data.get("goals") or {}).items():
            if t in self.data.goal:
                for m, v in by_m.items():
                    if m in self.data.goal[t]:
                        self.data.goal[t][m] = v

        # Member Goals — month grid per territory
        for t, by_m in (data.get("goal_members") or {}).items():
            if t in self.data.goal_members:
                for m, v in by_m.items():
                    if m in self.data.goal_members[t]:
                        self.data.goal_members[t][m] = v

        # Retention Goal — default with optional per-territory override.
        # The xlsx layout uses scalar overrides (one number applied to all months),
        # so we pass them through the same _apply_goal_field helper as YAML.
        self._apply_goal_field(
            field=self.data.goal_retention,
            default=data.get("goal_retention_default"),
            overrides=data.get("goal_retention_overrides") or {},
        )

        # Penetration Goal — statewide default + per-territory overrides.
        # Per-territory scalar (no month dimension). Falls back to YAML default
        # if the xlsx parser doesn't surface it (xlsx sheet is optional).
        self._apply_scalar_goal(
            field=self.data.goal_penetration,
            default=data.get("goal_penetration_default"),
            overrides=data.get("goal_penetration_overrides") or {},
        )

        # Penetration segment fields are computed from SLX (_query_penetration),
        # NOT loaded from admin inputs — goals are the only admin inputs.

    def _apply_scalar_goal(self, field: Dict, default, overrides: Dict) -> None:
        """
        Fill a goal_*[t] (per-territory scalar) field using a (default,
        per-territory overrides) pattern. Same default/override semantics as
        _apply_goal_field but for scalars rather than month grids.

        If default is None and the territory has no override, the cell stays None.
        """
        for territory in field:
            override = overrides.get(territory)
            if override is not None:
                field[territory] = override
            elif default is not None:
                field[territory] = default

    def _apply_goal_field(self, field: Dict, default, overrides: Dict) -> None:
        """
        Fill a goal_*[t][m] field using a (default, per-territory overrides) pattern.

        An override can be:
            scalar         — applied to every month for that territory
            dict[month→v]  — per-month value for that territory

        If default is None and the territory has no override, all cells stay None.
        """
        for territory, per_month in field.items():
            override = overrides.get(territory)
            if isinstance(override, dict):
                # Per-month override dict
                for m in per_month:
                    if m in override:
                        per_month[m] = override[m]
                    elif default is not None:
                        per_month[m] = default
            elif override is not None:
                # Scalar override — applied to every month for this territory
                for m in per_month:
                    per_month[m] = override
            elif default is not None:
                # No override; apply default
                for m in per_month:
                    per_month[m] = default

    # ------------------------------------------------------------------
    # Phase 2 — Layer 1: elementwise derived values
    # ------------------------------------------------------------------

    def _compute_layer1(self):
        """
        Compute all L1 variables (elementwise, no aggregation):
            combined_bills, attainment_pct, retention_pct, retention_str, pen_pct
        """
        for t in self.data.hosp_bills:
            for m in self.months:
                # combined_bills[t][m]
                hosp   = self.data.hosp_bills[t].get(m)
                allied = self.data.allied_bills[t].get(m)
                if hosp is not None and allied is not None:
                    self.data.combined_bills[t][m] = hosp + allied
                elif hosp is not None:
                    self.data.combined_bills[t][m] = hosp
                elif allied is not None:
                    self.data.combined_bills[t][m] = allied
                else:
                    self.data.combined_bills[t][m] = None

                # attainment_pct[t][m]
                rev  = self.data.revenue[t].get(m)
                goal = self.data.goal[t].get(m)
                self.data.attainment_pct[t][m] = _attainment(rev, goal)

                # retention_pct[t][m] and retention_str[t][m]
                if t == self.NO_RETENTION_TERRITORY:
                    self.data.retention_pct[t][m] = None
                    self.data.retention_str[t][m] = "—"
                else:
                    paid   = self.data.ret_paid[t].get(m)
                    billed = self.data.ret_billed[t].get(m)
                    if billed and billed > 0 and paid is not None:
                        self.data.retention_pct[t][m] = paid / billed
                        self.data.retention_str[t][m] = f"{paid}/{billed}"
                    else:
                        self.data.retention_pct[t][m] = None
                        self.data.retention_str[t][m] = "—"

            # pen_pct[t] (static — does not depend on m)
            #
            # Compute from admin-input sources (Hannah's CSV) to guarantee numerator
            # and denominator share the same filter universe. Previously this used
            # SLX-derived pen_active (compute_pen_active counts ALL active non-Allied
            # accounts, no size filter) divided by Hannah's filtered market — giving
            # ratios >100% for territories with many small restaurants.
            #
            # Correct: Hannah's combined active / Hannah's combined market.
            active_r = self.data.pen_active_restaurant.get(t)
            active_l = self.data.pen_active_lodging.get(t)
            market_r = self.data.pen_market_restaurant.get(t)
            market_l = self.data.pen_market_lodging.get(t)
            # A missing segment contributes ZERO — it doesn't veto the ratio
            # (P1-5, 7/16: Majors/NRA has no lodging market; the handmade shows
            # its combined pen as the restaurant-only 87.5% = 781/893).
            if active_r is None and active_l is None:
                self.data.pen_pct[t] = None
                continue
            combined_active = (active_r or 0) + (active_l or 0)
            combined_market = (market_r or 0) + (market_l or 0)
            self.data.pen_pct[t] = (
                combined_active / combined_market if combined_market > 0 else None
            )

    # ------------------------------------------------------------------
    # Phase 3 — Layer 2: aggregations
    # ------------------------------------------------------------------

    def _compute_layer2(self):
        """
        Compute all L2 variables (linear aggregations):
            ytd_revenue, ytd_goal, ytd_members,
            statewide_revenue, statewide_goal, statewide_members,
            avg_retention, statewide_avg_pen
        """
        territories = list(self.data.revenue.keys())

        for t in territories:
            # ytd_revenue[t] = Σ_m revenue[t][m]   (R_revenue @ 1_M)
            self.data.ytd_revenue[t] = _safe_sum(
                self.data.revenue[t].get(m) for m in self.months
            )
            # ytd_goal[t] = Σ_m goal[t][m]
            self.data.ytd_goal[t] = _safe_sum(
                self.data.goal[t].get(m) for m in self.months
            )
            # ytd_members[t] = Σ_m new_members[t][m]
            self.data.ytd_members[t] = _safe_sum_int(
                self.data.new_members[t].get(m) for m in self.months
            )
            # avg_retention[t] = count-WEIGHTED rate Σpaid / Σbilled across billed
            # months — NOT the unweighted mean of monthly ratios. A 100-billed
            # month must outweigh a 2-billed month; the old mean-of-percentages
            # skewed toward low-volume outliers. (R4 / fix-queue M1.)
            tot_paid = sum(
                v for m in self.months
                if (v := self.data.ret_paid[t].get(m)) is not None
            )
            tot_billed = sum(
                v for m in self.months
                if (v := self.data.ret_billed[t].get(m)) is not None
            )
            self.data.avg_retention[t] = (
                tot_paid / tot_billed if tot_billed > 0 else None
            )

        for m in self.months:
            # statewide_revenue[m] = Σ_t revenue[t][m]   (1_T.T @ R_revenue)
            self.data.statewide_revenue[m] = _safe_sum(
                self.data.revenue[t].get(m) for t in territories
            )
            # statewide_goal[m]
            self.data.statewide_goal[m] = _safe_sum(
                self.data.goal[t].get(m) for t in territories
            )
            # statewide_members[m]
            self.data.statewide_members[m] = _safe_sum_int(
                self.data.new_members[t].get(m) for t in territories
            )

        # statewide_avg_pen = aggregate Σactive / Σmarket across territories —
        # NOT the unweighted mean of territory rates. A large market must outweigh
        # a tiny one. (4c / fix-queue M2.) The universe MIRRORS the per-territory
        # pen_pct guard (P1-5): a territory with at least one active segment
        # contributes its 0-coalesced sums; a missing segment contributes zero
        # rather than vetoing the whole territory. (Finding #3, 2026-07-17: the
        # old "all four counts + both markets truthy" guard silently dropped a
        # restaurant-only territory like Majors/NRA — lodging market 0 → falsy —
        # from BOTH numerator and denominator, and via _pen_status skewed every
        # territory's Above/Near/Below flag.)
        tot_active = 0.0
        tot_market = 0.0
        for t in territories:
            ar = self.data.pen_active_restaurant.get(t)
            al = self.data.pen_active_lodging.get(t)
            mr = self.data.pen_market_restaurant.get(t)
            ml = self.data.pen_market_lodging.get(t)
            if ar is None and al is None:
                continue
            tot_active += (ar or 0) + (al or 0)
            tot_market += (mr or 0) + (ml or 0)
        self.data.statewide_avg_pen = (
            tot_active / tot_market if tot_market > 0 else None
        )

    # ------------------------------------------------------------------
    # Phase 4 — Layer 3: season-level ratios and classifications
    # ------------------------------------------------------------------

    def _compute_layer3(self):
        """
        Compute all L3 variables (season-level derived):
            season_attainment, dollars_per_member,
            ret_status, pen_status,
            statewide_attainment, mom_change,
            latest_billables, delta_oct_to_mar,
            best_month, trend
        """
        avg_pen = self.data.statewide_avg_pen

        for t in self.data.ytd_revenue:
            ytd_rev  = self.data.ytd_revenue.get(t)
            ytd_goal = self.data.ytd_goal.get(t)
            ytd_mem  = self.data.ytd_members.get(t)

            # season_attainment[t]
            self.data.season_attainment[t] = _attainment(ytd_rev, ytd_goal)

            # dollars_per_member[t]
            if ytd_rev is not None and ytd_mem and ytd_mem > 0:
                self.data.dollars_per_member[t] = ytd_rev / ytd_mem
            else:
                self.data.dollars_per_member[t] = None

            # ret_status[t]
            avg_ret = self.data.avg_retention.get(t)
            self.data.ret_status[t] = _retention_status(avg_ret)

            # pen_status[t]
            self.data.pen_status[t] = _pen_status(self.data.pen_pct.get(t), avg_pen)

            # latest_billables[t] = combined_bills[t][last available month]
            self.data.latest_billables[t] = _latest_value(
                self.data.combined_bills[t], self.months
            )

            # delta_oct_to_mar[t]
            oct_val = self.data.combined_bills[t].get("Oct")
            mar_val = self.data.combined_bills[t].get("Mar")
            if oct_val is not None and mar_val is not None:
                self.data.delta_oct_to_mar[t] = mar_val - oct_val
            else:
                self.data.delta_oct_to_mar[t] = None

            # best_month[t] = argmax_m revenue[t][m]
            rev_by_month = {
                m: self.data.revenue[t].get(m)
                for m in self.months
                if self.data.revenue[t].get(m) is not None
            }
            if rev_by_month:
                self.data.best_month[t] = max(rev_by_month, key=rev_by_month.get)
            else:
                self.data.best_month[t] = None

            # trend[t]: compare last 3 months avg vs prior 3 months avg
            self.data.trend[t] = _trend(
                [self.data.revenue[t].get(m) for m in self.months]
            )

        for i, m in enumerate(self.months):
            sw_rev  = self.data.statewide_revenue.get(m)
            sw_goal = self.data.statewide_goal.get(m)

            # statewide_attainment[m]
            self.data.statewide_attainment[m] = _attainment(sw_rev, sw_goal)

            # mom_change[m]
            if i == 0:
                self.data.mom_change[m] = None  # no prior month
            else:
                prev_m   = self.months[i - 1]
                prev_rev = self.data.statewide_revenue.get(prev_m)
                if sw_rev is not None and prev_rev and prev_rev != 0:
                    self.data.mom_change[m] = (sw_rev - prev_rev) / prev_rev
                else:
                    self.data.mom_change[m] = None


# ---------------------------------------------------------------------------
# Private helper functions
# ---------------------------------------------------------------------------

def _attainment(revenue, goal) -> Optional[float]:
    """
    Compute attainment fraction (revenue / goal).

    Returns None when:
      - revenue or goal is None (no data)
      - goal == 0 (meaningful: TM already met goal, or no goal was set for that
        month — the % cell stays blank rather than showing a misleading number)

    A percentage column with an unset/zero denominator is meaningless. The
    Scoreboard treats blank as "n/a" in this case.
    """
    if revenue is None or goal is None:
        return None
    if goal == 0:
        return None
    return revenue / goal


def _retention_status(avg_ret: Optional[float], threshold: float = DEFAULT_RETENTION_GOAL) -> str:
    """Return "On Track", "Watch", or "N/A" based on average retention fraction."""
    if avg_ret is None:
        return "N/A"
    return "On Track" if avg_ret >= threshold else "Watch"


def _pen_status(pen_pct: Optional[float], statewide_avg: Optional[float]) -> str:
    """
    Return "Above Avg", "Near Avg", "Below Avg", or "N/A".

    Thresholds: ±5% of statewide average.
      Above Avg : pen_pct >= statewide_avg * 1.05
      Near Avg  : pen_pct >= statewide_avg * 0.95
      Below Avg : pen_pct <  statewide_avg * 0.95
    """
    if pen_pct is None or statewide_avg is None or statewide_avg == 0:
        return "N/A"
    if pen_pct >= statewide_avg * 1.05:
        return "Above Avg"
    if pen_pct >= statewide_avg * 0.95:
        return "Near Avg"
    return "Below Avg"


def _latest_value(monthly_dict: Dict[str, Optional[int]], months: List[str]) -> Optional[int]:
    """Return the value from the last month in `months` that has a non-None value."""
    for m in reversed(months):
        v = monthly_dict.get(m)
        if v is not None:
            return v
    return None


def _trend(values: List[Optional[float]]) -> str:
    """
    Compute revenue trend arrow from a list of monthly values (in season order).

    Rule: compare mean of last 3 months vs mean of prior 3 months.
      ↑ if last3_avg > prior3_avg * 1.05
      ↓ if last3_avg < prior3_avg * 0.95
      → otherwise
      — if fewer than 6 months of data available

    Args:
        values: Monthly revenue values in season order. None values are skipped.
    """
    non_null = [v for v in values if v is not None]
    if len(non_null) < 6:
        return "—"

    last3  = non_null[-3:]
    prior3 = non_null[-6:-3]
    avg_last  = sum(last3)  / len(last3)
    avg_prior = sum(prior3) / len(prior3)

    if avg_prior == 0:
        return "—"
    if avg_last > avg_prior * 1.05:
        return "↑"
    if avg_last < avg_prior * 0.95:
        return "↓"
    return "→"


def _safe_sum(values) -> Optional[float]:
    """Sum a generator of float|None values. Returns None if all are None."""
    total = 0.0
    has_any = False
    for v in values:
        if v is not None:
            total += v
            has_any = True
    return total if has_any else None


def _safe_sum_int(values) -> Optional[int]:
    """Sum a generator of int|None values. Returns None if all are None."""
    total = 0
    has_any = False
    for v in values:
        if v is not None:
            total += int(v)
            has_any = True
    return total if has_any else None
