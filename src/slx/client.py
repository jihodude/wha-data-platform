"""
client.py — SLX SData REST API client for WHA Membership Scoreboard automation.

Authentication: Basic auth over VERIFIED TLS (valid DigiCert cert since ≤2026).
Base URL: https://crm.wrahome.com/sdata/slx/dynamic/-/

Territory resolution (CONFIRMED 2026-04-30):
    Territory is NOT a direct field on accounts.
    Path: account.AccountManager.Id -> users.$descriptor -> territory name.
    Each territory is a dedicated SLX "user" account (e.g. "PierceTerritory").
    The full user_id -> territory mapping is in territory_map.yaml under slx_user_to_territory.

Pagination:
    SData returns up to `count` records per page (default 100 here).
    Auto-pagination via $next link until all records fetched.

Usage:
    from src.slx.client import SLXClient
    client = SLXClient(username=os.environ["SLX_USERNAME"],
                       password=os.environ["SLX_PASSWORD"])
    rows = client._fetch_all("cMemberGens", where="...")
"""

import json
import time
import warnings
from typing import Any, Dict, Generator, List, Optional
from urllib.parse import quote, urljoin

import requests

BASE_URL = "https://crm.wrahome.com/sdata/slx/dynamic/-/"
DEFAULT_PAGE_SIZE = 100
REQUEST_DELAY = 0.1  # seconds between paginated requests — be polite to the server
MAX_CURSOR_PAGES = 4000  # hard safety cap on cursor pages (partial-data guard, finding #12)


class SLXError(Exception):
    """Raised when the SLX API returns an error response."""
    pass


def fetch_by_id_batches(client, entity, account_ids, *, batch_size=20,
                        page_size=100, request_delay=0.0):
    """Fetch all `entity` records for a list of account ids, in Id-batches
    ('Account.Id eq X or ...') — the workaround for SData's per-territory join
    under-fetch. Consolidates a loop pasted in attribution / target-backfill /
    retention (2026-07-17). Standalone (not a method) so any object implementing
    `_fetch_all` — including test doubles — works unchanged. Returns a flat list.
    """
    out = []
    ids = list(account_ids)
    for i in range(0, len(ids), batch_size):
        chunk = ids[i:i + batch_size]
        where = " or ".join(f"Account.Id eq '{a}'" for a in chunk)
        out.extend(client._fetch_all(entity, where=f"({where})", page_size=page_size))
        if request_delay:
            time.sleep(request_delay)
    return out


class SLXClient:
    """
    Thin wrapper around the SLX SData REST API.

    All methods return plain Python dicts/lists — no SData envelope metadata.
    Pagination is handled transparently; callers always receive the full result set.
    """

    def __init__(self, username: str, password: str, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/") + "/"
        self.session = requests.Session()
        self.session.auth = (username, password)
        # 2026-07-16 security sweep: the server presents a VALID DigiCert cert
        # (exp 2027-02); verification ON. It was disabled for a self-signed cert
        # that no longer exists — and traffic now crosses the public internet,
        # so unverified TLS + Basic auth would be MITM-able.
        self.session.verify = True

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # URL builder (IMPORTANT: SData requires literal single quotes in where
    # clauses — must NOT be percent-encoded as %27. requests.get(params=...)
    # uses quote_plus which encodes them, so we build URLs manually.)
    # ------------------------------------------------------------------

    def _build_url(
        self,
        entity: str,
        where: Optional[str] = None,
        select: Optional[str] = None,
        order_by: Optional[str] = None,
        count: Optional[int] = None,
        start_index: Optional[int] = None,
    ) -> str:
        """
        Build a fully-formed SData query URL.

        Single quotes in `where` are kept as literal characters (safe="'") so
        that SData can parse string literals correctly.
        """
        base = urljoin(self.base_url, entity)
        parts = ["format=json"]
        if count is not None:
            parts.append(f"count={count}")
        if where:
            # keep single quotes and @ literal (SData date filter syntax requires
            # both). Space is in the safe set, so it is NOT encoded here —
            # requests requotes it to %20 on send (#26: old comment claimed the
            # opposite).
            encoded_where = quote(where, safe="'@(),. /")
            parts.append(f"where={encoded_where}")
        if select:
            parts.append(f"select={quote(select, safe=',')}")
        if order_by:
            parts.append(f"orderby={order_by}")
        if start_index is not None:
            parts.append(f"startIndex={start_index}")
        return f"{base}?{'&'.join(parts)}"

    def _get(self, entity: str, extra_params: str = "") -> Dict:
        """
        GET /{entity}?format=json[&extra_params].
        Returns the parsed JSON response dict.
        Raises SLXError on API-level errors.
        """
        url = urljoin(self.base_url, entity)
        full_url = f"{url}?format=json"
        if extra_params:
            full_url += f"&{extra_params}"

        resp = self.session.get(full_url, timeout=90)
        resp.raise_for_status()
        data = resp.json()

        # SData signals errors as a list containing a severity+message dict
        if isinstance(data, list) and data and data[0].get("severity") == "Error":
            raise SLXError(f"SLX API error on {full_url}: {data[0].get('message')}")

        return data

    def _get_bytes(self, path: str) -> bytes:
        """GET /{path} as BINARY — attachment file streams.

        Added 2026-07-26 for CRM-report ingestion: every Crystal report run in
        the CRM is archived as an SLX attachment, and its bytes come from
        `attachments('<key>')/file`, which is not JSON (so `_get` cannot read
        it). No `format=json` is appended — some SData handlers corrupt binary
        streams when it is present. SLX sometimes answers a failed file read
        with a JSON error envelope under HTTP 200; that is raised, never
        returned as if it were a file.
        """
        url = urljoin(self.base_url, path)
        resp = self.session.get(url, timeout=180)
        resp.raise_for_status()
        data = resp.content
        if "json" in (resp.headers.get("content-type") or "").lower():
            try:
                parsed = json.loads(data)
            except ValueError:
                parsed = None
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict) \
                    and parsed[0].get("severity") == "Error":
                raise SLXError(f"SLX error fetching {path}: "
                               f"{parsed[0].get('message')}")
        return data

    def _get_record(self, entity: str, record_id: str) -> Dict:
        """GET /{entity}('{record_id}') — fetch a single record by ID."""
        path = f"{entity}('{record_id}')"
        return self._get(path)

    def _fetch_all(
        self,
        entity: str,
        where: Optional[str] = None,
        select: Optional[str] = None,
        order_by: Optional[str] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> List[Dict]:
        """
        Fetch all records from an entity, handling pagination automatically.

        Args:
            entity:    SData entity name (e.g. 'accounts', 'cMemberGens').
            where:     SData filter expression (e.g. "Status eq 'Active'").
            select:    Comma-separated field names to include in response.
            order_by:  Field name to sort by.
            page_size: Records per page (max ~200 for SLX; default 100).

        Returns:
            List of resource dicts (SData envelope stripped).

        Resilience:
            SLX has a known server-side bug where pagination past ~2800 records
            on some queries returns HTTP 500. We retry each page up to 3 times
            with exponential backoff. If a page still fails, we emit a warning
            and return whatever records we collected up to that point — partial
            data is better than total failure for a 25-min run.
        """
        # ── ID-CURSOR PAGINATION (2026-07-14, THE root-cause fix) ───────────
        # SData's $next paging returns a DIFFERENT random subset per pass on
        # large result sets (proven live: the same EastKing query gave 400 vs
        # 529 rows minutes apart, each missing different accounts; even
        # $totalResults tracked the broken plan). Fresh FIRST-PAGE queries are
        # reliable (Id-batches and count probes always were), so paginate by
        # cursor instead: order by Id, then re-issue `(<where>) and Id gt
        # '<last>'` per page. Validated: 529/529 accounts incl. all 249/249
        # ground-truth restaurants; works on custom tables. The old
        # $next-walk remains only as a fallback for entities that reject
        # Id ordering.
        base_where = f"({where})" if where else None
        effective_order = order_by or "Id"
        all_records: List[Dict] = []
        seen_keys: set = set()
        last_key = ""
        max_pages = MAX_CURSOR_PAGES  # hard safety cap

        for _ in range(max_pages):
            if last_key:
                w = f"{base_where} and Id gt '{last_key}'" if base_where else f"Id gt '{last_key}'"
            else:
                w = where
            url = self._build_url(entity, where=w, select=select,
                                  order_by=effective_order, count=page_size)
            page_data = self._fetch_page_with_retry(url, entity)
            if page_data is None:
                if not all_records:
                    # first cursor query failed outright — entity may reject
                    # Id ordering; fall back to the legacy $next walk.
                    return self._fetch_all_legacy(entity, where, select,
                                                  order_by, page_size)
                print(f"  [SLX] WARNING: '{entity}' cursor page failed at "
                      f"~{len(all_records)} records — retrying smaller page",
                      flush=True)
                if page_size > 10:
                    page_size = max(10, page_size // 5)
                    continue
                # GOLD-PLATE (2026-07-17): retries exhausted with only a PARTIAL
                # result. Returning it silently undercounts EVERY metric built on
                # this entity (billables, retention, drops, members, revenue). Fail
                # LOUD — a wrong number must never ship. Rerun the pull.
                raise SLXError(
                    f"[SLX] '{entity}' pagination FAILED after retries at "
                    f"~{len(all_records)} records — refusing to return partial data "
                    f"(would silently undercount). Rerun the pull."
                )
            resources = page_data.get("$resources", [])
            if not resources:
                break
            page_max = last_key
            for r in resources:
                k = r.get("$key") or r.get("Id")
                if k is None:
                    all_records.append(r)
                    continue
                if k not in seen_keys:
                    seen_keys.add(k)
                    all_records.append(r)
                if str(k) > str(page_max):
                    page_max = str(k)
            if page_max == last_key:
                break  # no forward progress — done
            last_key = page_max
            if len(resources) < page_size:
                break  # short page = final page
            time.sleep(REQUEST_DELAY)
        else:
            # GOLD-PLATE (finding #12): the loop ran all max_pages iterations
            # WITHOUT a natural break (short/empty/no-progress page) → there is
            # very likely MORE data we never fetched. Partial. Fail LOUD.
            raise SLXError(
                f"[SLX] '{entity}' hit the {max_pages}-page safety cap without "
                f"reaching the last page (~{len(all_records)} records) — refusing "
                f"to return partial data. Rerun / raise MAX_CURSOR_PAGES."
            )

        return all_records

    def _fetch_all_legacy(
        self,
        entity: str,
        where: Optional[str],
        select: Optional[str],
        order_by: Optional[str],
        page_size: int,
    ) -> List[Dict]:
        """Legacy $next-walk pagination — UNRELIABLE on large sets (random row
        drops per pass); used only when an entity rejects Id-cursor ordering."""
        print(f"  [SLX] NOTE: '{entity}' using legacy $next pagination "
              f"(cursor unsupported) — treat large results as approximate",
              flush=True)
        url = self._build_url(entity, where=where, select=select,
                              order_by=order_by, count=page_size)
        all_records: List[Dict] = []
        while url:
            page_data = self._fetch_page_with_retry(url, entity)
            if page_data is None:
                # GOLD-PLATE (finding #12): the cursor path raises on a mid-walk
                # page failure; this fallback used to `break` and return whatever
                # it had — the same silent-undercount failure mode, one path over.
                raise SLXError(
                    f"[SLX] '{entity}' legacy $next pagination FAILED at "
                    f"~{len(all_records)} records — refusing to return partial "
                    f"data (would silently undercount). Rerun the pull."
                )
            all_records.extend(page_data.get("$resources", []))
            url = page_data.get("$next")
            if url:
                time.sleep(REQUEST_DELAY)
        return all_records

    def _fetch_page_with_retry(
        self,
        url: str,
        entity: str,
        max_retries: int = 3,
    ) -> Optional[Dict]:
        """
        Fetch a single page with retry on transient server errors (500/502/503).

        Returns the parsed JSON dict, or None if all retries exhausted.
        Non-server errors (auth, malformed URL, etc.) still raise immediately.
        """
        import requests as _requests

        for attempt in range(max_retries):
            try:
                resp = self.session.get(url, timeout=60)
                if resp.status_code >= 500:
                    # Server error — retry with exponential backoff
                    if attempt < max_retries - 1:
                        backoff = 2 ** attempt  # 1s, 2s, 4s
                        time.sleep(backoff)
                        continue
                    # Last attempt failed — give up
                    return None
                resp.raise_for_status()
                data = resp.json()

                if isinstance(data, list) and data and data[0].get("severity") == "Error":
                    raise SLXError(f"SLX API error: {data[0].get('message')}")
                return data
            except _requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
            except _requests.exceptions.ConnectionError:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
        return None

    def _count(self, entity: str, where: Optional[str] = None) -> int:
        """
        Return the total record count for an entity + optional filter.
        Uses count=1 to minimize data transfer — only reads $totalResults.
        """
        url = self._build_url(entity, where=where, count=1)
        resp = self.session.get(url, timeout=90)
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, list) and data and data[0].get("severity") == "Error":
            raise SLXError(f"SLX API error: {data[0].get('message')}")

        return data.get("$totalResults", 0)

    # ------------------------------------------------------------------
    # Territory helpers
    # ------------------------------------------------------------------

    def get_territory_users(self) -> Dict[str, str]:
        """
        Return mapping of SLX user ID -> canonical territory name for all
        active territory users.

        These are dedicated SLX "user" accounts that act as territory assignments
        (not real people). Territory on an account = account.AccountManager.Id.

        Returns:
            Dict like {"U6UJ9A00009Z": "Pierce", "U6UJ9A0000A1": "Southwest", ...}
            Users with null territory (GeneralOpenTerritory) are excluded.
        """
        # NOTE: select parameter causes 500 on users entity — fetch all fields
        records = self._fetch_all(
            entity="users",
            where="UserName like '%Territory%'",
        )

        mapping = {}
        for rec in records:
            if not rec.get("Enabled"):
                continue  # skip disabled "Open" territory placeholders
            descriptor = rec.get("$descriptor", "")
            # Format is "Territory, TerritoryName" or "Territory, GeneralOpen"
            if "," in descriptor:
                territory_label = descriptor.split(",", 1)[1].strip()
                user_id = rec.get("$key")
                if user_id and territory_label not in ("GeneralOpen",):
                    mapping[user_id] = territory_label
        return mapping

    def get_bob_new_accounts(
        self,
        account_manager_id: str,
        start_date: str,
        end_date: str,
    ) -> List[Dict]:
        """
        Fetch Black-Owned Business (BOB) accounts that enrolled in the given month
        window — for the monthly "flag for manual revenue credit" alert.

        BOB = a diverse-owned business given a COMPED membership (the "diverse dues"
        / DIV discount: $0 collected, shows as negative invoice lines), yet the rep
        still earns REVENUE + new-member credit toward goal. Admin hands "all the Bobs
        for the month" to AR so the credit is applied — surfacing them here ensures
        they are not silently overlooked. (Primary source: the Dues/MPR training PDF;
        see docs/REFERENCE.md.) DISTINCT from the "BOB 2-Year" / "Best of Both" billing
        promo in revenue.py (BOB_PROMO_PO_LABEL). ⚠️ 2026-07-31: live evidence
        says these are the SAME program tracked two ways, not unrelated — four
        Snohomish Oct enrollees carry BOTH the 'BOB Two Year Membership' PO
        lines AND CDiverseOwnership=True with matching enroll dates.

        Args:
            account_manager_id: SLX user ID for the territory.
            start_date: ISO date string, start of the enrollment window ("2026-03-01").
            end_date:   ISO date string, INCLUSIVE last day of the window ("2026-03-31").

        Returns:
            List of account dicts: {account_id, account_name, ownership_type, enroll_date}.

        CDiverseOwnership (the diverse-ownership flag) and CDiverseEnrollDate (the
        diverse-enrollment date) are confirmed SData fields (docs/REFERENCE.md +
        archived HANDOFF). The 'accounts' entity is queried directly — ownership lives
        on the account, not the member gen.

        NOTE (2026-07-17, finding #4): the window scoping below was ADDED — the query
        previously ignored its dates and returned every diverse-owned account every
        month. Confirm CDiverseEnrollDate is populated on the next LIVE pull (a null
        date would under-report BOBs vs the old catch-all).
        """
        # Exclusive next-day end — last-day-of-month enrollees are stored at midnight,
        # so `le @end@` would drop them (same rule as the new-member cohort queries).
        from datetime import datetime, timedelta
        end_next = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        where = (
            f"AccountManager.Id eq '{account_manager_id}' "
            f"and Status eq 'Active' "
            f"and Type ne 'Allied' "
            f"and ParentId eq null "
            f"and CDiverseOwnership ne null "
            f"and CDiverseEnrollDate ge @{start_date}@ "
            f"and CDiverseEnrollDate lt @{end_next}@"
        )
        try:
            records = self._fetch_all(
                "accounts",
                where=where,
                select="AccountName,CDiverseOwnership,CDiverseEnrollDate",
            )
            return [
                {
                    "account_id":   r.get("$key"),
                    "account_name": r.get("AccountName"),
                    "ownership_type": r.get("CDiverseOwnership"),
                    "enroll_date":  r.get("CDiverseEnrollDate"),
                }
                for r in records
            ]
        except SLXError as exc:
            # GOLD-PLATE (2026-07-17): BOB accounts count toward rep new-member
            # goals — a silent [] undercounts them (and would swallow the
            # partial-data SLXError from _fetch_all). Fail LOUD.
            raise SLXError(
                f"[BOB] query FAILED for {account_manager_id}: {exc} — refusing to "
                f"return [] (would silently undercount BOB new-members). Rerun the pull."
            ) from exc

    def get_active_account_ids_for_territory(self, account_manager_id: str) -> List[str]:
        """
        Return all active account IDs (parents only) for a territory.
        Used as a pre-step before querying cMemberGens when joins fail.

        Args:
            account_manager_id: SLX user ID for the territory.

        Returns:
            List of account ID strings.
        """
        where = (
            f"Status eq 'Active' "
            f"and AccountManager.Id eq '{account_manager_id}' "
            f"and ParentId eq null"
        )
        records = self._fetch_all("accounts", where=where, select="Id")
        return [r.get("$key") for r in records if r.get("$key")]

    # ------------------------------------------------------------------
    # cMemberGens — general member data
    # ------------------------------------------------------------------

    def get_member_gen(self, account_id: str) -> Optional[Dict]:
        """
        Fetch the cMemberGens record for a specific account ID.

        Returns the record dict or None if not found.
        """
        where = f"Account.Id eq '{account_id}'"
        records = self._fetch_all("cMemberGens", where=where)
        return records[0] if records else None

    def get_member_gens_for_territory(self, account_manager_id: str) -> List[Dict]:
        """
        Fetch all cMemberGens records for accounts in a territory.
        Attempts cross-entity join; falls back to warning if not supported.

        Args:
            account_manager_id: SLX user ID for the territory.

        Returns:
            List of cMemberGens record dicts.
        """
        where = f"Account.AccountManager.Id eq '{account_manager_id}' and Account.Status eq 'Active'"
        try:
            return self._fetch_all("cMemberGens", where=where,
                                   select="EnrolledDate,ReinstatedDate,Duesbillmonth,Salescode,Rooms,Account")
        except SLXError as exc:
            warnings.warn(f"[get_member_gens_for_territory] Cross-entity join failed: {exc}")
            return []

    # ------------------------------------------------------------------
    # Raw entity access (for exploration / debugging)
    # ------------------------------------------------------------------

    def get_account(self, account_id: str) -> Dict:
        """Fetch a single account record by ID."""
        return self._get_record("accounts", account_id)

    def get_user(self, user_id: str) -> Dict:
        """Fetch a single user record by ID."""
        return self._get_record("users", user_id)

    def count_entity(self, entity: str, where: Optional[str] = None) -> int:
        """Generic count helper. Used for quick spot-checks."""
        return self._count(entity, where=where)
