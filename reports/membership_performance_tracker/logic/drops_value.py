"""
drops_value.py — the drops rebuild logic (Jiho ratified 2026-07-23):

  1. BILLABLE GATE — a drop counts only where the dues live. A record with no
     own dues anywhere (no Dues Level product, no positive WRA dues invoice,
     no dues-coded ledger cash) was never a dues-carrying member: it rides the
     detail sheet, never the counts. This alone dissolves the family-child
     problem (Taco Time ×4 / Chick-fil-A class): children with no own dues
     never count; the parent record carries its own loss.
  2. VALUATION — the same cascade, positive amounts only:
     Dues Level (MembershipProduct price — the field Crystal's export prints)
     → most recent SUBSTANTIVE WRA IN invoice (>= INVOICE_FLOOR, so trailing
     remnants like AC Hotel's $15.50 never masquerade as a dues level; a
     below-floor invoice is used only if nothing better exists and positive)
     → dues-coded ledger allocations.
  3. CLOSURE UNION — a closure record with was_member_at_closure='Y' and no
     status-flip drop record IS a member loss (Starbucks Fred Meyer class:
     the closure was recorded, the status flip forgotten). Materialized from
     native fields only (date_closed, its own reason), same gate, same
     valuation, provenance-flagged. Status-flip records always win dedup.
"""
from typing import Dict, Iterable, List, Optional

# Lowest real dues level in the book is ~$190 (RRO); anything under this on an
# invoice is a trailing remnant (fees, prorations), not a dues level.
INVOICE_FLOOR = 100.0


def resolve_dues_value(dues_level: Optional[float],
                       invoice_amounts_desc: Iterable[float],
                       ledger_dues_total: Optional[float]) -> Optional[float]:
    """The record's own dues value, or None (= not a dues-carrying member).

    invoice_amounts_desc: positive WRA IN invoice nets, most recent first.
    """
    if isinstance(dues_level, (int, float)) and dues_level > 0:
        return float(dues_level)
    best_small = None
    for amt in invoice_amounts_desc:
        if not isinstance(amt, (int, float)) or amt <= 0:
            continue   # negatives (credit invoices) can never value a drop
        if amt >= INVOICE_FLOOR:
            return float(amt)
        if best_small is None:
            best_small = float(amt)
    if isinstance(ledger_dues_total, (int, float)) and ledger_dues_total > 0:
        return float(ledger_dues_total)
    return best_small   # a sub-floor invoice only when nothing better exists


def closure_union(drops_detail: List[dict], closed_detail: List[dict],
                  min_date: str = "2025-10-01") -> List[dict]:
    """Member closures missing their status-flip drop record → synthetic drop
    rows from NATIVE closure fields, provenance-flagged. Dedup: any account
    already in drops_detail is untouched (status-flip record wins)."""
    have = {d.get("account_id") for d in drops_detail if d.get("account_id")}
    out = []
    for c in closed_detail or []:
        if c.get("was_member_at_closure") != "Y":
            continue
        aid = c.get("account_id")
        if not aid or aid in have:
            continue
        date_closed = c.get("date_closed")
        if not date_closed:
            continue   # unusable-date: counts nowhere, stays in closed_detail only
        if date_closed < min_date:
            # FY SCOPE (2026-07-23 overreach fix): closed_detail is ALL-TIME —
            # without this, decades of historical closures flood the detail.
            continue
        out.append({
            "account_id": aid,
            "account_name": c.get("account_name"),
            "territory": c.get("territory"),
            "business_type": c.get("business_type"),
            "is_target": c.get("is_target"),
            "drop_date": date_closed,
            "drop_reason": c.get("notes") or "Out of Business",
            "drop_category": "Closed",
            "amount_billed": None,          # valued by the same cascade sweep
            "source": "closure-record (status flip missing in CRM)",
        })
    return out
