"""C6+C11 — the lost-cohort supplemental fetch (fetch-axis defect, 2026-08-12).

Every retention fetch scopes on the CURRENT `Account.AccountManager.Id`. When
a business sells and flips to the retro program, the CRM reassigns its record
to a house user (RetroCoordinator, AlliedRelationsManager), and every invoice
on that record retroactively vanishes from its territory's history. Jen, on
tape: "there's a lot of RRO flips throughout the year, a LOT of them."
Measured 2026-08-12: 38 FY26 dues invoices / $45,882.50 (21 paid, $30,299.75)
sat on accounts outside every territory fetch — Sparta's Pizza among them,
which is why Snohomish BM12 read 21 against Jen's 22.

This module finds those invoices and resolves each account to a territory so
`_retention_counts` can take the rows as a SUPPLEMENT. It decides territory
only — the ratified cohort rules (in_cohort_as_of, R1 credit memos, A2 first
cycle) then judge each member exactly as they judge everyone else, which is
what reproduces Jen's trackers: a member sold before the cycle close leaves
both sides even when their bill was paid (Westport Winery), a member who paid
and flipped after close stays (Sparta's, Houston TX).

Resolution order (ruled by Jiho 2026-08-12 — config-driven, never guessed):
  1. Flip-link pointer walk. The retro record carries `CRetroOldLINumber`
     (its predecessor's L&I number -> `CLINum` join) and its own WRA number
     appears in the predecessor's `CRetroNewWRAID` (reverse join). Probed
     live on the Sparta's chain: both joins land on the same Closed record
     whose manager is the disabled SnohomishOpenTerritory seat. Those
     disabled seats map to canonical territories via
     `open_territory_user_to_territory` in territory_map.yaml.
  2. `AccountExtension.Originator` (the enrolling rep) via
     `seller_user_to_territory` in territory_map.yaml. Matched Jen's filing
     on every mappable case measured (Houston TX -> Marla -> Spokane/NE).
  3. Neither, or a conflict between candidates -> the row is FLAGGED with the
     member's name and dollars (`flags_out["lost_cohort_unresolved"]`) and
     enters no cell.
House users listed in `lost_cohort_house_users_flag_only` (the Allied
relations manager) are flag-only by the same ruling: the CRM holds no
territory for their members and Jen's sheets carry none of them.
"""
import re as _re
import time
import datetime as _dt
from datetime import date
from pathlib import Path
from typing import Dict, Optional, Tuple

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TERRITORY_MAP_PATH = PROJECT_ROOT / "config" / "territory_map.yaml"

# Every field the pointer walk or the downstream grouping reads. The invoice
# select mirrors what `_group_invoice_rows` and the R1 CM rule consume.
_ACCT_SELECT = ("AccountName,Aka,Status,AccountManager,CLINum,"
                "CRetroOldLINumber,CRetroNewWRAID,CRetroOldWRAID")
_INV_SELECT = ("Accountid,Account,CustomerNo,Comment,Invoice_Type,"
               "Invoice_Date,Invoice_number,Net_invoice,Balance")


def load_resolver_maps(path: Optional[Path] = None) -> Dict:
    """The three config tables the resolver stands on — all yaml, so a rep
    change or a newly noticed house user is an edit, not a deploy."""
    with open(path or TERRITORY_MAP_PATH) as fh:
        cfg = yaml.safe_load(fh)
    return {
        "seller": dict(cfg.get("seller_user_to_territory") or {}),
        "open_seats": dict(cfg.get("open_territory_user_to_territory") or {}),
        "house_flag_only": list(cfg.get("lost_cohort_house_users_flag_only")
                                or []),
    }


def _slx_day(raw) -> Optional[date]:
    # local copy of retention._slx_day — importing retention here would be a
    # circular import (retention imports this module at its call site)
    if raw is None:
        return None
    match = _re.search(r"/Date\((-?\d+)", str(raw))
    if not match:
        return None
    return _dt.datetime.fromtimestamp(
        int(match.group(1)) / 1000, tz=_dt.timezone.utc).date()


def _aid(row) -> Optional[str]:
    return row.get("Accountid") or (row.get("Account") or {}).get("$key")


def _mgr(acct) -> Optional[str]:
    am = (acct or {}).get("AccountManager") or {}
    return am.get("$key") if isinstance(am, dict) else am


def _territory_of(mgr_id, live_map, maps) -> Optional[str]:
    terr = live_map.get(mgr_id)
    if terr:
        return terr
    return maps["open_seats"].get(mgr_id)


def _pointer_candidates(client, acct, own_wras):
    """Predecessor records, by the two first-class joins probed live 8/12."""
    seen, cands = set(), []
    old_li = str(acct.get("CRetroOldLINumber") or "").strip()
    if old_li:
        for r in client._fetch_all("accounts", where=f"CLINum eq '{old_li}'",
                                   select=_ACCT_SELECT, page_size=20):
            if r.get("$key") not in seen | {acct.get("$key")}:
                seen.add(r.get("$key"))
                cands.append(r)
    for wra in sorted(own_wras):
        if not wra:
            continue
        for r in client._fetch_all("accounts",
                                   where=f"CRetroNewWRAID eq '{wra}'",
                                   select=_ACCT_SELECT, page_size=20):
            if r.get("$key") not in seen | {acct.get("$key")}:
                seen.add(r.get("$key"))
                cands.append(r)
    return cands


def _resolve_territory(client, acct, own_wras, originator_id, live_map, maps,
                       depth: int = 0) -> Tuple[Optional[str], str]:
    """-> (canonical territory | None, how). Never guesses: one answer or a
    reason string for the flag."""
    found: Dict[str, str] = {}
    for cand in _pointer_candidates(client, acct, own_wras):
        terr = _territory_of(_mgr(cand), live_map, maps)
        if terr is None and depth < 2:
            # the predecessor may itself be flipped/parked — walk once more
            terr, _ = _resolve_territory(
                client, cand, {str(cand.get("CRetroOldWRAID") or "").strip()},
                None, live_map, maps, depth + 1)
        if terr:
            found.setdefault(terr, cand.get("$key"))
    if len(found) == 1:
        return next(iter(found)), "flip-link"
    if len(found) > 1:
        return None, f"conflict: pointer walk reaches {sorted(found)}"
    if originator_id:
        terr = maps["seller"].get(originator_id)
        if terr:
            return terr, "originator"
        return None, f"originator '{originator_id}' not in seller map"
    return None, "no flip links, no originator"


def collect_lost_cohort(client, fiscal_year_start: int,
                        territory_user_map: Dict[str, Optional[str]],
                        request_delay: float = 0.05,
                        flags_out: Optional[Dict[str, list]] = None,
                        maps: Optional[Dict] = None) -> Dict[str, dict]:
    """One pass per run. Returns {territory: bundle}; a bundle carries raw
    invoice rows (IN/AD), CM rows, and the statuses/inactivation dates the
    cohort rules need — everything `_retention_counts` supplements with.
    """
    maps = maps or load_resolver_maps()
    fy_lo = f"{fiscal_year_start}-10-01"
    fy_hi = f"{fiscal_year_start + 1}-09-30"
    # CMs are issued whenever accounting gets to them (R1): reach close+6 of
    # the LAST bill month — Sep closes Oct 31, +6 months = Apr 30.
    cm_hi = f"{fiscal_year_start + 2}-04-30"

    rows = client._fetch_all(
        "dlInvoiceHistoryHeader",
        where=(f"Comp_code eq 'WRA' and (Invoice_Type eq 'IN' or "
               f"Invoice_Type eq 'AD' or Invoice_Type eq 'CM') "
               f"and Invoice_Date ge @{fy_lo}@ and Invoice_Date le @{cm_hi}@"),
        select=_INV_SELECT, page_size=200)
    # only CM keeps the extended window; IN/AD stay inside the FY
    def _in_fy(r):
        d = _slx_day(r.get("Invoice_Date"))
        return d is None or d.isoformat() <= fy_hi
    rows = [r for r in rows
            if r.get("Invoice_Type") == "CM" or _in_fy(r)]

    aids = sorted({_aid(r) for r in rows} - {None})
    acct_info: Dict[str, dict] = {}
    for i in range(0, len(aids), 40):
        ors = " or ".join(f"Id eq '{a}'" for a in aids[i:i + 40])
        for a in client._fetch_all("accounts", where=f"({ors})",
                                   select=_ACCT_SELECT, page_size=100):
            acct_info[a.get("$key")] = a
        if request_delay:
            time.sleep(request_delay)

    # a manager the map knows — including the deliberate null seats — is the
    # territory fetch's business; LOST means the map has never heard of it
    lost_ids = [aid for aid in aids
                if _mgr(acct_info.get(aid)) not in territory_user_map]
    if not lost_ids:
        return {}
    live_map = {uid: t for uid, t in territory_user_map.items() if t}
    rows_by_aid: Dict[str, list] = {}
    for r in rows:
        rows_by_aid.setdefault(_aid(r), []).append(r)

    bundles: Dict[str, dict] = {}
    for aid in lost_ids:
        acct = acct_info.get(aid) or {}
        own = rows_by_aid.get(aid, [])
        name = acct.get("AccountName") or aid
        aka = str(acct.get("Aka") or "")
        dollars = round(sum(float(r.get("Net_invoice") or 0) for r in own
                            if r.get("Invoice_Type") == "IN"), 2)
        months = sorted({str(r.get("Comment") or "").strip() for r in own
                         if str(r.get("Comment") or "").strip().isdigit()})

        def _flag(reason):
            if flags_out is not None:
                flags_out.setdefault("lost_cohort_unresolved", []).append({
                    "account": aid, "name": name, "aka": aka,
                    "bill_months": months, "dollars": dollars,
                    "reason": reason})

        if _mgr(acct) in maps["house_flag_only"]:
            _flag("house user — the CRM holds no territory for this member")
            continue

        ext_rows = client._fetch_all(
            "AccountExtension", where=f"Id eq '{aid}'",
            select="Originator,StatusDate", page_size=5)
        ext = ext_rows[0] if ext_rows else {}
        orig = ext.get("Originator")
        orig_id = orig.get("$key") if isinstance(orig, dict) else orig

        own_wras = {str(r.get("CustomerNo") or "").strip() for r in own}
        terr, how = _resolve_territory(client, acct, own_wras, orig_id,
                                       live_map, maps)
        if terr is None:
            _flag(how)
            continue

        b = bundles.setdefault(terr, {"records": [], "cm_rows": [],
                                      "statuses": {}, "inactivations": {}})
        for r in own:
            (b["cm_rows"] if r.get("Invoice_Type") == "CM"
             else b["records"]).append(r)
        b["statuses"][aid] = str(acct.get("Status") or "")
        when = _slx_day(ext.get("StatusDate"))
        if when is not None:
            b["inactivations"][aid] = when
        if request_delay:
            time.sleep(request_delay)
    return bundles
