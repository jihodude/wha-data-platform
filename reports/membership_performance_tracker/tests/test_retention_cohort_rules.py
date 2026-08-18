"""Cohort membership rules, re-grounded 2026-07-28 after the four named
residuals of the BM5 validation each exposed a wrong DEFINITION:

  · Deb Green Group  — the invoice Comment field is data entry, not structure
    (blank on their only bill). The member's own Duesbillmonth is the truth.
  · Dick's Restaurant Supply — allied is decided by the membership PRODUCT
    (ratified D2, 2026-07-16, billables) — not by Type, which reads Corporate.
  · Madeleine's / Cibrian — an ask fully rescinded and never reissued is not
    an ask. (The void-TIMING hypothesis was tested and FALSIFIED: both voids
    landed before close; Jennifer kept one and dropped the other. Arithmetic
    is the consistent rule; her Cibrian row is the inconsistency.)
"""
from datetime import date, datetime, timezone

from reports.membership_performance_tracker.logic import retention as R


def _ms(y, m, d):
    return f"/Date({int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)})/"


class _RosterSLX:
    """Territory fake: invoice rows + cMemberGens roster + products lookup."""
    def __init__(self, invoices, roster):
        self.invoices, self.roster = invoices, roster

    def _fetch_all(self, entity, where="", select=None, page_size=200):
        if entity == "dlInvoiceHistoryHeader":
            return self.invoices
        if entity == "cMemberGens":
            return [r for r in self.roster
                    if (r["Account"]["$key"] in where) or ("Account.Id" not in where)]
        if entity == "products":
            return [{"$key": "PALLD", "Name": "Allied Corporate"},
                    {"$key": "PHOSP", "Name": "Full Service Restaurant"}]
        return []


def _inv(acct, number, comment, net, bal, itype="IN"):
    return {"Accountid": acct, "Invoice_Type": itype, "Invoice_number": number,
            "Comment": comment, "Balance": bal, "Net_invoice": net,
            "Invoice_Date": _ms(2026, 4, 1)}


def _member(acct, bill_month=5, product=None, enrolled=(2020, 1, 1),
            product_id="Y-SOME-PRODUCT"):
    rec = {"Account": {"$key": acct}, "EnrolledDate": _ms(*enrolled),
           "Duesbillmonth": bill_month}
    if product_id:
        rec["MemrsProductID"] = product_id
    if product:
        rec["MembershipProduct"] = product
    return rec


def test_a_blank_comment_bill_joins_the_cycle_its_member_belongs_to():
    """Deb Green Group, live: their ONLY bill is #0148881, blank comment,
    billed June inside the BM5 window. Duesbillmonth=5 says whose cycle it is.
    Jennifer counts them billed AND paid; the comment anchor alone loses them."""
    slx = _RosterSLX(
        [_inv("DEB", "0148881", "", 795.0, 0.0),
         _inv("DEB", "0148881", "", -255.0, None, itype="AD")],
        [_member("DEB", bill_month=5)])

    paid, billed, *_ = R._retention_counts(slx, "U1", "5", "2026-02-01", "2026-07-31", 2025)

    assert (paid, billed) == (1, 1)


def test_a_blank_comment_bill_for_another_cycles_member_stays_out():
    """Same shape, but the member bills in cycle 8 — their stray in-window
    invoice is not a BM5 bill and must not inflate the BM5 cohort."""
    slx = _RosterSLX([_inv("OTHER", "X1", "", 500.0, 0.0)],
                     [_member("OTHER", bill_month=8)])

    paid, billed, *_ = R._retention_counts(slx, "U1", "5", "2026-02-01", "2026-07-31", 2025)

    assert billed == 0


def test_an_ask_fully_rescinded_and_never_reissued_is_not_an_ask():
    """Cibrian and Madeleine's, live: IN + AD net to zero, no replacement.
    Nothing was asked of the member by close, so there is nothing to retain
    or fail to retain. (Osteria differs: their ask nets to $100 — billed.)"""
    slx = _RosterSLX(
        [_inv("VOID", "0148212", "5", 575.0, 0.0),
         _inv("VOID", "0148212", "5", -575.0, None, itype="AD")],
        [_member("VOID")])

    paid, billed, *_ = R._retention_counts(slx, "U1", "5", "2026-02-01", "2026-07-31", 2025)

    assert billed == 0


def test_a_partial_write_off_still_leaves_a_real_ask():
    slx = _RosterSLX(
        [_inv("PART", "0148242", "5", 1170.0, 0.0),
         _inv("PART", "0148242", "5", -1070.0, None, itype="AD")],
        [_member("PART")])

    paid, billed, *_ = R._retention_counts(slx, "U1", "5", "2026-02-01", "2026-07-31", 2025)

    assert (paid, billed) == (1, 1)


def test_a_genuine_zero_dollar_bill_is_still_a_bill():
    """No adjustment anywhere — a comped $0 invoice with a zero balance is a
    billed-and-paid member (pre-existing edge, must survive the net-ask rule)."""
    slx = _RosterSLX([_inv("ZERO", "Z1", "5", 0.0, 0.0)], [_member("ZERO")])

    paid, billed, *_ = R._retention_counts(slx, "U1", "5", "2026-02-01", "2026-07-31", 2025)

    assert (paid, billed) == (1, 1)


def test_allied_members_are_OUT_of_hospitality_retention():
    """RULED 2026-08-14 by the owners of the number — Steven Sweeney, Marla
    Fruit, Jennifer Hurley: allied is OUT of retention, count and revenue.

    This supersedes the 2026-08-11 ruling that admitted them as Non-Target.
    Marla read Spokane at 93.2% against her own 95% (Jen: 24 of 27 paid, bill
    month 6); the four extra members were allied, sitting inside Non-Target and
    dragging a line that decides commission. No TM carries a goal on allied and
    they are not pursued — "if they leave, we leave."

    Allied is removed from the cohort, not flagged inside it. A flag only works
    if every consumer honours it, and the combined line did not.

    Product still decides what "allied" means (Dick's Restaurant Supply, live:
    Type='Corporate', product 'Allied Corporate').
    """
    slx = _RosterSLX(
        [_inv("DICKS", "0148181", "5", 1410.0, 0.0),
         _inv("HOSP", "H1", "5", 730.0, 0.0)],
        [_member("DICKS", product={"$key": "PALLD"}),
         _member("HOSP", product={"$key": "PHOSP"})])

    paid, billed, *_ = R._retention_counts(slx, "U1", "5", "2026-02-01", "2026-07-31", 2025)

    assert (paid, billed) == (1, 1), \
        "only the hospitality member is in the cohort (ruled 8/14)"


def test_allied_is_excluded_from_the_revenue_side_too():
    """The whole point of the 8/14 ruling: allied dollars must not move the
    revenue retention percentage, in either direction. Here the allied member
    would have paid in full and PUSHED THE NUMBER UP — it still must not count,
    because the line measures hospitality retention, not total cash."""
    slx = _RosterSLX(
        [_inv("DICKS", "0148181", "5", 1410.0, 0.0),      # allied, paid in full
         _inv("HOSP", "H1", "5", 1000.0, 1000.0)],        # hospitality, unpaid
        [_member("DICKS", product={"$key": "PALLD"}),
         _member("HOSP", product={"$key": "PHOSP"})])

    (paid, billed, _outstanding, _unknown,
     rev_retained, rev_up, _by_account) = R._retention_counts(
        slx, "U1", "5", "2026-02-01", "2026-07-31", 2025)

    assert (paid, billed) == (0, 1)
    assert rev_retained == 0.0, "the allied member's cash is not retained revenue"
    assert rev_up == 1000.0, "and their ask is not revenue up for renewal"


def test_allied_lands_in_NON_TARGET_whatever_its_size_says():
    """The backstop behind the 8/14 removal. Allied never reaches the split any
    more, but if some future path re-admits one it must not be able to land in
    Target and quietly change the number the team is paid on."""
    by_account = {
        "ALLD": [{"balance": 0.0, "invoice_total": 1410.0, "_allied": True}],
        "HOSP": [{"balance": 0.0, "invoice_total": 730.0}],
    }
    # target_map deliberately claims the allied account is TARGET
    split = R._retention_target_split(
        by_account, {"ALLD": R.TARGET, "HOSP": R.TARGET})

    assert split["billed_target"] == 1, "only the hospitality member is Target"
    assert split["billed_non_target"] == 1, "allied is forced Non-Target"
    assert split["revenue_up_non_target"] == 1410.0


def test_members_without_product_data_stay_in():
    """No product on file is not evidence of allied — never shrink the cohort
    on missing data."""
    slx = _RosterSLX([_inv("PLAIN", "P1", "5", 730.0, 0.0)], [_member("PLAIN")])

    paid, billed, *_ = R._retention_counts(slx, "U1", "5", "2026-02-01", "2026-07-31", 2025)

    assert (paid, billed) == (1, 1)


def test_roster_anchor_requires_a_membership_product():
    """Ada's Technical Books / Fuel Coffee, live: Duesbillmonth=5 and a small
    blank-comment WRA invoice — but NO membership product on the member record.
    Those invoices are retro-program fee pass-throughs (Ada's $63.27 equals its
    own 'Retro Fee Adj' line), not dues asks; both CRM surfaces exclude them.
    A member with no product has no dues relationship to renew. Deb Green
    carries MemrsProductID and stays in."""
    slx = _RosterSLX(
        [_inv("FEEONLY", "F1", "", 63.27, 0.0)],
        [_member("FEEONLY", bill_month=5, product_id=None)])   # no product at all

    paid, billed, *_ = R._retention_counts(slx, "U1", "5", "2026-02-01", "2026-07-31", 2025)

    assert billed == 0


def test_rro_leaves_the_cohort_from_its_FLIP_DATE_not_retroactively():
    """CORRECTED 2026-08-12 (Jen, recorded, reviewing Snohomish BM12).

    The 7/30 ruling stands for the cycle a member flips IN: "no longer
    considered a billable... completely removed out of June's retention".
    What was wrong was applying it BACKWARDS. RRO returned False above every
    date guard, so a flip erased cycles that had already closed — months in
    which the member was billed, paid, and was retained.

    Live case: Sparta's Pizza & Pasta House - Bothell (CustomerNo 0055412)
    billed $730 for bill month 12, paid in full, cycle closed 2026-01-31 —
    then flipped RRO on 2026-06-16 when the business was sold. Jen: "during
    when that month closed, that Member paid and they were retained."

    This is the SAME defect new sales carried until 2026-07-15 (target.py:79):
    a CURRENT status retroactively erasing a PAST event. There it cost 4
    members against the CRM's March figure; here 133 accounts flipped RRO
    during FY25-26.

    An exit has a date. RRO now uses the same date test as every other exit.
    """
    from datetime import date
    from reports.membership_performance_tracker.logic import retention as R
    in_cohort_as_of = R.in_cohort_as_of

    # THE SPARTA'S CASE — flip AFTER the close: they were a member then.
    assert in_cohort_as_of("RRO", date(2026, 6, 16), date(2026, 1, 31)) is True
    assert in_cohort_as_of("RRO LNI Active", date(2026, 9, 1), date(2026, 7, 31),
                           invoice_date=date(2026, 5, 1)) is True

    # The 7/30 ruling, unchanged, for the cycle they actually flipped in.
    assert in_cohort_as_of("RRO", date(2026, 6, 1), date(2026, 7, 31)) is False
    # Flip ON the closing day STAYS — RRO now inherits this function's own
    # convention for every exit: "a member inactivated ON the closing day
    # stays: they were a member through the close and did not pay, which is
    # exactly what a retention miss is."
    assert in_cohort_as_of("RRO", date(2026, 7, 31), date(2026, 7, 31)) is True
    # No date at all: we cannot place the flip, so Jen's 7/30 instruction wins.
    assert in_cohort_as_of("RRO", None, date(2026, 7, 31)) is False

    assert in_cohort_as_of("Active", None, date(2026, 7, 31)) is True


def test_retained_can_never_exceed_the_ask():
    """Found by Jiho's eyeball on the 2026-07-30 workbook: Snohomish Oct read
    Revenue Retention 100.9% — retained $30,521 against an ask of $30,241.

    Mechanism: `_netted_retained` computed the ask from the IN row ALONE while
    computing collected as IN + adjustments − outstanding, so an UPWARD
    adjustment inflated the numerator and never the denominator (live:
    `Anacortes Brewing` ask 1,040, AD +330, balance 0 → 1,370 collected =
    131.7%; the Target cell netted +330 −50 = the exact +$280 seen).

    Fixed for UPWARD adjustments only — those unambiguously raise what we asked
    for. Whether a WRITE-OFF should also shrink the ask is contested across our
    own records (net-ask rule vs the 7/28 tests vs the Dues-Level ruling) and is
    left open rather than silently resolved.
    """
    from reports.membership_performance_tracker.logic.retention import _netted_retained

    upward = [{"invoice_total": 1040.0, "balance": 0.0, "invoice_date": "2025-08-01",
               "adjustments": 330.0}]
    billed, retained = _netted_retained(upward)
    assert billed == 1370.0, "an upward adjustment raises the ask too"
    assert retained == 1370.0
    assert retained <= billed

    # Write-off: ask stays gross, collected drops — a retention LOSS, and the
    # ratio stays under 100 either way (the contested half, left as-is).
    writeoff = [{"invoice_total": 1170.0, "balance": 0.0, "invoice_date": "2026-04-01",
                 "adjustments": -1070.0}]
    billed, retained = _netted_retained(writeoff)
    assert (billed, retained) == (1170.0, 100.0)
    assert retained <= billed

    partial = [{"invoice_total": 730.0, "balance": 532.03, "invoice_date": "2026-04-01",
                "adjustments": 0.0}]
    billed, retained = _netted_retained(partial)
    assert billed == 730.0 and abs(retained - 197.97) < 0.01
