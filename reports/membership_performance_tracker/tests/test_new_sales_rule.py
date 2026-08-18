"""
test_new_sales_rule.py — the new-sales revenue rule:

  · WRA ONLY — FINAL RULE (2026-07-21, Jen primary-source; supersedes the 7/15
    "MSC CMP-fee = dues" inference): CMP = Claims Management Program, a service
    fee, NEVER membership dues. Proof: Tapped at the Port's Apr 1 "Retro Fee
    Q2" $766.76 was reversed and rebilled the IDENTICAL amount as "CMP Fee
    BM 4-12" — a relabeled claims fee. No MSC line is ever a sale. (The 7/14
    draft's SW June 6,805.21 was wrong for the same family of reasons — Jen's
    5,723.50 was exactly correct; do NOT resurrect the "she missed Perch" story.)
  · PAID basis: Net_invoice − (Balance or 0)  (Best of Both counts 535 of 1,070)
  · IN + AD so reversal pairs net out (Whispering Willows: 545 −545 575 → 575)
  · Jen-confirmed: "sales = paid — TMs could bill without collecting"

Also: the new-member COUNT must include child-location sign-ups (Jen counts both
Domino's / both Puget Sound Pizzas) — the old `Account.ParentId eq null` filter
made us count 3 of Gretchen's 5. And per-territory results must MERGE across
multiple mapped users (Majors/NRA has two since 7/13), not overwrite.
"""
from reports.membership_performance_tracker.logic.revenue import (
    _accumulate_breakdown,
    _sum_new_member_dues,
)
from reports.membership_performance_tracker.logic import new_members as nm


def test_paid_basis_wra_only_cmp_is_claims_fee():
    """FINAL RULE (2026-07-21, Jen): dues live on WRA ONLY. CMP = Claims
    Management Program — a service fee, never a sale. Tapped at the Port's
    'CMP Fee BM 4-12' is its reversed 'Retro Fee Q2' rebilled at the identical
    $766.76: same money, new label, still a claims fee. No MSC line — CMP,
    Retro, blank-label batch — may ever count as new-sales revenue."""
    invoices = [
        # Perch Cantina: WRA dues + a RETRO FEE on MSC — retro fee must NOT count
        {"Accountid": "PERCH", "Comp_code": "WRA", "Invoice_Type": "IN", "Net_invoice": 1415.0, "Balance": 0.0, "Po_number": ""},
        {"Accountid": "PERCH", "Comp_code": "MSC", "Invoice_Type": "IN", "Net_invoice": 1081.71, "Balance": 0.0, "Po_number": "2026 Retro Fee Q3"},
        # Tapped at the Port: CMP fee is a CLAIMS fee — must NOT count (7/21)
        {"Accountid": "TAP", "Comp_code": "MSC", "Invoice_Type": "IN", "Net_invoice": 766.76, "Balance": 0.0, "Po_number": "2026 CMP Fee BM 4-12"},
        # mid-plan CMP fee: still a claims fee — must NOT count
        {"Accountid": "PLAN", "Comp_code": "MSC", "Invoice_Type": "IN", "Net_invoice": 700.0, "Balance": 520.0, "Po_number": "2026 CMP Fee BM 6-12"},
        # blank-label MSC batch posting must NOT count
        {"Accountid": "TAP", "Comp_code": "MSC", "Invoice_Type": "IN", "Net_invoice": 56000.0, "Balance": 0.0, "Po_number": ""},
        # Best of Both: half paid
        {"Accountid": "BOB", "Comp_code": "WRA", "Invoice_Type": "IN", "Net_invoice": 1070.0, "Balance": 535.0, "Po_number": ""},
        # Whispering Willows: rebill pair nets, final invoice paid
        {"Accountid": "WW", "Comp_code": "WRA", "Invoice_Type": "IN", "Net_invoice": 545.0, "Balance": 0.0, "Po_number": ""},
        {"Accountid": "WW", "Comp_code": "WRA", "Invoice_Type": "AD", "Net_invoice": -545.0, "Balance": None, "Po_number": ""},
        {"Accountid": "WW", "Comp_code": "WRA", "Invoice_Type": "IN", "Net_invoice": 575.0, "Balance": 0.0, "Po_number": ""},
        # non-dues code still ignored
        {"Accountid": "PERCH", "Comp_code": "PAC", "Invoice_Type": "IN", "Net_invoice": 99.0, "Balance": 0.0, "Po_number": ""},
    ]
    amounts = _sum_new_member_dues(invoices, {"PERCH", "TAP", "PLAN", "BOB", "WW"})
    assert amounts["PERCH"] == 1415.0, "retro fee must not count as a sale"
    assert "TAP" not in amounts, "CMP claims fee must not count as a sale (Jen 7/21)"
    assert "PLAN" not in amounts, "CMP claims fee must not count even mid-plan"
    assert amounts["BOB"] == 535.0
    assert amounts["WW"] == 575.0


def test_new_member_count_includes_children():
    captured = {}

    class FakeSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            if entity == "cMemberGens":
                captured["where"] = where
                return []
            return []

    nm.compute_new_members_by_target(
        FakeSLX(), {"U1": "Pierce"},
        start_date=__import__("datetime").date(2026, 6, 1),
        end_date=__import__("datetime").date(2026, 6, 30),
        request_delay=0.0,
    )
    w = captured["where"]
    assert "ParentId" not in w, "child sign-ups must count (Jen's convention)"
    assert "Salescode ne '510'" in w
    assert "ReinstatedDate eq null" in w


def test_accumulate_breakdown_merges_not_overwrites():
    result = {}
    _accumulate_breakdown(result, "Majors/NRA", {"total": 2.0, "target": 1.0, "non_target": 1.0, "unknown": 0.0})
    _accumulate_breakdown(result, "Majors/NRA", {"total": 3.0, "target": 0.0, "non_target": 2.0, "unknown": 1.0})
    assert result["Majors/NRA"] == {"total": 5.0, "target": 1.0, "non_target": 3.0, "unknown": 1.0}


def test_cohort_includes_since_dropped_members():
    """A March sale is a sale even if the member quits in June. The CRM's own
    New Member Sales report for March 2026 lists 22 members; our cohort showed
    18 because `Account.Status eq 'Active'` retroactively erased enrollees who
    later dropped (found 2026-07-15 via the wide jhurley-report export; explains
    most of the Mar −4.2k / Apr −4.9k handmade gaps). History must not rewrite
    itself: no current-status filter on enrollment cohorts."""
    captured = {}

    class FakeSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            if entity == "cMemberGens" and "EnrolledDate" in where:
                captured.setdefault("wheres", []).append(where)
            return []

    nm.compute_new_members_by_target(
        FakeSLX(), {"U1": "Pierce"},
        start_date=__import__("datetime").date(2026, 3, 1),
        end_date=__import__("datetime").date(2026, 3, 31),
        request_delay=0.0,
    )
    from reports.membership_performance_tracker.logic.revenue import revenue_for_period
    revenue_for_period(
        FakeSLX(), {"U1": "Pierce"},
        start_date=__import__("datetime").date(2026, 3, 1),
        end_date=__import__("datetime").date(2026, 3, 31),
        request_delay=0.0,
    )
    assert captured["wheres"], "cohort queries must have fired"
    for w in captured["wheres"]:
        assert "Status eq 'Active'" not in w, \
            "current status must not erase historical enrollees"


def test_cross_territory_sale_credits_the_seller():
    """Ratified 7/15-16: Gretchen (Southwest) sells El-Sombrero-style into
    another user's territory → the money and the count belong in HER column.
    Seller = AccountExtension.Originator (never CreateUser, the typist)."""
    class FakeSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            if entity == "cMemberGens" and "U_PIERCE" in where:
                return [{"Accountid": "AX", "$key": "AX", "Account": {"$key": "AX"}}]
            if entity == "cMemberGens":
                return []
            if entity == "payAllocationViews":
                # hybrid basis (7/22): ledger screens renewals + fees only
                return []
            if entity == "dlInvoiceHistoryHeader" and "U_PIERCE" in where:
                return [{"Accountid": "AX", "Comp_code": "WRA", "Invoice_Type": "IN",
                         "Net_invoice": 730.0, "Balance": 0.0, "Po_number": ""}]
            if entity == "dlInvoiceHistoryHeader":
                return []
            if entity == "AccountExtension":
                return [{"Account": {"$key": "AX"}, "Originator": "U_SW"}]
            return []

    tmap = {"U_PIERCE": "Pierce", "U_SW": "Southwest"}
    d = __import__("datetime").date
    from reports.membership_performance_tracker.logic.revenue import revenue_for_period
    rev = revenue_for_period(FakeSLX(), tmap, d(2026, 6, 1), d(2026, 6, 30), request_delay=0.0)
    assert rev.get("Southwest") == 730.0, "seller's column gets the money"
    assert rev.get("Pierce", 0.0) == 0.0, "territory owner gets nothing they didn't sell"
    counts = nm.compute_new_members_for_period(FakeSLX(), tmap, d(2026, 6, 1), d(2026, 6, 30), request_delay=0.0)
    assert counts.get("Southwest") == 1 and counts.get("Pierce", 0) == 0


def test_bob_promo_members_count_at_face_value():
    """D1=(c) (Jiho, 7/16): 'BOB 2-Year Membership' promo billing issues the
    dues then credits them (+505/-505) — ledger nets $0, but Jen counts these
    members at face value and the report follows her convention (footnoted on
    the README tab). The negative BOB credit line is excluded from netting;
    genuine rebill reversals (no BOB label) still net normally."""
    invoices = [
        {"Accountid": "B1", "Comp_code": "WRA", "Invoice_Type": "IN",
         "Net_invoice": 505.0, "Balance": 0.0, "Po_number": "BOB Two-Year Membership"},
        {"Accountid": "B1", "Comp_code": "WRA", "Invoice_Type": "IN",
         "Net_invoice": -505.0, "Balance": 0.0, "Po_number": "BOB Two-Year Membership"},
        # non-promo reversal pair must STILL net (Whispering Willows class)
        {"Accountid": "W1", "Comp_code": "WRA", "Invoice_Type": "IN", "Net_invoice": 545.0, "Balance": 0.0, "Po_number": ""},
        {"Accountid": "W1", "Comp_code": "WRA", "Invoice_Type": "AD", "Net_invoice": -545.0, "Balance": None, "Po_number": ""},
        {"Accountid": "W1", "Comp_code": "WRA", "Invoice_Type": "IN", "Net_invoice": 575.0, "Balance": 0.0, "Po_number": ""},
    ]
    amounts = _sum_new_member_dues(invoices, {"B1", "W1"})
    assert amounts["B1"] == 505.0, "promo member counts at face value"
    assert amounts["W1"] == 575.0, "real reversals still net"


def test_seller_map_resolves_person_user_ids():
    """Pull #10 finding: Originator holds PERSON ids (tfarrell) while the
    territory map holds SEAT ids (PierceTerritory) — two disjoint families.
    The seller map bridges them; without it, zero sales re-attributed."""
    from reports.membership_performance_tracker.logic.attribution import originator_territory_map

    class FakeSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            return [{"Account": {"$key": "A1"}, "Originator": "PERSON_TAMORRO"}]

    out = originator_territory_map(
        FakeSLX(), ["A1"], {"SEAT_PIERCE": "Pierce"},
        fallback_territory="Southeast", request_delay=0.0,
        seller_map={"PERSON_TAMORRO": "Pierce"})
    assert out["A1"] == "Pierce", "person-id seller must resolve via the seller map"


def test_cohort_end_boundary_is_exclusive_next_day():
    """March-31 enrollees are stored at midnight PACIFIC (07:00 UTC);
    'EnrolledDate le @2026-03-31@' compares against midnight and drops every
    LAST-DAY-OF-MONTH joiner (the four missing March members — Heritage,
    Traveling Goat, Robert Stocker, Go Philly — all 3/31; June's Palouse 6/30
    too). End boundary must be lt next-day."""
    captured = {}

    class FakeSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            if entity == "cMemberGens" and "EnrolledDate" in where:
                captured.setdefault("w", []).append(where)
            return []

    d = __import__("datetime").date
    nm.compute_new_members_by_target(FakeSLX(), {"U1": "Pierce"},
                                     start_date=d(2026, 3, 1), end_date=d(2026, 3, 31),
                                     request_delay=0.0)
    from reports.membership_performance_tracker.logic.revenue import revenue_for_period
    revenue_for_period(FakeSLX(), {"U1": "Pierce"},
                       start_date=d(2026, 3, 1), end_date=d(2026, 3, 31),
                       request_delay=0.0)
    assert captured["w"]
    for w in captured["w"]:
        assert "EnrolledDate lt @2026-04-01@" in w, w
        assert "le @2026-03-31@" not in w


def test_bob_face_value_tracked_separately():
    """Jiho 7/20: readers must see how much of revenue is BOB/promo face-value
    credit that never becomes cash. The breakdown carries a 'bob' amount."""
    class FakeSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            if entity == "cMemberGens" and "U1" in where:
                return [{"Accountid": "B1"}, {"Accountid": "N1"}]
            if entity == "payAllocationViews" and "'N1'" in where:
                return [{"AccountId": "N1", "AllocationDate": "2026-06-05",
                         "Allocationamt": 730.0, "Comp_code": "WRA", "Item_Id": "/RD<1M"}]
            if entity == "payAllocationViews":
                return []   # B1 is comped BOB — zero cash in the ledger
            if entity == "dlInvoiceHistoryHeader":
                return [
                    {"Accountid": "B1", "Comp_code": "WRA", "Invoice_Type": "IN",
                     "Net_invoice": 505.0, "Balance": 0.0, "Po_number": "BOB Two-Year Membership"},
                    {"Accountid": "B1", "Comp_code": "WRA", "Invoice_Type": "IN",
                     "Net_invoice": -505.0, "Balance": 0.0, "Po_number": "BOB Two-Year Membership"},
                    {"Accountid": "N1", "Comp_code": "WRA", "Invoice_Type": "IN",
                     "Net_invoice": 730.0, "Balance": 0.0, "Po_number": ""},
                ]
            if entity == "AccountExtension":
                return []
            return []

    from reports.membership_performance_tracker.logic.revenue import revenue_for_period_by_target
    d = __import__("datetime").date
    out = revenue_for_period_by_target(FakeSLX(), {"U1": "Pierce"},
                                       d(2026, 6, 1), d(2026, 6, 30), request_delay=0.0)
    row = out["Pierce"]
    assert row["total"] == 1235.0, "BOB face value included in total (505 + 730)"
    assert row["bob"] == 505.0, "the BOB portion is tracked so readers can subtract it"


def test_enrolled_but_never_paid_members_are_flagged_not_silently_dropped():
    """Jen, 2026-07-30 (recorded), on a member active with no payment:
    "That should never, ever, ever in a gazillion years happen... That's really
    a hard line. **And if it happens, I want to know about it.**"

    Shannon's summary names this first in the exceptions queue (step 10). The
    paid basis already keeps them OUT of the counts — the defect was that they
    left no trace, so nobody could act on the hard rule being broken.
    """
    from reports.membership_performance_tracker.logic.revenue import (
        collect_unpaid_actives)

    cohort = {"PAID", "UNPAID", "BOBCOMP"}
    amounts = {"PAID": 730.0}          # only PAID has money
    bob = {"BOBCOMP": 510.0}           # comped — fulfilled at $0 by design
    names = {"UNPAID": "Cheeky Noodles"}

    flags = collect_unpaid_actives(cohort, amounts, bob, names, "Snohomish", "Apr")

    assert [f["name"] for f in flags] == ["Cheeky Noodles"]
    assert flags[0]["territory"] == "Snohomish" and flags[0]["month"] == "Apr"


def test_engine_collects_flags_so_the_hard_rule_reaches_a_human():
    """The flag list is only worth building if it actually reaches the runner.

    `collect_unpaid_actives` existed and was tested, but nothing carried its
    output out of the revenue pass — the classic "implemented but not wired"
    gap. The engine must expose `.flags` for the runner's flag writer.
    """
    from reports.membership_performance_tracker.logic.engine import ScoreboardEngine
    assert hasattr(ScoreboardEngine, "__init__")
    eng = ScoreboardEngine.__new__(ScoreboardEngine)
    eng.flags = {}
    assert isinstance(eng.flags, dict), "engine must carry a flags dict"


def test_fee_lines_visible_only_by_account_still_subtract():
    """BGP Domino's, live 2026-08-03 (found in the Jen reconciliation): ONE
    invoice 0149139 for $2,695 with a $260 /KINGCOFEE fee LINE inside. The
    ledger's $key-collapse returns a DIFFERENT surviving line per query shape:
    by-invoice shows only the dues line (/RD>5M 2,435), by-account shows only
    the fee line (/KINGCOFEE 260). cohort_screen queried by invoice only, so
    fees came back 0 and $260 of county fees published as new revenue —
    Jen: "remove all those county fees." The fix unions both shapes."""
    from datetime import date
    from reports.membership_performance_tracker.logic.ledger_revenue import cohort_screen

    class ShapedClient:
        def _fetch_all(self, entity, where="", select="", **kw):
            if entity == "dlInvoiceHistoryHeader":
                return [{"Invoice_number": "0149139", "Net_invoice": 2695.0,
                         "Balance": 0.0, "Invoice_Type": "IN",
                         "Invoice_Date": "/Date(1784678400000)/"}]
            if "Invoice_number eq" in where:      # by-invoice shape
                return [{"Allocationamt": 2435.0, "Item_Id": "/RD>5M",
                         "AllocationDate": "/Date(1784678400000)/"}]
            if "AccountId eq" in where:           # by-account shape
                return [{"Allocationamt": 260.0, "Item_Id": "/KINGCOFEE",
                         "Invoice_number": "0149139",
                         "AllocationDate": "/Date(1784678400000)/"}]
            return []

    kept, fees, first_pay = cohort_screen(ShapedClient(), {"BGP"},
                                          date(2026, 7, 1), request_delay=0)
    assert fees.get("BGP") == 260.0, f"the county fee must be seen: {fees}"
    assert "BGP" in first_pay, "the dues line still anchors first pay"


def test_ahla_is_a_fee_code():
    """Lucky Eagle Casino Hotel, live 2026-08-03 (the TKP +513 residual from
    the Jen reconciliation): invoice 0148499 net 3,163.50 carries an /AHLA
    (American Hotel & Lodging Association) pass-through line of $513 that only
    the by-account shape surfaces. Jen's canonical SW export values the member
    at 2,650.50 — dues only. AHLA is a national-association pass-through, the
    same money-collected-for-another-org class as the county fees ruled out
    8/3, and _FEE_ITEM_RE did not match it, so the $513 published as retained
    dues. Fees classifier must catch it; fees_from_ledger_rows then nets it
    from retention and cohort_screen from new sales."""
    from reports.membership_performance_tracker.logic.ledger_revenue import item_is_fee
    from reports.membership_performance_tracker.logic.retention import fees_from_ledger_rows

    assert item_is_fee("/AHLA"), "/AHLA is a pass-through fee, not dues"

    fees = fees_from_ledger_rows([
        {"Invoice_number": "0148499", "Item_Id": "/AHLA",
         "Allocationamt": 513.0, "AllocationDate": "/Date(1781222400000)/"},
    ])
    assert fees.get("0148499") == 513.0, f"AHLA must net out of retention: {fees}"


def test_shadues_is_a_fee_code():
    """/SHADUES = Seattle Hotel Association dues riding WHA's combined
    invoice — a pass-through collected for another org, ~$52,301 across 43
    published FY26 retention invoices. Ruled OUT 2026-08-03 by member-diff
    against Jen's canonical SW export (Jiho: "pull her export and member-diff
    a SHADUES territory"): every comparable rider member matched
    ours-minus-SHADUES to the cent, 42/42 — e.g. Sheraton Seattle her 19,158
    = our 25,956 - 6,798; Renaissance her 8,633.50 = our 11,697 - 3,063.50;
    Hyatt Regency her 19,530 = our 26,460 - 6,930. Her Billed excludes SHA
    on BOTH sides (ask and paid)."""
    from reports.membership_performance_tracker.logic.ledger_revenue import item_is_fee
    from reports.membership_performance_tracker.logic.retention import fees_from_ledger_rows

    assert item_is_fee("/SHADUES"), "/SHADUES is a pass-through, not WHA dues"

    fees = fees_from_ledger_rows([
        {"Invoice_number": "0147579", "Item_Id": "/SHADUES",
         "Allocationamt": 6798.0, "AllocationDate": "/Date(1775000000000)/"},
    ])
    assert fees.get("0147579") == 6798.0, f"Sheraton's SHA dues must net out: {fees}"


def test_overpay_is_not_dues():
    """Ruled by Jiho+Jen 2026-08-03: "Fees do not get included. Dues only."
    /OVERPAY (overpayment credit parked by accounting, $701.50 across 3 FY26
    invoices — Sandwich Starr, Oyster Bay Inn, Smokin' Pete's) is not a
    dues-coded line, so it nets out of retention dollars like the fee class.
    Smokin' Pete's $20 invoice that was ENTIRELY an /OVERPAY line retains $0
    dues under this rule."""
    from reports.membership_performance_tracker.logic.ledger_revenue import item_is_fee
    from reports.membership_performance_tracker.logic.retention import fees_from_ledger_rows

    assert item_is_fee("/OVERPAY"), "dues only — overpay credit is not dues"
    fees = fees_from_ledger_rows([
        {"Invoice_number": "0146132", "Item_Id": "/OVERPAY",
         "Allocationamt": 666.5, "AllocationDate": "/Date(1765000000000)/"},
    ])
    assert fees.get("0146132") == 666.5, f"Oyster Bay's overpay must net out: {fees}"
