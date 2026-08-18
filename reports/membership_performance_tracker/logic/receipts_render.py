"""receipts_render.py — turn the raw capture into the receipts artifact.

THE HARD RULE (Jiho, 2026-07-31): this module is an accurate WINDOW into the
program, never a second implementation. Every disposition is derived by
calling the pipeline's OWN functions (`retained_as_of`, `_netted_retained`,
`retained_dollars_as_of`, `_member_retained`, `_file_month`, …) on the same
raw rows the pipeline used — and every cell is gated: the sum of receipt rows
must equal the published cache value, or the render REFUSES. Drift between
this window and the program is a hard failure, not a footnote.

The drops loop WAS the one exception — a hand-kept copy of `feed_drops`'
filing rules, with the per-cell gate as its drift alarm. Closed 2026-08-14
(docs/superpowers/specs/2026-08-14-receipts-single-path.md): `render_drops`
and `feed_drops` are now two projections of `crystal_feed.drop_ledger`, so
the count and the member list behind it are the same objects read twice. A
detector cannot prevent a class of error; only structure can.

Qualifies-as vocabulary is CLOSED (no generated prose — ruled): retention
`paid in window · paid after close · still owes · comped · bill rescinded ·
no payment on record`; drops carry their own 19 CRM reasons; new members
`first payment · BOB comp`; billables `active with dues product`.
"""
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional

from reports.membership_performance_tracker.logic import receipts_capture as rc
from reports.membership_performance_tracker.logic.retention import (
    _member_retained, _netted_retained, retained_as_of, retained_dollars_as_of)

MONTH_INT_TO_ABB = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
                    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}


# Territory keys: the renderer takes names from the SLX user descriptor
# ("SpokaneNE"), every cache field uses the display name ("Spokane/NE").
# The gates looked up the raw key, missed, and `continue`d — 80 retention
# cells were silently UNGATED (overnight review, receipts unit F3).
_TERR_ALIASES = {"SpokaneNE": "Spokane/NE", "MajorsNRA": "Majors/NRA",
                 "Spokane/NE": "SpokaneNE", "Majors/NRA": "MajorsNRA"}


def _pub_cell(cache_fields, field, terr, month):
    """The published cell for (field, territory, month), or None only when
    the field genuinely has no such cell under ANY spelling of the key."""
    per_terr = cache_fields.get(field) or {}
    for key in (terr, _TERR_ALIASES.get(terr)):
        if key is None:
            continue
        slot = per_terr.get(key)
        if isinstance(slot, dict):
            if month in slot:
                return slot[month]
        elif slot is not None and month is None:
            return slot
    return None


def _iso_to_date(s) -> Optional[date]:
    try:
        y, m, d = str(s)[:10].split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Retention — dispositions via the pipeline's own functions, per account
# ---------------------------------------------------------------------------

def _band(rows, territory: str, aid: str, band_of) -> str:
    """THE T/NT LOCK, mirrored from `_retention_target_split` (retention.py).

    Allied is Non-Target by definition (ruled 2026-08-11), so size data must
    never promote one into Target. The face applies this lock; these receipts
    have to agree with the face or the conservation gate refuses the cell.

    Found 2026-08-13: without it, Seattle Laundry rendered under "Target"
    while July's amendment moved a NON-target cell — the target map had banded
    it on size. No allied member in an open month happened to be large enough
    to trip this yet, so it stayed invisible.
    """
    if rows and rows[0].get("_allied"):
        return "Non-Target"
    return band_of(territory, aid)


def render_retention(raw: dict, user_to_territory: Dict[str, str],
                     band_of: Callable[[str, str], str],
                     name_of: Callable[[str], str]) -> List[dict]:
    """One receipt row per cohort member (and per excluded member) per cycle.

    band_of(territory, account_id) and name_of(account_id) are injected so
    render-time SLX lookups stay outside this module (testable offline).
    """
    payments_by_bm = {k: v for k, v in (raw["families"].get("retention_payments") or {}).items()}
    rows_out: List[dict] = []
    for key, snap in (raw["families"].get("retention") or {}).items():
        manager, bm_str = key.split("|")
        territory = user_to_territory.get(manager)
        if not territory:
            continue
        bm = int(bm_str)
        display = MONTH_INT_TO_ABB[1 if bm == 12 else bm + 1]
        as_of = _iso_to_date(snap.get("as_of"))
        pay_index = {inv: _iso_to_date(d)
                     for inv, d in (payments_by_bm.get(bm_str) or {}).items()}

        for aid, rows in (snap.get("by_account") or {}).items():
            invs = [str(r.get("invoice_number") or "") for r in rows]
            dates = [pay_index[n] for n in invs if pay_index.get(n)]
            first_pay = min(dates) if dates else None
            comped = bool(rows and rows[0].get("_comp"))
            bob = bool(rows and any(r.get("_bob") for r in rows))
            # SAME functions, SAME order as _retention_counts / the split:
            ask, retained = retained_dollars_as_of(rows, first_pay, as_of)
            has_paid = retained_as_of(rows, first_pay, as_of)
            if bob:
                # BOB ruling (8/4): comped renewal COUNTS at face, both
                # sides — the 8/6 wiring check caught this branch missing
                # (Velvet's Big Easy rendered "no payment on record" while
                # the face counted it at face).
                face = next((r.get("dues_level") for r in rows
                             if isinstance(r.get("dues_level"), (int, float))
                             and r.get("dues_level") > 0), None) or max(
                    (r.get("invoice_total") or 0 for r in rows), default=0.0)
                qualifies, counted = "BOB — counted at face", True
                ask = retained = round(float(face), 2)
            elif comped:
                qualifies, counted, ask, retained = "comped", True, 0.0, 0.0
            elif has_paid:
                qualifies, counted = "paid in window", True
            elif _member_retained(rows):
                qualifies, counted = "paid after close", False
            elif any((r.get("balance") or 0) > 0 for r in rows):
                qualifies, counted = "still owes", False
            else:
                qualifies, counted = "no payment on record", False
            rows_out.append({
                "metric": "Retention", "month": display, "territory": territory,
                "band": _band(rows, territory, aid, band_of), "member": name_of(aid),
                "member_id": aid,
                "invoice": ", ".join(sorted({i for i in invs if i})),
                "key_date": str(first_pay) if first_pay else "",
                "ask": round(ask, 2), "retained": round(retained, 2),
                "counted": counted, "qualifies": qualifies,
            })
        for aid, why in (snap.get("removed_by") or {}).items():
            qual = ("bill rescinded" if "rescinded" in str(why)
                    else "first cycle" if "first cycle" in str(why)
                    else "left mid-cycle" if "drop" in str(why)
                    else str(why))
            rows_out.append({
                "metric": "Retention", "month": display, "territory": territory,
                "band": band_of(territory, aid), "member": name_of(aid),
                "member_id": aid, "invoice": "", "key_date": "",
                "ask": 0.0, "retained": 0.0, "counted": False,
                "qualifies": qual,
            })
    return rows_out


def gate_retention(rows: List[dict], cache_fields: dict) -> List[str]:
    """Σ receipt rows must equal every published retention cell. Errors back."""
    agg = defaultdict(lambda: {"paid": 0, "billed": 0, "ask": 0.0, "ret": 0.0})
    for r in rows:
        if r["qualifies"] in ("bill rescinded", "first cycle", "left mid-cycle"):
            continue        # excluded from cohort — displayed, never counted
        if "voided by credit memo" in str(r["qualifies"]):
            # R1 = A (8/12): a fully-voided cycle leaves BOTH sides of the
            # fraction. A fixed-list membership test here would have counted
            # these rows as billed and broken the gate the day the rule
            # shipped — the same fixed-list trap gate F3 documented.
            continue
        if r["qualifies"] in ("paid after close", "still owes",
                              "no payment on record") or r["counted"]:
            key = (r["territory"], r["month"], r["band"])
            agg[key]["billed"] += 1
            if r["counted"]:
                agg[key]["paid"] += 1
            agg[key]["ask"] += r["ask"]
            agg[key]["ret"] += r["retained"]
    errors = []
    band_field = {"Target": "target", "Non-Target": "non_target", "Unknown": "non_target"}
    merged = defaultdict(lambda: {"paid": 0, "billed": 0, "ask": 0.0, "ret": 0.0})
    for (t, m, band), v in agg.items():
        suffix = band_field.get(band, "non_target")
        k = (t, m, suffix)
        for f in v:
            merged[k][f] += v[f]
    for (t, m, suffix), v in merged.items():
        for field, ours in (("ret_paid_%s" % suffix, v["paid"]),
                            ("ret_billed_%s" % suffix, v["billed"]),
                            ("rev_up_%s" % suffix, v["ask"]),
                            ("rev_retained_%s" % suffix, v["ret"])):
            pub = _pub_cell(cache_fields, field, t, m)
            if pub is None:
                continue
            if abs(float(pub) - float(ours)) > 0.51:
                errors.append(f"{field} {t} {m}: receipts {ours} != published {pub}")
    return errors


# ---------------------------------------------------------------------------
# New members / revenue / BOB — captured display-ready; unknown folds NT
# exactly as the engine folds it (engine.py revenue assignment).
# ---------------------------------------------------------------------------

def render_new_members(raw: dict, name_of: Callable[[str], str]) -> List[dict]:
    rows_out = []
    for key, r in (raw["families"].get("new_members") or {}).items():
        aid = key.split("|")[0]
        band = {"target": "Target", "non_target": "Non-Target",
                "unknown": "Non-Target"}.get(r.get("band"), "Non-Target")
        qual = "BOB comp" if r.get("bob") else "first payment"
        # ASK vs COLLECTED (Shannon, 8/12: "what does Collected None mean?").
        # New-sales revenue is on Jen's PAID basis, so `amount` is cash — but
        # the console displayed it under "Asked $" and a literal None under
        # "Collected $". The receipts now carry both truths: `ask` = the net
        # bill (captured by revenue.py; None on captures older than 8/12 — we
        # never fabricate a bill), `retained` = amount − bob, cash net of the
        # comped credit, so a BOB comp reads asked 505 / collected 0 and a
        # partial payer reads asked 1,070 / collected 500. `amount` is
        # untouched — the conservation gate sums it against the face.
        _ask = r.get("ask")
        rows_out.append({
            "metric": "New Members / New Sales", "month": r.get("month"),
            "territory": r.get("territory"), "band": band,
            "member": name_of(aid), "member_id": aid, "invoice": "",
            "key_date": str(r.get("first_pay") or "")[:10],
            "amount": round(r.get("amount") or 0.0, 2),
            "bob": round(r.get("bob") or 0.0, 2),
            "ask": (round(float(_ask), 2)
                    if isinstance(_ask, (int, float)) else None),
            "retained": round((r.get("amount") or 0.0)
                              - (r.get("bob") or 0.0), 2),
            "counted": bool(r.get("counted")), "qualifies": qual,
        })
    return rows_out


def gate_new_members(rows: List[dict], cache_fields: dict) -> List[str]:
    agg = defaultdict(lambda: {"n": 0, "amt": 0.0, "bob": 0.0})
    for r in rows:
        # TWO FLAGS, TWO MEANINGS (settled 2026-08-20, after each meaning bit
        # in turn). `counted` answers "is this member IN THE COUNT metric";
        # the row's `amount` answers "does this row carry money". They are
        # independent:
        #   · a sale stranded into a sealed month (2026-08-14, $575 into
        #     closed July) is in NEITHER — merge_sealed zeroes its amount,
        #     the same convention retention uses for exclusions ("an excluded
        #     member carries no money", 2026-08-15);
        #   · a REFUND is uncounted but its money is real and negative — a
        #     member's $1,754.50 reversal sat in the NorthKing Aug cell while
        #     this gate (then skipping every uncounted row) refused to
        #     acknowledge it, blocking receipts three nights running
        #     (2026-08-18/19/20) over a number that was correct.
        # So: dollars sum over EVERY row, counts over counted rows. A row that
        # must move no total carries amount 0 — explicitly, visibly, on the
        # row itself.
        k = (r["territory"], r["month"],
             "target" if r["band"] == "Target" else "non_target")
        if r["counted"]:
            agg[k]["n"] += 1
        agg[k]["amt"] += r["amount"]
        agg[k]["bob"] += r["bob"]
    errors = []
    for (t, m, suffix), v in agg.items():
        for field, ours in ((f"new_members_{suffix}", v["n"]),
                            (f"revenue_{suffix}", v["amt"]),
                            (f"revenue_bob_{suffix}", v["bob"])):
            pub = _pub_cell(cache_fields, field, t, m)
            if pub is None:
                continue
            if abs(float(pub) - float(ours)) > 0.51:
                errors.append(f"{field} {t} {m}: receipts {ours} != published {pub}")
    return errors


# ---------------------------------------------------------------------------
# Billables — the full roster; unknown band folds NT (model convention)
# ---------------------------------------------------------------------------

def render_billables(raw: dict, name_of: Callable[[str], str],
                     snapshot_month: str) -> List[dict]:
    rows_out = []
    for aid, r in (raw["families"].get("billables") or {}).items():
        band = ("Allied" if r.get("allied")
                else {"Target": "Target"}.get(r.get("band"), "Non-Target"))
        rows_out.append({
            "metric": "Billables", "month": snapshot_month,
            "territory": r.get("territory"), "band": band,
            "member": name_of(aid), "member_id": aid, "invoice": "",
            "key_date": "", "amount": 1, "counted": True,
            "qualifies": "active with dues product",
            "product": r.get("product") or "",
        })
    return rows_out


def gate_billables(rows: List[dict], cache_fields: dict,
                   snapshot_month: str) -> List[str]:
    agg = defaultdict(lambda: {"Target": 0, "Non-Target": 0, "Allied": 0})
    for r in rows:
        agg[r["territory"]][r["band"]] += 1
    errors = []
    for t, v in agg.items():
        for field, ours in (("hosp_bills_target", v["Target"]),
                            ("hosp_bills_non_target", v["Non-Target"]),
                            ("allied_bills", v["Allied"])):
            pub = _pub_cell(cache_fields, field, t, snapshot_month)
            if pub is None:
                continue
            if abs(float(pub) - float(ours)) > 0.51:
                errors.append(f"{field} {t}: receipts {ours} != published {pub}")
    return errors


# ---------------------------------------------------------------------------
# Drops — a RENDER of crystal_feed.drop_ledger, which is also what the
# published grids are summed from. Not a mirror of it: the same objects.
# Ruled 2026-08-14 (docs/superpowers/specs/2026-08-14-receipts-single-path.md).
# ---------------------------------------------------------------------------

def render_drops(period: str, drops_detail, hygiene, today=None,
                 filed_overrides: Optional[Dict[str, tuple]] = None,
                 band=None, drop_date_of=None) -> List[dict]:
    """Every exported drop row, as a member row for the Trace page.

    ONE LOOP, TWO PROJECTIONS (ruled 2026-08-14). This used to be a hand-kept
    copy of `feed_drops`' filing loop, and the copy is what the conservation
    gate spent this month catching: the allied ruling and the admin-reason
    exclusion each landed on one loop and not the other, and receipts refused
    to publish for two runs running. Both now read `crystal_feed.drop_ledger`,
    so a rule cannot reach the number without reaching its explanation.

    Uncounted rows are rendered too — an export row with no receipt is a row
    nobody can ask about. `counted` says which is which.

    band / drop_date_of default to the detail-export bridges, which is what a
    standalone receipts build has. A caller holding the PULL's own bridges
    (the runner) should pass them: same ledger, same inputs, same answer.

    filed_overrides {mid: (month, note)} — the PULL's own filing decisions
    (drop_date_fallback / hygiene_counted flags). The published filing always
    wins over a render-time re-derivation; the note explains it (8/6 wiring
    check: Cibrian filed Jun-at-class-close by the feed, Jul by the renderer
    — two truths is zero truths). Redundant when the caller passes the same
    bridges, and kept for the callers that cannot.
    """
    from reports.membership_performance_tracker.logic import crystal_banding as cb
    from reports.membership_performance_tracker.logic import crystal_feed as cf
    if band is None:
        band = cb.band_from_detail(drops_detail)
    if drop_date_of is None:
        drop_date_of = cb.drop_dates_from_detail(drops_detail)
    entries = cf.drop_ledger(period, None, band, hygiene, drop_date_of, today)
    out = []
    for e in entries:
        r = _drop_row(e["row"], e["month"], e["explain"], e["counted"],
                      reason=e["reason"])
        r["band"] = e["band"]
        if e["key_date"]:
            r["key_date"] = e["key_date"]
        ov = (filed_overrides or {}).get(str(e["row"].mid))
        if e["counted"] and ov and ov[0]:
            r["month"] = ov[0]
            if ov[1]:
                r["qualifies"] += f" ({ov[1]})"
        out.append(r)
    return out


def _drop_row(row, month, qualifies, counted, reason=""):
    """`qualifies` is display text and gets suffixes appended; `reason` is
    Crystal's own status reason, raw — `drops_by_category` is keyed on it, so
    it has to survive un-decorated (mapper.py:257 reads that grid)."""
    return {"metric": "Drops", "month": month, "territory": row.territory,
            "band": "", "member": row.name, "member_id": row.mid,
            "invoice": "", "key_date": str(row.status_date or ""),
            "amount": round(row.dues or 0.0, 2), "counted": counted,
            "qualifies": qualifies, "reason": reason}


def gate_drops(rows: List[dict], published_fields: dict) -> List[str]:
    agg = defaultdict(lambda: {"n": 0, "amt": 0.0})
    for r in rows:
        if not r["counted"]:
            continue
        k = (r["territory"], r["month"],
             "target" if r["band"] == "Target" else "non_target")
        agg[k]["n"] += 1
        agg[k]["amt"] += r["amount"]
    errors = []
    for (t, m, suffix), v in agg.items():
        for field, ours in ((f"drops_{suffix}", v["n"]),
                            (f"drops_revenue_{suffix}", v["amt"])):
            pub = _pub_cell(published_fields, field, t, m)
            if pub is None:
                continue
            if abs(float(pub) - float(ours)) > 0.51:
                errors.append(f"{field} {t} {m}: receipts {ours} != published {pub}")
    return errors


def coverage_leftovers(invoiced_ids, receipts_rows, flags, account_info=None):
    """CONSERVATION OF MEMBERS (scope locked with Jiho 2026-08-04).

    Every account billed this FY must exit the pipeline with a receipts
    disposition (counted yes OR no) or a data-defect flag. This function
    returns the accounts that did NEITHER — the silent exclusions — each
    classified so only true unknowns demand attention:

      · 'retro (excluded by rule)'            — RRO/RRO LNI status: correct
      · 'no account manager (unassigned book)'— real member, nobody's roster
      · 'UNKNOWN — investigate'               — no explanation; a finding

    `account_info` maps account id -> {'status': ..., 'manager': ...} for
    the leftover set only (fetched small, after the diff).
    """
    covered = {str(r.get("member_id") or "") for r in (receipts_rows or [])}
    for family, rows in (flags or {}).items():
        # this check's OWN output families must never count as coverage —
        # they made the uncovered count alternate 0/true on alternating
        # runs (self-covering feedback, found 8/10)
        if str(family).startswith("_") or family in (
                "uncovered_billed_accounts", "billed_excluded_by_rule"):
            continue
        for r in rows or []:
            if isinstance(r, dict):
                covered.add(str(r.get("account") or r.get("member_id") or ""))
    covered.discard("")

    def _is_recent(iso, days):
        if not iso:
            return False
        try:
            from datetime import date, timedelta
            y, m, d = str(iso)[:10].split("-")
            return date.today() - date(int(y), int(m), int(d)) <= timedelta(days=days)
        except Exception:
            return False

    RETRO_USER = "U6UJ9A00008G"          # the Retro Coordinator login (D11)
    _INTERNAL = ("washington hospitality", "seattle hotel assoc",
                 "restaurant association")
    out = []
    for aid in sorted(set(invoiced_ids) - covered):
        info = (account_info or {}).get(aid) or {}
        status = str(info.get("status") or "").strip()
        name = str(info.get("name") or "").lower()
        bm = str(info.get("bill_month") or "").strip()
        tm_users = info.get("tm_users") or set()
        mgr = info.get("manager")
        # Classifier v2 (2026-08-04 investigation: 108 UNKNOWN -> 0)
        if status.upper().startswith("RRO") or mgr == RETRO_USER or bm in ("14", "15", "16"):
            klass = "retro/NRA book (excluded by rule)"
        elif any(k in name for k in _INTERNAL):
            klass = "internal/association account"
        elif info.get("type") == "Individual":
            klass = "individual membership (not a territory metric)"
        elif info.get("type") == "Allied" and tm_users and mgr not in tm_users:
            klass = "allied house account (ruled out 7/15)"
        elif not mgr:
            klass = "no account manager (unassigned book)"
        elif tm_users and mgr not in tm_users:
            klass = f"non-TM book (staff login {mgr})"
        elif info.get("parent"):
            klass = "corporate child (parent-billed, R8)"
        elif status in ("Inactive", "Closed"):
            klass = ("dropped with NO StatusDate — invisible to every drops "
                     "report incl. Crystal (D5 defect); fix the record")
        elif status in ("N/A", "") and _is_recent(info.get("enrolled"), 45):
            # Boylston class (8/10): brand-new enrollee billed at signup,
            # account Status not set yet — flows into the metrics once
            # staff finish the record and the payment posts
            klass = ("brand-new enrollee — record still being set up "
                     "(status not yet set)")
        else:
            klass = "UNKNOWN — investigate"
        out.append({"account": aid, "status": status or "?",
                    "class": klass,
                    "defect": "billed this FY but appears in no metric's "
                              "receipts and no flag — a silent exclusion"})
    return out


def duplicate_names(names: dict) -> list:
    """Multi-record families by normalized name (Jiho 8/4: FLAG, humans
    decide). `names` maps account id -> AccountName for the FY universe.
    Returns one flag row per family: {name, accounts, defect}."""
    import re as _re
    import unicodedata as _ud
    from collections import defaultdict as _dd
    by_norm = _dd(list)
    for aid, name in (names or {}).items():
        key = _re.sub(r"[^a-z0-9]", "", _ud.normalize("NFKD", str(name or "")).lower())
        if key:
            by_norm[key].append((aid, name))
    out = []
    for key, members in sorted(by_norm.items()):
        if len(members) > 1:
            out.append({
                "name": members[0][1],
                "accounts": sorted(a for a, _ in members),
                "defect": "multiple account records share this name — "
                          "name-matching and per-member metrics can pick "
                          "the wrong record; a human should pick the "
                          "canonical one"})
    return out


def _classify_drop_rows_for_test(rows, period, allied=False):
    """Test seam: classify plain row objects — no archive, no banding.

    This used to be a fourth hand-written copy of the drop rules, kept only so
    they could be tested without a Crystal fixture. It now calls the same
    `classify_drop` the published grids and the Trace page both go through, so
    what these tests assert is what actually ships.
    """
    from datetime import date as _d
    from reports.membership_performance_tracker.logic.crystal_feed import (
        classify_drop, _fy_of)
    out = []
    for row in rows:
        e = classify_drop(row, allied, fy_start=_fy_of(period),
                          today=_d(int(period[:4]), int(period[5:7]), 28))
        r = _drop_row(e["row"], e["month"], e["explain"], e["counted"],
                      reason=e["reason"])
        r["band"] = e["band"]
        out.append(r)
    return out


# Segment label + band for each captured penetration roster key.
_PEN_SEGMENTS = {"restaurant":    ("Restaurant", "Target"),
                 "lodging":       ("Lodging", "Target"),
                 "restaurant_nt": ("Restaurant", "Non-Target"),
                 "lodging_nt":    ("Lodging", "Non-Target")}


def render_penetration(raw: dict, name_of: Callable[[str], str]) -> List[dict]:
    """Every location behind a penetration percentage, named.

    Penetration is active ÷ market, so the rows ARE the denominator: one row
    per market location, `counted` when it is an active member. That is what
    makes the percentage traceable — you can see who is in and who is not.

    Wired into the normal build 2026-08-13 (Jiho: "we are not deferring
    this"). July's rosters existed only because a one-off backfill script
    attached them after the fact, so every other month published penetration
    with nothing behind it. The capture already recorded these id lists per
    territory; only the rendering was missing.
    """
    out = []
    for _key, snap in (raw["families"].get("penetration") or {}).items():
        # keyed by territory in older captures, by seat user id since 8/6 —
        # the territory always travels inside the payload
        territory = (snap or {}).get("territory") or _key
        for seg, (seg_label, band) in _PEN_SEGMENTS.items():
            part = (snap or {}).get(seg) or {}
            active = set(part.get("active") or ())
            for aid in (part.get("market") or ()):
                is_active = aid in active
                out.append({
                    "metric": "Penetration", "month": "",
                    "territory": territory, "band": band,
                    "segment": seg_label,
                    "member": name_of(aid), "member_id": aid,
                    "invoice": "", "key_date": "", "amount": 1,
                    "counted": is_active,
                    "qualifies": ("active member location" if is_active
                                  else "in the market, not a member"),
                })
    return out


def gate_penetration(rows: List[dict], cache_fields: dict) -> List[str]:
    """Active + market per territory/segment must reproduce the published
    penetration counts — the same conservation contract every other family
    signs."""
    agg = defaultdict(lambda: {"active": 0, "market": 0})
    for r in rows:
        k = (r["territory"], r["segment"], r["band"])
        agg[k]["market"] += 1
        if r["counted"]:
            agg[k]["active"] += 1
    FIELD = {("Restaurant", "Target"): ("pen_active_restaurant",
                                        "pen_market_restaurant"),
             ("Lodging", "Target"): ("pen_active_lodging",
                                     "pen_market_lodging"),
             ("Restaurant", "Non-Target"): ("pen_active_nt_restaurant", None),
             ("Lodging", "Non-Target"): ("pen_active_nt_lodging", None)}
    errors = []
    for (terr, seg, band), v in agg.items():
        act_f, mkt_f = FIELD.get((seg, band), (None, None))
        for field, ours in ((act_f, v["active"]), (mkt_f, v["market"])):
            if not field:
                continue
            pub = (cache_fields.get(field) or {}).get(terr)
            if isinstance(pub, dict):          # month-keyed variants
                pub = next(iter(pub.values()), None)
            if pub is None:
                continue
            if int(pub) != int(ours):
                errors.append(f"{field} {terr}: receipts {ours} != published {pub}")
    return errors
