"""
data.py — Retention drilldown data layer.

Pure transforms over pre-fetched SLX payloads + a thin live-SLX collector on
top. The transforms (`build_member_rows`, `summarize_territory`,
`pick_latest_note`) are testable without a live SLX, the way revenue.py is.
The collector (`collect_drilldown`) wires them to the SLX client.

What this report shows — per territory, for members in a given bill month:
    MID, Member Name, TM (rep), Billed, Paid, Balance, Last Note

"Last Note" is the most recent rep collection-cycle note from SLX History,
verbatim — no hand-summarization. Only attached to UNPAID members (members
with Balance > 0); paid members' note column stays blank because old notes
(marketing emails from 2019, etc.) are noise on a paid row.

Bill month = `cMemberGens.Duesbillmonth` (the member's annual renewal cycle
month). NOT the invoice date.

Balance is current-as-of-probe-time, NOT point-in-time historical. If a
member paid after the original bill, the new run will show them paid.
"""

import time
from typing import Dict, Iterable, List, Optional

from src.slx.client import SLXClient


# Dues-bearing comp codes. WRA-only here, NOT MSC, because retention/collection
# is about the standard WRA dues cycle. New-member payment-plan MSC dues are a
# different metric (handled in revenue.py).
DUES_COMP_CODES = frozenset({"WRA"})


# ---------------------------------------------------------------------------
# Pure transforms — testable without live SLX
# ---------------------------------------------------------------------------

def build_member_rows(
    invoices: Iterable[dict],
    notes_by_account: Dict[str, str],
    tm_name: str,
    as_of=None,
    payment_dates: Dict[str, object] = None,
    statuses: Dict[str, str] = None,
    bob_ids=None,
    dues_levels: Dict[str, float] = None,
) -> List[dict]:
    """
    Group WRA invoices by account → {mid, name, tm, billed, paid, balance,
    retained, kind, last_note}.

    Args:
        invoices:         dlInvoiceHistoryHeader records for this territory.
                          Non-WRA rows are ignored.
        notes_by_account: {Accountid: latest_note_text}. Only consulted for
                          accounts with a positive balance (i.e. unpaid).
        tm_name:          The rep's name for this territory (NOT the territory
                          name — that's what Jennifer's reference file had wrong).
        statuses:         {Accountid: Account.Status} — needed to tell a comp
                          (member still Active) from a rescinded bill.
        bob_ids:          Accountids with CDiverseOwnership true (BOB roster).
        dues_levels:      {Accountid: membership product price} — the ask.

    Returns:
        One row per account, sorted by MID for stable output.
    """
    # SHARED RULES — the drilldown and the MPR retention family use ONE
    # definition of everything, imported from retention.py, never re-derived:
    #   · 2026-07-28  retained/rescinded/close-date semantics
    #   · 2026-07-31  single-chosen-bill valuation (A1b), comp-at-$0 (A1)
    #   · 2026-08-04  comp-vs-void day gap, BOB face-both-sides, dues-level ask
    # Re-aligned 2026-08-05 after Jiho caught comps listed as PAID AT FACE here.
    from reports.membership_performance_tracker.logic.retention import (
        _group_invoice_rows, _netted_retained, comp_or_rescinded, retained_as_of)

    wra = [inv for inv in invoices
           if inv.get("Comp_code") in DUES_COMP_CODES
           and inv.get("Invoice_Type") in ("IN", "AD")]

    ident: Dict[str, tuple] = {}
    for inv in wra:
        aid = inv.get("Accountid")
        if aid and inv.get("Invoice_Type") == "IN" and aid not in ident:
            ident[aid] = (inv.get("CustomerNo") or "", inv.get("Bill_to_name") or "")

    by_account = _group_invoice_rows(wra)
    bob_ids = bob_ids or set()

    by_aid: Dict[str, dict] = {}
    for aid, rows in by_account.items():
        level = (dues_levels or {}).get(aid)
        if isinstance(level, (int, float)) and level > 0:
            for r in rows:
                r["dues_level"] = float(level)

        first_pay = None
        if payment_dates:
            dates = [payment_dates[r["invoice_number"]] for r in rows
                     if r.get("invoice_number") in payment_dates]
            first_pay = min(dates) if dates else None

        mid, name = ident.get(aid, ("", ""))
        row = {"mid": mid, "name": name, "tm": tm_name,
               "billed": 0.0, "paid": 0.0, "balance": 0.0,
               "retained": False, "kind": "", "last_note": ""}

        # face = what the membership is worth: the dues level when known,
        # else the cycle's positive bills (one value per invoice number)
        per_inv: Dict[str, float] = {}
        for r in rows:
            n = r.get("invoice_number")
            if n not in per_inv and isinstance(r.get("invoice_total"), (int, float)):
                per_inv[n] = r["invoice_total"]
        face = float(level) if isinstance(level, (int, float)) and level > 0 \
            else sum(v for v in per_inv.values() if v > 0)

        verdict = None if aid in bob_ids else \
            comp_or_rescinded(rows, (statuses or {}).get(aid))
        if verdict in ("rescinded", "void"):
            continue        # out of both sides, same as the MPR face
        if verdict == "comp":
            # A1: counted retained, $0/$0 dollars; the face is NAMED on the
            # row so a human sees why Paid is blank-of-dollars, not missing.
            row.update(retained=True, kind="comp",
                       last_note=f"Comped membership — dues level ${face:,.2f}"
                       + (" (credit within a week — review)"
                          if any(r.get("_comp_review") for r in rows) else ""))
            by_aid[aid] = row
            continue
        if aid in bob_ids and _cycle_comped_off(rows):
            # BOB ruling (8/4): comped renewal counts FACE on both sides;
            # same-day credit is a BOB's normal issuance, never a void.
            row.update(billed=face, paid=face, retained=True, kind="bob",
                       last_note="BOB — comped membership, counted at face")
            by_aid[aid] = row
            continue

        amount, collected = _netted_retained(rows)
        if isinstance(level, (int, float)) and level > 0:
            amount = float(level)
            collected = min(collected, amount)
        # balance = what is actually still OWED (the ledger's outstanding),
        # not billed − paid: a write-off leaves a gap between those two, and
        # a written-off member must not glow red as if collectable.
        outstanding = sum(b for b in (r.get("balance") for r in rows)
                          if isinstance(b, (int, float)) and b > 0)
        row.update(billed=amount, paid=collected, balance=outstanding,
                   retained=retained_as_of(rows, first_pay, as_of))
        by_aid[aid] = row

    # Attach notes only to unpaid members
    for aid, row in by_aid.items():
        if row["balance"] > 0:
            row["last_note"] = notes_by_account.get(aid, "") or ""

    return sorted(by_aid.values(), key=lambda r: r["mid"])


def _cycle_comped_off(rows: list) -> bool:
    """Was this BOB's cycle credited to $0? (The void/comp day-gap test never
    applies to BOBs, so only the fully-credited shape matters here.)"""
    from reports.membership_performance_tracker.logic.retention import _cycle_rescinded
    return _cycle_rescinded(rows)


def summarize_territory(rows: List[dict]) -> dict:
    """
    Per-territory totals + ratios. Returns labeled fields so the writer can
    drop them into a header card without computing anything itself.

    collection_rate = Σ Paid / Σ Billed     (dollar collection)
    retention_rate  = count_paid / count_billed  (member retention)

    Both None when there's no data — writer renders as "—".
    """
    billed_total = sum(r["billed"] for r in rows)
    paid_total   = sum(r["paid"]   for r in rows)
    count_billed = len(rows)
    # retained flag when present (shared rule, 2026-07-28); balance==0 kept as
    # the fallback so hand-built rows in older callers still summarize.
    count_paid   = sum(1 for r in rows if r.get("retained", r["balance"] == 0))
    return {
        "billed_total":   billed_total,
        "paid_total":     paid_total,
        "count_billed":   count_billed,
        "count_paid":     count_paid,
        "collection_rate": (paid_total / billed_total) if billed_total else None,
        "retention_rate":  (count_paid / count_billed) if count_billed else None,
    }


def pick_latest_note(notes: Iterable[dict]) -> str:
    """
    Pick the most-recent History.Notes text, by CompletedDate descending.
    Strips whitespace; returns "" if the field is None or list is empty.
    """
    notes = list(notes)
    if not notes:
        return ""
    # SLX dates are sortable as ISO-like strings; the "/Date(<ms>)/" format
    # sorts correctly by string compare for same-format dates.
    latest = max(notes, key=lambda n: n.get("CompletedDate") or "")
    text = latest.get("Notes")
    if text is None:
        return ""
    return text.strip()


def _to_float(v) -> float:
    """Coerce SLX numeric strings/None to float, defaulting to 0.0."""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Live SLX collector — wires the transforms together
# ---------------------------------------------------------------------------

def collect_drilldown(
    client: SLXClient,
    territory_user_map: Dict[str, str],
    rep_name_map: Dict[str, str],
    bill_month: int,
    fiscal_year_start: int,
    request_delay: float = 0.15,
) -> Dict[str, dict]:
    """
    For each territory: pull the BM-N member cohort + their dues invoices +
    recent collection notes for unpaid members. Returns one entry per
    territory containing rows + summary.

    Args:
        client:               Authenticated SLXClient.
        territory_user_map:   {slx_user_id: canonical_territory_name}
        rep_name_map:         {canonical_territory_name: rep_first_name}
        bill_month:           Duesbillmonth integer (1=Jan ... 12=Dec).
        fiscal_year_start:    Calendar year the FY begins (e.g. 2025 for FY 2025-26).
        request_delay:        Pause between SLX calls.

    Returns:
        {territory: {"rows": [...], "summary": {...}}}
    """
    result: Dict[str, dict] = {}

    # SHARED RULE (2026-07-28): same close, same payment ledger, same allied
    # classifier as the MPR retention family — one definition, two surfaces.
    from reports.membership_performance_tracker.logic.retention import (
        as_of_date, _first_payment_dates, _bill_month_date_window,
        _account_statuses, attach_dues_levels)
    as_of = as_of_date(bill_month, fiscal_year_start)
    win_start, win_end = _bill_month_date_window(bill_month, fiscal_year_start)
    payment_dates = _first_payment_dates(client, win_start, win_end)

    # BOB roster (8/4 ruling): CDiverseOwnership true — comped renewals count
    # at face and are exempt from the same-day void test. One fetch, all
    # territories (same query revenue.py uses).
    try:
        bob_ids = {r.get("$key") for r in client._fetch_all(
            "accounts", where="CDiverseOwnership eq true", select="Id")} - {None}
    except Exception:
        bob_ids = set()

    # WHA FY runs Oct (fiscal_year_start) → Sep (fiscal_year_start+1).
    fy_start = f"{fiscal_year_start}-10-01"
    fy_end   = f"{fiscal_year_start + 1}-09-30"

    for user_id, territory in territory_user_map.items():
        if territory is None:
            continue
        tm_name = rep_name_map.get(territory, territory)

        # 1) Members in this bill month for this territory
        member_where = (
            f"Account.AccountManager.Id eq '{user_id}' "
            f"and Duesbillmonth eq {bill_month} "
            f"and Account.Status ne 'Closed'"
        )
        # Full records (no select): MembershipProduct feeds the D2 allied
        # exclusion — Dick's Restaurant Supply is Type 'Corporate' with product
        # 'Allied Corporate' and belongs to billables, not hospitality retention.
        members = client._fetch_all("cMemberGens", where=member_where)
        time.sleep(request_delay)
        product_names = getattr(client, "_product_name_cache", None)
        def _prod_name(prod):
            nonlocal product_names
            if isinstance(prod, dict):
                if product_names is None:
                    product_names = {pr.get("$key"): (pr.get("Name") or "")
                                     for pr in client._fetch_all(
                                         "products", select="Name", page_size=200)}
                    client._product_name_cache = product_names
                return product_names.get(prod.get("$key"), "")
            return str(prod or "")
        account_ids = set()
        member_recs = {}
        for m in members:
            acct_nav = m.get("Account")
            aid = (m.get("Accountid")
                   or (acct_nav.get("$key") if isinstance(acct_nav, dict) else None)
                   or m.get("$key"))
            prod = m.get("MembershipProduct")
            if prod is not None and "allied" in _prod_name(prod).lower():
                continue
            if aid:
                account_ids.add(aid)
                member_recs[aid] = m

        if not account_ids:
            result[territory] = {"rows": [], "summary": summarize_territory([])}
            continue

        # Dues levels (GO 8/4): the membership product's price is the ask.
        # attach_dues_levels stamps grouped rows, so run it on stub rows and
        # collect the stamps — the pricing/per-room logic stays in ONE place.
        stub = {aid: [{}] for aid in account_ids}
        attach_dues_levels(client, stub, member_recs)
        dues_levels = {aid: rows[0]["dues_level"]
                       for aid, rows in stub.items() if rows[0].get("dues_level")}

        # Account statuses — comp (still Active) vs rescinded needs them.
        try:
            statuses = _account_statuses(client, user_id)
        except Exception:
            statuses = {}
        time.sleep(request_delay)

        # 2) WRA dues invoices for the territory in the current FY
        # AD rows ride along since 2026-07-28: a write-off zeroes a balance
        # without money arriving, and the drilldown must not list it as paid.
        inv_where = (
            f"Account.AccountManager.Id eq '{user_id}' "
            f"and Comp_code eq 'WRA' "
            f"and (Invoice_Type eq 'IN' or Invoice_Type eq 'AD') "
            f"and Invoice_Date ge @{fy_start}@ "
            f"and Invoice_Date le @{fy_end}@"
        )
        invoices = client._fetch_all(
            "dlInvoiceHistoryHeader",
            where=inv_where,
            select="Accountid,CustomerNo,Bill_to_name,Net_invoice,Balance,"
                   "Comp_code,Invoice_Type,Invoice_Date,Invoice_number",
        )
        time.sleep(request_delay)
        # Restrict to this territory's BM-N cohort
        invoices = [i for i in invoices if i.get("Accountid") in account_ids]

        # 3) Build rows (sans notes), figure out who's unpaid
        rows_no_notes = build_member_rows(invoices, notes_by_account={}, tm_name=tm_name,
                                          as_of=as_of, payment_dates=payment_dates,
                                          statuses=statuses, bob_ids=bob_ids,
                                          dues_levels=dues_levels)
        unpaid_account_ids = set()
        aid_by_mid = {(inv.get("CustomerNo") or ""): inv.get("Accountid")
                      for inv in invoices}
        for row in rows_no_notes:
            if row["balance"] > 0:
                aid = aid_by_mid.get(row["mid"])
                if aid:
                    unpaid_account_ids.add(aid)

        # 4) Pull latest collection note per unpaid member
        notes_by_account: Dict[str, str] = {}
        for aid in unpaid_account_ids:
            note_where = (
                f"Account.Id eq '{aid}' and Type eq 'atNote' "
                f"and Description like 'AC%Notice'"
            )
            try:
                hist = client._fetch_all(
                    "History",
                    where=note_where,
                    select="CompletedDate,Notes",
                    page_size=50,
                )
            except Exception:
                hist = []
            notes_by_account[aid] = pick_latest_note(hist)
            time.sleep(request_delay)

        # 5) Build final rows (with notes) + summary
        rows = build_member_rows(invoices, notes_by_account, tm_name=tm_name,
                                 as_of=as_of, payment_dates=payment_dates,
                                 statuses=statuses, bob_ids=bob_ids,
                                 dues_levels=dues_levels)
        result[territory] = {
            "rows":    rows,
            "summary": summarize_territory(rows),
        }

    return result
