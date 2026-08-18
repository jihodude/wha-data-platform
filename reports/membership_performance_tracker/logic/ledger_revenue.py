"""
ledger_revenue.py — the payment ledger's TWO reliable jobs for new-sales.

FINAL DESIGN (2026-07-22, after the ledger proved INCOMPLETE for recent dues
cash — Pond/Trailbreaker's June payments have no allocation rows while their
$65 fees do; Capitol shows only the refund half):

  · DOLLARS are INVOICE-BASED (revenue.py: Net − Balance, WRA only, validated
    for months against the membership team's published editions).
  · The ledger (payAllocationViews: AccountId, AllocationDate, Allocationamt,
    Comp_code, Item_Id) contributes:
      1. RENEWAL DETECTION — any WRA activity before the cohort window marks
         prior membership (old rows are the ledger's reliable region; catches
         unmarked reinstatements the Salescode-510/ReinstatedDate fields miss).
      2. FEE IDENTIFICATION — county/local fees and event purchases bundled
         into invoice Nets, subtracted one-per-code-per-cycle (cohort_screen).

  · BOB/comped members: $0 cash, counted at face value via the invoice path
    (the negative promo credit is skipped there — Jen's convention).
  · summarize_month / pay-month machinery below is retained as the future
    "cash received" view; it is NOT the report's basis.
"""

import time
from datetime import date, timedelta
from typing import Dict, Iterable, Optional, Set, Tuple

from src.slx.client import SLXClient

# MEMBERSHIP-DUES item codes — evidence-derived (2026-07-21) from the payment
# footprint of the KNOWN Feb+Jun new-member cohorts (57 accounts): their dues
# rows carry the size-band product codes; everything else they paid for was
# events (/CONVEXHIBITOR, /CONFTICKET), county/local fees (/SERESTFEE,
# /SPOKCOFEE, /KINGCOFEE, /SPHOTELFEE — excluded; the Spokane old-vs-Jen delta
# of +374.50 shows Jen's numbers exclude them), SHA dues (/SHADUES — pending
# Jen), or claims money (MSC — never dues). Extend ONLY with documented
# evidence.
import re as _re
_DUES_ITEM_RE = _re.compile(
    r"^/("
    r"RD[<>]"          # restaurant dues bands (/RD<1M, /RD>2M, ...)
    r"|RDTT"           # restaurant dues special postings
    r"|HD[>1]"         # hotel dues bands (/HD>50, /HD1TO50)
    r"|AL[<>]"         # allied dues bands (/AL<2M, /AL>4M)
    r"|ALAB$|ALNP$|ALSPEC"   # allied dues specials
    r"|[<>]\d\+"       # lodging band codes (/>2+21, /<2+1, ...)
    r"|HB\+|MB\+|LB\+" # hotel/motel/lodge band codes
    r"|NONPRO$|NONCOM$|INDV$|ESSENTIALS$"  # nonprofit/noncommercial/indiv/essential
    r"|HRVFLAT$"       # flat hospitality dues posting
    # /DUETMS EXCLUDED (7/21 evidence): the Harry's-family invoices behind it
    # are labeled "MSC Fees Paid in WHA" / "Due to MSC - Retro Fees" — claims
    # money cross-posted under WRA; most carriers have no membership record.
    # /DUEFRE EXCLUDED: never appeared in any known new member's payments.
    r")"
)

# BOB/diversity + dues discount credits: EXCLUDED entirely (not netted) — the
# face-value convention (Jen counts promo members at face value; the credit
# shows on the separate BOB row, invoice-derived).
_DUES_DISCOUNT_RE = _re.compile(r"^/(DUESDISCOUNT|DIVDISCOUNT|ALLDISCOUNT|"
                                r"DIVALLDISCOUNT|DISCSEAREST|DISCKINGREST)$")


def item_is_dues(item: str) -> bool:
    """True if the ledger Item_Id is a membership-dues charge code."""
    return bool(_DUES_ITEM_RE.match((item or "").strip()))


def parse_slx_date(v) -> Optional[date]:
    """SLX SData date → datetime.date. Handles '/Date(ms)/' and ISO strings."""
    import re
    from datetime import datetime, timezone
    if v is None:
        return None
    if isinstance(v, date):
        return v
    m = re.search(r"/Date\((-?\d+)", str(v))
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).date()
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def is_dues_allocation(row: dict, dues_items=None) -> bool:
    """WRA comp code + a membership-dues item code. MSC is never dues.
    `dues_items` may be a set (tests) or None (use the pattern classifier)."""
    if row.get("Comp_code") != "WRA":
        return False
    item = (row.get("Item_Id") or "").strip()
    if dues_items is not None:
        return item in dues_items
    return item_is_dues(item)


# A first-cycle window: payments within ~10.5 months AFTER the first-ever dues
# activity are the member's first-year money (new revenue). Beyond that it's
# their year-2 renewal. 320 (not 365) because anniversary renewals post DAYS
# EARLY: Grassa-Vancouver 341d, Primo Grill 356d, Rosie's 356d, Village Inn
# 330d — all real year-2 renewals a 365-day window wrongly admitted (7/21).
FIRST_CYCLE_DAYS = 320


def summarize_month(
    allocations: Iterable[dict],
    first_pay_by_account: Dict[str, date],
    dues_items,
    month_start: date,
    month_end: date,
) -> Tuple[Dict[str, float], Set[str]]:
    """
    Pure core. From one month's allocation rows + each account's first-ever
    dues-payment date, return:
        ({account_id: new_dues_$_paid_this_month}, {account_ids counted NEW})

    Rules (Jen 7/21): $ by pay month; count once at first-payment month;
    ever-paid-before = renewal (their rows simply don't qualify as new).
    """
    revenue: Dict[str, float] = {}
    new_accounts: Set[str] = set()

    for row in allocations:
        if not is_dues_allocation(row, dues_items):
            continue
        aid = row.get("AccountId")
        paid_on = parse_slx_date(row.get("AllocationDate"))
        amt = row.get("Allocationamt")
        if aid is None or paid_on is None or not isinstance(amt, (int, float)):
            continue
        if not (month_start <= paid_on <= month_end):
            continue
        first = first_pay_by_account.get(aid)
        if first is None:
            # History fetch missed this account — a pipeline bug. Never guess.
            import warnings
            warnings.warn(f"[ledger] no first-payment record for {aid} — skipped")
            continue
        # Renewal test: money at/after 12 months from first payment is year-2+.
        if (paid_on - first).days >= FIRST_CYCLE_DAYS:
            continue
        revenue[aid] = revenue.get(aid, 0.0) + amt
        if month_start <= first <= month_end:
            new_accounts.add(aid)

    # Drop accounts whose in-month rows netted to zero AND aren't new counts
    revenue = {a: v for a, v in revenue.items() if v != 0 or a in new_accounts}
    return revenue, new_accounts


def fetch_month_allocations(client: SLXClient, month_start: date,
                            month_end: date) -> list:
    """All allocation rows dated in [month_start, month_end] (global — territory
    attribution happens later via the seller map).

    ⚠ NO LIVE CALLERS (2026-07-24 audit) — do not revive without reading the
    dues #25 gate record (reports/dues_analysis/analysis/2026-07-24-slx-cash-
    gate.md): payAllocationViews' $key is the payment-DOCUMENT id; multi-line
    docs collapse to one arbitrary line's content, and date-window queries are
    additionally blind to rows by-invoice queries return. Sums built from this
    fetch under/mis-count multi-line payment documents."""
    end_next = (month_end + timedelta(days=1)).strftime("%Y-%m-%d")
    return client._fetch_all(
        "payAllocationViews",
        where=(f"AllocationDate ge @{month_start.strftime('%Y-%m-%d')}@ "
               f"and AllocationDate lt @{end_next}@"),
        select="AccountId,AllocationDate,Allocationamt,Comp_code,Item_Id,Invoice_number",
    )


def fetch_first_dues_payment(client: SLXClient, account_ids: Iterable[str],
                             dues_items=None,
                             request_delay: float = 0.05) -> Dict[str, date]:
    """Earliest dues AllocationDate per account (full-history fetch per
    account). The renewal test depends on this being ALL-TIME, not windowed.

    ⚠ KNOWN-UNRELIABLE ACCESS PATH (2026-07-24 audit): AccountId filters on
    payAllocationViews miss rows (Pond class), and the view collapses
    multi-line payment docs to one arbitrary line — a first payment can be
    invisible here. Prefer the invoice-table basis (cohort_screen)."""
    out: Dict[str, date] = {}
    for aid in set(account_ids):
        rows = client._fetch_all(
            "payAllocationViews",
            where=f"AccountId eq '{aid}'",
            select="AllocationDate,Allocationamt,Comp_code,Item_Id",
        )
        # Renewal test uses ANY dues activity (incl. negatives/discount rows —
        # the Kimball class: a discount implies a payment existed). But the
        # CYCLE ANCHOR must be the first POSITIVE payment: an account whose
        # only visible history is a refund (Fremont-Brewing class, Feb -2,775)
        # is an established member whose payments predate the ledger view —
        # never "new". Anchor on the earlier of the two (any-activity) so both
        # tests are conservative.
        acts, pos = [], []
        for r in rows:
            if not is_dues_allocation(r, dues_items):
                continue
            amt = r.get("Allocationamt")
            if not isinstance(amt, (int, float)):
                continue
            d = parse_slx_date(r.get("AllocationDate"))
            if not d:
                continue
            acts.append(d)
            if amt > 0:
                pos.append(d)
        if pos:
            # earliest ANY-activity anchors the cycle (catches pre-payment
            # discounts); positive payment must exist to qualify at all
            out[aid] = min(acts)
        time.sleep(request_delay)
    return out


def ledger_new_sales_for_month(
    client: SLXClient,
    territory_user_map: Dict[str, str],
    month_start: date,
    month_end: date,
    request_delay: float = 0.05,
) -> Dict[str, Dict]:
    """
    Per-territory new-sales for one month from the payment ledger:
        {territory: {"revenue": $, "count": n, "accounts": {aid: $}}}

    Seller-credited via AccountExtension.Originator (existing convention).
    """
    from reports.membership_performance_tracker.logic.attribution import (
        originator_territory_map)

    dues_items = None  # pattern classifier (item_is_dues)
    allocs = fetch_month_allocations(client, month_start, month_end)
    dues_rows = [r for r in allocs if is_dues_allocation(r, dues_items)]
    involved = {r.get("AccountId") for r in dues_rows if r.get("AccountId")}
    first_pay = fetch_first_dues_payment(client, involved, dues_items,
                                         request_delay=request_delay)
    revenue, new_accounts = summarize_month(
        dues_rows, first_pay, dues_items, month_start, month_end)

    # Seller territory per account (falls back to the account's own manager
    # inside originator_territory_map when Originator is missing/non-TM).
    orig = originator_territory_map(
        client, list(revenue.keys() | new_accounts), territory_user_map,
        fallback_territory=None, request_delay=request_delay)

    out: Dict[str, Dict] = {}
    for aid, amt in revenue.items():
        t = orig.get(aid)
        if t is None:
            continue
        row = out.setdefault(t, {"revenue": 0.0, "count": 0, "accounts": {}})
        row["revenue"] += amt
        row["accounts"][aid] = amt
    for aid in new_accounts:
        t = orig.get(aid)
        if t is None:
            continue
        out.setdefault(t, {"revenue": 0.0, "count": 0, "accounts": {}})["count"] += 1
    return out


# Days of slack before the cohort window when testing "paid before": bills for
# a sign-up can post days ahead of the enrollment record (check with the
# application), so only activity comfortably BEFORE the window marks a renewal.
RENEWAL_LOOKBACK_GUARD_DAYS = 60



def cohort_dues_and_renewals(client: SLXClient, account_ids, window_start: date,
                             request_delay: float = 0.05):
    """⚠ DORMANT — no live callers (2026-07-24 audit); superseded by
    cohort_screen. Do not revive: it reads payAllocationViews per AccountId
    (blind filter) and sums line amounts the view COLLAPSES on multi-line
    payment docs ($key = payment-document id) — see
    reports/dues_analysis/analysis/2026-07-24-slx-cash-gate.md.

    One ledger pass per cohort account serving BOTH rulings (7/22):

    1. Renewal test (ratified): any dues activity before window_start − 60d
       → renewal, excluded.
    2. Dues dollars for kept accounts: the sum of their dues-coded payment
       allocations (positive and negative) within the first cycle (< 320 days
       from first activity). Charge-type codes exclude county/local fees,
       events, and claims money STRUCTURALLY — the June residual classes
       (Spokane +195 = 3×$65 SPOKCOFEE; Meinert's $2,500 invoice artifact
       with zero dues cash) cannot recur.

    Returns (kept_ids, excluded_ids, dues_by_account). BOB/comped members have
    no allocations → kept with $0 here; their face value rides the invoice
    path (_sum_bob_face_value) and is added by the caller.
    """
    cutoff = window_start - timedelta(days=RENEWAL_LOOKBACK_GUARD_DAYS)
    kept, excluded = set(), set()
    dues: Dict[str, float] = {}
    for aid in set(account_ids):
        rows = client._fetch_all(
            "payAllocationViews",
            where=f"AccountId eq '{aid}'",
            select="AllocationDate,Allocationamt,Comp_code,Item_Id",
        )
        acts = []
        for r in rows:
            if not is_dues_allocation(r):
                continue
            amt = r.get("Allocationamt")
            d = parse_slx_date(r.get("AllocationDate"))
            if d is None or not isinstance(amt, (int, float)):
                continue
            acts.append((d, amt))
        time.sleep(request_delay)
        if not acts:
            kept.add(aid)          # never paid — new (Sophon/BOB class)
            dues[aid] = 0.0
            continue
        first = min(d for d, _ in acts)
        if first < cutoff:
            excluded.add(aid)      # paid before — renewal
            continue
        kept.add(aid)
        dues[aid] = sum(amt for d, amt in acts
                        if (d - first).days < FIRST_CYCLE_DAYS)
    return kept, excluded, dues


# County/local fees and event purchases that ride WRA alongside dues — named
# from evidence (7/22): Spokane +195 was exactly 3 x /SPOKCOFEE; NK carried
# /KINGCOFEE; new members also buy convention items. These are subtracted from
# invoice-based dues sums (invoice headers bundle fee + dues in one Net).
_FEE_ITEM_RE = _re.compile(
    r"^/(SERESTFEE|SPOKCOFEE|KINGCOFEE|KIHOTELFEE|SPHOTELFEE"
    r"|CONVEXHIBITOR|CONFTICKET|HOSPSUMATTEND"
    # /HMGMTCO (2026-07-23): hotel-management-company fee — surfaced by the
    # unclassified-code guard on the Jan hotel-group wave; management fees are
    # never dues.
    r"|HMGMTCO"
    # /AHLA (2026-08-03, Lucky Eagle Casino Hotel): American Hotel & Lodging
    # Association pass-through riding the combined invoice — Jen's canonical
    # export values the member at dues only (2,650.50 vs our 3,163.50; the
    # $513 gap was exactly this line). Same collected-for-another-org class
    # as the county fees ruled out 8/3.
    # /SHADUES (2026-08-03, ruled by member-diff): Seattle Hotel Association
    # dues pass-through, ~$52,301 across 43 published FY26 retention invoices.
    # Every comparable member in Jen's canonical SW export matched
    # ours-minus-SHADUES to the cent (42/42 — Sheraton, Westin, Renaissance,
    # Hyatt Regency…). Her Billed excludes SHA on both sides.
    # /OVERPAY (2026-08-03, ruled by Jiho+Jen: "Fees do not get included.
    # Dues only."): overpayment credit parked by accounting — not dues, nets
    # out like the fee class ($701.50 across 3 FY26 invoices).
    r"|AHLA|SHADUES|OVERPAY)$"
)


def item_is_fee(item: str) -> bool:
    """True if the ledger Item_Id is a county/local fee or event purchase."""
    return bool(_FEE_ITEM_RE.match((item or "").strip()))


def cohort_screen(client: SLXClient, account_ids, window_start: date,
                  request_delay: float = 0.05, comped_out: dict = None):
    """Screen an enrollment cohort (rebuilt 7/22b on RELIABLE queries after
    payAllocationViews proved unfilterable by account: rows that
    Invoice_number lookups return are invisible to AccountId/Account.Id
    filters for some accounts — Pond's 1,070 dues payment being the proof).

    ⛔ The prior-payer RENEWAL TEST that lived here was REMOVED 2026-07-30
    (recorded call): a member who dropped and returns after ~6 months IS a new
    member — "That exact same member" (Jen) — and on such rejoins the admin
    REWRITES the enroll date, so the EnrolledDate cohort is already gated
    upstream. Screening prior payments here is exactly how Jalapenos (14 paid
    invoices to 2017, genuinely new in July 2026) got wrongly excluded.

    What remains:
    1. FEES — for each account's in-window invoices, allocations are fetched
       BY INVOICE NUMBER (the query shape that provably returns rows) and
       fee-coded items are summed one-per-code for subtraction.
    2. FIRST PAY — earliest dues-coded AllocationDate per account (cohort-
       scoped; absent when the ledger is blind).

    Returns (account_ids, fees_by_account, first_pay_date_by_account).
    """
    cutoff = window_start - timedelta(days=RENEWAL_LOOKBACK_GUARD_DAYS)
    kept = set()
    fees: Dict[str, float] = {}
    first_pay: Dict[str, "date"] = {}   # earliest dues AllocationDate per account
    for aid in set(account_ids):
        inv = client._fetch_all(
            "dlInvoiceHistoryHeader",
            where=f"Accountid eq '{aid}' and Comp_code eq 'WRA'",
            select="Invoice_number,Net_invoice,Balance,Invoice_Type,Invoice_Date",
        )
        time.sleep(request_delay)
        window_invoices = []
        _win_rows = []                      # (invoice_number, date, net)
        for r in inv:
            if r.get("Invoice_Type") not in ("IN", "AD"):
                continue
            d = parse_slx_date(r.get("Invoice_Date"))
            net = r.get("Net_invoice")
            if d is None or not isinstance(net, (int, float)):
                continue
            if d >= cutoff and r.get("Invoice_number"):
                window_invoices.append(r.get("Invoice_number"))
                _win_rows.append((r.get("Invoice_number"), d, net))
        # SAME-DAY REVERSAL IS A CORRECTION, NOT MONEY (Gold Coast Kitchen,
        # found live 2026-08-11). Its BOB discount was entered a second time
        # and reversed on the SAME invoice the SAME day (0147750: IN -730 and
        # AD +730, both 2/2). Valuing the face as "sum of every positive net"
        # counted that reversal as a second bill — face $1,460 against a $730
        # BOB share, which is the whole of the unexplained "half-comped BOB".
        # Net each (invoice, day) group first; a group that cancels itself out
        # never happened. Groups that do NOT cancel are left completely alone,
        # so a genuine same-day bill-plus-partial-credit still values normally.
        _groups: Dict[tuple, list] = {}
        for invno, d, net in _win_rows:
            _groups.setdefault((invno, d), []).append(net)
        _win_nets = [n for grp in _groups.values() if abs(sum(grp)) > 0.005
                     for n in grp]
        kept.add(aid)
        # COMP TRIPWIRE (ruled 2026-08-04: no comping new memberships outside
        # BOB): a new member whose window bill was fully credited (positive
        # bill present, window nets sum to <= 0) is a comped new sale — the
        # policy says this never happens, so it must be loudly visible when
        # it does. Face = the positive bill total.
        if comped_out is not None:
            _pos = sum(n for n in _win_nets if isinstance(n, (int, float)) and n > 0)
            _tot = sum(n for n in _win_nets if isinstance(n, (int, float)))
            if _pos > 0 and _tot <= 0:
                comped_out[aid] = _pos
        fee_by_code = {}
        # UNION OF QUERY SHAPES (2026-08-03, BGP Domino's — found live in the
        # Jen reconciliation): the ledger's $key-collapse returns a DIFFERENT
        # surviving line per access path. Invoice 0149139 shows only its dues
        # line (/RD>5M 2,435) by-invoice and only its fee line (/KINGCOFEE
        # 260) by-account. Querying one shape made fees invisible and $260 of
        # county fees published as new revenue. Neither shape is complete;
        # the union is strictly better than either.
        merged, seen = [], set()
        for invno in window_invoices:
            for x in client._fetch_all(
                    "payAllocationViews",
                    where=f"Invoice_number eq '{invno}'",
                    select="Allocationamt,Item_Id,AllocationDate"):
                x = dict(x); x.setdefault("Invoice_number", invno)
                merged.append(x)
            time.sleep(request_delay)
        try:
            for x in client._fetch_all(
                    "payAllocationViews",
                    where=f"AccountId eq '{aid}'",
                    select="Allocationamt,Item_Id,Invoice_number,AllocationDate"):
                if str(x.get("Invoice_number") or "") in set(window_invoices):
                    merged.append(dict(x))
        except Exception:
            pass                      # by-account misses rows too (Pond class)
        deduped = []
        for x in merged:
            k = (str(x.get("Invoice_number") or ""), (x.get("Item_Id") or "").strip(),
                 x.get("Allocationamt"), str(x.get("AllocationDate") or ""))
            if k not in seen:
                seen.add(k)
                deduped.append(x)
        if True:
            for x in deduped:
                amt = x.get("Allocationamt")
                item = (x.get("Item_Id") or "").strip()
                # First-pay anchor (Option 2, Jiho 2026-07-22): the earliest
                # dues-coded payment date anchors the member's report month.
                if (item_is_dues(item) and isinstance(amt, (int, float)) and amt > 0):
                    ad = parse_slx_date(x.get("AllocationDate"))
                    if ad is not None and (aid not in first_pay or ad < first_pay[aid]):
                        first_pay[aid] = ad
                if item_is_fee(item) and isinstance(amt, (int, float)) and amt > 0:
                    # one fee per code per cycle (Capitol double-dip rule)
                    fee_by_code[item] = max(fee_by_code.get(item, 0.0), amt)
                elif (item and not item_is_dues(item)
                      and not item_is_fee(item)
                      and not _DUES_DISCOUNT_RE.match(item)):
                    # FUTURE-PROOF GUARD (Jiho 7/22: "withstand the upcoming
                    # months"): a charge code we've never classified appeared
                    # on a NEW member's invoice. It is NOT silently absorbed
                    # into dues — say so loudly so it gets classified. This is
                    # the announcement the CMP and county-fee classes never got.
                    import warnings
                    warnings.warn(
                        f"[revenue] UNCLASSIFIED charge code {item!r} "
                        f"(${amt}) on new member {aid} invoice {invno} — "
                        f"classify it as dues or fee in ledger_revenue.py")
        fees[aid] = sum(fee_by_code.values())
    return kept, fees, first_pay
