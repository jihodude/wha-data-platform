"""
writer.py — TrackerV4Writer: writes mapper output into the v4 template workbook.

Targets three sheets in `Membership_Performance_Tracker_v4.xlsx`:
  1. Data - Monthly Metrics    — long-form metric rows (the central data store)
  2. Data - Drops              — per-account drop detail
  3. Data - Closed Businesses  — per-account closed-business detail

All other sheets (Summary Dashboard, 11 TM sheets, Ref sheets) are computed by
Excel formulas reading from these three data sheets. We do NOT write to them —
touching those would clobber formatting and formulas.

UPSERT semantics for Data - Monthly Metrics:
    Existing rows matching the same (Year, Month, Territory, Metric) tuple get
    overwritten in place. New rows are appended at the bottom. This means:
      • Running the engine again with refreshed SLX data updates existing rows
      • Historical backfills (different years) append without conflict
      • Partial runs (e.g. only current_month) only touch the rows they own

REPLACE semantics for Data - Drops and Data - Closed Businesses:
    These sheets contain detail snapshots — every run starts fresh. The writer
    clears existing data rows (preserving headers) before writing the new set.

Row offsets (confirmed from template inspection):
    Data - Monthly Metrics:    header at row 4, data starts at row 5
    Data - Drops:              header at row 3, data starts at row 4
    Data - Closed Businesses:  header at row 3, data starts at row 4

Template preservation:
    The template file is never modified — all writes go to a copy at output_path.
    Existing formatting, merged cells, formulas, and other sheets are preserved.

Usage:
    from reports.membership_performance_tracker.writer import TrackerV4Writer

    writer = TrackerV4Writer(template_path=Path("data/raw/v4_template.xlsx"))
    writer.write(
        output_path=Path("data/output/Tracker v4 2026-03.xlsx"),
        metric_rows=mapper_rows,           # from TrackerV4Mapper.map()
        drops_rows=data.drops_detail,      # from ScoreboardData
        closed_rows=data.closed_detail,
    )
"""

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl

from reports.membership_performance_tracker.trend_sheet import build_monthly_trend_sheet


# ---------------------------------------------------------------------------
# Sheet / column constants — confirmed against v4 template
# ---------------------------------------------------------------------------

METRICS_SHEET = "Data - Monthly Metrics"
METRICS_HEADER_ROW = 4
METRICS_DATA_START_ROW = 5
# Column order on Data - Monthly Metrics sheet:
# A=Year (1), B=Month (2), C=Territory (3), D=Metric (4), E=Value (5), F=Notes (6)
METRICS_COL_YEAR      = 1
METRICS_COL_MONTH     = 2
METRICS_COL_TERRITORY = 3
METRICS_COL_METRIC    = 4
METRICS_COL_VALUE     = 5
METRICS_COL_NOTES     = 6

DROPS_SHEET = "Data - Drops"
DROPS_HEADER_ROW = 3
DROPS_DATA_START_ROW = 4
# A=Account ID  B=Account Name  C=Territory  D=Territory Manager  E=Business Type
# F=Employee Count  G=Target (Y/N)  H=Renewal Year  I=Renewal Month  J=Drop Reason
# K=Amount Billed ($)  L=Drop Date  M=Drop Category (header written by the
# writer — the template predates categories; ratified rollup, detail-level)
DROPS_COLUMNS = [
    "account_id",        # col A
    "account_name",      # col B
    "territory",         # col C
    "territory_manager", # col D
    "business_type",     # col E
    "employee_count",    # col F
    "target_yn",         # col G — via _yn(): True/'Y'→Y, False/'N'→N, unknown→blank
    "renewal_year",      # col H
    "renewal_month",     # col I
    "drop_reason",       # col J
    "amount_billed",     # col K
    "drop_date",         # col L
    "drop_category",     # col M — Closed/Sold/Non-Payment/Voluntary/Admin
]

CLOSED_SHEET = "Data - Closed Businesses"
CLOSED_HEADER_ROW = 3
CLOSED_DATA_START_ROW = 4

# A=Account ID  B=Account Name  C=Territory  D=Territory Manager  E=Business Type
# F=Target (Y/N)  G=Was Member at Closure (Y/N)  H=Date Closed  I=Notes
CLOSED_COLUMNS = [
    "account_id",         # col A
    "account_name",       # col B
    "territory",          # col C
    "territory_manager",  # col D
    "business_type",      # col E
    "target_yn",          # col F — derived
    "was_member_yn",      # col G — derived from was_member_at_closure
    "date_closed",        # col H
    "notes",              # col I
]


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

class TrackerV4Writer:
    """
    Writes engine output to a copy of the v4 tracker template.

    Args:
        template_path: Path to the v4 template xlsx. Never modified — always copied.
    """

    def __init__(self, template_path: Path):
        self.template_path = Path(template_path)
        if not self.template_path.exists():
            raise FileNotFoundError(f"v4 template not found: {self.template_path}")

    def write(
        self,
        output_path: Path,
        metric_rows: List[Dict[str, Any]],
        drops_rows: Optional[List[Dict[str, Any]]] = None,
        closed_rows: Optional[List[Dict[str, Any]]] = None,
        dashboard_month: "Optional[str]" = None,
        dashboard_year: "Optional[int]" = None,
    ) -> Path:
        """
        Apply all data writes to a copy of the template.

        Args:
            output_path:    Destination for the populated workbook.
            metric_rows:    From TrackerV4Mapper.map() — list of {year, month,
                            territory, metric, value, notes} dicts.
            drops_rows:     From ScoreboardData.drops_detail.
            closed_rows:    From ScoreboardData.closed_detail.

        Returns:
            output_path (for chaining / logging).
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy2(self.template_path, output_path)
        wb = openpyxl.load_workbook(output_path)

        # Always upsert metrics
        self._write_metrics(wb, metric_rows)

        # Definitions & provenance (Q-FINAL B1, 7/16): the trust story lives
        # IN the artifact — every number family sourced, every known
        # CRM-report divergence named where reviewers will actually look.
        self._write_provenance(wb)

        # Replace-mode for detail sheets
        if drops_rows is not None:
            self._write_detail(
                wb, DROPS_SHEET, DROPS_DATA_START_ROW, DROPS_COLUMNS,
                self._prep_drops(drops_rows),
            )
            # Column M postdates the template's header row — stamp it here.
            wb[DROPS_SHEET].cell(row=DROPS_HEADER_ROW, column=13,
                                 value="Drop Category")
            # C9 (SuzAnne, walkthrough 19:05: "total would be very helpful")
            # — the detail list she researches drop reasons in never said how
            # many rows it held; only the main summary did. Written fresh
            # each run, in the blank row above the header.
            _n = len(drops_rows)
            _reasons = len({str(r.get("drop_reason") or "").strip()
                            for r in drops_rows
                            if str(r.get("drop_reason") or "").strip()})
            wb[DROPS_SHEET].cell(
                row=DROPS_HEADER_ROW - 1, column=1,
                value=f"Total drops listed: {_n}  ·  "
                      f"distinct drop reasons: {_reasons}")
        if False and closed_rows is not None:   # tab removed 8/6 (Jiho) —
            # closed businesses are fully off the face; the engine's
            # closed_detail stays internal
            self._write_detail(
                wb, CLOSED_SHEET, CLOSED_DATA_START_ROW, CLOSED_COLUMNS,
                self._prep_closed(closed_rows),
            )

        # Benefit reviews were retired entirely 2026-07-20 (off the report
        # since 7/13; collection stopped 7/20) — remove the sheet if an older
        # template still carries it.
        if "Benefit Reviews" in wb.sheetnames:
            wb.remove(wb["Benefit Reviews"])

        # Dashboard selector defaults to the REPORT month/year (2026-07-14) —
        # the template shipped stuck on "Apr", so every open showed the wrong
        # month until someone flipped the dropdown.
        if dashboard_month and "Summary Dashboard" in wb.sheetnames:
            dash = wb["Summary Dashboard"]
            dash["E4"] = dashboard_month
            if dashboard_year:
                dash["B4"] = dashboard_year

        # All-TM monthly trend page (formula-driven, statewide SUMIFS over the
        # data sheet). Idempotent (re)build after Summary Dashboard — does not
        # touch any data we just wrote. See trend_sheet.py.
        build_monthly_trend_sheet(wb)

        wb.save(output_path)
        wb.close()
        return output_path

    # ------------------------------------------------------------------
    # Data - Monthly Metrics (upsert)
    # ------------------------------------------------------------------

    def _write_metrics(self, wb, rows: List[Dict[str, Any]]) -> None:
        """
        Upsert (Year, Month, Territory, Metric) rows into Data - Monthly Metrics.

        Existing rows with the same key tuple are overwritten in place; new keys
        are appended after the last non-empty data row.
        """
        if METRICS_SHEET not in wb.sheetnames:
            import warnings
            warnings.warn(f"[v4 writer] sheet '{METRICS_SHEET}' missing from template")
            return

        ws = wb[METRICS_SHEET]

        # Build index of existing rows: (year, month, territory, metric) -> row_number
        existing: Dict[Tuple, int] = {}
        last_row = METRICS_DATA_START_ROW - 1
        for row_idx in range(METRICS_DATA_START_ROW, ws.max_row + 1):
            year      = ws.cell(row=row_idx, column=METRICS_COL_YEAR).value
            month     = ws.cell(row=row_idx, column=METRICS_COL_MONTH).value
            territory = ws.cell(row=row_idx, column=METRICS_COL_TERRITORY).value
            metric    = ws.cell(row=row_idx, column=METRICS_COL_METRIC).value
            # Stop at the first fully-empty row (template may have empty trailing rows)
            if all(v is None for v in (year, month, territory, metric)):
                break
            existing[(year, month, territory, metric)] = row_idx
            last_row = row_idx

        next_append_row = last_row + 1

        for r in rows:
            key = (r["year"], r["month"], r["territory"], r["metric"])
            row_idx = existing.get(key)
            if row_idx is None:
                row_idx = next_append_row
                next_append_row += 1
                ws.cell(row=row_idx, column=METRICS_COL_YEAR,      value=r["year"])
                ws.cell(row=row_idx, column=METRICS_COL_MONTH,     value=r["month"])
                ws.cell(row=row_idx, column=METRICS_COL_TERRITORY, value=r["territory"])
                ws.cell(row=row_idx, column=METRICS_COL_METRIC,    value=r["metric"])
                existing[key] = row_idx
            value_cell = ws.cell(row=row_idx, column=METRICS_COL_VALUE, value=r["value"])
            # D7 ship-gate (2026-07-30, Jiho: "instead of 0.56, 56% is what we
            # want"): percentage metrics carry a % format IN THE STORE too, so
            # a raw decimal can never render anywhere the row is read.
            if "%" in str(r["metric"]):
                value_cell.number_format = "0.0%"
            if r.get("notes"):
                ws.cell(row=row_idx, column=METRICS_COL_NOTES, value=r["notes"])

    # ------------------------------------------------------------------
    # Detail sheets (replace mode)
    # ------------------------------------------------------------------


    _PROVENANCE = [
        ("Where the numbers come from (and why some differ from CRM reports)", None),
        ("New sales revenue", "CRM membership dues payments (WRA), counted in the month each payment "
         "ARRIVES - installments land as they come (membership team rule, 7/30). Claims-program fees "
         "(CMP, Retro) are never counted. Credit follows the SELLER (CRM 'Acct. Originator'), so "
         "cross-territory sales sit in the seller's column."),
        ("New members", "Members enrolled in the month, counted when their first payment arrives "
         "(a sale is a sale when it's paid). Separately-billed locations count. A member who returns "
         "after a ~6-month gap IS a new member (membership team rule, 7/30) - the enroll date is the "
         "authority. History is never rewritten: members who later drop still count for their join month."),
        ("Billables", "Active accounts carrying a membership product - computed directly from the CRM "
         "database (7/30). Hospitality/allied split follows the PRODUCT (e.g. 'Allied Corporate Dues' "
         "= allied). ~11 statewide vendor partners under the house AlliedRelationsManager user are "
         "excluded from territory counts."),
        ("Lodging targets", "Hotels with 40+ rooms are Target (confirmed by the membership team, 7/21)."),
        ("Retention", "Month column M shows bill-month M-1 cohorts, first-cycle members excluded - the CRM's own AdjustedRetention conventions. "
         "A partial payer counts as retained (they stayed). Members who convert to the retro program (RRO) "
         "leave that cycle's retention entirely - both sides of the ratio (membership team rule, 7/30). "
         "Allied members are NOT in these lines - they carry no TM goal and are tracked separately "
         "(ruled 8/14). 'T + NT' is Target plus Non-Target, hospitality only."),
        ("Drops", "The CRM drop report's Inactive and Closed members, bill months 1-12. RRO (retro) rows are "
         "FYI, never drops; bill month 14 is out by design; Allied drops are included as Non-Target; a few "
         "stale records (last billed years ago) are excluded and listed in the flags file. "
         "Lost revenue = each member's Dues Level (membership product price)."),
        ("Penetration", "Active vs total market by territory; restaurants = accounts typed 'Restaurant' (ratified scope). "
         "Matches the CRM penetration reports and the HCB workbook."),
        ("Promo memberships", "'BOB 2-Year' promo members count at face value (the promo credit "
         "is not subtracted) - matching the membership team's convention. Ledger cash differs by design."),
        ("Questions?", "Every rule's full story: docs/DECISIONS.md in the project repo. "
         "Verification: every monthly run is gated against the CRM's own reports before publishing."),
    ]

    def _write_provenance(self, wb) -> None:
        """README tab is BLANK for now (Jiho 2026-07-21): all content removed;
        the tab gets rebuilt after the v1 stamp together with the SOP redo,
        GitHub redo, and folder reconstruction (post-v1 bundle — see PLAN.md
        and docs/RECONCILIATION.md for where the divergence registry lives
        meanwhile). self._PROVENANCE is retained as the rebuild's source text."""
        if "README" not in wb.sheetnames:
            return
        ws = wb["README"]
        for rng in list(ws.merged_cells.ranges):
            ws.unmerge_cells(str(rng))
        for row in ws.iter_rows():
            for c in row:
                c.value = None

    def _write_detail(
        self,
        wb,
        sheet_name: str,
        data_start_row: int,
        column_keys: List[str],
        rows: List[List[Any]],
    ) -> None:
        """
        Replace all data rows on a detail sheet (preserves header + formatting).

        Args:
            sheet_name:     Target sheet name.
            data_start_row: 1-based row where data begins (header row + 1).
            column_keys:    Ordered list of dict keys → 1-based column positions.
            rows:           Pre-flattened list of [col1, col2, ...] lists.
        """
        if sheet_name not in wb.sheetnames:
            import warnings
            warnings.warn(f"[v4 writer] sheet '{sheet_name}' missing from template")
            return

        ws = wb[sheet_name]
        n_cols = len(column_keys)

        # Usability (Q-FINAL B4, 7/16): detail sheets run thousands of rows —
        # freeze the header and give reviewers an autofilter.
        from openpyxl.utils import get_column_letter
        header_row = data_start_row - 1
        ws.freeze_panes = f"A{data_start_row}"
        ws.auto_filter.ref = (
            f"A{header_row}:{get_column_letter(n_cols)}"
            f"{max(data_start_row, header_row + len(rows))}"
        )

        # Clear existing data rows (preserve header at data_start_row - 1)
        if ws.max_row >= data_start_row:
            for row_idx in range(data_start_row, ws.max_row + 1):
                for col_idx in range(1, n_cols + 1):
                    ws.cell(row=row_idx, column=col_idx).value = None

        # Write new rows
        for offset, row_values in enumerate(rows):
            for col_idx, val in enumerate(row_values, start=1):
                ws.cell(row=data_start_row + offset, column=col_idx, value=val)

    # ------------------------------------------------------------------
    # Detail-row preparation (flatten dicts → ordered lists)
    # ------------------------------------------------------------------

    def _prep_drops(self, raw_rows: List[Dict[str, Any]]) -> List[List[Any]]:
        """
        Flatten drop dicts (from fetch_drops_and_closed) into ordered column lists.

        Source dict keys (from reports.membership_performance_tracker.logic.drops.fetch_drops_and_closed):
            account_id, account_name, territory, territory_manager, business_type,
            employee_count, is_target, renewal_year, renewal_month, drop_reason,
            amount_billed, drop_date
        """
        out: List[List[Any]] = []
        for r in raw_rows:
            out.append([
                # Member ID (the number the CRM reports show) when available;
                # internal account id as fallback (2026-07-14, fix #3).
                r.get("member_id") or r.get("account_id"),
                r.get("account_name"),
                r.get("territory"),
                r.get("territory_manager"),
                r.get("business_type"),
                r.get("employee_count"),
                self._yn(r.get("is_target")),
                r.get("renewal_year"),
                r.get("renewal_month"),
                r.get("drop_reason"),
                r.get("amount_billed"),
                r.get("drop_date"),
                r.get("drop_category"),
            ])
        return out

    def _prep_closed(self, raw_rows: List[Dict[str, Any]]) -> List[List[Any]]:
        """
        Flatten closed-business dicts into ordered column lists.

        Source dict keys: account_id, account_name, territory, territory_manager,
        business_type, is_target, was_member_at_closure, date_closed, notes
        """
        out: List[List[Any]] = []
        for r in raw_rows:
            out.append([
                # Member ID (the number the CRM reports show) when available;
                # internal account id as fallback (2026-07-14, fix #3).
                r.get("member_id") or r.get("account_id"),
                r.get("account_name"),
                r.get("territory"),
                r.get("territory_manager"),
                r.get("business_type"),
                self._yn(r.get("is_target")),
                self._yn(r.get("was_member_at_closure")),
                r.get("date_closed"),
                r.get("notes"),
            ])
        return out

    @staticmethod
    def _yn(flag: Any) -> str:
        """Normalize a tri-state Target/membership flag to 'Y'/'N'/'' for display.

        Accepts BOTH conventions in the codebase: the bool tri-state
        (True/False/None) used by the penetration/target classifier, and the
        string tri-state ('Y'/'N'/'?') emitted by reports.membership_performance_tracker.logic.drops. Anything
        unrecognized ('?', '', None, …) renders blank.
        """
        if flag is True:
            return "Y"
        if flag is False:
            return "N"
        if isinstance(flag, str):
            s = flag.strip().upper()
            if s == "Y":
                return "Y"
            if s == "N":
                return "N"
        return ""
