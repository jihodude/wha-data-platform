"""C6+C11 — the lost-cohort supplemental fetch (fetch-axis defect, P3/Sparta's).

Historical cohorts are scoped by the CURRENT AccountManager, so when the CRM
flips a sold business to a retro/house user, every invoice on that record
retroactively vanishes from its territory's history. Measured 2026-08-12:
38 FY26 dues invoices / $45,882.50 on non-territory records.

The fix: ONE unscoped FY fetch finds invoices on non-seat accounts, a resolver
assigns each account a territory, and `_retention_counts` receives the rows as
a supplement — the ratified cohort rules (in_cohort_as_of, R1, A2) then decide
who counts, exactly as they do for everyone else. Jen's rule, from tape:
"during when that month closed, that Member paid and they were retained."

Resolution order (ruled by Jiho 2026-08-12, config-driven, never guessed):
  1. flip-link pointer walk: CRetroOldLINumber -> CLINum join, and
     CRetroNewWRAID reverse join from the lost record's own WRA number,
     landing on a predecessor whose manager is a live seat or one of the six
     name-unambiguous disabled open seats (open_territory_user_to_territory).
  2. AccountExtension.Originator -> seller_user_to_territory (yaml, editable).
  3. neither, or a conflict -> FLAGGED with name and dollars; no cell.
House users (AlliedRelationsManager) are flag-only by ruling: Jen's sheets
carry none of their members and the CRM holds no territory for them.
"""
import re
from datetime import date

import pytest

from reports.membership_performance_tracker.logic.lost_cohort import (
    collect_lost_cohort, load_resolver_maps)
from reports.membership_performance_tracker.logic.retention import (
    _retention_counts, compute_retention_all_months)


# ---------------------------------------------------------------------------
# FakeClient — routes _fetch_all by entity + where-clause content, in the
# exact RAW SData shapes production sees (fixture-shape mismatches burned
# this project twice on 8/12; every row here mirrors a live probe).
# ---------------------------------------------------------------------------

class FakeClient:
    def __init__(self, routes):
        # routes: list of (entity, where_regex, rows)
        self.routes = routes
        self.calls = []

    def _fetch_all(self, entity, where="", select=None, page_size=None,
                   **kwargs):
        self.calls.append((entity, where))
        for ent, pat, rows in self.routes:
            if ent == entity and re.search(pat, where or ""):
                return [dict(r) for r in rows]
        return []


SEATS = {"U-SNOHO": "Snohomish", "U-SPOKANE": "Spokane/NE",
         "U-PIERCE": "Pierce", "U-GENOPEN": None}
MAPS = {
    "open_seats": {"U-SNOHO-OPEN": "Snohomish"},
    "seller": {"U-MARLA": "Spokane/NE", "U-TAMORRO": "Pierce"},
    "house_flag_only": ["U-ALLIED-HOUSE"],
}

FY = 2025           # FY 2025-26: Oct 2025 .. Sep 2026


def _inv(aid, cust, comment, number, net, balance, day="2026-01-05",
         itype="IN"):
    return {"Accountid": aid, "CustomerNo": cust, "Comment": comment,
            "Invoice_number": number, "Net_invoice": net, "Balance": balance,
            "Invoice_Date": f"/Date({day})/", "Invoice_Type": itype}


def _acct(key, mgr, status="RRO", name="?", **cretro):
    row = {"$key": key, "AccountName": name, "Status": status,
           "AccountManager": {"$key": mgr}}
    row.update(cretro)
    return row


def _ext(originator=None, status_ms=None):
    row = {}
    if originator:
        row["Originator"] = originator
    if status_ms is not None:
        row["StatusDate"] = f"/Date({status_ms})/"
    return row


# epoch ms helpers for StatusDate fixtures
MS_2026_06_16 = 1781568000000     # after every FY26 close — member at close
MS_2025_12_30 = 1767052800000     # before the bm12 close (2026-01-31)

UNSCOPED = r"Comp_code eq 'WRA'(?!.*AccountManager)"


def _client_for_spartas():
    """The proven chain: lost RRO record with pointers -> Closed predecessor
    under the disabled SnohomishOpenTerritory user."""
    return FakeClient([
        ("dlInvoiceHistoryHeader", UNSCOPED, [
            _inv("A-LOST", "0055412", "12", "0146509", 795.0, 0.0),
        ]),
        ("accounts", r"Id eq 'A-LOST'", [
            _acct("A-LOST", "U-RETRO", name="Charles Goddes",
                  CRetroOldLINumber="563,066-01", CLINum="607,450-01")]),
        ("accounts", r"CLINum eq '563,066-01'", [
            _acct("A-OLD", "U-SNOHO-OPEN", status="Closed",
                  name="Sparta's Pizza", CRetroNewWRAID="0055412")]),
        ("accounts", r"CRetroNewWRAID eq '0055412'", [
            _acct("A-OLD", "U-SNOHO-OPEN", status="Closed",
                  name="Sparta's Pizza", CRetroNewWRAID="0055412")]),
        ("AccountExtension", r"Id eq 'A-LOST'",
         [_ext(status_ms=MS_2026_06_16)]),
    ])


# ---------------------------------------------------------------------------
# the resolver
# ---------------------------------------------------------------------------

def test_pointer_walk_resolves_spartas_to_snohomish():
    bundles = collect_lost_cohort(_client_for_spartas(), FY, SEATS,
                                  request_delay=0, maps=MAPS)
    assert "Snohomish" in bundles
    rows = bundles["Snohomish"]["records"]
    assert [r["Invoice_number"] for r in rows] == ["0146509"]
    # status + flip date travel with the bundle so the cohort test can rule
    assert bundles["Snohomish"]["statuses"]["A-LOST"] == "RRO"
    assert bundles["Snohomish"]["inactivations"]["A-LOST"] == date(2026, 6, 16)


def test_originator_fallback_resolves_houston_tx():
    """No pointers anywhere (in-place flip) — Originator via the yaml seller
    map. Live case: Houston TX Chicken, originator Marlaf, Jen files it under
    SpokaneNE on her BM12 tracker."""
    client = FakeClient([
        ("dlInvoiceHistoryHeader", UNSCOPED, [
            _inv("A-HOU", "0058137", "12", "0150001", 795.0, 0.0)]),
        ("accounts", r"Id eq 'A-HOU'", [
            _acct("A-HOU", "U-RETRO", name="Houston Tx Hot Chicken")]),
        ("AccountExtension", r"Id eq 'A-HOU'",
         [_ext(originator={"$key": "U-MARLA"}, status_ms=MS_2026_06_16)]),
    ])
    bundles = collect_lost_cohort(client, FY, SEATS, request_delay=0,
                                  maps=MAPS)
    assert [r["Invoice_number"] for r in bundles["Spokane/NE"]["records"]] \
        == ["0150001"]


def test_unresolvable_is_flagged_never_guessed():
    """Former-rep originator not in the seller map -> no cell, one flag."""
    client = FakeClient([
        ("dlInvoiceHistoryHeader", UNSCOPED, [
            _inv("A-UNK", "0031084", "5", "0150002", 830.0, 830.0)]),
        ("accounts", r"Id eq 'A-UNK'", [
            _acct("A-UNK", "U-RETRO", name="Cheveux de Chien LLC")]),
        ("AccountExtension", r"Id eq 'A-UNK'",
         [_ext(originator={"$key": "U-FORMER-REP"})]),
    ])
    flags = {}
    bundles = collect_lost_cohort(client, FY, SEATS, request_delay=0,
                                  maps=MAPS, flags_out=flags)
    assert bundles == {}
    (entry,) = flags["lost_cohort_unresolved"]
    assert entry["name"] == "Cheveux de Chien LLC"
    assert entry["dollars"] == 830.0


def test_conflicting_pointer_candidates_are_flagged():
    client = FakeClient([
        ("dlInvoiceHistoryHeader", UNSCOPED, [
            _inv("A-CONF", "0099999", "3", "0150003", 500.0, 0.0)]),
        ("accounts", r"Id eq 'A-CONF'", [
            _acct("A-CONF", "U-RETRO", CRetroOldLINumber="111,111-00")]),
        ("accounts", r"CLINum eq '111,111-00'", [
            _acct("A-P1", "U-SNOHO"), _acct("A-P2", "U-PIERCE")]),
        ("AccountExtension", r"Id eq 'A-CONF'", [_ext()]),
    ])
    flags = {}
    bundles = collect_lost_cohort(client, FY, SEATS, request_delay=0,
                                  maps=MAPS, flags_out=flags)
    assert bundles == {}
    assert "conflict" in flags["lost_cohort_unresolved"][0]["reason"]


def test_allied_house_user_is_flag_only_even_with_mappable_originator():
    """Ruled 2026-08-12: AlliedRelationsManager members have no territory in
    the CRM and Jen's sheets carry none of them — visible, never counted."""
    client = FakeClient([
        ("dlInvoiceHistoryHeader", UNSCOPED, [
            _inv("A-PAY", "0054568", "5", "0150004", 1140.0, 0.0)]),
        ("accounts", r"Id eq 'A-PAY'", [
            _acct("A-PAY", "U-ALLIED-HOUSE", status="Active",
                  name="Paylocity")]),
        ("AccountExtension", r"Id eq 'A-PAY'",
         [_ext(originator={"$key": "U-MARLA"})]),
    ])
    flags = {}
    bundles = collect_lost_cohort(client, FY, SEATS, request_delay=0,
                                  maps=MAPS, flags_out=flags)
    assert bundles == {}
    assert flags["lost_cohort_unresolved"][0]["reason"].startswith(
        "house user")


def test_seat_managed_accounts_are_never_lost():
    """An account under a mapped seat (even the deliberate null seat) is the
    territory fetch's business, not ours."""
    client = FakeClient([
        ("dlInvoiceHistoryHeader", UNSCOPED, [
            _inv("A-NORM", "0011111", "4", "0150005", 510.0, 0.0),
            _inv("A-OPEN", "0022222", "4", "0150006", 510.0, 0.0)]),
        ("accounts", r"Id eq 'A-NORM'", [
            _acct("A-NORM", "U-SNOHO", status="Active"),
            _acct("A-OPEN", "U-GENOPEN", status="Active")]),
    ])
    flags = {}
    bundles = collect_lost_cohort(client, FY, SEATS, request_delay=0,
                                  maps=MAPS, flags_out=flags)
    assert bundles == {} and flags == {}


def test_repo_yaml_carries_the_resolver_maps():
    maps = load_resolver_maps()
    assert maps["open_seats"].get("U6UJ9A000047") == "Snohomish"
    assert "U6UJ9A0000A4" in maps["house_flag_only"]
    assert maps["seller"], "seller_user_to_territory must be present"


# ---------------------------------------------------------------------------
# injection into _retention_counts
# ---------------------------------------------------------------------------

def _territory_client(records, cm_rows=()):
    """Serve the territory-scoped fetches _retention_counts makes."""
    return FakeClient([
        ("dlInvoiceHistoryHeader",
         r"AccountManager.*(Invoice_Type eq 'IN' or Invoice_Type eq 'AD')",
         list(records)),
        ("dlInvoiceHistoryHeader", r"AccountManager.*Invoice_Type eq 'CM'",
         list(cm_rows)),
    ])


def _counts(client, bundle, month="12", statuses=None, inactivations=None,
            payment_dates=None):
    return _retention_counts(
        client, "U-SNOHO", month, "2025-12-01", "2025-12-31", FY,
        as_of=date(2026, 1, 31), payment_dates=payment_dates or {},
        statuses=statuses or {}, inactivations=inactivations or {},
        lost_bundle=bundle)


def test_lost_member_lands_in_the_cell_and_counts_paid():
    terr = _territory_client([_inv("A-T1", "0000001", "12", "0140000",
                                   510.0, 0.0)])
    bundle = {"records": [_inv("A-LOST", "0055412", "12", "0146509",
                               795.0, 0.0)],
              "cm_rows": [],
              "statuses": {"A-LOST": "RRO"},
              "inactivations": {"A-LOST": date(2026, 6, 16)}}
    paid, billed, *_ , by_acct = _counts(
        terr, bundle, statuses={"A-T1": "Active"})
    assert billed == 2 and paid == 2
    assert "A-LOST" in by_acct


def test_pre_close_flip_is_filtered_by_the_ratified_cohort_rule():
    """Boundary Bay pattern: billed bm12, out of business 12/30, RRO. Jen does
    not track it; in_cohort_as_of removes it — both sides."""
    terr = _territory_client([_inv("A-T1", "0000001", "12", "0140000",
                                   510.0, 0.0)])
    bundle = {"records": [_inv("A-BB", "0019442", "12", "0146600",
                               1070.0, 1070.0)],
              "cm_rows": [],
              "statuses": {"A-BB": "RRO"},
              "inactivations": {"A-BB": date(2025, 12, 30)}}
    paid, billed, *_ , by_acct = _counts(
        terr, bundle, statuses={"A-T1": "Active"})
    assert billed == 1
    assert "A-BB" not in by_acct


def test_double_count_guard_by_invoice_number_and_wra_month():
    terr = _territory_client([
        _inv("A-T1", "0000001", "12", "0140000", 510.0, 0.0),
        _inv("A-T2", "0055412", "12", "0146777", 795.0, 0.0)])
    bundle = {"records": [
        # same invoice number as a territory row -> skipped
        _inv("A-DUP1", "0999999", "12", "0140000", 510.0, 0.0),
        # same (WRA#, bill month) as a territory row -> skipped
        _inv("A-DUP2", "0055412", "12", "0146888", 795.0, 0.0)],
        "cm_rows": [], "statuses": {}, "inactivations": {}}
    paid, billed, *_ , by_acct = _counts(
        terr, bundle, statuses={"A-T1": "Active", "A-T2": "Active"})
    assert billed == 2
    assert "A-DUP1" not in by_acct and "A-DUP2" not in by_acct


def test_lost_cm_rows_join_the_r1_rule():
    """A lost cycle fully voided by credit memo leaves BOTH sides (R1=A)."""
    terr = _territory_client([_inv("A-T1", "0000001", "12", "0140000",
                                   510.0, 0.0)])
    bundle = {"records": [_inv("A-CMX", "0033333", "12", "0146999",
                               730.0, 0.0)],
              "cm_rows": [{"Invoice_number": "0146999", "Invoice_Type": "CM",
                           "Net_invoice": -730.0, "Comment": "12",
                           "Accountid": "A-CMX", "CustomerNo": "0033333"}],
              "statuses": {"A-CMX": "RRO"},
              "inactivations": {"A-CMX": date(2026, 6, 16)}}
    paid, billed, *_ , by_acct = _counts(
        terr, bundle, statuses={"A-T1": "Active"})
    assert billed == 1
    assert "A-CMX" not in by_acct


# ---------------------------------------------------------------------------
# wiring: compute_retention_all_months
# ---------------------------------------------------------------------------

def test_all_months_carries_lost_members_into_their_cell(monkeypatch):
    from reports.membership_performance_tracker.logic import retention as rmod

    def fake_collect(client, fiscal_year_start, territory_user_map, **kw):
        return {"Snohomish": {
            "records": [_inv("A-LOST", "0055412", "12", "0146509",
                             795.0, 0.0)],
            "cm_rows": [],
            "statuses": {"A-LOST": "RRO"},
            "inactivations": {"A-LOST": date(2026, 6, 16)}}}
    monkeypatch.setattr(
        "reports.membership_performance_tracker.logic.lost_cohort."
        "collect_lost_cohort", fake_collect)

    client = FakeClient([
        ("dlInvoiceHistoryHeader",
         r"U-SNOHO.*(Invoice_Type eq 'IN' or Invoice_Type eq 'AD')",
         [_inv("A-T1", "0000001", "12", "0140000", 510.0, 0.0)]),
        ("accounts", r"AccountManager.Id eq 'U-SNOHO'",
         [{"$key": "A-T1", "Status": "Active"}]),
    ])
    res = compute_retention_all_months(
        client, {"U-SNOHO": "Snohomish"}, [12], FY, request_delay=0,
        today=date(2026, 8, 12))
    row = res[12]["Snohomish"]
    assert row["billed"] == 2 and row["paid"] == 2


def test_lost_fetch_failure_never_kills_the_nightly(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("SLX hiccup")
    monkeypatch.setattr(
        "reports.membership_performance_tracker.logic.lost_cohort."
        "collect_lost_cohort", boom)
    client = FakeClient([
        ("dlInvoiceHistoryHeader",
         r"U-SNOHO.*(Invoice_Type eq 'IN' or Invoice_Type eq 'AD')",
         [_inv("A-T1", "0000001", "12", "0140000", 510.0, 0.0)]),
        ("accounts", r"AccountManager.Id eq 'U-SNOHO'",
         [{"$key": "A-T1", "Status": "Active"}]),
    ])
    flags = {}
    res = compute_retention_all_months(
        client, {"U-SNOHO": "Snohomish"}, [12], FY, request_delay=0,
        today=date(2026, 8, 12), flags_out=flags)
    assert res[12]["Snohomish"]["billed"] == 1
    assert "lost_cohort_failed" in flags
