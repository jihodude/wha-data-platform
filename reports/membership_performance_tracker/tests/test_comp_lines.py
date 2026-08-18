"""Comp lines — ruled 2026-08-04 (strategy meeting, Anthony's call).

The retention calculation is UNCHANGED (comps counted retained at $0/$0 —
"that's how it is at the moment", ratified). What's new is VISIBILITY:

  · Retention section gets a comp line: how many members were comped this
    month and the face dollars "we could have collected" — sitting outside
    the % calculation.
  · New Sales gets a comp line that must always read ZERO — comping new
    memberships (outside BOB) is now banned, so any number appearing there
    is an out-of-policy audit flag ("oh shoot — investigate").
"""
from datetime import date

import reports.membership_performance_tracker.logic.retention as R


class _CompSLX:
    """One territory, one bill month: two members — one paid normally, one
    comped (billed 1,891, credited -1,891 weeks later, still Active)."""
    def _fetch_all(self, path, where="", **kw):
        if path == "dlInvoiceHistoryHeader":
            rows = [
                # normal payer
                {"Accountid": "PAY1", "Invoice_number": "I-PAY", "Comment": "5",
                 "Net_invoice": 510.0, "Balance": 0.0, "Invoice_Type": "IN",
                 "Invoice_Date": "/Date(1745000000000)/"},
                # comped member: bill + later credit, nets zero
                {"Accountid": "COMP1", "Invoice_number": "I-COMP", "Comment": "5",
                 "Net_invoice": 1891.0, "Balance": 0.0, "Invoice_Type": "IN",
                 "Invoice_Date": "/Date(1745000000000)/"},
                {"Accountid": "COMP1", "Invoice_number": "I-COMPC", "Comment": "5",
                 "Net_invoice": -1891.0, "Balance": None, "Invoice_Type": "IN",
                 "Invoice_Date": "/Date(1747000000000)/"},
            ]
            return [r for r in rows if "Accountid eq" not in where or
                    where.split("Accountid eq '")[1].split("'")[0] == r["Accountid"]]
        if path == "payAllocationViews":
            if "AccountId eq" in where:
                return []
            return [{"AccountId": "PAY1", "Invoice_number": "I-PAY",
                     "Item_Id": "/RD<10", "Allocationamt": 510.0,
                     "AllocationDate": "/Date(1746000000000)/"}]
        if path == "cMemberGens":
            return []          # nobody first-cycle
        if path == "accounts":
            if "CDiverseOwnership" in where:
                return []                    # no BOBs in the base fixture
            return [{"$key": "PAY1", "Status": "Active"},
                    {"$key": "COMP1", "Status": "Active"}]
        return []


def test_retention_row_carries_comp_count_and_face_dollars():
    res = R.compute_retention_all_months(
        _CompSLX(), {"U1": "TKP"}, bill_months=[5], fiscal_year_start=2025,
        request_delay=0.0, today=date(2026, 7, 20),
    )
    row = res[5]["TKP"]
    assert row["comped_count"] == 1, f"one comped member: {row}"
    assert row["comped_dollars"] == 1891.0, "face value we could have collected"
    # the calc itself unchanged: comp counted retained at $0/$0
    assert row["paid"] == 2 and row["billed"] == 2
    assert row["revenue_retained"] == 510.0
    assert row["revenue_up_for_renewal"] == 510.0, \
        "comp face must NOT sit in revenue up for renewal (ruled 8/4)"


def test_merge_sums_comp_fields():
    a = {"paid": 1, "billed": 1, "comped_count": 1, "comped_dollars": 500.0,
         "revenue_retained": 0.0, "revenue_up_for_renewal": 0.0}
    b = {"paid": 2, "billed": 2, "comped_count": 0, "comped_dollars": 0.0,
         "revenue_retained": 100.0, "revenue_up_for_renewal": 100.0}
    m = R._merge_retention_rows(a, b)
    assert m["comped_count"] == 1 and m["comped_dollars"] == 500.0


def test_cohort_screen_flags_comped_new_sale():
    """The tripwire: a NEW member whose first bill was fully credited. Policy
    says this never happens — so it must be loudly visible when it does."""
    from reports.membership_performance_tracker.logic.ledger_revenue import cohort_screen

    class Shaped:
        def _fetch_all(self, entity, where="", select="", **kw):
            if entity == "dlInvoiceHistoryHeader":
                return [{"Invoice_number": "N1", "Net_invoice": 730.0,
                         "Balance": 0.0, "Invoice_Type": "IN",
                         "Invoice_Date": "/Date(1784678400000)/"},
                        {"Invoice_number": "N2", "Net_invoice": -730.0,
                         "Balance": None, "Invoice_Type": "IN",
                         "Invoice_Date": "/Date(1785678400000)/"}]
            return []

    comped = {}
    cohort_screen(Shaped(), {"NEWCOMP"}, date(2026, 7, 1),
                  request_delay=0, comped_out=comped)
    assert comped.get("NEWCOMP") == 730.0, f"comped new sale must be flagged: {comped}"


def test_model_and_mapper_carry_the_comp_metrics():
    from reports.membership_performance_tracker.logic.model import empty_scoreboard
    from reports.membership_performance_tracker.mapper import TrackerV4Mapper

    data = empty_scoreboard(["May"])
    assert hasattr(data, "ret_comped")
    assert hasattr(data, "ret_comped_dollars")
    assert hasattr(data, "revenue_comped_new")

    data.ret_comped.setdefault("TKP", {})["May"] = 1
    data.ret_comped_dollars.setdefault("TKP", {})["May"] = 1891.0
    data.revenue_comped_new.setdefault("TKP", {})["May"] = 0.0

    mapper = TrackerV4Mapper(fiscal_year_start=2025, current_month="May")
    rows = mapper.map(data)
    metrics = {r[3] for r in rows} if rows and isinstance(rows[0], (list, tuple)) else {
        r["metric"] for r in rows}
    assert "Retention - Comped (#)" in metrics
    assert "Retention - Comped ($)" in metrics
    assert "New Sales - Comped ($)" in metrics


class _VoidSLX(_CompSLX):
    """Same as _CompSLX but the credited member's reversal is SAME-DAY —
    a billing correction (void), not a comp (Southern Kitchen, 10/16/2025:
    bill 510 and -510 both dated the same day; NOT in the GS comp ledger)."""
    def _fetch_all(self, path, where="", **kw):
        rows = super()._fetch_all(path, where=where, **kw)
        if path == "dlInvoiceHistoryHeader":
            for r in rows:
                if r["Invoice_number"] == "I-COMPC":
                    r["Invoice_Date"] = "/Date(1745000000000)/"   # == bill date
        return rows


def test_same_day_reversal_is_void_not_comp():
    """Discriminator (approved 8/4): comp = credit issued LATER (>=7 days,
    the decision took time — Hama Hama 83d, Governor 53d); a same-day mirror
    is a data-entry void. Voids leave the cohort entirely (bill never
    happened) and must NOT appear on the comp line."""
    res = R.compute_retention_all_months(
        _VoidSLX(), {"U1": "TKP"}, bill_months=[5], fiscal_year_start=2025,
        request_delay=0.0, today=date(2026, 7, 20),
    )
    row = res[5]["TKP"]
    assert row["comped_count"] == 0, f"a void is not a comp: {row}"
    assert row["paid"] == 1 and row["billed"] == 1, \
        "the voided bill leaves both sides entirely"


class _BobSLX(_CompSLX):
    """The comped member is a BOB (CDiverseOwnership) with TEXT-comment
    invoices ('2026 Dues - BOB Initiative') — invisible to Comment='M'
    filters (Serious Soul Cafe class). Their comped renewal counts at FACE
    (ruled 8/4: 'counting towards their revenue renewal'), NOT on the comp
    line."""
    def _fetch_all(self, path, where="", **kw):
        if path == "dlInvoiceHistoryHeader":
            rows = super()._fetch_all(path, where=where, **kw)
            for r in rows:
                if r["Accountid"] == "COMP1":
                    r["Comment"] = "2026 Dues - BOB Initiative"
            return rows
        if path == "cMemberGens":
            return [{"Account": {"$key": "COMP1"}, "Duesbillmonth": "5",
                     "MembershipProduct": "Membership Dues",
                     "EnrolledDate": "/Date(1600000000000)/"}]
        if path == "accounts" and "CDiverseOwnership" in where:
            return [{"$key": "COMP1", "Status": "Active"}]
        return super()._fetch_all(path, where=where, **kw)


def test_bob_comped_renewal_counts_at_face_not_on_comp_line():
    res = R.compute_retention_all_months(
        _BobSLX(), {"U1": "TKP"}, bill_months=[5], fiscal_year_start=2025,
        request_delay=0.0, today=date(2026, 7, 20),
    )
    row = res[5]["TKP"]
    assert row["billed"] == 2 and row["paid"] == 2, f"BOB admitted + retained: {row}"
    assert row["revenue_up_for_renewal"] == 510.0 + 1891.0, \
        "BOB face counts in the ask (ruled 8/4)"
    assert row["revenue_retained"] == 510.0 + 1891.0, \
        "BOB face counts as retained revenue (ruled 8/4)"
    assert row["comped_count"] == 0, "a BOB is not on the comp line"
    assert row["bob_count"] == 1 and row["bob_dollars"] == 1891.0


def test_bob_joins_do_not_trip_the_comped_new_flag():
    """8/5 fix: the 8/4 verification's 22 tripwire hits were ALL BOB joins
    (months matched the BOB enrollment calendar). BOB comps are the program
    working, not violations — only non-BOB comped new sales flag."""
    from reports.membership_performance_tracker.logic import revenue as REV
    from datetime import date

    class SLX:
        def _fetch_all(self, entity, where="", select="", **kw):
            if entity == "accounts" and "CDiverseOwnership" in where:
                return [{"$key": "BOBNEW"}]
            if entity == "cMemberGens":
                return [{"Accountid": "BOBNEW"}]
            if entity == "dlInvoiceHistoryHeader":
                return [{"Invoice_number": "B1", "Net_invoice": 510.0,
                         "Balance": 0.0, "Invoice_Type": "IN",
                         "Invoice_Date": "/Date(1784678400000)/"},
                        {"Invoice_number": "B2", "Net_invoice": -510.0,
                         "Balance": None, "Invoice_Type": "IN",
                         "Invoice_Date": "/Date(1785678400000)/"}]
            return []

    out = REV.revenue_and_counts_by_first_pay(
        SLX(), {"U1": "TKP"},
        [("Jul", date(2026, 7, 1), date(2026, 7, 31))], request_delay=0)
    assert out["TKP"]["Jul"]["comped_new"] == 0.0, \
        "a BOB join must not appear as an out-of-policy comped new sale"


def test_comped_new_flag_carries_the_account_ids():
    """Jiho 8/5: member identities never sit on the report face — the flag
    carries ACCOUNT IDS pointing into the transparency dataset (the 8/5
    battery hit took live SLX queries to identify Delfino's; a human should
    just read the flag)."""
    from reports.membership_performance_tracker.logic import revenue as REV
    from datetime import date

    class SLX:
        def _fetch_all(self, entity, where="", select="", **kw):
            if entity == "accounts" and "CDiverseOwnership" in where:
                return []                       # not a BOB
            if entity == "cMemberGens":
                return [{"Accountid": "NEWCOMP"}]
            if entity == "dlInvoiceHistoryHeader":
                return [{"Invoice_number": "N1", "Net_invoice": 1170.0,
                         "Balance": 0.0, "Invoice_Type": "IN",
                         "Invoice_Date": "/Date(1779235200000)/"},
                        {"Invoice_number": "N2", "Net_invoice": -1170.0,
                         "Balance": None, "Invoice_Type": "IN",
                         "Invoice_Date": "/Date(1779235200000)/"}]
            return []

    out = REV.revenue_and_counts_by_first_pay(
        SLX(), {"U1": "NorthKing"},
        [("May", date(2026, 5, 1), date(2026, 5, 31))], request_delay=0)
    cell = out["NorthKing"]["May"]
    assert cell["comped_new"] == 1170.0
    assert cell["comped_new_accounts"] == {"NEWCOMP": 1170.0}, \
        "the flag must be able to NAME the account, not just the dollars"


def test_comp_line_splits_by_band_and_sums_to_combined():
    """Ruled 8/5 (supersedes 8/4 combined-only): the comp line appears in
    BOTH band sections so the combined comp traces to its band. Invariant:
    target + non-target = combined, members and dollars. A member the
    target map can't classify folds into non-target — the same convention
    the revenue side uses (engine folds unknown into NT for display)."""
    res = R.compute_retention_all_months(
        _CompSLX(), {"U1": "TKP"}, bill_months=[5], fiscal_year_start=2025,
        request_delay=0.0, today=date(2026, 7, 20),
        include_target_split=True,
    )
    row = res[5]["TKP"]
    assert row["comped_count"] == 1
    assert (row["comped_target_count"] + row["comped_non_target_count"]
            == row["comped_count"])
    assert (row["comped_target_dollars"] + row["comped_non_target_dollars"]
            == row["comped_dollars"])
    assert row["comped_non_target_count"] == 1, \
        "unclassifiable band folds into non-target (revenue precedent)"

    # without the split, band fields must be ABSENT — never a silent
    # everything-is-NT fold (the 8/5 backfill bug: default False built no
    # target map and published fold-garbage that summed correctly)
    res2 = R.compute_retention_all_months(
        _CompSLX(), {"U1": "TKP"}, bill_months=[5], fiscal_year_start=2025,
        request_delay=0.0, today=date(2026, 7, 20),
    )
    assert "comped_target_count" not in res2[5]["TKP"], \
        "band fields must not exist when no target map was built"


def test_band_comp_metrics_flow_to_model_and_mapper():
    from reports.membership_performance_tracker.mapper import (
        METRIC_FIELD_MAP, TrackerV4Mapper)
    from reports.membership_performance_tracker.logic.model import empty_scoreboard
    for metric, field in (
            ("Retention - Comped Target (#)", "ret_comped_target"),
            ("Retention - Comped Non-Target (#)", "ret_comped_non_target"),
            ("Retention - Comped Target ($)", "ret_comped_dollars_target"),
            ("Retention - Comped Non-Target ($)", "ret_comped_dollars_non_target")):
        assert METRIC_FIELD_MAP.get(metric) == ("tm", field), metric
    fy = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
          "Apr", "May", "Jun", "Jul", "Aug", "Sep"]
    d = empty_scoreboard(fy)
    d.ret_comped_target.setdefault("TKP", {})["May"] = 1
    d.ret_comped_dollars_non_target.setdefault("TKP", {})["May"] = 730.0
    rows = TrackerV4Mapper(fiscal_year_start=2025, current_month="Jul").map(d)
    got = {r["metric"]: r["value"] for r in rows
           if r["territory"] == "TKP" and r["month"] == "May"
           and "Comped" in r["metric"]}
    assert got.get("Retention - Comped Target (#)") == 1
    assert got.get("Retention - Comped Non-Target ($)") == 730.0


def test_bob_face_reaches_the_band_split_too():
    """8/6 wiring check: the T/NT split (which every TM sheet reads) had a
    _comp branch but NO _bob branch — Velvet's Big Easy published as unpaid
    with $0 retained in the band sections while the combined engine path
    counted it at face. One rule, BOTH paths."""
    res = R.compute_retention_all_months(
        _BobSLX(), {"U1": "TKP"}, bill_months=[5], fiscal_year_start=2025,
        request_delay=0.0, today=date(2026, 7, 20),
        include_target_split=True,
    )
    row = res[5]["TKP"]
    # the BOB (unknown band → NT fold) must be paid + at face in the split
    assert row["paid_target"] + row["paid_non_target"] == row["paid"]
    assert (row["revenue_retained_target"] + row["revenue_retained_non_target"]
            == row["revenue_retained"])
    assert (row["revenue_up_target"] + row["revenue_up_non_target"]
            == row["revenue_up_for_renewal"])
