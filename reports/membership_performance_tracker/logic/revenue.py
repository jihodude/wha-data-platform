"""
revenue.py — Compute new-sales revenue per territory from SLX dues invoices.

Dollar amounts live on dlInvoiceHistoryHeader.Net_invoice. We want only invoices
sent to NEW members (their first-year dues), not renewals.

Approach (per territory, per date window):
  1. Find new members enrolled in the window via cMemberGens
       — exclude reinstatements (Salescode = '510' OR ReinstatedDate set).
  2. Pull dues invoices for that territory across a window that runs from just
     before enrollment through the member's first ~10 billing months (payment-
     plan installments lag enrollment by months — see below).
  3. Sum signed Net_invoice for invoices whose Accountid is in the new-member set,
     restricted to dues comp codes (`_sum_new_member_dues`), and attribute the
     total to the member's enrollment month.

Comp codes — FINAL RULE (2026-07-21, Jen primary-source):
  - Dues = WRA ONLY. No MSC line is ever a sale.
  - CMP = Claims Management Program — a service fee, NOT dues and NOT payment
    plans. The 7/15 "CMP Fee = pro-rated dues" belief was a mis-inference from
    Tapped at the Port, whose "CMP Fee BM 4-12" is its reversed "Retro Fee Q2"
    rebilled at the identical $766.76 (their dues level is $0.00 — dues bill
    at the parent group, if at all). See DECISIONS.md 2026-07-21.
  - Non-dues codes (PAC, EDF...) stay excluded. We sum BOTH IN and AD and rely
    on the sign of Net_invoice, so a reversed + rebilled installment nets.

Recognition basis (UNDER REBUILD — DECISIONS.md 2026-07-21):
  - This module attributes by ENROLLMENT month (the member's first-year dues,
    summed into the month they signed up). Jen's pinned rule is PAYMENT month:
    each payment counts where it was paid ($$$), while the member counts once
    in their sign-up month (#). Payment dates live in `payAllocationViews`
    (AllocationDate — validated 7/21); the ledger-based replacement is the
    Phase 1 rebuild. Until it ships, monthly revenue splits are approximate
    wherever billing month ≠ payment month.

NRA exception:
  - NRA chains have no WRA/MSC sign-up invoice (dues are paid to NRA directly,
    prorated back via accounting GL). They produce $0 here — matches the SOP.
    For NRA revenue, see the finance Dues Summary workbook.
"""

import time
from datetime import date, timedelta
from typing import Dict, Iterable, Optional

from src.slx.client import SLXClient
from reports.membership_performance_tracker.logic.target import (
    NON_TARGET, TARGET, build_target_map, classify, new_member_cohort_where)
from reports.membership_performance_tracker.logic.attribution import originator_territory_map


# 2026-07-14 — PAID basis decoded from the CRM "New Member Sales" report + Jen
# ("sales = paid; TMs could bill without collecting"): Net_invoice − Balance
# (Best of Both counts 535 of 1,070), IN+AD so rebill pairs net.
# 2026-07-21 — WRA ONLY (Jen): CMP = Claims Management Program fees, never
# dues; the 7/15 MSC "CMP Fee" inclusion is dead (see module docstring).
SALES_COMP_CODES = frozenset({"WRA"})

# Po_number label rule — named so the billing rule is discoverable, not a magic
# substring buried at the call site (matched case-insensitively):
#   Negative "BOB Two-Year Membership" credit lines are skipped (face-value rule
#   D1=c, 7/16). BOB = the Black-Owned Business comped two-year membership: the
#   dues are billed then credited back, so the SELLER keeps face-value sales
#   credit while $0 is collected (Jen's convention, footnoted on README).
#   ("Best of Both Worlds" in old notes was just an ACCOUNT NAME in a paid-basis
#   example — not this program. One BOB concept, clarified 2026-07-20.)
BOB_PROMO_PO_LABEL = "bob"


def _countable_ids(account_amounts, bob_amounts) -> set:
    """Paid-only member counts (Jiho ratified 2026-07-22): a new member COUNTS
    only if their dues actually got paid (net amount > 0), or they are a BOB
    (comped — deemed fulfilled at $0; face value tracked in the BOB row).
    Refund-only and never-paid enrollees do not count. Derived from the SAME
    amounts as the dollars, so count-without-revenue is structurally impossible
    (BOB excepted, and BOB is visible in its own row)."""
    return ({a for a, v in account_amounts.items() if v and v > 0}
            | {a for a, v in bob_amounts.items() if v})


def _accumulate_breakdown(result: Dict, territory: str, breakdown: Dict) -> None:
    """Merge a per-user breakdown into the territory total (multi-user
    territories like Majors/NRA must SUM, not last-user-wins)."""
    if territory in result:
        for k, v in breakdown.items():
            result[territory][k] = result[territory].get(k, 0) + (v or 0)
    else:
        result[territory] = dict(breakdown)

# Dues installments for a payment-plan new member can be billed many months
# after enrollment (multiple WRA invoices across the year — payment plans have
# no code of their own; Jen 7/21). Look forward far enough to capture the full
# first year of dues, but stop short of ~12 months so we don't pick up the
# member's year-2 renewal.
INVOICE_LOOKFORWARD_DAYS = 305
INVOICE_LOOKBACK_DAYS = 30


def _sum_new_member_dues(
    invoices: Iterable[dict],
    new_ids: set,
    dues_comp_codes: Iterable[str] = SALES_COMP_CODES,
) -> Dict[str, float]:
    """
    Sum PAID dues (Net_invoice − Balance) into {account_id: total} for new
    members. WRA only (2026-07-21, Jen: CMP/MSC lines are claims-program fees,
    never dues). IN + AD so rebill/reversal pairs net out.
    """
    codes = frozenset(dues_comp_codes)
    amounts: Dict[str, float] = {}
    for inv in invoices:
        aid = inv.get("Accountid")
        if aid not in new_ids:
            continue
        code = inv.get("Comp_code")
        if code not in codes:
            continue
        if inv.get("Invoice_Type") not in ("IN", "AD"):
            continue
        amt = inv.get("Net_invoice")
        # D1=(c) (Jiho 7/16): "BOB 2-Year Membership" promo billing credits the
        # dues right back (+505/-505 -> ledger $0), but these ARE sales at face
        # value (Jen's convention; footnoted on the README tab). Skip the
        # negative BOB credit line; genuine reversals (no BOB label) still net.
        if (isinstance(amt, (int, float)) and amt < 0
                and BOB_PROMO_PO_LABEL in (inv.get("Po_number") or "").lower()):
            continue
        if isinstance(amt, (int, float)):
            paid = amt - (inv.get("Balance") or 0)
            amounts[aid] = amounts.get(aid, 0.0) + paid
    return amounts


def _sum_bob_face_value(invoices: Iterable[dict], new_ids: set) -> Dict[str, float]:
    """Per-account FACE-VALUE portion of counted revenue that is BOB/promo
    credit (Jiho 7/20): the positive BOB-labeled dues lines that count as sales
    while the comp credits them back — so readers can subtract it to see cash.
    Mirrors the main sum's filters (dues codes, IN/AD, paid basis)."""
    out: Dict[str, float] = {}
    for inv in invoices:
        aid = inv.get("Accountid")
        if aid not in new_ids:
            continue
        if inv.get("Comp_code") not in SALES_COMP_CODES:
            continue
        if inv.get("Invoice_Type") not in ("IN", "AD"):
            continue
        amt = inv.get("Net_invoice")
        if (isinstance(amt, (int, float)) and amt > 0
                and BOB_PROMO_PO_LABEL in (inv.get("Po_number") or "").lower()):
            out[aid] = out.get(aid, 0.0) + (amt - (inv.get("Balance") or 0))
    return out


# ⛔ NOT THE REPORT'S BASIS (2026-07-30). `revenue_for_period` and
# `revenue_for_period_by_target` attribute dues to the member's ENROLLMENT
# month. The MPR attributes each payment to the month it ARRIVES
# (`revenue_and_counts_by_first_pay`, the only one the engine calls) — Jen,
# recorded 7/30: installments land as they come. These two survive because
# tests exercise the shared cohort filter through them and because
# scripts/recompute_revenue.py is a diagnostic. Do not wire either into a
# report path without re-reading docs/metrics/new-sales-revenue-target.md.
def revenue_for_period(
    client: SLXClient,
    territory_user_map: Dict[str, str],
    start_date: date,
    end_date: date,
    request_delay: float = 0.15,
) -> Dict[str, float]:
    """
    New-sales revenue per territory for a date window.

    Args:
        client:              Authenticated SLXClient.
        territory_user_map:  {slx_user_id: canonical_territory_name}
        start_date:          Window start (inclusive).
        end_date:            Window end (inclusive).
        request_delay:       Pause between SLX calls.

    Returns:
        {territory_name: total_new_member_revenue_for_window}
        Territories with no new sign-ups → 0.0.
    """
    start_str = start_date.strftime("%Y-%m-%d")

    result: Dict[str, float] = {}

    for user_id, territory in territory_user_map.items():
        if territory is None:
            continue

        # ── Step 1: account ids of new members enrolled in window
        new_where = new_member_cohort_where(user_id, start_str, end_date)
        new_recs = client._fetch_all("cMemberGens", where=new_where, select="Accountid")
        # cMemberGens $key == account id; explicit Accountid field may be None
        new_ids = {(r.get("Accountid") or r.get("$key")) for r in new_recs}
        new_ids.discard(None)
        time.sleep(request_delay)

        # Hybrid basis (7/22): invoice dollars minus ledger-identified fees;
        # ledger for renewal detection only (see revenue_for_period_by_target).
        from reports.membership_performance_tracker.logic.ledger_revenue import (
            cohort_screen)
        # 2026-07-30: no prior-payer screen — rejoins past the ~6-month gap
        # ARE new members (enroll-date rewrite is the upstream gate).
        kept, fees, first_pay = cohort_screen(
            client, new_ids, start_date, request_delay=request_delay)
        new_ids = kept

        if not new_ids:
            result[territory] = result.get(territory, 0.0)
            continue

        # ── Step 2: dues invoices for territory across the new members' first
        # billing year. Comp code / invoice type / netting are applied
        # client-side in _sum_new_member_dues (more robust than multi-clause
        # SData OR-filters, which can 500 on this server).
        inv_start = (start_date - timedelta(days=INVOICE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        inv_end   = (end_date   + timedelta(days=INVOICE_LOOKFORWARD_DAYS)).strftime("%Y-%m-%d")
        inv_where = (
            f"Account.AccountManager.Id eq '{user_id}' "
            f"and Invoice_Date ge @{inv_start}@ "
            f"and Invoice_Date le @{inv_end}@"
        )
        invoices = client._fetch_all(
            "dlInvoiceHistoryHeader",
            where=inv_where,
            select="Accountid,Net_invoice,Comp_code,Invoice_Type,Balance,Po_number,Invoice_Date",
        )
        time.sleep(request_delay)

        # ── Step 3: invoice dues minus ledger fees per account, credited to
        # the SELLER (AccountExtension.Originator — ratified 7/15-16).
        dues = _sum_new_member_dues(invoices, new_ids)
        account_amounts = {aid: dues.get(aid, 0.0) - fees.get(aid, 0.0)
                          for aid in new_ids}
        account_amounts = {a: v for a, v in account_amounts.items() if v}
        orig_terr = originator_territory_map(
            client, account_amounts.keys(), territory_user_map,
            fallback_territory=territory, request_delay=request_delay)
        result.setdefault(territory, 0.0)
        for aid, amt in account_amounts.items():
            t = orig_terr.get(aid, territory)
            result[t] = result.get(t, 0.0) + amt

    return result


def revenue_for_period_by_target(
    client: SLXClient,
    territory_user_map: Dict[str, str],
    start_date: date,
    end_date: date,
    request_delay: float = 0.15,
) -> Dict[str, Dict]:
    """
    New-sales revenue per territory split by Target / Non-Target.

    Same logic as revenue_for_period() — restricts to new member invoices in the
    window, excludes reinstatements — then uses build_target_map() classification
    to break revenue into Target / Non-Target / Unknown buckets.

    Costs 3 extra API calls per territory vs revenue_for_period (build_target_map).
    Use revenue_for_period() when you only need the total.

    Args:
        client:              Authenticated SLXClient.
        territory_user_map:  {slx_user_id: canonical_territory_name}
        start_date:          Window start (inclusive).
        end_date:            Window end (inclusive).
        request_delay:       Pause between SLX calls.

    Returns:
        {
            "Pierce": {
                "total":      12500.0,
                "target":      9800.0,
                "non_target":  2400.0,
                "unknown":      300.0,
            },
            ...
        }
    """
    from calendar import monthrange

    start_str = start_date.strftime("%Y-%m-%d")

    # Widen the invoice search window beyond the enrollment window. Billing lags
    # enrollment — and payment-plan installments (multiple WRA invoices) can be
    # billed many months later. Look back 30 days (enroll-Feb-28 → bill early
    # March) and forward through the member's first ~10 billing months,
    # stopping short of a year so we don't capture their year-2 renewal.
    inv_start = (start_date - timedelta(days=INVOICE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    inv_end   = (end_date   + timedelta(days=INVOICE_LOOKFORWARD_DAYS)).strftime("%Y-%m-%d")

    result: Dict[str, Dict] = {}

    for user_id, territory in territory_user_map.items():
        if territory is None:
            continue

        # Step 1: new member account IDs enrolled in window
        new_where = new_member_cohort_where(user_id, start_str, end_date)
        new_recs = client._fetch_all("cMemberGens", where=new_where, select="Accountid")
        new_ids = {(r.get("Accountid") or r.get("$key")) for r in new_recs}
        new_ids.discard(None)
        time.sleep(request_delay)

        if not new_ids:
            _accumulate_breakdown(result, territory,
                                  {"total": 0.0, "target": 0.0, "non_target": 0.0,
                                   "unknown": 0.0, "bob": 0.0, "count_total": 0,
                                   "count_target": 0, "count_non_target": 0,
                                   "count_unknown": 0})
            continue

        # Step 2 (HYBRID BASIS, 7/22): the payment ledger proved INCOMPLETE
        # for recent dues cash, so DOLLARS stay invoice-based (Net − Balance —
        # validated for months against the membership team's editions). The
        # ledger contributes what it is reliable for: renewal detection (old
        # rows) and fee identification (county/event charges bundled into
        # invoice Nets get subtracted per account).
        from reports.membership_performance_tracker.logic.ledger_revenue import (
            cohort_screen)
        # 2026-07-30: no prior-payer screen — rejoins past the ~6-month gap
        # ARE new members (enroll-date rewrite is the upstream gate).
        kept, fees, first_pay = cohort_screen(
            client, new_ids, start_date, request_delay=request_delay)
        new_ids = kept

        inv_where = (
            f"Account.AccountManager.Id eq '{user_id}' "
            f"and Invoice_Date ge @{inv_start}@ "
            f"and Invoice_Date le @{inv_end}@"
        )
        invoices = client._fetch_all(
            "dlInvoiceHistoryHeader",
            where=inv_where,
            select="Accountid,Net_invoice,Comp_code,Invoice_Type,Balance,Po_number,Invoice_Date",
        )
        time.sleep(request_delay)

        bob_amounts = _sum_bob_face_value(invoices, new_ids)
        dues = _sum_new_member_dues(invoices, new_ids)
        account_amounts = {aid: dues.get(aid, 0.0) - fees.get(aid, 0.0)
                          for aid in new_ids}
        account_amounts = {a: v for a, v in account_amounts.items() if v}

        # Step 3: build target map and split
        # status=None — new members are Active by definition, but use None to be safe
        # in case any went inactive between enrollment and report date
        target_map = build_target_map(client, user_id, status=None,
                                      request_delay=request_delay)
        # Seller-credit (7/15-16): each account's dues land in the SELLER's
        # territory column; T/NT classification stays from the ACCOUNT's data.
        orig_terr = originator_territory_map(
            client, set(account_amounts) | _countable_ids(account_amounts, bob_amounts),
            territory_user_map,
            fallback_territory=territory, request_delay=request_delay)
        _accumulate_breakdown(result, territory,
                              {"total": 0.0, "target": 0.0, "non_target": 0.0,
                               "unknown": 0.0, "bob": 0.0, "count_total": 0,
                               "count_target": 0, "count_non_target": 0,
                               "count_unknown": 0})
        countable = _countable_ids(account_amounts, bob_amounts)
        for aid in set(account_amounts) | countable:
            amt = account_amounts.get(aid, 0.0)
            cls = classify(target_map, aid)
            bucket = ("target" if cls == TARGET
                      else "non_target" if cls == NON_TARGET else "unknown")
            row = {"total": amt, "target": 0.0, "non_target": 0.0, "unknown": 0.0,
                   "bob": bob_amounts.get(aid, 0.0), "count_total": 0,
                   "count_target": 0, "count_non_target": 0, "count_unknown": 0}
            row[bucket] = amt
            if aid in countable:
                row["count_total"] = 1
                row["count_" + bucket] = 1
            _accumulate_breakdown(result, orig_terr.get(aid, territory), row)

    return result




# ---------------------------------------------------------------------------
# Option 2 (Jiho ratified 2026-07-22): FIRST-PAYMENT-MONTH anchoring.
# A member and ALL their first-year dollars live in the month their FIRST dues
# payment landed — never the enrollment month, never spread across months, and
# never retroactive (a cell only deepens as later installments arrive; the
# member's placement is fixed the day their first money lands).
# Anchor resolution: ledger first dues AllocationDate → (ledger-blind fallback)
# earliest PAID WRA invoice date → BOB anchors at enrollment (comped, no
# payment ever). Anchor outside this edition's months → belongs to a later
# edition, excluded here.
# ---------------------------------------------------------------------------

def _resolve_anchor(first_pay_date, earliest_paid_invoice_date, is_bob,
                    enroll_abb, date_to_abb):
    """Month label for a member's cell, or None (outside this edition).

    Out-of-span ledger dates FALL THROUGH to the invoice date (2026-07-23:
    Springhill Suites' allocation row was dated 2025-01-05 — a year before
    enrollment; the old early-return silently dropped a $4,563 paying member).
    A ledger date landing outside the span is treated as unreliable, not as
    proof the member belongs to another edition — the invoice date decides."""
    if first_pay_date is not None:
        abb = date_to_abb(first_pay_date)
        if abb is not None:
            return abb
        import warnings
        warnings.warn(f"[revenue] ledger first-pay {first_pay_date} outside the "
                      f"edition span — falling back to invoice date "
                      f"{earliest_paid_invoice_date}")
    if earliest_paid_invoice_date is not None:
        return date_to_abb(earliest_paid_invoice_date)
    if is_bob:
        return enroll_abb
    return None


def collect_unpaid_actives(cohort_ids, account_amounts, bob_amounts,
                           name_by_id, territory, month) -> list:
    """Enrollees carrying NO money — the hard rule Jen wants flagged.

    2026-07-30 (recorded): *"A member should not be active without some sort of
    payment. That's really a hard line. And if it happens, I want to know about
    it."* Shannon's summary lists this first in the exceptions queue.

    The paid basis already keeps them out of the counts; the defect was silence.
    BOB comps are NOT unpaid — they are fulfilled at $0 by design.
    """
    out = []
    for aid in sorted(cohort_ids):
        if account_amounts.get(aid):
            continue
        if bob_amounts.get(aid):
            continue          # comped, not unpaid
        out.append({"account_id": aid,
                    "name": name_by_id.get(aid, aid),
                    "territory": territory,
                    "month": month,
                    "why": "enrolled and active with no dues payment — "
                           "policy says this should never happen"})
    return out


def revenue_and_counts_by_first_pay(
    client: SLXClient,
    territory_user_map: Dict[str, str],
    month_windows,          # [(abb, start_date, end_date), ...] FY order
    request_delay: float = 0.15,
    flags_out: Dict[str, list] = None,
) -> Dict[str, Dict[str, Dict]]:
    """
    {territory: {month_abb: {total,target,non_target,unknown,bob,
                             count_total,count_target,count_non_target,count_unknown}}}
    Discovery is identical to the per-enrollment-month sweep (same queries,
    same renewal screen, same classification, same seller credit) — only the
    BUCKETING changes: each member's row lands in their first-payment month.
    """
    span_start, span_end = month_windows[0][1], month_windows[-1][2]

    def date_to_abb(d):
        if d is None or d < span_start or d > span_end:
            return None
        for abb, ws, we in month_windows:
            if ws <= d <= we:
                return abb
        return None

    def zero_row():
        return {"total": 0.0, "target": 0.0, "non_target": 0.0, "unknown": 0.0,
                "bob": 0.0, "bob_target": 0.0, "bob_non_target": 0.0,
                "count_total": 0, "count_target": 0,
                "count_non_target": 0, "count_unknown": 0,
                "count_bob": 0,
                "comped_new": 0.0}

    result: Dict[str, Dict[str, Dict]] = {}
    # one entry per member per anchor month — the receipts capture AND the
    # aggregation input, by construction the same objects (2026-08-18)
    member_rows: Dict[str, dict] = {}
    for _u, terr in territory_user_map.items():
        if terr:
            result.setdefault(terr, {abb: zero_row() for abb, _s, _e in month_windows})

    # BOB EXEMPTION on the comped-new tripwire (8/5): BOB joins are comped
    # BY DESIGN (board program) — the 8/4 verification's 22 tripwire hits
    # all aligned with the BOB enrollment calendar. Only NON-BOB comped new
    # sales are policy violations. Best-effort: an empty roster on fetch
    # failure means flags may include BOBs (never fewer flags).
    try:
        _bob_roster = {r.get("$key") for r in client._fetch_all(
            "accounts", where="CDiverseOwnership eq true", select="Id")} - {None}
    except Exception:
        _bob_roster = set()

    for abb, start_date, end_date in month_windows:
        start_str = start_date.strftime("%Y-%m-%d")
        inv_start = (start_date - timedelta(days=INVOICE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        inv_end = (end_date + timedelta(days=INVOICE_LOOKFORWARD_DAYS)).strftime("%Y-%m-%d")
        for user_id, territory in territory_user_map.items():
            if territory is None:
                continue
            new_where = new_member_cohort_where(user_id, start_str, end_date)
            new_recs = client._fetch_all("cMemberGens", where=new_where, select="Accountid")
            new_ids = {(r.get("Accountid") or r.get("$key")) for r in new_recs}
            new_ids.discard(None)
            time.sleep(request_delay)
            if not new_ids:
                continue
            from reports.membership_performance_tracker.logic.ledger_revenue import (
                cohort_screen)
            # 2026-07-30: no prior-payer screen — rejoins past the ~6-month
            # gap ARE new members, and the enroll-date rewrite upstream is the
            # gate (see cohort_screen's docstring).
            # COMP TRIPWIRE (ruled 2026-08-04): comping a new membership is
            # banned outside BOB — any face dollars landing here surface on
            # the "New Sales - Comped ($)" line as an out-of-policy flag.
            _comped_new = {}
            kept, fees, first_pay = cohort_screen(
                client, new_ids, start_date, request_delay=request_delay,
                comped_out=_comped_new)
            _credited_faces = dict(_comped_new)   # pre-filter: face values
            # RECORD-CLEANUP (Jen 8/10, Delfino's Pizzeria University): a
            # fully-credited cycle on an account closed as a DUPLICATE is a
            # payment transfer's residue — the real sale lives on the twin
            # record and is counted there. Not a comp; excluded, disclosed.
            if _comped_new:
                _cleanup = set()
                for a in list(_comped_new):
                    try:
                        ext = client._fetch_all(
                            "AccountExtension", where=f"Account.Id eq '{a}'",
                            select="Statusreason")
                        reason = str((ext[0] if ext else {}).get("Statusreason")
                                     or "").strip().lower()
                        if reason == "duplicate record":
                            _cleanup.add(a)
                    except Exception:
                        pass
                if _cleanup and flags_out is not None:
                    flags_out.setdefault("record_cleanup", []).extend(
                        {"account_id": a, "territory": territory, "month": abb,
                         "face_dollars": _comped_new[a],
                         "why": "billed and fully credited on a record closed "
                                "as a duplicate — the payment moved to the "
                                "surviving record; one sale, counted once"}
                        for a in sorted(_cleanup))
                for a in _cleanup:
                    _comped_new.pop(a, None)
                    _credited_faces.pop(a, None)
                    kept.discard(a)
            _comped_new = {a: v for a, v in _comped_new.items()
                           if a not in _bob_roster}
            if _comped_new:
                result[territory][abb]["comped_new"] += sum(_comped_new.values())
                # the flag must be able to NAME the account (Jiho 8/5) — ids
                # ride to the transparency dataset, never the report face
                result[territory][abb].setdefault(
                    "comped_new_accounts", {}).update(_comped_new)
            if not kept:
                continue
            inv_where = (
                f"Account.AccountManager.Id eq '{user_id}' "
                f"and Invoice_Date ge @{inv_start}@ "
                f"and Invoice_Date le @{inv_end}@"
            )
            invoices = client._fetch_all(
                "dlInvoiceHistoryHeader", where=inv_where,
                select="Accountid,Net_invoice,Comp_code,Invoice_Type,Balance,Po_number,Invoice_Date",
            )
            time.sleep(request_delay)
            bob_amounts = _sum_bob_face_value(invoices, kept)
            dues = _sum_new_member_dues(invoices, kept)
            account_amounts = {aid: dues.get(aid, 0.0) - fees.get(aid, 0.0)
                               for aid in kept}
            account_amounts = {a: v for a, v in account_amounts.items() if v}
            # BOB IDENTITY = the diversity checkbox (Jiho ruling 8/10): the
            # DIV credit-back lags weeks and carries no billing code (Simply
            # Soulful: plain +730/-730 INs), so the checkbox is the only
            # timely signal. Checkbox enrollees count at FACE — revenue on
            # both sides plus the BOB share — credited back yet or not.
            for aid in kept & _bob_roster:
                face = (_credited_faces.get(aid, 0.0)
                        or (dues.get(aid, 0.0) - fees.get(aid, 0.0)))
                if face > 0:
                    bob_amounts[aid] = max(bob_amounts.get(aid, 0.0), face)
                    if account_amounts.get(aid, 0.0) < face:
                        account_amounts[aid] = face
            countable = _countable_ids(account_amounts, bob_amounts)
            # earliest PAID invoice date per account (the ledger-blind fallback)
            from reports.membership_performance_tracker.logic.ledger_revenue import (
                parse_slx_date)
            earliest_paid = {}
            # The NET BILL per account (IN + AD, so rebill/reversal pairs net
            # out) — captured for the receipts so the trace page can show
            # "asked" and "collected" as separate truths (Shannon 8/12: the
            # paid amount was displayed under "Asked $" with Collected None).
            # Display-only: nothing published reads this.
            account_billed: Dict[str, float] = {}
            for r in invoices:
                aid = r.get("Accountid")
                if aid not in kept or r.get("Comp_code") != "WRA":
                    continue
                _net = r.get("Net_invoice")
                if (r.get("Invoice_Type") in ("IN", "AD")
                        and isinstance(_net, (int, float))):
                    account_billed[aid] = account_billed.get(aid, 0.0) + _net
                if r.get("Invoice_Type") != "IN":
                    continue
                net = r.get("Net_invoice")
                if not isinstance(net, (int, float)):
                    continue
                if (net - (r.get("Balance") or 0)) <= 0:
                    continue
                d = parse_slx_date(r.get("Invoice_Date"))
                if d is not None and (aid not in earliest_paid or d < earliest_paid[aid]):
                    earliest_paid[aid] = d
            target_map = build_target_map(client, user_id, status=None,
                                          request_delay=request_delay)
            orig_terr = originator_territory_map(
                client, set(account_amounts) | countable, territory_user_map,
                fallback_territory=territory, request_delay=request_delay)
            # Jen's hard rule — active without payment must be SEEN, not silently
            # excluded by the paid basis (2026-07-30; Shannon's exceptions queue).
            if flags_out is not None:
                flags_out.setdefault("active_without_payment", []).extend(
                    collect_unpaid_actives(kept, account_amounts, bob_amounts,
                                           {}, territory, abb))
            for aid in set(account_amounts) | countable:
                amt = account_amounts.get(aid, 0.0)
                anchor = _resolve_anchor(
                    first_pay.get(aid), earliest_paid.get(aid),
                    bool(bob_amounts.get(aid)), abb, date_to_abb)
                if anchor is None:
                    continue    # paid outside this edition's span (or unresolvable)
                cls = classify(target_map, aid)
                bucket = ("target" if cls == TARGET
                          else "non_target" if cls == NON_TARGET else "unknown")
                terr_key = orig_terr.get(aid, territory)
                # ONE PATH (ruled 2026-08-14 for drops; applied to new sales
                # 2026-08-18). This loop used to accumulate the published cell
                # HERE and record the member row for the receipts as a separate
                # act. Two writes of one fact drift: the 2026-08-18 nightly
                # published NorthKing Aug = 2,924.00 while the member rows
                # behind it held 4,678.50 — and the CRM's own New Member Sales
                # export agreed with the member rows to the penny. The
                # conservation gate refused every receipt in the artifact over
                # that one cell.
                #
                # Now the member row is the ONLY thing this loop produces; the
                # published cells are summed from the rows afterwards
                # (aggregate_new_sales). A cell and its member list are the
                # same objects read twice, so they cannot disagree. Same key
                # semantics as the receipts capture (last write per
                # aid|anchor wins) — the aggregation input IS the capture.
                row = {"territory": terr_key, "month": anchor, "band": bucket,
                       "amount": amt, "bob": bob_amounts.get(aid, 0.0),
                       "ask": round(account_billed.get(aid, 0.0), 2),
                       "counted": aid in countable,
                       "first_pay": first_pay.get(aid) or earliest_paid.get(aid)}
                member_rows[f"{aid}|{anchor}"] = row
                from reports.membership_performance_tracker.logic import (
                    receipts_capture as _rc)
                _rc.record("new_members", f"{aid}|{anchor}", row)
    aggregate_new_sales(member_rows.values(), result, month_windows, zero_row)
    return result


def aggregate_new_sales(rows, result, month_windows, zero_row) -> Dict:
    """Member rows → the published new-sales cells. The only place they
    become numbers (mirrors crystal_feed.aggregate_drops, ruled 2026-08-14).

    `result` may already hold comped-new flag dollars written by the
    discovery passes; aggregation adds into those cells rather than
    replacing them. Unknown-size members keep their own bucket here — the
    engine folds unknown into Non-Target at assignment, exactly as before.
    """
    for r in rows:
        cell = result.setdefault(
            r["territory"], {a: zero_row() for a, _s, _e in month_windows}
        ).setdefault(r["month"], zero_row())
        amt = r["amount"]
        bucket = r["band"]
        cell["total"] += amt
        cell[bucket] += amt
        bob = r.get("bob") or 0.0
        cell["bob"] += bob
        if bob:
            # unknowns fold NT, mirroring the count/revenue folds
            cell["bob_target" if bucket == "target" else "bob_non_target"] += bob
        if r.get("counted"):
            cell["count_total"] += 1
            cell["count_" + bucket] += 1
            if bob:
                # new-BOB COUNT requested by leadership (2026-08-12)
                cell["count_bob"] += 1
    return result
