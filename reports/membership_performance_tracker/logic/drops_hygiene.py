"""drops_hygiene.py — the billed-last-cycle test, demoted to data hygiene.

2026-07-30: the export's real block (Inactive/Closed, bill months 1–12) is the
drops answer — but it carries stale strays the team's month-scoped process
never sees: rows whose status date is decades old (Brooklyn Bros Pizzeria,
2003) and rows with no WRA dues invoice EVER (the signed-up-then-vanished
class and three genuine record anomalies). Counting them would put members in
the headline that Jen's numbers never contained.

The test is the ratified definition made mechanical: a drop in cycle M was
BILLED at the previous occurrence of cycle M. Verdicts are computed live (one
CustomerNo query per member, memoized), persisted beside the cache, and
replayed on --from-cache runs so both paths publish identical numbers.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Callable, Dict, Optional

# Billing slack around a cycle's first notice (matches the proving run).
GRACE_DAYS = 90


def notice_date(bill_month: int, fy_start_year: int) -> dt.date:
    """First-notice date for cycle M in the FY starting fy_start_year.

    Cycle M is first-noticed in M-1 (REFERENCE: 1st notice M-1, 2nd M, 3rd
    M+1). FY months 10-12 fall in fy_start_year; 1-9 in the next year.
    """
    year = fy_start_year if bill_month >= 10 else fy_start_year + 1
    month = bill_month - 1 or 12
    if bill_month == 1:
        year -= 1
    return dt.date(year, month, 1)


def verdict(bill_month: int, fy_start_year: int,
            latest_positive_invoice: Optional[dt.date]) -> Optional[str]:
    """None = counts. A string = the named exclusion reason.

    `latest_positive_invoice` is the member's newest WRA dues invoice with a
    positive net — None when they have none at all.
    """
    if latest_positive_invoice is None:
        return "no WRA dues invoice ever — not a dues-carrying member"
    prev_cycle = notice_date(bill_month, fy_start_year) - dt.timedelta(
        days=365 + GRACE_DAYS)
    if latest_positive_invoice < prev_cycle:
        years = (notice_date(bill_month, fy_start_year)
                 - latest_positive_invoice).days / 365.25
        return (f"last WRA dues invoice {latest_positive_invoice} — "
                f"{years:.1f}y before cycle {bill_month}; left in an earlier year")
    return None


def build_checker(client, fy_start_year: int,
                  cache_path: Path) -> Callable:
    """A DropRow -> Optional[str] checker: live when a client exists, replayed
    from the verdict cache otherwise. Live verdicts are persisted as they are
    computed, so the next --from-cache run publishes the same numbers.
    """
    stored: Dict[str, Optional[str]] = {}
    if cache_path.exists():
        stored = json.loads(cache_path.read_text()).get("verdicts", {})

    def latest_invoice(mid: str) -> Optional[dt.date]:
        rows = client._fetch_all(
            "dlInvoiceHistoryHeader",
            where=f"CustomerNo eq '{mid}' and Comp_code eq 'WRA'",
            select="Net_invoice,Invoice_Type,Invoice_Date",
        )
        best: Optional[dt.date] = None
        for r in rows:
            if r.get("Invoice_Type") not in ("IN", "Invoice", "AD"):
                continue
            net = r.get("Net_invoice")
            if not isinstance(net, (int, float)) or net <= 0:
                continue
            d = _slx_day(r.get("Invoice_Date"))
            if d and (best is None or d > best):
                best = d
        return best

    def check(row) -> Optional[str]:
        mid = getattr(row, "mid", "") or ""
        bm = getattr(row, "bill_month", None)
        if not mid or not bm:
            return None                      # nothing to test against
        if mid in stored:
            return stored[mid]
        if client is None:
            return None                      # cache path without verdicts: count
        v = verdict(int(bm), fy_start_year, latest_invoice(mid))
        stored[mid] = v
        cache_path.write_text(json.dumps(
            {"fy_start": fy_start_year, "verdicts": stored}, indent=0, default=str))
        return v

    return check


def _slx_day(raw) -> Optional[dt.date]:
    import re
    if raw is None:
        return None
    if isinstance(raw, dt.date):
        return raw
    m = re.search(r"/Date\((-?\d+)", str(raw))
    if not m:
        return None
    return dt.datetime.fromtimestamp(int(m.group(1)) / 1000,
                                     tz=dt.timezone.utc).date()
