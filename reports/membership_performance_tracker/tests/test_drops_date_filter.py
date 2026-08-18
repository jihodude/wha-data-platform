"""
test_drops_date_filter.py — the drops fetch must bound AccountExtension by
StatusDate so it stops pulling every inactive account back to ~2001.

Root cause (pre-fix): fetch_drops_and_closed filtered by Statusreason only, no
date bound → ~1,500 accounts × ~5 sub-queries each = 30-40 min of the pull, and
the Data - Drops detail sheet dumped drops back to 2001. The aggregated counts
were already FY-windowed downstream (engine.aggregate_drops_buckets), so bounding
the fetch by a StatusDate floor loses nothing in the numbers — it only removes
ancient noise and slashes the pull. StatusDate generally lags the real drop date,
so a floor a few months before FY start can't exclude a genuine in-window drop.
"""
from datetime import date

from reports.membership_performance_tracker.logic.drops import fetch_drops_and_closed


class _RecordingClient:
    """Captures every _fetch_all where-clause; returns nothing so the per-account
    sub-query loop never runs (we only assert on the top-level AccountExtension query)."""

    def __init__(self):
        self.calls = []

    def _fetch_all(self, entity, where=None, select=None, page_size=None, **kwargs):
        self.calls.append({"entity": entity, "where": where})
        return []

    def _ae_where(self):
        return next(c["where"] for c in self.calls if c["entity"] == "AccountExtension")


def test_status_date_floor_added_when_cutoff_given():
    client = _RecordingClient()
    fetch_drops_and_closed(
        client,
        territory_user_map={"USER1": "Pierce"},
        rep_map={"Pierce": "Tamorro"},
        request_delay=0.0,
        min_status_date=date(2025, 7, 1),
    )
    where = client._ae_where()
    assert "StatusDate ge @2025-07-01@" in where


def test_no_status_date_floor_when_cutoff_omitted():
    client = _RecordingClient()
    fetch_drops_and_closed(
        client,
        territory_user_map={"USER1": "Pierce"},
        rep_map={"Pierce": "Tamorro"},
        request_delay=0.0,
    )
    where = client._ae_where()
    assert "StatusDate" not in where
    # all-reasons rule (2026-07-14): reason-null excluded, no whitelist
    assert "Statusreason ne null" in where


def test_status_scope_covers_closed_and_rro():
    """Dropped members are NOT all Status='Inactive': OOB accounts are 97%
    'Closed', Sold split Closed/RRO (SLX probe 2026-07-14, gate showed OOB
    1/167 matched). Scope = everything except still-Active."""
    client = _RecordingClient()
    fetch_drops_and_closed(
        client,
        territory_user_map={"USER1": "Pierce"},
        rep_map={"Pierce": "Tamorro"},
        request_delay=0.0,
    )
    where = client._ae_where()
    assert "Account.Status eq 'Inactive'" not in where
    assert "Account.Status ne 'Active'" in where


class _MemberFilterClient:
    """A1 has a cMemberGens row (real member), A2 does not (prospect noise).
    Both carry a drop reason on AccountExtension."""

    _many = False

    def _fetch_all(self, entity, where=None, select=None, page_size=None, **kw):
        if entity == "AccountExtension":
            base = [
                {"Account": {"$key": "A1"}, "Statusreason": "Out of Business",
                 "StatusDate": "/Date(1750000000000)/"},
                {"Account": {"$key": "A2"}, "Statusreason": "No Answer",
                 "StatusDate": "/Date(1750000000000)/"},
            ]
            if self._many:
                base += [{"Account": {"$key": f"M{i}"}, "Statusreason": "Sold",
                          "StatusDate": "/Date(1750000000000)/"} for i in range(119)]
            return base
        if entity == "cMemberGens" and "AccountManager" in (where or ""):
            rows = [{"Account": {"$key": "A1"}, "Membernum": "0012345"}]
            if self._many:
                rows += [{"Account": {"$key": f"M{i}"}} for i in range(119)]
            return rows
        if entity == "accounts":
            return [{"$key": "A1", "AccountName": "Real Member Cafe",
                     "Type": "Restaurant"}]
        return []


def test_only_membership_holders_count_as_drops():
    """Their 'dropped members' report has a member ID on every row — accounts
    without a membership record (prospects marked OOB/No Answer) are out.
    SLX holds 1,944 OOB accounts since 2025-07; their report shows 167."""
    drops, closed = fetch_drops_and_closed(
        _MemberFilterClient(),
        territory_user_map={"USER1": "Pierce"},
        rep_map={"Pierce": "Tamorro"},
        request_delay=0.0,
    )
    all_ids = {r["account_id"] for r in drops} | {r["account_id"] for r in closed}
    assert "A1" in all_ids, "member-backed drop must be kept"
    assert "A2" not in all_ids, "prospect without membership record must be excluded"


def test_enrichment_progress_prints_every_50(capsys):
    """The drops stage is a 60-90 min silent black box — it cost us pull #7
    (killed a healthy pull we couldn't see into). Print every 50 accounts."""
    client = _MemberFilterClient()
    # 120 member-backed candidates → expect prints at 50 and 100
    client._many = True
    fetch_drops_and_closed(
        client, territory_user_map={"USER1": "Pierce"},
        rep_map={"Pierce": "Tamorro"}, request_delay=0.0)
    out = capsys.readouterr().out
    assert "[drops] 50/" in out and "[drops] 100/" in out


def test_drop_amount_is_dues_level_from_product(capsys):
    """P1-4 (2026-07-16): dropped CHILD locations have no own invoices (Papa
    Murphy's #105 → $0; the franchisee parent holds the dues) — 473 zero-amount
    rows. Their convention (drops export `dues` col = AccountProfile "Dues
    Level") = the membership product's Price. amount_billed := product price;
    invoice archaeology only as fallback."""
    class _Client(_MemberFilterClient):
        def _fetch_all(self, entity, where=None, select=None, page_size=None, **kw):
            if entity == "AccountExtension":
                # Non-Payment → the DROPS branch (closed rows carry no amount col)
                return [{"Account": {"$key": "A1"}, "Statusreason": "Non-Payment",
                         "StatusDate": "/Date(1750000000000)/"}]
            if entity == "cMemberGens" and "Account.Id" in (where or ""):
                return [{"Account": {"$key": "A1"}, "Duesbillmonth": 5,
                         "Membernum": "0012345",
                         "MembershipProduct": {"$key": "PROD7"}}]
            if entity == "products":
                return [{"$key": "PROD7", "Name": "1 million to 2 million Dues",
                         "Price": 730.0, "Family": "Dues"}]
            return super()._fetch_all(entity, where, select, page_size, **kw)

    drops, closed = fetch_drops_and_closed(
        _Client(), territory_user_map={"USER1": "Pierce"},
        rep_map={"Pierce": "Tamorro"}, request_delay=0.0)
    rows = drops + closed
    a1 = next(r for r in rows if r["account_id"] == "A1")
    assert a1["amount_billed"] == 730.0, "dues level (product price), not invoice archaeology"
