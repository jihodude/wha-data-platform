"""
test_data.py — pure-transform tests for the retention drilldown data layer.

The data layer takes pre-fetched SLX payloads (invoices, history records) and
returns the per-territory member rows + subtotals the writer needs. By keeping
the transforms pure we can test them without a live SLX, the way revenue.py
already does.
"""

from reports.retention_detail.data import (
    build_member_rows,
    summarize_territory,
    pick_latest_note,
)


# ----- build_member_rows -----

def test_groups_invoices_by_account_and_computes_billed_paid_balance():
    invoices = [
        {"Accountid": "A1", "CustomerNo": "0001234", "Bill_to_name": "Cafe Alpha",
         "Net_invoice": 1070.0, "Balance": 0.0,
         "Comp_code": "WRA", "Invoice_Type": "IN"},
        {"Accountid": "A2", "CustomerNo": "0005678", "Bill_to_name": "Pub Beta",
         "Net_invoice": 510.0, "Balance": 510.0,
         "Comp_code": "WRA", "Invoice_Type": "IN"},
    ]
    rows = build_member_rows(invoices, notes_by_account={}, tm_name="Bailey")

    assert len(rows) == 2
    a = next(r for r in rows if r["mid"] == "0001234")
    b = next(r for r in rows if r["mid"] == "0005678")
    assert a == {
        "mid": "0001234", "name": "Cafe Alpha", "tm": "Bailey",
        "billed": 1070.0, "paid": 1070.0, "balance": 0.0,
        "retained": True, "last_note": "", "kind": "",
    }
    assert b == {
        "mid": "0005678", "name": "Pub Beta", "tm": "Bailey",
        "billed": 510.0, "paid": 0.0, "balance": 510.0,
        "retained": False, "last_note": "", "kind": "",
    }


def test_only_counts_wra_in_invoices():
    # PAC / MSC / AD / EDF should NOT be summed into billed dues here.
    invoices = [
        {"Accountid": "A1", "CustomerNo": "0001", "Bill_to_name": "X",
         "Net_invoice": 1070.0, "Balance": 0.0, "Comp_code": "WRA", "Invoice_Type": "IN"},
        {"Accountid": "A1", "CustomerNo": "0001", "Bill_to_name": "X",
         "Net_invoice": 250.0, "Balance": 250.0, "Comp_code": "PAC", "Invoice_Type": "IN"},
        {"Accountid": "A1", "CustomerNo": "0001", "Bill_to_name": "X",
         "Net_invoice": 100.0, "Balance": 0.0, "Comp_code": "EDF", "Invoice_Type": "IN"},
    ]
    rows = build_member_rows(invoices, notes_by_account={}, tm_name="Amy")
    assert rows[0]["billed"] == 1070.0
    assert rows[0]["paid"]   == 1070.0
    assert rows[0]["balance"] == 0.0


def test_attaches_latest_note_to_unpaid_member():
    invoices = [
        {"Accountid": "A1", "CustomerNo": "0001", "Bill_to_name": "Pub",
         "Net_invoice": 510.0, "Balance": 510.0, "Comp_code": "WRA", "Invoice_Type": "IN"},
    ]
    notes_by_account = {"A1": "Brad ghosted me to pay."}
    rows = build_member_rows(invoices, notes_by_account, tm_name="Amy")
    assert rows[0]["last_note"] == "Brad ghosted me to pay."


def test_paid_member_has_no_note_attached_even_if_one_exists():
    # We only attach a note when the member is unpaid — for the rest the
    # column would be noise (notes can be years old marketing emails, etc).
    invoices = [
        {"Accountid": "A1", "CustomerNo": "0001", "Bill_to_name": "Cafe",
         "Net_invoice": 1070.0, "Balance": 0.0, "Comp_code": "WRA", "Invoice_Type": "IN"},
    ]
    notes_by_account = {"A1": "Old note from 2019 about marketing."}
    rows = build_member_rows(invoices, notes_by_account, tm_name="Amy")
    assert rows[0]["last_note"] == ""


def test_multiple_invoices_collapse_to_one_member_row_single_chosen_bill():
    # SHARED RULE (re-aligned 2026-08-05): the MPR values a multi-invoice
    # cycle with the SINGLE-CHOSEN-BILL model (A1b, 2026-07-31 — county-fee
    # members carry fee + dues + combined same-day invoices for ONE
    # obligation; summing them published fake-100% territories). The old
    # drilldown summed every IN row and told a different story from the MPR
    # face for the same member. One definition, two surfaces.
    invoices = [
        {"Accountid": "A1", "CustomerNo": "0001", "Bill_to_name": "Pub",
         "Net_invoice": 510.0, "Balance": 0.0, "Comp_code": "WRA",
         "Invoice_Type": "IN", "Invoice_number": "I1",
         "Invoice_Date": "/Date(1767312000000)/"},
        {"Accountid": "A1", "CustomerNo": "0001", "Bill_to_name": "Pub",
         "Net_invoice": 560.0, "Balance": 560.0, "Comp_code": "WRA",
         "Invoice_Type": "IN", "Invoice_number": "I2",
         "Invoice_Date": "/Date(1771891200000)/"},
    ]
    rows = build_member_rows(invoices, notes_by_account={}, tm_name="Amy")
    assert len(rows) == 1
    # latest positive invoice is the bill (I2, 560); its balance is out
    assert rows[0]["billed"]  == 560.0
    assert rows[0]["paid"]    == 0.0
    assert rows[0]["balance"] == 560.0


# ----- summarize_territory -----

def test_summarize_territory_computes_totals_and_ratios():
    rows = [
        {"mid": "1", "name": "A", "tm": "X", "billed": 1000, "paid": 1000, "balance": 0,    "last_note": ""},
        {"mid": "2", "name": "B", "tm": "X", "billed": 500,  "paid": 0,    "balance": 500,  "last_note": "lvm"},
        {"mid": "3", "name": "C", "tm": "X", "billed": 800,  "paid": 800,  "balance": 0,    "last_note": ""},
    ]
    s = summarize_territory(rows)
    assert s["billed_total"] == 2300
    assert s["paid_total"]   == 1800
    assert s["count_billed"] == 3
    assert s["count_paid"]   == 2     # only members with balance == 0 count as paid
    assert abs(s["collection_rate"] - (1800 / 2300)) < 1e-9
    assert abs(s["retention_rate"] - (2 / 3))         < 1e-9


def test_summarize_territory_handles_empty():
    s = summarize_territory([])
    assert s["billed_total"] == 0
    assert s["paid_total"]   == 0
    assert s["count_billed"] == 0
    assert s["count_paid"]   == 0
    assert s["collection_rate"] is None
    assert s["retention_rate"] is None


# ----- pick_latest_note -----

def test_pick_latest_note_takes_most_recent_by_completed_date():
    notes = [
        {"CompletedDate": "/Date(1709251200000)/", "Notes": "older note"},
        {"CompletedDate": "/Date(1739251200000)/", "Notes": "newer note"},
        {"CompletedDate": "/Date(1719251200000)/", "Notes": "middle note"},
    ]
    assert pick_latest_note(notes) == "newer note"


def test_pick_latest_note_returns_empty_string_for_no_notes():
    assert pick_latest_note([]) == ""


def test_pick_latest_note_strips_whitespace_and_handles_none_field():
    notes = [
        {"CompletedDate": "/Date(1739251200000)/", "Notes": "   hi   "},
    ]
    assert pick_latest_note(notes) == "hi"
    assert pick_latest_note([{"CompletedDate": "/Date(1739251200000)/", "Notes": None}]) == ""


# ----- shared retention rule (2026-07-28) -------------------------------------
# The drilldown must agree with the MPR's retention family — one definition of
# "retained" in the codebase, not two. These pin the three defects the old
# balance==0 test carried.

def _row(acct, mid, name, net, bal, itype="IN", number="I1"):
    return {"Accountid": acct, "CustomerNo": mid, "Bill_to_name": name,
            "Net_invoice": net, "Balance": bal, "Comp_code": "WRA",
            "Invoice_Type": itype, "Invoice_number": number}


def test_a_write_off_is_not_a_payment_in_the_drilldown_either():
    """Cibrian shape: IN 510 + AD -510, balance zeroed by forgiveness. The old
    balance==0 test listed them PAID $510 — and their whole ask nets to zero,
    so they are not billed at all (rescinded-ask rule, same as the MPR)."""
    invoices = [_row("A1", "01", "Cibrian LLC", 510.0, 0.0),
                _row("A1", "01", "Cibrian LLC", -510.0, None, itype="AD")]

    rows = build_member_rows(invoices, notes_by_account={}, tm_name="Kris")

    assert rows == []


def test_a_partial_write_off_shows_the_real_ask_and_the_real_money():
    """Osteria shape: billed $1,170, $1,070 written off, $100 collected.

    Re-aligned 2026-08-05 to the MPR's ASYMMETRIC rule (_netted_retained):
    a downward AD reduces COLLECTED ONLY — we asked for 1,170 and chose not
    to collect part of it, a retention loss, not a smaller ask. (The old
    expectation here was the net-ask reading; that contest is documented in
    retention.py and docs/metrics — this surface follows the MPR face.)
    Balance stays $0: nothing is actually owed after a write-off, so the row
    must not glow red as collectable."""
    invoices = [_row("A1", "02", "Osteria", 1170.0, 0.0),
                _row("A1", "02", "Osteria", -1070.0, None, itype="AD")]

    rows = build_member_rows(invoices, notes_by_account={}, tm_name="Sam")

    assert rows[0]["billed"] == 1170.0
    assert rows[0]["paid"] == 100.0
    assert rows[0]["balance"] == 0.0
    assert rows[0]["retained"] is True


def test_money_after_the_close_is_not_retained_in_the_drilldown():
    """Duke Atlas shape: paid in full, but on 7/16 against a 6/30 close."""
    from datetime import date
    invoices = [_row("A1", "03", "Duke Atlas", 810.0, 0.0, number="INV9")]

    rows = build_member_rows(invoices, notes_by_account={}, tm_name="Pat",
                             as_of=date(2026, 6, 30),
                             payment_dates={"INV9": date(2026, 7, 16)})

    assert rows[0]["paid"] == 810.0          # the money is real
    assert rows[0]["retained"] is False      # it just is not a renewal


def test_summary_counts_retained_not_zero_balance():
    rows = [
        {"mid": "1", "name": "A", "tm": "X", "billed": 100, "paid": 100,
         "balance": 0, "retained": True, "last_note": ""},
        {"mid": "2", "name": "B", "tm": "X", "billed": 100, "paid": 100,
         "balance": 0, "retained": False, "last_note": ""},   # late payer
    ]

    assert summarize_territory(rows)["count_paid"] == 1


# ----- the 8/4 face rules (re-aligned 2026-08-05) -----------------------------
# Jiho's report, 8/5 morning: the drilldown still showed comped members as
# PAID AT FACE, contradicting the MPR it drills into. These pin the ratified
# comp/void/BOB/dues-level rules onto this surface — classification is done
# by the SAME retention.py machinery, never re-derived here.

_JAN2  = "/Date(1767312000000)/"    # 2026-01-02
_FEB24 = "/Date(1771891200000)/"    # 2026-02-24  (53-day gap → comp)
_OCT16 = "/Date(1760572800000)/"    # 2025-10-16  (same-day mirror → void)


def _cycle(acct, mid, name, net, bal, number, when, itype="IN"):
    r = _row(acct, mid, name, net, bal, itype=itype, number=number)
    r["Invoice_Date"] = when
    return r


def test_comped_member_is_retained_but_never_paid_at_face():
    """Governor Hotel shape: billed +1,891 Jan 2, credited −1,891 Feb 24,
    still Active. The MPR counts them retained at $0/$0 (A1 ruling); the old
    drilldown listed them PAID $1,891 — the contradiction Jiho caught."""
    invoices = [_cycle("A1", "01", "Governor Hotel", 1891.0, 0.0, "I1", _JAN2),
                _cycle("A1", "01", "Governor Hotel", -1891.0, 0.0, "I2", _FEB24)]

    rows = build_member_rows(invoices, notes_by_account={}, tm_name="Kris",
                             statuses={"A1": "Active"})

    assert len(rows) == 1
    r = rows[0]
    assert r["kind"] == "comp"
    assert r["retained"] is True          # count-in
    assert r["billed"] == 0.0             # dollars-out
    assert r["paid"] == 0.0
    assert r["balance"] == 0.0            # never red-flagged as owing
    assert "Comped" in r["last_note"]     # a human reading the row sees why
    assert "1,891" in r["last_note"]      # the face is named, not hidden


def test_same_day_credit_mirror_is_a_void_and_stays_off_the_report():
    """Southern Kitchen shape: bill and credit on the SAME day = data-entry
    void (8/4 ruling), not a comp. Out of both sides, same as the MPR."""
    invoices = [_cycle("A1", "02", "Voided Cafe", 510.0, 0.0, "I1", _OCT16),
                _cycle("A1", "02", "Voided Cafe", -510.0, 0.0, "I2", _OCT16)]

    rows = build_member_rows(invoices, notes_by_account={}, tm_name="Kris",
                             statuses={"A1": "Active"})

    assert rows == []


def test_bob_comped_renewal_counts_at_face_both_sides():
    """BOB ruling (8/4): a comped BOB renewal keeps FACE dollars on both
    sides — the rep gets revenue credit. Same-day credit is a BOB's normal
    issuance pattern, so BOBs are exempt from the void test."""
    invoices = [_cycle("B1", "03", "Serious Soul Cafe", 510.0, 0.0, "I1", _OCT16),
                _cycle("B1", "03", "Serious Soul Cafe", -510.0, 0.0, "I2", _OCT16)]

    rows = build_member_rows(invoices, notes_by_account={}, tm_name="Sheryl",
                             statuses={"B1": "Active"}, bob_ids={"B1"})

    assert len(rows) == 1
    r = rows[0]
    assert r["kind"] == "bob"
    assert r["retained"] is True
    assert r["billed"] == 510.0
    assert r["paid"] == 510.0
    assert r["balance"] == 0.0
    assert "BOB" in r["last_note"]


def test_dues_level_overrides_the_invoice_ask():
    """Dues-level ask (GO 8/4): when the membership product's price is known,
    the ASK is the level — invoices are deleted/recreated on adjustments and
    can embed fees, so they are not the stable record."""
    invoices = [_cycle("A1", "04", "Hometowne", 2111.5, 0.0, "I1", _JAN2)]

    rows = build_member_rows(invoices, notes_by_account={}, tm_name="Pat",
                             dues_levels={"A1": 2061.5})

    assert rows[0]["billed"] == 2061.5    # the level, not the invoice net
    assert rows[0]["paid"] == 2061.5      # collected capped at the level
    assert rows[0]["balance"] == 0.0


def test_comp_face_prefers_the_dues_level():
    invoices = [_cycle("A1", "05", "Falls Cafe", 1891.0, 0.0, "I1", _JAN2),
                _cycle("A1", "05", "Falls Cafe", -1891.0, 0.0, "I2", _FEB24)]

    rows = build_member_rows(invoices, notes_by_account={}, tm_name="Kris",
                             statuses={"A1": "Active"},
                             dues_levels={"A1": 2061.5})

    assert rows[0]["kind"] == "comp"
    assert "2,061.50" in rows[0]["last_note"] or "2,061" in rows[0]["last_note"]


def test_summary_excludes_comp_dollars_but_counts_the_member():
    """The territory card must tell the MPR's story: a comp is one retained
    MEMBER contributing zero DOLLARS to either side."""
    invoices = [_cycle("A1", "01", "Governor Hotel", 1891.0, 0.0, "I1", _JAN2),
                _cycle("A1", "01", "Governor Hotel", -1891.0, 0.0, "I2", _FEB24),
                _cycle("A2", "02", "Paid Pub", 510.0, 0.0, "I3", _JAN2)]

    rows = build_member_rows(invoices, notes_by_account={}, tm_name="Kris",
                             statuses={"A1": "Active", "A2": "Active"})
    s = summarize_territory(rows)

    assert s["count_billed"] == 2
    assert s["count_paid"] == 2
    assert s["billed_total"] == 510.0
    assert s["paid_total"] == 510.0
