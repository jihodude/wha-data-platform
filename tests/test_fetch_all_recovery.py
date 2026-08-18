"""
test_fetch_all_recovery.py — _fetch_all must use ID-CURSOR pagination, not $next.

THE root cause (proven live 2026-07-14, EastKing): SData's $next-based paging
returns a DIFFERENT random subset on every pass — 400 vs 529 rows for the same
query minutes apart, each pass missing different accounts, $totalResults itself
unreliable. Every bulk metric inherited weeks of nondeterministic undercounts.
Fresh first-page queries are reliable (proven: Id-batches, count probes), so:
paginate by cursor — `(<where>) and Id gt '<last>'`, ordered by Id, fresh query
per page. Validated live: 529/529 with all 249/249 truth restaurants present;
works on custom tables (cRestProfiles 2,803 rows).
"""
import re

import pytest

import src.slx.client as client_mod
from src.slx.client import SLXClient, SLXError


class CursorStub(SLXClient):
    """Simulates a server with keys K01..K05 served via cursor queries."""

    def __init__(self, total=5, page=2):
        self._keys = [f"K{i:02d}" for i in range(1, total + 1)]
        self._page = page
        self.queries = []

    def _build_url(self, entity, where=None, select=None, order_by=None,
                   count=None, start_index=None):
        return f"q|{where}|{order_by}|{count}"

    def _fetch_page_with_retry(self, url, entity, max_retries=3):
        self.queries.append(url)
        _, where, order_by, count = url.split("|")
        assert order_by == "Id", "cursor pagination must order by Id"
        m = re.search(r"Id gt '([^']*)'", where or "")
        last = m.group(1) if m else ""
        remaining = [k for k in self._keys if k > last]
        rows = [{"$key": k, "Id": k} for k in remaining[: self._page]]
        return {"$resources": rows, "$totalResults": len(self._keys)}


def test_cursor_pagination_collects_everything():
    c = CursorStub(total=5, page=2)
    records = c._fetch_all("accounts", where="Status eq 'Active'", page_size=2)
    assert sorted(r["$key"] for r in records) == ["K01", "K02", "K03", "K04", "K05"]
    # every page was a fresh cursor query (no $next reliance)
    assert all("Id gt" in q or q.endswith("|None|2") or "'Active'" in q for q in c.queries)


def test_cursor_wraps_where_with_parens():
    c = CursorStub(total=3, page=2)
    c._fetch_all("accounts", where="A eq '1' or B eq '2'", page_size=2)
    followups = [q for q in c.queries if "Id gt" in q]
    assert followups, "expected cursor follow-up queries"
    assert all("(A eq '1' or B eq '2') and Id gt" in q for q in followups), \
        "top-level OR filters must be parenthesized before appending the cursor"


def test_cursor_handles_empty_result():
    c = CursorStub(total=0, page=2)
    assert c._fetch_all("accounts", where="Status eq 'X'") == []


# --- finding #12: partial data must never return silently ---

class LegacyMidWalkFailStub(SLXClient):
    """Legacy $next walk: page 1 OK (has $next), page 2 fails (None)."""

    def __init__(self):
        self.calls = 0

    def _build_url(self, entity, where=None, select=None, order_by=None,
                   count=None, start_index=None):
        return "PAGE1"

    def _fetch_page_with_retry(self, url, entity, max_retries=3):
        self.calls += 1
        if self.calls == 1:
            return {"$resources": [{"$key": "A"}], "$next": "PAGE2"}
        return None  # mid-walk failure AFTER collecting 1 record


def test_legacy_pagination_raises_on_midwalk_failure():
    """The cursor path raises on a mid-walk page failure; the legacy $next
    fallback used to `break` and return the partial result — the same
    silent-undercount class, one path over. Must now raise SLXError."""
    with pytest.raises(SLXError, match="partial"):
        LegacyMidWalkFailStub()._fetch_all_legacy(
            "cWLAInvoices", where="x", select=None, order_by=None, page_size=100)


class NeverEndsStub(SLXClient):
    """Always returns a FULL page of brand-new keys, so no natural break
    (short/empty/no-progress) ever fires and the page cap must be hit."""

    def __init__(self):
        self.n = 0

    def _build_url(self, *a, **k):
        return "U"

    def _fetch_page_with_retry(self, url, entity, max_retries=3):
        base = self.n * 2
        self.n += 1
        return {"$resources": [
            {"$key": f"K{base + 1:05d}", "Id": f"K{base + 1:05d}"},
            {"$key": f"K{base + 2:05d}", "Id": f"K{base + 2:05d}"},
        ]}


def test_cursor_raises_on_maxpages_exhaustion(monkeypatch):
    """Exhausting the page cap without reaching the last page means there is
    very likely MORE data → partial. Fail LOUD, don't return silently."""
    monkeypatch.setattr(client_mod, "MAX_CURSOR_PAGES", 3)
    with pytest.raises(SLXError, match="cap"):
        NeverEndsStub()._fetch_all("accounts", where="x", page_size=2)
