"""
test_queue_batch_0714.py — three queued fixes:

A. Drops carry the user-facing MEMBER ID (cMemberGens.Membernum — same 7-digit
   number as the CRM reports' "Sale"/member column). Zero extra queries: it rides
   the renewal-info fetch drops already makes. Writer emits it in col A with
   account-id fallback. (Fix #3 from the truth-PDF finding.)
B. Retention per-territory rows MERGE across multiple mapped users (Majors/NRA
   has two since 7/13) — counts sum, the derived % is recomputed, not summed.
C. Benefit Reviews: the output SHEET is removed from the rendered report
   (decided 7/13, reconfirmed 7/14). Admin plumbing stays dormant.
"""
from pathlib import Path

import openpyxl

from reports.membership_performance_tracker.logic.drops import _get_renewal_info
from reports.membership_performance_tracker.logic.retention import _merge_retention_rows
from reports.membership_performance_tracker.writer import TrackerV4Writer

TEMPLATE = Path("reports/membership_performance_tracker/template.xlsx")


# ---------- A: member id ----------

class FakeSLX:
    def _fetch_all(self, entity, where="", select=None, page_size=200):
        if entity == "cMemberGens":
            return [{"Duesbillmonth": 6, "Membernum": "0066653",
                     "Account": {"$key": "A1"}}]
        if entity == "dlInvoiceHistoryHeader":
            return []
        raise AssertionError(entity)


def test_renewal_info_returns_membernum():
    year, month, membernum, product, _wra = _get_renewal_info(FakeSLX(), "A1")
    assert membernum == "0066653"
    assert month == "June"


def test_writer_prefers_member_id_in_col_a():
    w = TrackerV4Writer(template_path=TEMPLATE)
    rows = w._prep_drops([{
        "account_id": "A6UJ9A0001", "member_id": "0066653",
        "account_name": "Puget Sound Pizza - LakeBay", "territory": "Pierce",
        "territory_manager": "Tamorro", "business_type": "Restaurant",
        "employee_count": 14, "is_target": "Y", "renewal_year": 2026,
        "renewal_month": "May", "drop_reason": "Non-Payment",
        "amount_billed": 730.0, "drop_date": "2026-06-22",
    }])
    assert rows[0][0] == "0066653", "member id must lead col A when present"
    rows2 = w._prep_drops([{"account_id": "A6UJ9A0002", "account_name": "X",
                               "territory": "Pierce", "territory_manager": "T",
                               "business_type": "R", "employee_count": None,
                               "is_target": "N", "renewal_year": None,
                               "renewal_month": None, "drop_reason": "Sold",
                               "amount_billed": None, "drop_date": None}])
    assert rows2[0][0] == "A6UJ9A0002", "fallback to account id when no member id"


# ---------- B: retention merge ----------

def test_retention_rows_merge_and_recompute_pct():
    dst = {"paid": 10, "billed": 12, "revenue_retained": 1000.0,
           "revenue_up_for_renewal": 1200.0, "revenue_retention_pct": 83.3}
    src = {"paid": 2, "billed": 4, "revenue_retained": 200.0,
           "revenue_up_for_renewal": 800.0, "revenue_retention_pct": 25.0}
    out = _merge_retention_rows(dst, src)
    assert out["paid"] == 12 and out["billed"] == 16
    assert out["revenue_retained"] == 1200.0
    assert out["revenue_up_for_renewal"] == 2000.0
    assert out["revenue_retention_pct"] == 60.0, "pct recomputed, never summed"


# ---------- C: benefit reviews sheet removed ----------

def test_benefit_reviews_sheet_absent_from_output(tmp_path):
    out = tmp_path / "r.xlsx"
    TrackerV4Writer(template_path=TEMPLATE).write(out, metric_rows=[])
    wb = openpyxl.load_workbook(out, read_only=True)
    assert "Benefit Reviews" not in wb.sheetnames


def test_dashboard_selector_defaults_to_report_month(tmp_path):
    out = tmp_path / "d.xlsx"
    TrackerV4Writer(template_path=TEMPLATE).write(
        out, metric_rows=[], dashboard_month="Jun", dashboard_year=2026)
    wb = openpyxl.load_workbook(out, read_only=True)
    ws = wb["Summary Dashboard"]
    assert ws["E4"].value == "Jun", "dashboard must open on the report month"
    assert ws["B4"].value == 2026


def test_drop_categories():
    from reports.membership_performance_tracker.logic.drops import _drop_category
    assert _drop_category("Out of Business") == "Closed"
    assert _drop_category("Selling") == "Sold"
    assert _drop_category("Non-Payment") == "Non-Payment"
    assert _drop_category("No Benefit") == "Voluntary"
    assert _drop_category("Budget") == "Voluntary"
    assert _drop_category("Old Record Cleanup") == "Admin"
    # surfaced by the ne-Active scope in pull #8 (2026-07-14 evening): record
    # hygiene + retro-program lifecycle are NOT member losses — Admin, not
    # Voluntary (the fallback was silently counting them into monthly buckets)
    assert _drop_category("Copied Record") == "Admin"
    assert _drop_category("Duplicate Record") == "Admin"
    assert _drop_category("Retro Final Distribution") == "Admin"
    # 7/16 (Jiho deferred to evidence): only 5 rows, absent from their own
    # drops export, samples are chain sub-records (one dated 2018) — annual-
    # update housekeeping, not member losses.
    assert _drop_category("Per Annual Update") == "Admin"


# ---------- D: drop category column reaches the SHEET (gap found 7/15) ----------

def test_drops_sheet_carries_category_column(tmp_path):
    """Categories existed in the data since pull #6 but the writer never emitted
    them — the detail sheet ended at Drop Date. Column M = Drop Category."""
    w = TrackerV4Writer(template_path=TEMPLATE)
    rows = w._prep_drops([{
        "account_id": "A1", "account_name": "X", "territory": "Pierce",
        "territory_manager": "T", "business_type": "R", "employee_count": 5,
        "is_target": "N", "renewal_year": 2026, "renewal_month": "Jun",
        "drop_reason": "Out of Business", "drop_category": "Closed",
        "amount_billed": 100.0, "drop_date": "2026-06-01",
    }])
    assert rows[0][12] == "Closed", "category must be the 13th column"

    out = tmp_path / "c.xlsx"
    w.write(out, metric_rows=[], drops_rows=[{
        "account_id": "A1", "account_name": "X", "territory": "Pierce",
        "territory_manager": "T", "business_type": "R", "employee_count": 5,
        "is_target": "N", "renewal_year": 2026, "renewal_month": "Jun",
        "drop_reason": "Out of Business", "drop_category": "Closed",
        "amount_billed": 100.0, "drop_date": "2026-06-01",
    }])
    wb = openpyxl.load_workbook(out, read_only=True)
    ws = wb["Data - Drops"]
    assert ws["M3"].value == "Drop Category", "header cell M3"
    assert ws["M4"].value == "Closed", "first data row category"


# ---------- E: detail-sheet usability (Q-FINAL B4, 7/16) ----------

def test_detail_sheets_have_filter_and_frozen_header(tmp_path):
    """2,600-row detail sheets need autofilter + frozen header row to be
    usable by humans (reviewers sort/filter; headers must not scroll away)."""
    out = tmp_path / "u.xlsx"
    TrackerV4Writer(template_path=TEMPLATE).write(out, metric_rows=[], drops_rows=[{
        "account_id": "A1", "account_name": "X", "territory": "Pierce",
        "territory_manager": "T", "business_type": "R", "employee_count": 5,
        "is_target": "N", "renewal_year": 2026, "renewal_month": "Jun",
        "drop_reason": "Sold", "drop_category": "Sold",
        "amount_billed": 100.0, "drop_date": "2026-06-01",
    }], closed_rows=[])
    wb = openpyxl.load_workbook(out)
    ws = wb["Data - Drops"]
    assert ws.freeze_panes == "A4", "Data - Drops: header rows must stay visible"
    assert ws.auto_filter.ref and ws.auto_filter.ref.startswith("A3"), \
        "Data - Drops: autofilter on the header row"
    # closed businesses fully off the face (Jiho 8/6; her own reports had
    # dropped the label — the 7/27 ruling's last remnant)
    assert "Data - Closed Businesses" not in wb.sheetnames


# ---------- F: definitions & provenance on the README tab (Q-FINAL B1, 7/16) ----------

def test_readme_not_in_the_workbook(tmp_path):
    """Jiho 2026-08-06 (supersedes the 7/21 blank-README ruling): the report
    carries NO README sheet — orientation lives in the SOP, and a README
    belongs in the repository, not the deliverable."""
    out = tmp_path / "p.xlsx"
    TrackerV4Writer(template_path=TEMPLATE).write(out, metric_rows=[])
    wb = openpyxl.load_workbook(out, read_only=True)
    assert "README" not in wb.sheetnames


# ---------- G: true-0 vs no-data dash (Q-FINAL B9, 7/16) ----------

def test_template_distinguishes_zero_from_no_data():
    """A real zero renders 0; an absent month renders '-'. SUMIFS alone
    returns 0 for missing data, so every metric formula is wrapped in
    IF(COUNTIFS(criteria)=0,'-',SUMIFS(...)) and the number formats' zero
    section shows an actual zero (proven via LibreOffice recalc semantics)."""
    wb = openpyxl.load_workbook(TEMPLATE)
    ws = wb["TM - Southwest"]
    wrapped = zero_fmt = 0
    for row in ws.iter_rows(min_row=10, max_row=45, min_col=2, max_col=16):
        for c in row:
            if isinstance(c.value, str) and c.value.startswith("=IF(COUNTIFS("):
                wrapped += 1
            if c.number_format.endswith(";0") or c.number_format.endswith("0.0%;\\(0.0%\\);0.0%"):
                zero_fmt += 1
    assert wrapped > 50, f"metric formulas must be no-data-aware (found {wrapped})"
    assert zero_fmt > 50, f"zero must display as zero (found {zero_fmt})"


def test_never_a_member_class_is_admin_not_voluntary():
    """2026-07-22 drops reconciliation: an account that was NEVER a member
    cannot 'drop' — these are record hygiene, not member losses. Same for
    invalid leads and L&I account-number changes."""
    from reports.membership_performance_tracker.logic.drops import _drop_category
    assert _drop_category("Never a Member") == "Admin"
    assert _drop_category("Not a valid WRA Lead") == "Admin"
    assert _drop_category("L I Account Change") == "Admin"


def test_unknown_drop_reason_warns_and_counts_voluntary():
    """Closed vocabulary (2026-07-22): a never-seen reason must ANNOUNCE itself
    (the announcement 'Never a Member' never got) — but still count, because
    silently excluding a possible real loss is the worse failure."""
    import warnings as w
    from reports.membership_performance_tracker.logic.drops import _drop_category
    with w.catch_warnings(record=True) as caught:
        w.simplefilter("always")
        assert _drop_category("Mystery Reason 2027") == "Voluntary"
    assert any("UNRECOGNIZED" in str(c.message) for c in caught)
    with w.catch_warnings(record=True) as caught:
        w.simplefilter("always")
        assert _drop_category("No Answer") == "Voluntary"   # known: silent
        assert _drop_category("") == "Voluntary"            # blank: silent
    assert not caught


def test_drops_sheet_carries_a_total_line(tmp_path):
    """C9 (SuzAnne, walkthrough 19:05: "total would be very helpful") — the
    detail list she researches reasons in must say how many rows it holds."""
    out = tmp_path / "t.xlsx"
    base = {"account_id": "A", "account_name": "X", "territory": "Pierce",
            "territory_manager": "T", "business_type": "R",
            "employee_count": 5, "is_target": "N", "renewal_year": 2026,
            "renewal_month": "Jun", "drop_category": "Closed",
            "amount_billed": 100.0, "drop_date": "2026-06-01"}
    TrackerV4Writer(template_path=TEMPLATE).write(out, metric_rows=[], drops_rows=[
        dict(base, account_id="A1", drop_reason="Out of Business"),
        dict(base, account_id="A2", drop_reason="Non-Payment"),
        dict(base, account_id="A3", drop_reason="Non-Payment"),
    ])
    wb = openpyxl.load_workbook(out, read_only=True)
    v = wb["Data - Drops"]["A2"].value
    assert v == "Total drops listed: 3  ·  distinct drop reasons: 2", v
