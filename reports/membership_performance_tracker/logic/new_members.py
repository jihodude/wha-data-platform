"""
new_members.py — Compute new member counts per territory.

Feeds Scoreboard row 6: # of New Members

Definition (ratified 2026-07-14 — see docs/DECISIONS.md + the report SPEC):
    New member = an account ENROLLED within the reporting month's date window
    (EnrolledDate in [start, end) — NOT a 180-day rolling rule). Rules:
      - Reinstatements are excluded (Salescode '510' or ReinstatedDate set) —
        they count as new revenue but NOT new members.
      - Child / add-on locations COUNT (no ParentId filter — Jen counts both
        Domino's, both Puget Sound Pizzas).
      - Since-dropped members COUNT (no current Status filter — history must not
        rewrite itself: a March sale is a sale even if the member quits in June).
      - Credited to the SELLER (AccountExtension.Originator), which may differ
        from the account's own territory.

Implementation:
    compute_new_members_by_target() queries cMemberGens for the month window and
    returns {territory: {total, target, non_target, unknown}}. Target/Non-Target
    classification lives in target.py; seller credit in attribution.py.

    SUPERSEDED + REMOVED (2026-07-17): the 180-day rolling rule
    (compute_new_members), the 'Account.Status = Active' cohort filter, and the
    'ParentId eq null' child exclusion. Do not reintroduce them.
Date syntax: @YYYY-MM-DD@ (@ must be literal in URL, not encoded as %40).

Usage:
    from src.slx.client import SLXClient
    from reports.membership_performance_tracker.logic.new_members import compute_new_members_by_target

    client = SLXClient(username, password)
    result = compute_new_members_by_target(client, territory_user_map, start_date, end_date)
    # result["Pierce"] == {"total": 17, "target": 12, "non_target": 5, "unknown": 0}
"""

import time
from datetime import date, timedelta
from typing import Dict, List, Optional

from src.slx.client import SLXClient
from reports.membership_performance_tracker.logic.target import (
    NON_TARGET, TARGET, build_target_map, classify, new_member_cohort_where)
from reports.membership_performance_tracker.logic.attribution import originator_territory_map
from reports.membership_performance_tracker.logic.revenue import _accumulate_breakdown


def compute_new_members_by_target(
    client: SLXClient,
    territory_user_map: Dict[str, str],
    start_date: date,
    end_date: date,
    request_delay: float = 0.15,
) -> Dict[str, Dict]:
    """
    Count new members enrolled in a date window, split by Target / Non-Target.

    Applies the same reinstatement and add-on location exclusions as
    compute_new_members_for_period(). Adds Target/Non-Target breakdown
    using build_target_map() (3 extra queries per territory).

    Args:
        client:              Authenticated SLXClient instance.
        territory_user_map:  Dict mapping SLX user ID -> canonical territory name.
        start_date:          Start of enrollment window (inclusive).
        end_date:            End of enrollment window (inclusive).
        request_delay:       Seconds to pause between API calls.

    Returns:
        Dict keyed by canonical territory name:
        {
            "Pierce": {
                "total":       5,
                "target":      3,
                "non_target":  2,
                "unknown":     0,
            },
            ...
        }
    """
    start_str = start_date.strftime("%Y-%m-%d")
    result: Dict[str, Dict] = {}

    for user_id, territory in territory_user_map.items():
        if territory is None:
            continue

        # Fetch enrolled account IDs (not just a count — we need IDs to classify)
        where = new_member_cohort_where(user_id, start_str, end_date)
        records = client._fetch_all("cMemberGens", where=where,
                                    select="Account", page_size=200)
        time.sleep(request_delay)

        account_ids: List[str] = []
        for r in records:
            acct = r.get("Account") or {}
            aid = acct.get("$key")
            if aid:
                account_ids.append(aid)

        if not account_ids:
            _accumulate_breakdown(result, territory,
                                  {"total": 0, "target": 0, "non_target": 0, "unknown": 0})
            continue

        # ⛔ prior-payer screen REMOVED 2026-07-30 (recorded call): a >6-month
        # rejoin IS a new member ("That exact same member" — Jen), and the
        # enroll-date rewrite upstream already gates the cohort.

        # status=None (7/16): since-dropped enrollees are in the cohort now —
        # an Active-scoped map would mis-classify them to "unknown".
        target_map = build_target_map(client, user_id, status=None,
                                      request_delay=request_delay)
        # Seller-credit (7/15-16): count lands in the SELLER's column.
        orig_terr = originator_territory_map(
            client, account_ids, territory_user_map,
            fallback_territory=territory, request_delay=request_delay)
        _accumulate_breakdown(result, territory,
                              {"total": 0, "target": 0, "non_target": 0, "unknown": 0})
        for aid in account_ids:
            cls = classify(target_map, aid)
            bucket = ("target" if cls == TARGET
                      else "non_target" if cls == NON_TARGET else "unknown")
            row = {"total": 1, "target": 0, "non_target": 0, "unknown": 0}
            row[bucket] = 1
            _accumulate_breakdown(result, orig_terr.get(aid, territory), row)

    return result


def compute_new_members_for_period(
    client: SLXClient,
    territory_user_map: Dict[str, str],
    start_date: date,
    end_date: date,
    request_delay: float = 0.15,
) -> Dict[str, int]:
    """
    Count new members enrolled within a specific date range (for monthly tracking).

    Unlike the 180-day rule (which is a rolling window), this version lets you
    compute new members enrolled in a specific calendar month — useful for
    Month-by-Month sheet historical data.

    Reinstatement exclusion (per SOP):
        Reinstatements count as new revenue but NOT new members. Two conditions
        identify a reinstatement:
          - Salescode eq '510'   (dues code assigned to reinstatements)
          - ReinstatedDate is set (any non-null value)
        Both are excluded here. Note: Salescode NULL trap — using plain
        `Salescode ne '510'` would silently exclude accounts where Salescode IS NULL
        (the majority of records). Always use `(Salescode ne '510' or Salescode eq null)`.

    Add-on location exclusion (per SOP):
        When a chain adds a new child location to an existing corporate membership,
        the rep earns revenue credit but the child location does NOT count as a new
        member. (2026-07-14: child sign-ups now COUNT — Jen's report counts each; the old ParentId=null exclusion made us count 3 of Gretchen's 5.) Legacy note: child locations were
        excluded here so only new corporate-level members are counted.

        Example: Marriott (existing member) adds a new Seattle property as a child
        account → revenue credited to rep, but new_members count stays the same.

    Args:
        client:              Authenticated SLXClient instance.
        territory_user_map:  Dict mapping SLX user ID -> canonical territory name.
        start_date:          Start of enrollment window (inclusive).
        end_date:            End of enrollment window (inclusive).
        request_delay:       Seconds to pause between API calls.

    Returns:
        Dict keyed by canonical territory name -> int count of new (non-reinstated,
        non-add-on) members. Only corporate-level new accounts are counted.
    """
    start_str = start_date.strftime("%Y-%m-%d")

    result: Dict[str, int] = {}

    for user_id, territory in territory_user_map.items():
        if territory is None:
            continue

        where = new_member_cohort_where(user_id, start_str, end_date)
        # Fetch ids (not a server count) so each enrollee credits its SELLER
        # (AccountExtension.Originator — ratified 7/15-16).
        records = client._fetch_all("cMemberGens", where=where,
                                    select="Account", page_size=200)
        ids = [(r.get("Account") or {}).get("$key") for r in records]
        ids = [i for i in ids if i]
        # ⛔ prior-payer screen REMOVED 2026-07-30 — see the note above.
        orig_terr = originator_territory_map(
            client, ids, territory_user_map,
            fallback_territory=territory, request_delay=request_delay)
        result.setdefault(territory, 0)
        for aid in ids:
            t = orig_terr.get(aid, territory)
            result[t] = result.get(t, 0) + 1
        time.sleep(request_delay)

    return result
