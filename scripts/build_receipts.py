#!/usr/bin/env python3
"""build_receipts.py — post-landing: raw capture → receipts → sheet → SharePoint.

    MPR_PERIOD=2026-07 PYTHONPATH=$PWD python3 scripts/build_receipts.py

Refuses to publish when any conservation gate fails (Σ member rows must equal
every published cell — the accurate-window guarantee). Pushes both artifacts
to the report's SP Data folder, sibling of Output (location ruled 2026-08-03;
the 7/31 hub-root "Data - MPR" folder was wrong and was deleted). Needs SLX for names and
retention bands; run only when no pull is in flight.
"""
import datetime as _dt
import json
import os
import re as _re2
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from reports.membership_performance_tracker.logic import receipts_capture as rc
from reports.membership_performance_tracker.logic import receipts_render as rr
from reports.membership_performance_tracker.logic import receipts_sheet as rs
from reports.membership_performance_tracker.logic import drops_hygiene
from reports.membership_performance_tracker.logic.cache import load_scoreboard
from reports.membership_performance_tracker.logic.target import build_target_map
from src.slx.client import SLXClient



_MON = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May",
        "Jun", "Jul", "Aug", "Sep"]


def harvest_sealed_carry(closes_dir, receipts_dir, period):
    """(sealed_months, {(family, month): rows}, fresh_families) for the carry.

    SEALED MONTHS CARRY FORWARD (8/10): a sealed month's receipts are part of
    its locked record, carried VERBATIM from the sealed edition; only open
    months render fresh.

    S5 (overnight review 8/10): each close harvests ITS OWN month only. The
    original tested rows against the ACCUMULATING month set, so once two
    months were sealed, July's rows carried from BOTH editions and every
    July cell doubled — hard-stopping the first September build. Extracted
    from main() on 8/12 precisely so that failure mode has a test.

    Amendment handling (same 8/10 fix): when rebuilding the sealed edition
    itself, families amended AFTER the record's last render must render
    fresh — the gates force them to reproduce the AMENDED sealed grids.
    """
    import datetime as _dt
    import re as _re
    sealed_months = set()
    rows_by_family_month = {}
    fresh_families = set()
    for _c in sorted(Path(closes_dir).glob("close_*.json")):
        _per = _re.search(r"close_(\d{4}-\d{2})", _c.name).group(1)
        try:
            _doc = json.loads(_c.read_text())
        except (ValueError, OSError):
            continue          # unreadable close file — never a code error
        if not _doc.get("sealed"):
            continue
        _skip_fams = set()
        _rec_path = Path(receipts_dir) / f"receipts_{_per}.json"
        if _per == period:
            _rec_mtime = (_dt.datetime.fromtimestamp(_rec_path.stat().st_mtime)
                          if _rec_path.exists() else _dt.datetime.min)
            for _a in (_doc.get("amendments") or []):
                try:
                    _at = _dt.datetime.fromisoformat(str(_a.get("at")))
                    if _at.tzinfo is not None:
                        _at = _at.astimezone().replace(tzinfo=None)
                except Exception:
                    continue
                if _at <= _rec_mtime:
                    continue          # already reflected in the record
                for _f in (_a.get("fields") or {}):
                    if str(_f).startswith("drops"):
                        _skip_fams.add("Drops")
                    elif str(_f).startswith(("ret_", "rev_", "retention")):
                        _skip_fams.add("Retention")
                    elif "revenue" in str(_f) or "count" in str(_f):
                        _skip_fams.add("New Members / New Sales")
            fresh_families |= _skip_fams
        _y, _m = int(_per[:4]), int(_per[5:7])
        _own_month = _MON[(_m - 10) % 12]
        sealed_months |= {_own_month}
        if _rec_path.exists():
            for _r in json.loads(_rec_path.read_text())["rows"]:
                if _r["metric"] in _skip_fams:
                    continue
                # S5: harvest THIS close's own month only — never the
                # accumulating set (that is the doubling bug).
                if _r["metric"] in ("Retention", "New Members / New Sales",
                                    "Drops") and _r.get("month") == _own_month:
                    rows_by_family_month.setdefault(
                        (_r["metric"], _r["month"]), []).append(_r)
    return sealed_months, rows_by_family_month, fresh_families


# WHY THE WHOLE FAMILY STILL CARRIES (tried and reverted, 8/13):
# a sealed month freezes retention, drops AND BOB revenue — but BOB revenue
# lives inside the new-sales family, so rendering that family fresh for a
# sealed month makes its BOB cells disagree with the frozen face and the
# conservation gate correctly refuses to publish (SouthKing Jul: 1,070 vs a
# sealed 0). The freeze is per FIELD; the carry is per FAMILY. Making them
# agree means either freezing new-sales counts/revenue too (a closed month
# then never picks up a late-settling sale — Tommy's Car Wash, paid 7/15
# after July's build) or splitting the carry field-by-field. Both change
# published numbers, so both are Jiho's call — see docs/handoff/
# 2026-08-13-STAGED.md section F. Until then the carry stays whole and one
# cell in the grid (Spokane/NE Jul new sales) simply does not reconcile;
# with the alarm gone it says nothing rather than crying wolf.


def merge_sealed(rows, family, sealed_months, rows_by_family_month,
                 fresh_families):
    """Fresh rows for open months + carried rows for sealed months."""
    if family in fresh_families:
        return rows          # amended family: fresh render IS the record
    if not sealed_months:
        return rows
    fresh = [r for r in rows if r.get("month") not in sealed_months]
    kept = []
    for m in sealed_months:
        kept.extend(rows_by_family_month.get((family, m), []))

    # NOBODY FALLS OFF THE TABLE (8/13). A fresh row can file INTO a closed
    # month — a drop with no end date lands at its class close, a CRM edit or
    # one of our own fixes moves it — and the closed edition, photographed
    # earlier, has never heard of it. It used to be dropped on both sides at
    # once: gone from the open month it left, absent from the closed month it
    # arrived in, counted nowhere. Two real drops (Bob's Burgers & Brew
    # corporate $2,775, Marina Square $510) went missing exactly this way, and
    # nothing said so — the cell gate compares sums, and zero matched zero.
    #
    # Keep them, marked as not counted, filed under the month they arrived in.
    # They cost nothing (excluded rows never enter a total, so no published
    # number and no gate can move) and they turn a silent loss into a line in
    # "considered but excluded" that says what to do about it.
    def _who(r):
        return (str(r.get("member_id") or ""), r.get("member"), r.get("territory"))

    known = {_who(r) for r in kept}
    stranded = []
    for r in rows:
        if r.get("month") in sealed_months and _who(r) not in known:
            s = dict(r)
            s["counted"] = False
            # A STRANDED ROW CARRIES NO MONEY (2026-08-20) — the same
            # convention retention applies to its exclusions ("an excluded
            # member carries no money", 2026-08-15). The dollars gates now sum
            # amounts over EVERY row, counted or not, because refunds are
            # uncounted rows with real (negative) money — so a row meant to
            # move no total must say so on the row itself, not rely on the
            # gate skipping it. The original figure stays visible in the text.
            _orig = s.get("amount")
            if _orig:
                s["qualifies"] = (f"{s.get('qualifies') or ''} "
                                  f"(${_orig:,.2f})").strip()
            s["amount"] = 0.0
            if "bob" in s:
                s["bob"] = 0.0
            if "ask" in s:
                s["ask"] = 0.0
            if "retained" in s:
                s["retained"] = 0.0
            s["qualifies"] = (
                f"{s.get('qualifies') or ''} — belongs in {r.get('month')}, which is "
                f"closed, so it is not in that month's locked numbers. Editing the "
                f"closed month is what makes it count.").lstrip(" —")
            stranded.append(s)
    return fresh + kept + stranded


def filed_overrides_from_flags(flags: dict) -> dict:
    """{mid: (month, note)} — where the PUBLISHED run filed each drop.

    Two classes never file at their own date, and both are recorded by the
    feed as it decides them:
      · drop_date_fallback — no usable end date, filed at the class close;
      · hygiene_counted    — billing stale, counted at the status-flip date.

    The renderer would otherwise re-derive the month and can land elsewhere,
    which is C10: the receipts filed the estimated-date class one month after
    the face. The published filing is the one the report shows, so it wins.
    """
    out = {}
    for family, note in (("drop_date_fallback", "date estimated — filed as published"),
                         ("hygiene_counted", "billing stale — filed as published")):
        for f in (flags.get(family) or []):
            mid, filed = str(f.get("mid") or ""), f.get("filed")
            if mid and filed:
                out[mid] = (filed, note)
    return out


# back-compat alias for the call site's local name
_filed_overrides = filed_overrides_from_flags


def main() -> int:
    period = os.environ.get("MPR_PERIOD", "2026-07")
    raw = rc.load_raw(period)
    cache_path = ROOT / "data" / "cache" / f"scoreboard_{period}.json"
    data = load_scoreboard(cache_path)
    import json
    cache_fields = json.loads(cache_path.read_text())["fields"]

    client = SLXClient(username=os.environ["SLX_USERNAME"],
                       password=os.environ["SLX_PASSWORD"])
    users = client.get_territory_users()

    # --- render-time SLX: names (batched) + retention bands (per territory)
    ids = set()
    ids |= {aid for snap in raw["families"].get("retention", {}).values()
            for aid in list(snap.get("by_account") or {}) + list(snap.get("removed_by") or {})}
    ids |= {k.split("|")[0] for k in raw["families"].get("new_members", {})}
    ids |= set(raw["families"].get("billables", {}))
    # penetration rosters name the MARKET, not just members (8/13): without
    # these the location rows render as bare account ids.
    for _snap in (raw["families"].get("penetration") or {}).values():
        for _seg in ("restaurant", "lodging", "restaurant_nt", "lodging_nt"):
            ids |= set(((_snap or {}).get(_seg) or {}).get("market") or ())
    names = {}
    idlist = sorted(ids)
    for i in range(0, len(idlist), 15):
        chunk = idlist[i:i + 15]
        ors = " or ".join(f"Id eq '{a}'" for a in chunk)
        for attempt in (1, 2, 3):
            try:
                for r in client._fetch_all("accounts", where=f"({ors})",
                                           select="AccountName", page_size=50):
                    names[r.get("$key")] = r.get("AccountName")
                break
            except Exception:
                time.sleep(2 * attempt)
        time.sleep(0.05)
    print(f"names resolved: {len(names)}/{len(ids)}")

    tmaps = {}
    for uid, terr in users.items():
        if terr and terr not in tmaps:
            try:
                tmaps[terr] = build_target_map(client, uid, status=None)
            except Exception:
                tmaps[terr] = {}
    def band_of(territory, aid):
        b = (tmaps.get(territory) or {}).get(aid)
        return {"Target": "Target"}.get(str(b), "Non-Target")
    def name_of(aid):
        return names.get(aid) or aid

    fy_start = int(period[:4]) if int(period[5:7]) >= 10 else int(period[:4]) - 1
    hyg = drops_hygiene.build_checker(None, fy_start,
                                      ROOT / "data" / "cache" / f"drops_hygiene_FY{fy_start}.json")

    # SEALED MONTHS CARRY FORWARD (8/10, caught by the conservation gate:
    # a member changed territories in the CRM after July sealed — a fresh
    # render filed their July cohort row under the NEW territory while the
    # published July stays sealed with the old one; 4 cells refused).
    # Sealed months' receipts are part of the locked record: story-family
    # rows for any month covered by a seal are carried VERBATIM from the
    # sealed edition's receipts; only open months render fresh.
    # S5 CARRY (extracted 2026-08-12 so it is TESTABLE — Jiho: "use the
    # functions responsible for the sealment"): harvesting per close was
    # inline in main(), where no test could reach it, and its failure mode
    # is doubling every sealed cell the moment TWO months are sealed —
    # which first happens at the August close, after handoff, and
    # hard-stops the September build. See harvest_sealed_carry().
    sealed_months, sealed_rows_by_family_month, _fresh_families = \
        harvest_sealed_carry(ROOT / "data" / "closes",
                             ROOT / "data" / "receipts", period)

    def _merge_sealed(rows, family):
        return merge_sealed(rows, family, sealed_months,
                            sealed_rows_by_family_month, _fresh_families)

    all_rows, errors = [], []
    ret_rows = rr.render_retention(raw, users, band_of, name_of)
    ret_rows = _merge_sealed(ret_rows, "Retention")
    errors += rr.gate_retention(ret_rows, cache_fields)
    all_rows += ret_rows

    nm_rows = rr.render_new_members(raw, name_of)
    nm_rows = _merge_sealed(nm_rows, "New Members / New Sales")
    errors += rr.gate_new_members(nm_rows, cache_fields)
    all_rows += nm_rows

    snapshot_month = rs.MONTH_ORDER[(int(period[5:7]) - 10) % 12]
    pen_rows = rr.render_penetration(raw, name_of)
    errors += rr.gate_penetration(pen_rows, cache_fields)
    all_rows += pen_rows

    bill_rows = rr.render_billables(raw, name_of, snapshot_month)
    errors += rr.gate_billables(bill_rows, cache_fields, snapshot_month)
    all_rows += bill_rows

    # published drops = the overlay's grids; rebuild them for the gate
    from reports.membership_performance_tracker.logic import crystal_banding, crystal_feed
    band = crystal_banding.band_from_detail(data.drops_detail)
    dates = crystal_banding.drop_dates_from_detail(data.drops_detail)
    fresh_drop_flags = {}
    published = crystal_feed.feed_drops(period, None, band,
                                        flags_out=fresh_drop_flags,
                                        hygiene=hyg, drop_date_of=dates)
    # C10 (sized 8/12, fixed 8/13): the feed above just decided where every
    # dateless and billing-stale drop files, and recorded each decision. Hand
    # those decisions to the renderer instead of letting it re-derive them —
    # `render_drops` has taken `filed_overrides` for exactly this since 8/6
    # ("two truths is zero truths") and this caller never passed them. Without
    # it the receipts filed the estimated-date class one month later than the
    # face (measured: receipts Dec = face Nov + face Dec across 6 territories),
    # so those cells read as conservation mismatches on every build.
    drop_rows = rr.render_drops(period, data.drops_detail, hyg,
                                filed_overrides=_filed_overrides(fresh_drop_flags))
    drop_rows = _merge_sealed(drop_rows, "Drops")
    # Gate against what is actually PUBLISHED: sealed months stamp their
    # frozen values over the fresh feed. Without this, a newer archive
    # vintage (8/10: July 1 sealed vs 16 in the fresh capture) trips the
    # gate on sealed columns the workbook will never show.
    try:
        import json as _cjson
        from types import SimpleNamespace
        from reports.membership_performance_tracker.logic import month_close as _mc
        closes = []
        for cf in sorted((ROOT / "data" / "closes").glob("close_*.json")):
            try:
                closes.append(_cjson.loads(cf.read_text()))
            except Exception:
                pass
        if closes:
            ns = SimpleNamespace(**published)
            _mc.apply_frozen(ns, closes, period=period)
            published = vars(ns)
    except Exception as exc:
        print(f"⚠ frozen stamp on gate baseline failed: {type(exc).__name__}: {exc}")
    errors += rr.gate_drops(drop_rows, published)
    all_rows += drop_rows

    if errors:
        print(f"\n⛔ CONSERVATION GATE FAILED — {len(errors)} cell(s) where the "
              f"receipts do not equal the published number. NOT publishing.")
        for e in errors[:20]:
            print("   ", e)
        # SAY IT SOMEWHERE THAT SURVIVES THE CONTAINER (2026-08-18). Until now
        # this list existed only in `data/output/scheduled_run.log` on Cloud
        # Run's ephemeral disk, and the runner reported EVERY non-zero return
        # as "SP push failed" — so a gate failure and an unreachable SharePoint
        # were indistinguishable from outside the box, and the evidence died
        # with the next instance recycle. The 2026-08-18 nightly failed exactly
        # this way and could not be diagnosed remotely at all.
        #
        # The failing cells now go to SharePoint as their own small artifact,
        # readable by anyone with hub access and no container access at all.
        # Best-effort: a reporting failure must never mask the real one.
        try:
            from src.hub.datahub import DataHub as _DH
            _hub = _DH.connect(require_sharepoint=False)
            if getattr(_hub, "_sp", None) is not None:
                _hub.write_hub_file(
                    "Reports/Membership Performance Report/Data/"
                    f"receipts_gate_failure_{period}.json",
                    json.dumps({
                        "period": period,
                        "at": _dt.datetime.now().isoformat(timespec="seconds"),
                        "reason": "conservation gate",
                        "cell_count": len(errors),
                        "cells": errors,
                        "note": "The published report is unaffected. These are "
                                "cells where the member rows behind a number "
                                "did not reproduce it, so the receipts were "
                                "not published and the Trace page still shows "
                                "the previous run's member lists.",
                    }, indent=1).encode())
                print("   ↑ failing cells written to SharePoint: "
                      f"Data/receipts_gate_failure_{period}.json")
        except Exception as _exc:
            print(f"   (could not record the failure to SharePoint: "
                  f"{type(_exc).__name__}: {_exc})")
        return 1

    receipts_dir = ROOT / "data" / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    # NEVER DESTROY A FAMILY THIS SCRIPT DOESN'T RENDER (8/10 review):
    # save_receipts_json rewrites the file wholesale, and this script
    # renders only the four story/photo families — the rebuild silently
    # deleted July's 15,609 backfilled Penetration rows. Any family
    # present in the existing record but absent from this render is
    # carried verbatim.
    _prior = receipts_dir / f"receipts_{period}.json"
    if _prior.exists():
        try:
            _rendered = {r.get("metric") for r in all_rows}
            _keep = [r for r in json.loads(_prior.read_text())["rows"]
                     if r.get("metric") not in _rendered]
            if _keep:
                all_rows = all_rows + _keep
                _fams = sorted({r.get("metric") for r in _keep})
                print(f"carried {len(_keep)} row(s) of unrendered "
                      f"famil(ies) {_fams} from the existing record")
        except Exception as _exc:
            print(f"⚠ could not carry unrendered families: "
                  f"{type(_exc).__name__}: {_exc}")
    jpath = rs.save_receipts_json(period, all_rows, receipts_dir)
    print(f"receipts: {len(all_rows)} rows, every cell reconciled → {jpath.name}")

    # ── CONSERVATION OF MEMBERS (scope locked 2026-08-04): every account
    # billed this FY must have a receipts disposition or a flag. The diff
    # runs here because this script has both the rendered receipts and a
    # live client. Leftovers merge into flags_<period>.json as
    # 'uncovered_billed_accounts' — only UNKNOWN rows demand action.
    import json as _json
    flags_path = ROOT / "data" / "cache" / f"flags_{period}.json"
    flags_doc = {}
    if flags_path.exists():
        try:
            flags_doc = _json.loads(flags_path.read_text())
        except Exception:
            flags_doc = {}
    flags = flags_doc.get("flags") or {}
    # the drops-feed families are recomputed above from the same inputs —
    # refresh their stored rows so wording/logic fixes land without
    # waiting for the next pull (8/10)
    for fam in ("drop_date_fallback", "hygiene", "hygiene_counted",
                "no_cycle", "rro_fyi"):
        if fam in fresh_drop_flags:
            flags[fam] = fresh_drop_flags[fam]
    try:
        fy_start_year = int(period[:4]) if int(period[5:7]) >= 10 else int(period[:4]) - 1
        import calendar as _cal
        _py, _pm = int(period[:4]), int(period[5:7])
        _pend = f"{_py}-{_pm:02d}-{_cal.monthrange(_py, _pm)[1]:02d}"
        # universe scoped to THIS edition's window (8/10: August enrollees
        # billed after July's month-end surfaced as July UNKNOWNs — they
        # belong to later editions)
        inv_rows = client._fetch_all(
            "dlInvoiceHistoryHeader",
            where=(f"Comp_code eq 'WRA' and Invoice_Type eq 'IN' "
                   f"and Invoice_Date ge @{fy_start_year}-10-01@ "
                   f"and Invoice_Date le @{_pend}@"),
            select="Accountid,Invoice_Date", page_size=200)
        invoiced_ids = {r.get("Accountid") for r in inv_rows} - {None}
        leftovers_raw = rr.coverage_leftovers(invoiced_ids, all_rows, flags)
        info = {}
        left_ids = [r["account"] for r in leftovers_raw]
        for i in range(0, len(left_ids), 12):
            chunk = left_ids[i:i + 12]
            ors = " or ".join(f"Id eq '{a}'" for a in chunk)
            for a in client._fetch_all("accounts", where=f"({ors})"):
                info[a.get("$key")] = {
                    "status": a.get("Status"),
                    "manager": (a.get("AccountManager") or {}).get("$key"),
                    "name": a.get("AccountName"),
                    "type": (a.get("Type") or "").strip(),
                    "parent": ((a.get("Parent") or {}).get("$key")
                               if isinstance(a.get("Parent"), dict)
                               else a.get("ParentId")),
                    "tm_users": set(users)}
            time.sleep(0.05)
        from src.slx.client import fetch_by_id_batches as _fbib
        for rec in _fbib(client, "cMemberGens", left_ids, page_size=100,
                         request_delay=0.05):
            aid = (rec.get("Account") or {}).get("$key")
            if aid in info:
                info[aid]["bill_month"] = str(rec.get("Duesbillmonth") or "").strip()
                em = _re2.search(r"/Date\((\-?\d+)", str(rec.get("EnrolledDate") or ""))
                if em:
                    import datetime as _dt
                    info[aid]["enrolled"] = _dt.datetime.utcfromtimestamp(
                        int(em.group(1)) / 1000).strftime("%Y-%m-%d")
        leftovers = rr.coverage_leftovers(invoiced_ids, all_rows, flags,
                                          account_info=info)
        for r in leftovers:
            r["member"] = (info.get(r["account"]) or {}).get("name")
        # UNKNOWN rows demand action (red); rule-explained exclusions are
        # the audit trail (gray) — split so the red section stays honest
        flags["uncovered_billed_accounts"] = [
            r for r in leftovers if r["class"].startswith("UNKNOWN")]
        flags["billed_excluded_by_rule"] = [
            r for r in leftovers if not r["class"].startswith("UNKNOWN")]
        # duplicate families across the resolved universe + leftovers
        allnames = dict(names)
        for aid, i2 in info.items():
            if i2.get("name"):
                allnames.setdefault(aid, i2["name"])
        flags["duplicate_records"] = rr.duplicate_names(allnames)
        unknown = sum(1 for r in leftovers if r["class"].startswith("UNKNOWN"))
        print(f"conservation: {len(invoiced_ids)} FY-billed accounts, "
              f"{len(leftovers)} uncovered ({unknown} UNKNOWN)")
        flags_doc.setdefault("period", period)
        flags_doc["flags"] = flags
        flags_path.write_text(_json.dumps(flags_doc, indent=1, default=str))
    except Exception as exc:
        print(f"⚠ conservation diff failed (receipts intact): "
              f"{type(exc).__name__}: {exc}")

    # ── FLAG ENRICHMENT (Jiho 8/10): flags must speak human — resolve
    # account ids to names, attach WRA numbers via the SLX↔Crystal
    # crosswalk (dlInvoiceHistoryHeader.CustomerNo), note reinstates.
    flag_names = dict(names)
    try:
        for aid, i2 in info.items():
            if i2.get("name"):
                flag_names.setdefault(aid, i2["name"])
    except NameError:
        pass
    try:
        need_ids = [r.get("account_id") or r.get("account")
                    for fam in ("active_without_payment", "voided_bills",
                                "record_cleanup")
                    for r in (flags.get(fam) or [])]
        need_ids = [a for a in need_ids if a and a not in flag_names]
        for i in range(0, len(need_ids), 12):
            ors = " or ".join(f"Id eq '{a}'" for a in need_ids[i:i + 12])
            for a in client._fetch_all("accounts", where=f"({ors})",
                                       select="AccountName"):
                if a.get("AccountName"):
                    flag_names[a.get("$key")] = a["AccountName"]
            time.sleep(0.05)
        for r in (flags.get("active_without_payment") or []):
            aid = r.get("account_id")
            if aid and r.get("name") in (None, "", aid):
                r["name"] = flag_names.get(aid, aid)
            if aid and not r.get("mid"):
                hh = client._fetch_all("dlInvoiceHistoryHeader",
                                       where=f"Account.Id eq '{aid}'",
                                       select="CustomerNo", page_size=5)
                mids = {h.get("CustomerNo") for h in hh} - {None, ""}
                if len(mids) == 1:
                    r["mid"] = next(iter(mids))
                time.sleep(0.05)
        import re as _re
        comp_ids = {m for r in (flags.get("comped_new_sales") or [])
                    for m in _re.findall(r"A6UJ[A-Z0-9]+",
                                         " ".join(map(str, r.get("accounts") or [])))}
        comp_ids -= set(flag_names)
        if comp_ids:
            ors = " or ".join(f"Id eq '{a}'" for a in comp_ids)
            for a in client._fetch_all("accounts", where=f"({ors})",
                                       select="AccountName"):
                if a.get("AccountName"):
                    flag_names[a.get("$key")] = a["AccountName"]
        for r in (flags.get("comped_new_sales") or []):
            accts = r.get("accounts")
            fixed = [_re.sub(r"A6UJ[A-Z0-9]+",
                             lambda m: flag_names.get(m.group(0), m.group(0)), str(x))
                     for x in (accts if isinstance(accts, list) else [accts])]
            r["accounts"] = fixed
            r["defect"] = _re.sub(r"; identify via the account id.*$",
                                  ". Investigate.", str(r.get("defect") or ""))
        for r in (flags.get("drop_date_fallback") or []):
            mid = r.get("mid")
            if not mid or "since returned" in (r.get("reason") or ""):
                continue
            hh = client._fetch_all("dlInvoiceHistoryHeader",
                                   where=f"CustomerNo eq '{mid}'",
                                   page_size=5)
            aid = next((h["Account"]["$key"] for h in hh
                        if isinstance(h.get("Account"), dict)
                        and h["Account"].get("$key")), None)
            if aid:
                acc = client.get_account(aid)
                if isinstance(acc, dict) and acc.get("Status") == "Active":
                    r["reason"] = ((r.get("reason") or "")
                                   + " — member has since returned (active now)")
            time.sleep(0.05)
        flags_doc.setdefault("period", period)
        flags_doc["flags"] = flags
        flags_path.write_text(_json.dumps(flags_doc, indent=1, default=str))
    except Exception as exc:
        print(f"⚠ flag enrichment incomplete (flags intact): "
              f"{type(exc).__name__}: {exc}")

    # WORKBOOK CLEANUP (Jiho 8/12 night): the in-workbook Members/Flags tabs
    # are retired — the Trace page + its Excel download is the member-level
    # surface. The JSON artifacts (receipts/flags) still publish unchanged;
    # strip the tabs if an older build carries them.
    from openpyxl import load_workbook
    xlsx = ROOT / "data" / "output" / f"Membership_Performance_Report_{period}.xlsx"
    if xlsx.exists():
        wb = load_workbook(xlsx)
        stripped = False
        for stale in ("Data - MPR Members", "Data - MPR Flags"):
            if stale in wb.sheetnames:
                wb.remove(wb[stale])
                stripped = True
        if stripped:
            wb.save(xlsx)
            print(f"retired Members/Flags tabs stripped → {xlsx.name}")

    try:
        from src.hub.datahub import DataHub
        hub = DataHub.connect(require_sharepoint=False)
        if getattr(hub, "_sp", None) is not None:
            # Location ruled 2026-08-03 (Jiho): receipts live in the report's
            # own Data folder, sibling of Output — NOT a hub-root folder. The
            # workbook itself is never copied here; the Members sheet already
            # travels inside the report xlsx that Output carries.
            hub.write_hub_file(
                "Reports/Membership Performance Report/Data/"
                f"receipts_{period}.json", jpath.read_bytes())
            if flags_path.exists():
                hub.write_hub_file(
                    "Reports/Membership Performance Report/Data/"
                    f"flags_{period}.json", flags_path.read_bytes())
            print("pushed to SharePoint: Reports/Membership Performance "
                  "Report/Data/")
        else:
            print("no SP credentials — local only")
    except Exception as exc:
        print(f"⚠ SP push failed (local artifacts intact): {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
