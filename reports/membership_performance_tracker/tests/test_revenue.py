"""
test_revenue.py — new-member sales revenue summation contract.

RESOLVED 2026-07-21 (Jen, primary source): "Tapped at the Port"'s MSC lines
("2026 Retro Fee Q2" reversed → rebilled identical $766.76 as "2026 CMP Fee
BM 4-12") are CLAIMS MANAGEMENT PROGRAM fees, not dues — the member's dues
level is $0.00 (billed at the parent group, if at all). The 7/15 belief that
CMP-fee MSC lines were payment-plan dues was a mis-inference from that very
account. Rule: dues = WRA only; no MSC line is ever a sale.

These tests pin the client-side summation contract in `_sum_new_member_dues`:
  - count WRA dues only; every MSC line (CMP/Retro/blank) is excluded,
  - net AD reversals against their IN by summing signed Net_invoice,
  - ignore non-dues comp codes and non-new accounts.
"""

from reports.membership_performance_tracker.logic.revenue import _sum_new_member_dues


def test_msc_cmp_fee_is_never_a_sale():
    # 7/21 rule: CMP = Claims Management Program fee — excluded even for a
    # brand-new member, even when fully paid.
    new_ids = {"ACCT_NEW"}
    invoices = [
        {"Accountid": "ACCT_NEW", "Comp_code": "MSC", "Invoice_Type": "IN",
         "Net_invoice": 766.76, "Balance": 0.0, "Po_number": "2026 CMP Fee BM 4-12"},
    ]
    amounts = _sum_new_member_dues(invoices, new_ids)
    assert amounts == {}


def test_ad_reversal_nets_against_in():
    # Tapped-at-the-Port footprint: 4/1 IN +766.76, 4/1 AD -766.76 (reversal),
    # 5/1 IN +766.76. Net billed = 766.76, NOT 1533.52 (which IN-only would give).
    # (updated 2026-07-14: rule is WRA-only paid-basis; reversal footprint now
    # exercised with WRA rows — same netting behavior, paid = Net − Balance.)
    new_ids = {"ACCT_NEW"}
    invoices = [
        {"Accountid": "ACCT_NEW", "Comp_code": "WRA", "Invoice_Type": "IN",
         "Net_invoice": 766.76, "Balance": 0.0},
        {"Accountid": "ACCT_NEW", "Comp_code": "WRA", "Invoice_Type": "AD",
         "Net_invoice": -766.76, "Balance": None},
        {"Accountid": "ACCT_NEW", "Comp_code": "WRA", "Invoice_Type": "IN",
         "Net_invoice": 766.76, "Balance": 0.0},
    ]
    amounts = _sum_new_member_dues(invoices, new_ids)
    assert amounts == {"ACCT_NEW": 766.76}


def test_wra_dues_still_counted():
    # No regression: standard WRA dues invoices are still summed.
    new_ids = {"ACCT_NEW"}
    invoices = [
        {"Accountid": "ACCT_NEW", "Comp_code": "WRA", "Invoice_Type": "IN",
         "Net_invoice": 1070.0},
    ]
    amounts = _sum_new_member_dues(invoices, new_ids)
    assert amounts == {"ACCT_NEW": 1070.0}


def test_non_dues_comp_codes_excluded():
    # PAC (political) and EDF (education foundation) are not membership dues —
    # they must not inflate new-sales revenue even for a new member.
    new_ids = {"ACCT_NEW"}
    invoices = [
        {"Accountid": "ACCT_NEW", "Comp_code": "PAC", "Invoice_Type": "IN",
         "Net_invoice": 250.0},
        {"Accountid": "ACCT_NEW", "Comp_code": "EDF", "Invoice_Type": "IN",
         "Net_invoice": 100.0},
    ]
    amounts = _sum_new_member_dues(invoices, new_ids)
    assert amounts == {}


def test_invoices_for_non_new_accounts_excluded():
    # An invoice for an account that did NOT enroll in the window is a renewal,
    # not a new sale — excluded.
    new_ids = {"ACCT_NEW"}
    invoices = [
        {"Accountid": "ACCT_OLD", "Comp_code": "WRA", "Invoice_Type": "IN",
         "Net_invoice": 2790.0},
        {"Accountid": "ACCT_NEW", "Comp_code": "WRA", "Invoice_Type": "IN",
         "Net_invoice": 510.0},
    ]
    amounts = _sum_new_member_dues(invoices, new_ids)
    assert amounts == {"ACCT_NEW": 510.0}


def test_non_numeric_amounts_ignored():
    new_ids = {"ACCT_NEW"}
    invoices = [
        {"Accountid": "ACCT_NEW", "Comp_code": "WRA", "Invoice_Type": "IN",
         "Net_invoice": None},
        {"Accountid": "ACCT_NEW", "Comp_code": "WRA", "Invoice_Type": "IN",
         "Net_invoice": 510.0},
    ]
    amounts = _sum_new_member_dues(invoices, new_ids)
    assert amounts == {"ACCT_NEW": 510.0}


# ---------------------------------------------------------------------------
# Paid-only member counts (Jiho ratified 2026-07-22 late): "do not count
# members as new unless they have paid." Counts derive from the SAME paid
# amounts as the dollars — misalignment (count>0, $0) becomes structurally
# impossible, except BOB (comped: counts, $0 by design, face in BOB row).
# ---------------------------------------------------------------------------

def test_countable_ids_paid_only():
    from reports.membership_performance_tracker.logic.revenue import _countable_ids
    account_amounts = {"PAID": 510.0, "REFUND_ONLY": -730.0}
    bob_amounts = {"BOBM": 510.0}
    # PAID counts; refund-only does NOT; BOB counts (comped = deemed fulfilled);
    # an enrollee with no paid dues (absent from account_amounts) does NOT.
    assert _countable_ids(account_amounts, bob_amounts) == {"PAID", "BOBM"}


def test_countable_ids_empty():
    from reports.membership_performance_tracker.logic.revenue import _countable_ids
    assert _countable_ids({}, {}) == set()


# ---------------------------------------------------------------------------
# Option 2 (Jiho 2026-07-22): first-payment-month anchoring.
# ---------------------------------------------------------------------------

def test_first_pay_anchor_resolution():
    from datetime import date
    from reports.membership_performance_tracker.logic.revenue import _resolve_anchor
    d2a = lambda d: {7: "Jul", 6: "Jun"}.get(d.month) if d and d.year == 2026 else None
    # ledger date wins: June enrollee, first payment July -> Jul
    assert _resolve_anchor(date(2026, 7, 8), date(2026, 6, 15), False, "Jun", d2a) == "Jul"
    # ledger blind -> paid-invoice date month
    assert _resolve_anchor(None, date(2026, 6, 15), False, "Jun", d2a) == "Jun"
    # BOB: no payment ever -> enrollment month
    assert _resolve_anchor(None, None, True, "Jun", d2a) == "Jun"
    # nothing at all -> outside (None)
    assert _resolve_anchor(None, None, False, "Jun", d2a) is None
    # payment beyond the edition span -> None (a later edition's member)
    assert _resolve_anchor(date(2027, 1, 5), None, False, "Jun", d2a) is None


def test_first_pay_bucketing_end_to_end(monkeypatch):
    """June enrollee whose first payment lands in July: the JULY cell gets the
    member AND the dollars; June gets nothing. (The exact case Jiho named.)"""
    from datetime import date
    import reports.membership_performance_tracker.logic.revenue as rev

    class FakeSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            if entity == "cMemberGens":
                # enrollee appears only in the June enrollment window
                return [{"Accountid": "A1"}] if "@2026-06-01@" in where else []
            if entity == "dlInvoiceHistoryHeader":
                inv = {"Accountid": "A1", "Invoice_number": "9", "Net_invoice": 510.0,
                       "Balance": 0.0, "Comp_code": "WRA", "Invoice_Type": "IN",
                       "Invoice_Date": date(2026, 6, 20), "Po_number": ""}
                return [inv]
            if entity == "payAllocationViews":
                return [{"Allocationamt": 510.0, "Item_Id": "/RD<1M",
                         "AllocationDate": date(2026, 7, 8)}]
            return []
    monkeypatch.setattr(rev, "build_target_map", lambda *a, **k: {})
    monkeypatch.setattr(rev, "classify", lambda tm, aid: rev.NON_TARGET)
    monkeypatch.setattr(rev, "originator_territory_map",
                        lambda *a, **k: {"A1": "Pierce"})
    windows = [("Jun", date(2026, 6, 1), date(2026, 6, 30)),
               ("Jul", date(2026, 7, 1), date(2026, 7, 31))]
    out = rev.revenue_and_counts_by_first_pay(FakeSLX(), {"U1": "Pierce"}, windows,
                                              request_delay=0.0)
    jun, jul = out["Pierce"]["Jun"], out["Pierce"]["Jul"]
    assert jul["count_total"] == 1 and jul["non_target"] == 510.0, jul
    assert jun["count_total"] == 0 and jun["total"] == 0.0, jun


def test_out_of_span_ledger_date_falls_back_to_invoice_date():
    """Springhill case (2026-07-23): mis-dated ledger row (a year early) must
    not silently drop a paying member — invoice date decides."""
    import warnings as w
    from datetime import date
    from reports.membership_performance_tracker.logic.revenue import _resolve_anchor
    d2a = lambda d: "Jan" if (d and d.year == 2026 and d.month == 1) else None
    with w.catch_warnings(record=True) as caught:
        w.simplefilter("always")
        assert _resolve_anchor(date(2025, 1, 5), date(2026, 1, 5), False, "Jan", d2a) == "Jan"
    assert any("outside the edition span" in str(x.message) for x in caught)


def test_checkbox_bob_credited_back_counts_at_face(monkeypatch):
    """Jiho ruling 8/10 (Simply Soulful): BOB identity = the diversity
    checkbox — the credit-back lags weeks and carries NO billing code
    (plain +730/-730 INs). A checkbox enrollee whose bill was credited
    back counts at FACE: in revenue (both sides, like every BOB), on the
    BOB line, in the member count — and never on the comps alarm."""
    from datetime import date
    import reports.membership_performance_tracker.logic.revenue as rev

    class FakeSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            if entity == "accounts" and "CDiverseOwnership eq true" in where:
                return [{"$key": "B1"}]
            if entity == "cMemberGens":
                return [{"Accountid": "B1"}] if "@2026-05-01@" in where else []
            if entity == "dlInvoiceHistoryHeader":
                return [
                    {"Accountid": "B1", "Invoice_number": "11", "Net_invoice": 730.0,
                     "Balance": 0.0, "Comp_code": "WRA", "Invoice_Type": "IN",
                     "Invoice_Date": date(2026, 5, 21), "Po_number": ""},
                    {"Accountid": "B1", "Invoice_number": "12", "Net_invoice": -730.0,
                     "Balance": 0.0, "Comp_code": "WRA", "Invoice_Type": "IN",
                     "Invoice_Date": date(2026, 5, 21), "Po_number": ""},
                ]
            if entity == "payAllocationViews":
                return [{"Allocationamt": 730.0, "Item_Id": "/RD<1M",
                         "AllocationDate": date(2026, 5, 21)}]
            return []
    monkeypatch.setattr(rev, "build_target_map", lambda *a, **k: {})
    monkeypatch.setattr(rev, "classify", lambda tm, aid: rev.NON_TARGET)
    monkeypatch.setattr(rev, "originator_territory_map",
                        lambda *a, **k: {"B1": "NorthKing"})
    from datetime import date as _d
    windows = [("May", _d(2026, 5, 1), _d(2026, 5, 31))]
    out = rev.revenue_and_counts_by_first_pay(FakeSLX(), {"U1": "NorthKing"},
                                              windows, request_delay=0.0)
    may = out["NorthKing"]["May"]
    assert may["bob"] == 730.0, may
    assert may["non_target"] == 730.0 and may["count_total"] == 1, may
    assert may["comped_new"] == 0.0, "checkbox BOBs never trip the comps alarm"


def test_duplicate_record_cleanup_never_reaches_the_comps_line(monkeypatch):
    """Jen 8/10 (Delfino's Pizzeria University): a fully-credited cycle on
    an account closed as 'Duplicate Record' is a payment transfer's residue
    — one real sale, counted once on the surviving twin. Not a comp:
    excluded from the comps line, disclosed via a cleanup flag."""
    from datetime import date
    import reports.membership_performance_tracker.logic.revenue as rev

    class FakeSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            if entity == "accounts" and "CDiverseOwnership eq true" in where:
                return []
            if entity == "AccountExtension":
                return [{"Statusreason": "Duplicate Record"}]
            if entity == "cMemberGens":
                return [{"Accountid": "D1"}] if "@2026-05-01@" in where else []
            if entity == "dlInvoiceHistoryHeader":
                mk = lambda no, net: {
                    "Accountid": "D1", "Invoice_number": no, "Net_invoice": net,
                    "Balance": 0.0, "Comp_code": "WRA", "Invoice_Type": "AD",
                    "Invoice_Date": date(2026, 5, 20), "Po_number": ""}
                return [mk("21", 1070.0), mk("22", 100.0),
                        mk("23", -1070.0), mk("24", -100.0)]
            if entity == "payAllocationViews":
                return []
            return []
    monkeypatch.setattr(rev, "build_target_map", lambda *a, **k: {})
    monkeypatch.setattr(rev, "classify", lambda tm, aid: rev.NON_TARGET)
    monkeypatch.setattr(rev, "originator_territory_map",
                        lambda *a, **k: {"D1": "NorthKing"})
    windows = [("May", date(2026, 5, 1), date(2026, 5, 31))]
    flags = {}
    out = rev.revenue_and_counts_by_first_pay(FakeSLX(), {"U1": "NorthKing"},
                                              windows, request_delay=0.0,
                                              flags_out=flags)
    may = out["NorthKing"]["May"]
    assert may["comped_new"] == 0.0, may
    assert may["total"] == 0.0, "cleanup residue never counts anywhere"
    rows = flags.get("record_cleanup") or []
    assert rows and rows[0]["face_dollars"] == 1170.0, flags
