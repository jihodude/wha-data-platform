"""run_timing.py — say out loud which timing assumption a run is relying on.

The team's sequence, from the 2026-07-30 recorded call:

    Accounting posts all payments  →  RETENTION is pulled  →  Sheryl runs ITD
                                                          →  BILLABLES + PENETRATION

Two failure modes sit either side of that window, and both produce numbers that
look perfectly reasonable:

  · **Too early** — Accounting has not finished posting, so payments are missing
    and retention reads LOW. Jen expects to run "by the second business day",
    but has seen it slip "as late as the 5th business day".
  · **Too late** — ITD has already inactivated the non-payers, so a retention
    report for that cycle reads ~100%. Jen: *"you can't run a retention report,
    say, for bill month 2 right now, and it will show you anything accurate.
    It will look 100% because all the members are dropped."*

Neither the ITD date nor Accounting's green light is visible from SData, so
this CANNOT be enforced. It can be stated — which is the whole point: the
failure Jiho named on the call was that the program "is just being ran every
first of the month", silently.
"""
from __future__ import annotations

import calendar
import datetime as dt
from typing import Dict, Optional

# Accounting's posting window, in BUSINESS days of the month after the period.
ACCOUNTING_EXPECTED_BY_BUSINESS_DAY = 2
ACCOUNTING_LATEST_SEEN_BUSINESS_DAY = 5
# Beyond this many days past the period end, assume ITD has run for that cycle.
ITD_ASSUMED_RUN_AFTER_DAYS = 45


def _business_day_of_month(day: dt.date) -> int:
    """1 for the month's first weekday, 2 for the second, and so on."""
    count = 0
    for d in range(1, day.day + 1):
        if dt.date(day.year, day.month, d).weekday() < 5:
            count += 1
    return count


def period_end(period: str) -> dt.date:
    year, month = (int(x) for x in period.split("-")[:2])
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def timing_note(period: str, today: Optional[dt.date] = None) -> Dict:
    """What this run's numbers depend on, and what may be wrong with them.

    Returns {"risk": <slug or None>, "message": str, "period_end": date}.
    """
    today = today or dt.date.today()
    end = period_end(period)

    if today <= end:
        return {"risk": "period-still-open", "period_end": end,
                "message": (f"{period} has not closed yet ({end} is the period end). "
                            f"Retention for its cycle is PROVISIONAL — members can "
                            f"still pay, and billables is a live snapshot of today, "
                            f"not of the month end.")}

    days_past = (today - end).days
    if days_past > ITD_ASSUMED_RUN_AFTER_DAYS:
        return {"risk": "itd-has-run-retention-inflated", "period_end": end,
                "message": (f"{period} closed {days_past} days ago, so ITD has almost "
                            f"certainly run for that cycle. Retention re-derived now "
                            f"reads HIGH — Jen: it 'will look 100% because all the "
                            f"members are dropped'. Prefer the published figure for a "
                            f"month this old (closed months use published numbers).")}

    bday = _business_day_of_month(today)
    if bday < ACCOUNTING_EXPECTED_BY_BUSINESS_DAY:
        return {"risk": "accounting-may-be-incomplete", "period_end": end,
                "message": (f"Run on business day {bday} of the following month. "
                            f"Accounting posts payments by business day "
                            f"{ACCOUNTING_EXPECTED_BY_BUSINESS_DAY} and has slipped to "
                            f"{ACCOUNTING_LATEST_SEEN_BUSINESS_DAY}; payments may be "
                            f"missing, so retention will read LOW. Wait for the green "
                            f"light before publishing.")}

    return {"risk": None, "period_end": end,
            "message": (f"Run on business day {bday} after {period} closed — inside the "
                        f"normal window. Assumes Accounting has posted and ITD has not "
                        f"yet run for this cycle (retention before ITD, billables and "
                        f"penetration after).")}


def billables_without_invoices(carriers: Dict[str, str], invoiced_ids,
                               name_by_id: Dict[str, str] = None) -> list:
    """Members carrying a dues product who hold NO invoice for the year.

    Jen, 2026-07-30 [46:23], on the active duplicate an RRO conversion leaves
    behind: *"Unless it's a baby underneath the corporate, it should not. That
    is a no-no. I'd like to see that."* She describes the mechanism at [45:51] —
    a conversion "usually also creates an inactive", so a sold hotel ends up
    with an RRO record AND a fresh active one.

    Two live classes land here and both need a human:
      · the RRO-conversion duplicate (two `Four Points Bellingham` records);
      · the Four Points class proper — billed $2,046 by Jen, invoiced by nobody.

    Cheap by construction: both inputs are already fetched by the billables and
    retention passes, so this costs no extra SLX call.
    """
    name_by_id = name_by_id or {}
    invoiced = set(invoiced_ids or ())
    return [
        {"account_id": aid,
         "name": name_by_id.get(aid, aid),
         "territory": territory,
         "why": "carries a dues product but has no invoice this fiscal year — "
                "an RRO-conversion duplicate, or billed outside the system"}
        for aid, territory in sorted(carriers.items())
        if aid not in invoiced
    ]
