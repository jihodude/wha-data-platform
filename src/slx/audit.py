"""
audit.py — SLX Database Change audit log queries.

When any field on any record is changed in SLX, a `history` row is
auto-created with:
  - Category   = 'Database Change'
  - Type       = 'atDatabaseChange'
  - Result     = 'Update' (or 'Insert' / 'Delete')
  - Description= 'Change to <FieldName>'  (one or more, comma-separated)
  - Notes      = '<FieldName>: <new value>\\r\\n  Old Value: <old value>'

This module exposes that audit log as a clean Python API.

Verified live (2026-05-01):
  • 191,875 'Database Change' records in the live history (going back to ~2008)
  •  13,843 of those are bill-month changes ('Description like %duesbill%')

Use cases:
  - bill_month_changes(client, since, until)  → who moved bill month, when
  - status_flips_within(client, days=7)       → late-pay candidates
  - field_changes(client, "CBillingAccount")  → consolidation activity timeline
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Iterable

from src.slx.client import SLXClient


# Notes follow this pattern (single-field changes):
#   "Duesbillmonth: 9\r\n  Old Value: 8"
# For multi-field changes the lines repeat.  Capture each "Field: new\r\n  Old Value: old".
_FIELD_BLOCK_RE = re.compile(
    r"(?P<field>\w+):\s*(?P<new>.*?)(?:\r\n|\n)\s*Old Value:\s*(?P<old>.*?)(?=(?:\r\n|\n)\w+:|$)",
    re.DOTALL,
)


@dataclass
class FieldChange:
    """A single field-level change captured by the SLX audit trail."""
    account_id:   str
    account_name: Optional[str]
    field:        str
    old_value:    Optional[str]
    new_value:    Optional[str]
    when:         Optional[datetime]
    by_user_id:   Optional[str]


# ---------------------------------------------------------------------------
# Generic field-change query
# ---------------------------------------------------------------------------

def field_changes(
    client:     SLXClient,
    field_name: str,
    since:      Optional[date] = None,
    until:      Optional[date] = None,
    page_size:  int = 200,
    where_extra: Optional[str] = None,
) -> List[FieldChange]:
    """
    Pull every 'Database Change' history entry that mentions `field_name`.

    Args:
        field_name:  SLX column name (e.g. 'Duesbillmonth', 'CBillingAccount',
                     'Status').  Matched as a substring of the Description
                     so all surface-level capitalisations work.
        since/until: Inclusive CreateDate window. Either may be None.
        where_extra: Additional WHERE clause AND-ed on (e.g. a territory filter
                     via "Account.AccountManager.Id eq 'U6UJ9A00009Z'").

    Returns:
        List[FieldChange], one per logged change.
    """
    where_parts = ["Category eq 'Database Change'",
                   f"Description like '%{field_name}%'"]
    if since:
        where_parts.append(f"CreateDate ge @{since.strftime('%Y-%m-%d')}@")
    if until:
        where_parts.append(f"CreateDate le @{until.strftime('%Y-%m-%d')}@")
    if where_extra:
        where_parts.append(f"({where_extra})")
    where = " and ".join(where_parts)

    raw = client._fetch_all(
        "history",
        where=where,
        select="AccountId,AccountName,CreateDate,CreateUser,Description,Notes",
        page_size=page_size,
    )

    changes: List[FieldChange] = []
    for r in raw:
        notes = r.get("Notes") or ""
        for m in _FIELD_BLOCK_RE.finditer(notes):
            f = m.group("field")
            if field_name.lower() not in f.lower():
                continue   # multi-field record; skip blocks for other fields
            changes.append(FieldChange(
                account_id   = r.get("AccountId") or "",
                account_name = r.get("AccountName"),
                field        = f,
                old_value    = (m.group("old") or "").strip() or None,
                new_value    = (m.group("new") or "").strip() or None,
                when         = _parse_slx_date(r.get("CreateDate")),
                by_user_id   = (r.get("CreateUser") or "").strip() or None,
            ))
    return changes


# ---------------------------------------------------------------------------
# Pre-baked queries for the three edge cases
# ---------------------------------------------------------------------------

def bill_month_changes(
    client: SLXClient,
    since:  Optional[date] = None,
    until:  Optional[date] = None,
) -> List[FieldChange]:
    """All Duesbillmonth changes in window. Replaces Cheryl's manual group export."""
    return field_changes(client, "Duesbillmonth", since=since, until=until)


def billing_account_changes(
    client: SLXClient,
    since:  Optional[date] = None,
    until:  Optional[date] = None,
) -> List[FieldChange]:
    """All CBillingAccount changes (consolidation activity)."""
    return field_changes(client, "CBillingAccount", since=since, until=until)


def status_changes(
    client: SLXClient,
    since:  Optional[date] = None,
    until:  Optional[date] = None,
) -> List[FieldChange]:
    """All account Status changes (late-pay flips, ITD events, reinstatements)."""
    return field_changes(client, "Status", since=since, until=until)


def status_flips_within(
    client: SLXClient,
    since:  Optional[date],
    until:  Optional[date],
    max_days_between: int = 7,
) -> List[Dict]:
    """
    Detect Active → Inactive → Active sequences within `max_days_between` days
    on the same account.  These are likely late-payment grace cases that staff
    "count as retained" even though the system briefly flipped them.

    Returns:
        [{account_id, account_name, inactive_at, reactive_at, gap_days,
          old, new}, ...]
    """
    raw = status_changes(client, since=since, until=until)
    by_account: Dict[str, List[FieldChange]] = {}
    for c in raw:
        by_account.setdefault(c.account_id, []).append(c)

    results: List[Dict] = []
    for aid, changes in by_account.items():
        changes.sort(key=lambda c: c.when or datetime.min)
        # walk consecutive pairs looking for Active→non-Active→Active
        for i in range(len(changes) - 1):
            a, b = changes[i], changes[i + 1]
            went_inactive = (a.new_value or "").lower() != "active" and (a.old_value or "").lower() == "active"
            came_back     = (b.new_value or "").lower() == "active" and (b.old_value or "").lower() != "active"
            if went_inactive and came_back and a.when and b.when:
                gap_days = (b.when - a.when).days
                if gap_days <= max_days_between:
                    results.append({
                        "account_id":   aid,
                        "account_name": a.account_name,
                        "inactive_at":  a.when.isoformat(),
                        "reactive_at":  b.when.isoformat(),
                        "gap_days":     gap_days,
                        "went_to":      a.new_value,
                        "came_back":    b.new_value,
                    })
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_slx_date(s: Optional[str]) -> Optional[datetime]:
    """SLX returns dates as '/Date(<unix-ms>[+-tz])/'. Convert to UTC datetime."""
    if not s:
        return None
    m = re.search(r"/Date\((\-?\d+)", s)
    if not m:
        return None
    try:
        ts_ms = int(m.group(1))
        return datetime.utcfromtimestamp(ts_ms / 1000)
    except (ValueError, OverflowError):
        return None


def group_by_account(changes: Iterable[FieldChange]) -> Dict[str, List[FieldChange]]:
    """Bucket a list of changes by account_id, sorted by `when` ascending."""
    out: Dict[str, List[FieldChange]] = {}
    for c in changes:
        out.setdefault(c.account_id, []).append(c)
    for v in out.values():
        v.sort(key=lambda c: c.when or datetime.min)
    return out


def changes_to_dict(changes: Iterable[FieldChange]) -> List[Dict]:
    """Serialize a list of FieldChange to JSON-friendly dicts."""
    out: List[Dict] = []
    for c in changes:
        out.append({
            "account_id":   c.account_id,
            "account_name": c.account_name,
            "field":        c.field,
            "old_value":    c.old_value,
            "new_value":    c.new_value,
            "when":         c.when.isoformat() if c.when else None,
            "by_user_id":   c.by_user_id,
        })
    return out
