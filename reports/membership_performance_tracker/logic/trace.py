"""trace.py — a published number → its constituents (Jiho's ruling, 8/6:
"the ability for someone to look at a number and trace it back to its
constituents — that is the foundation of explanation and analysis and
forensics").

Reads the rendered receipts the pipeline itself produced (receipts_render
output — never a parallel derivation) and checks CONSERVATION against the
published cache: the member rows must reproduce the face cell, or the
trace says so loudly. Consumed by the console's "Trace a number" page.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional

from reports.membership_performance_tracker.logic import adjustments as _adj

_ROOT = Path(__file__).resolve().parents[3]
RECEIPTS_DIR = _ROOT / "data" / "receipts"
CACHE_DIR = _ROOT / "data" / "cache"

FAMILIES = ("Retention", "Drops", "Billables", "New Members / New Sales")


_TERR_FIX = {"SpokaneNE": "Spokane/NE", "MajorsNRA": "Majors/NRA"}


def _fetch_sp_snapshot(period: str) -> Optional[Dict]:
    """The SP snapshot envelope for a period, or None (offline / none yet)."""
    try:
        from src.hub.datahub import DataHub
        from src.hub.audit import _load_latest_snapshot
        hub = DataHub.connect(require_sharepoint=False)
        if hub._sp is None:
            return None
        return _load_latest_snapshot(period, hub)
    except Exception:
        return None


# build stamps seen by the most recent _load, keyed by period — lets trace()
# distinguish "receipts predate the face" (calm) from a real mismatch (red)
# without changing _load's signature for its callers.
_BUILD_STAMPS: Dict[str, Dict] = {}


def _load(period: str):
    env = json.loads((RECEIPTS_DIR / f"receipts_{period}.json").read_text())
    rows = env["rows"]
    _BUILD_STAMPS[period] = {"receipts": env.get("generated_at")}
    # the renderer strips slashes from territory names (SpokaneNE); every
    # other layer keeps them — normalize at the door (8/6 wiring check)
    for r in rows:
        r["territory"] = _TERR_FIX.get(r.get("territory"), r.get("territory"))
    sb_path = CACHE_DIR / f"scoreboard_{period}.json"
    if not sb_path.exists():
        # A fresh cloud instance only session-syncs the VIEWED month's
        # scoreboard; this page's picker spans every month with receipts —
        # heal the gap from the SP snapshot (8/10, hydration directive)
        env = _fetch_sp_snapshot(period)
        if env is not None and "data" in env:
            from reports.membership_performance_tracker.logic.cache import (
                save_scoreboard, scoreboard_from_dict)
            save_scoreboard(scoreboard_from_dict(env["data"]), sb_path,
                            saved_at=env.get("captured_at"),
                            source="sp-published")
    sb = json.loads(sb_path.read_text())
    fields = sb["fields"]
    _BUILD_STAMPS[period]["face"] = (sb.get("_meta") or {}).get("pulled_at") \
        or (sb.get("_meta") or {}).get("saved_at")
    return rows, fields


# The all-territories view (Jiho 8/12): published = the sum of every
# territory's cell, members = every territory's rows. One sentinel value the
# console offers at the top of the Territory dropdown.
TOTAL_TERRITORY = "Total"


def _cell(fields, name, terr, month):
    fam = fields.get(name) or {}
    if terr == TOTAL_TERRITORY:
        vals = []
        for tv in fam.values():
            v = tv.get(month) if isinstance(tv, dict) else tv
            if isinstance(v, (int, float)):
                vals.append(v)
        return sum(vals) if vals else None
    v = fam.get(terr)
    if isinstance(v, dict):
        v = v.get(month)
    return v


def _published(fields, family, terr, month) -> Dict:
    if family == "Retention":
        # counts from the SPLIT fields — the TM sheets sum T+NT, so the
        # sheet's number IS the split sum (8/6: the combined engine field
        # can differ when a branch exists in one path only; conserve
        # against what the reader sees)
        return {
            "ret_billed": ((_cell(fields, "ret_billed_target", terr, month) or 0)
                           + (_cell(fields, "ret_billed_non_target", terr, month) or 0)),
            "ret_paid": ((_cell(fields, "ret_paid_target", terr, month) or 0)
                         + (_cell(fields, "ret_paid_non_target", terr, month) or 0)),
            "rev_up": ((_cell(fields, "rev_up_target", terr, month) or 0)
                       + (_cell(fields, "rev_up_non_target", terr, month) or 0)),
            "rev_retained": ((_cell(fields, "rev_retained_target", terr, month) or 0)
                             + (_cell(fields, "rev_retained_non_target", terr, month) or 0)),
        }
    if family == "Drops":
        return {
            "drops": ((_cell(fields, "drops_target", terr, month) or 0)
                      + (_cell(fields, "drops_non_target", terr, month) or 0)),
            "drops_revenue": ((_cell(fields, "drops_revenue_target", terr, month) or 0)
                              + (_cell(fields, "drops_revenue_non_target", terr, month) or 0)),
        }
    if family == "Billables":
        return {
            "hosp_bills": _cell(fields, "hosp_bills", terr, month),
            "allied_bills": _cell(fields, "allied_bills", terr, month),
        }
    if family == "Penetration":
        # scalar-per-territory fields — _cell passes scalars through, and the
        # Total sentinel sums them like every other family
        return {
            "active_target_restaurant": _cell(fields, "pen_active_restaurant", terr, None),
            "market_target_restaurant": _cell(fields, "pen_market_restaurant", terr, None),
            "active_target_lodging": _cell(fields, "pen_active_lodging", terr, None),
            "market_target_lodging": _cell(fields, "pen_market_lodging", terr, None),
            "active_nt_restaurant": _cell(fields, "pen_active_nt_restaurant", terr, None),
            "active_nt_lodging": _cell(fields, "pen_active_nt_lodging", terr, None),
        }
    if family == "New Members / New Sales":
        return {
            "revenue": ((_cell(fields, "revenue_target", terr, month) or 0)
                        + (_cell(fields, "revenue_non_target", terr, month) or 0)),
            "new_members": ((_cell(fields, "new_members_target", terr, month) or 0)
                            + (_cell(fields, "new_members_non_target", terr, month) or 0)),
        }
    return {}


def _in_cohort(r: dict) -> bool:
    """Billed-cohort membership: counted rows plus billed-but-unpaid rows
    ("still owes" carries a real ask). Exclusions (allied, first cycle,
    voids, retro) carry ask 0 and counted False."""
    return bool(r.get("counted")) or (r.get("ask") or 0) > 0


# Which published key each adjustable field lands in, per family — so the
# conservation check can add a hand correction to the side the members are on.
_ADJ_TO_CHECK = {
    "ret_billed_target": "ret_billed", "ret_billed_non_target": "ret_billed",
    "ret_paid_target": "ret_paid", "ret_paid_non_target": "ret_paid",
    "rev_up_target": "rev_up", "rev_up_non_target": "rev_up",
    "rev_retained_target": "rev_retained",
    "rev_retained_non_target": "rev_retained",
    "drops_target": "drops", "drops_non_target": "drops",
    "drops_revenue_target": "drops_revenue",
    "drops_revenue_non_target": "drops_revenue",
    "new_members_target": "new_members", "new_members_non_target": "new_members",
    "revenue_target": "revenue", "revenue_non_target": "revenue",
    "hosp_bills_target": "hosp_bills", "hosp_bills_non_target": "hosp_bills",
    "allied_bills": "allied_bills",
}

# Which family each adjustable field belongs to, so a page shows only the
# corrections inside the number it is displaying. Without this the Drops view
# listed retention corrections and vice versa (Jiho, 8/14).
_FIELD_FAMILY = {
    "ret_billed_target": "Retention", "ret_billed_non_target": "Retention",
    "ret_paid_target": "Retention", "ret_paid_non_target": "Retention",
    "rev_up_target": "Retention", "rev_up_non_target": "Retention",
    "rev_retained_target": "Retention", "rev_retained_non_target": "Retention",
    "ret_comped_target": "Retention", "ret_comped_non_target": "Retention",
    "ret_comped_dollars_target": "Retention",
    "ret_comped_dollars_non_target": "Retention",
    "ret_bob": "Retention", "ret_bob_dollars": "Retention",
    "drops_target": "Drops", "drops_non_target": "Drops",
    "drops_revenue_target": "Drops", "drops_revenue_non_target": "Drops",
    "new_members_target": "New Members / New Sales",
    "new_members_non_target": "New Members / New Sales",
    "new_members_bob": "New Members / New Sales",
    "revenue_target": "New Members / New Sales",
    "revenue_non_target": "New Members / New Sales",
    "revenue_bob_target": "New Members / New Sales",
    "revenue_bob_non_target": "New Members / New Sales",
    "revenue_comped_new": "New Members / New Sales",
    "hosp_bills_target": "Billables", "hosp_bills_non_target": "Billables",
    "allied_bills": "Billables",
    "pen_market_restaurant": "Penetration", "pen_market_lodging": "Penetration",
    "pen_active_restaurant": "Penetration", "pen_active_lodging": "Penetration",
    "pen_market_nt_restaurant": "Penetration",
    "pen_market_nt_lodging": "Penetration",
    "pen_active_nt_restaurant": "Penetration",
    "pen_active_nt_lodging": "Penetration",
}

_CHECK_KEY = {
    "members billed": "ret_billed", "members paid": "ret_paid",
    "revenue up": "rev_up", "revenue retained": "rev_retained",
    "drops": "drops", "dropped revenue": "drops_revenue",
    "new members": "new_members", "new sales revenue": "revenue",
    "hospitality billables": "hosp_bills", "allied billables": "allied_bills",
}


def _conserve(members: List[dict], published: Dict, family: str,
              adjustments: Optional[List[dict]] = None) -> Dict:
    """Do the member rows reproduce the published cell? Loud when not.

    A hand adjustment is part of the answer, not a discrepancy: the published
    cell carries it, so the members' side must carry it too or every adjusted
    cell would report as broken. The equation is
    Σ member rows + Σ adjustments == published cell.
    """
    problems = []
    by_key: Dict[str, float] = {}
    for e in (adjustments or []):
        key = _ADJ_TO_CHECK.get(e.get("field"))
        if key:
            by_key[key] = by_key.get(key, 0.0) + float(e.get("delta") or 0)
    counted = [r for r in members if r.get("counted")]
    if family == "Retention":
        cohort = [r for r in members if _in_cohort(r)]
        billed = len(cohort)
        paid = sum(1 for r in cohort if r.get("counted"))
        ask = sum(r.get("ask") or 0 for r in cohort)
        got = sum(r.get("retained") or 0 for r in cohort)
        checks = [("members billed", billed, published.get("ret_billed")),
                  ("members paid", paid, published.get("ret_paid")),
                  ("revenue up", round(ask, 2), round(published.get("rev_up") or 0, 2)),
                  ("revenue retained", round(got, 2),
                   round(published.get("rev_retained") or 0, 2))]
    elif family == "Drops":
        checks = [("drops", len(counted), published.get("drops")),
                  ("dropped revenue",
                   round(sum(r.get("amount") or 0 for r in counted), 2),
                   round(published.get("drops_revenue") or 0, 2))]
    elif family == "Billables":
        # allied is encoded as band == "Allied" on rendered rows (8/6:
        # checking a nonexistent "allied" key lumped 17 allied into hosp)
        hosp = sum(1 for r in counted if r.get("band") != "Allied")
        alld = sum(1 for r in counted if r.get("band") == "Allied")
        checks = [("hospitality billables", hosp, published.get("hosp_bills")),
                  ("allied billables", alld, published.get("allied_bills"))]
    elif family == "Penetration":
        def _n(seg, band, active_only):
            return sum(1 for r in members
                       if r.get("segment") == seg and r.get("band") == band
                       and (r.get("counted") if active_only else True))
        checks = [
            ("active target restaurants", _n("Restaurant", "Target", True),
             published.get("active_target_restaurant")),
            ("target restaurant market", _n("Restaurant", "Target", False),
             published.get("market_target_restaurant")),
            ("active target lodging", _n("Lodging", "Target", True),
             published.get("active_target_lodging")),
            ("target lodging market", _n("Lodging", "Target", False),
             published.get("market_target_lodging")),
            ("active non-target restaurants", _n("Restaurant", "Non-Target", True),
             published.get("active_nt_restaurant")),
            ("active non-target lodging", _n("Lodging", "Non-Target", True),
             published.get("active_nt_lodging")),
        ]
    elif family == "New Members / New Sales":
        # BOB joins are INSIDE the band revenue/counts (the BOB line is a
        # visibility slice, not an exclusion) — 8/6: filtering them out
        # false-flagged the whole BOB enrollment season
        checks = [("new members", len(counted), published.get("new_members")),
                  ("new sales revenue",
                   round(sum(r.get("amount") or 0 for r in counted), 2),
                   round(published.get("revenue") or 0, 2))]
    else:
        checks = []
    for label, got_v, want in checks:
        if want is None:
            continue
        got_v = (got_v or 0) + by_key.get(_CHECK_KEY.get(label, ""), 0.0)
        if abs((got_v or 0) - want) > 0.011:
            problems.append(f"{label}: receipts say {got_v}, the face says {want}")
    return {"ok": not problems, "problems": problems}


def trace(period: str, family: str, territory: str,
          month: Optional[str] = None) -> Dict:
    """Everything a human needs to believe (or challenge) one number."""
    rows, fields = _load(period)
    # FROZEN months (the two-photograph close): the FACE shows the close
    # record's values, not the cache — conserve against what is published
    from reports.membership_performance_tracker.logic import month_close as _mc
    frozen_note = None
    # 8/10 review: this ran for RETENTION ONLY, so every other family
    # conserved against the raw cache while the workbook showed the sealed
    # face — after July's re-seal the page red-alarmed 30 correct drops
    # cells. The baseline must be what is PUBLISHED for every family.
    class _F:
        pass
    import copy as _copy
    _closes = _mc.load_all_closes()
    if _closes:
        fields = _copy.deepcopy(fields)
        holder = _F()
        for k, v in fields.items():
            setattr(holder, k, v)
        _mc.apply_frozen(holder, _closes, period=period)
        fields = {k: getattr(holder, k) for k in fields}
    # ADJUSTMENTS (8/14): the report applies these between apply_frozen and the
    # mapper, so this page must apply them too — otherwise the number on the
    # screen and the number in the workbook disagree, which is the one thing
    # this page exists to prevent.
    _adjustments = _adj.for_build(
        _adj.load_fy(_adj.fy_start_of(period)), period)
    if _adjustments:
        fields = _copy.deepcopy(fields)
        holder = _F()
        for k, v in fields.items():
            setattr(holder, k, v)
        _adj.apply_to(holder, _adjustments, recompute=_adj.recompute)
        fields = {k: getattr(holder, k) for k in fields}
    # The note must fire whenever the frozen slice was actually APPLIED above,
    # not only on the sealed period's own rebuild. `apply_frozen` month-slices
    # retention onto EVERY build of the same fiscal year, so on the 2026-08
    # report July's face is the seal while its receipts are a fresh recompute —
    # a by-design difference. Gating the note on `doc["period"] == period` made
    # it unreachable on exactly those builds, so the page alarmed with no
    # explanation (found 2026-08-12 on July retention). Same class as the 8/10
    # baseline defect noted above: the face was corrected, the wording was not.
    _build_fy = _mc._fy_start_of(period)
    for doc in _closes:
        _doc_fy = _mc._fy_start_of(doc.get("period"))
        if (_build_fy is not None and _doc_fy is not None
                and _doc_fy != _build_fy):
            continue                      # apply_frozen skipped it too
        if (month == doc.get("month") and family == "Retention"
                and doc.get("frozen")):
            # PLAIN FACT, NOT AN EXCUSE (2026-08-14). This used to read
            # "FROZEN from the pre-ITD snapshot (<filename>); receipts show
            # the post-ITD capture — the two-photograph close, by design".
            # Three problems. It is only ever shown on the SUCCESS strip —
            # there is no alarm branch (ruled 8/13) — so it could never
            # explain a mismatch; it only undercut a claim that had just
            # passed, which is why it read as a false scare. It was written
            # in vocabulary that exists nowhere outside this repo. And it
            # borrowed the credibility of a real rule: the two-photograph
            # close says RETENTION is measured pre-ITD and BILLABLES post-ITD,
            # which is true and load-bearing — it says nothing that sanctions
            # a retention number and its own member list coming from
            # different moments. So: state what a reader needs, and stop.
            frozen_note = (f"{month} is closed — these are the numbers it was "
                           f"closed with, so they do not move.")
    # month-less rows: photo families carry one capture (any month view);
    # Drops' month-less rows are EXCLUSIONS (RRO/no-cycle) whose reason
    # should be visible whichever month is viewed (8/6 round-2: the Retro
    # Coordinator territory always rendered empty)
    members = [r for r in rows
               if r.get("metric") == family
               and (territory == TOTAL_TERRITORY
                    or r.get("territory") == territory)
               and (territory != TOTAL_TERRITORY or r.get("territory"))
               and (month is None or r.get("month") == month
                    or (family in ("Billables", "Penetration", "Drops")
                        and not r.get("month")))]
    members.sort(key=lambda r: (not r.get("counted"),
                                str(r.get("territory") or ""),
                                str(r.get("member") or "")))
    published = _published(fields, family, territory, month)
    # ONLY what is inside THIS number: same family, same territory (or Total),
    # same month. The page says "this number includes…", so it must not list a
    # correction that lives somewhere else on the report.
    cell_adjustments = [e for e in _adj.for_build(
        _adj.load_fy(_adj.fy_start_of(period)), period)
                        if _FIELD_FAMILY.get(e.get("field")) == family
                        and (territory in (TOTAL_TERRITORY, e.get("territory")))
                        and (month is None or e.get("month") == month)]
    conservation = _conserve(members, published, family, cell_adjustments)

    return {
        "period": period, "family": family, "territory": territory,
        "month": month, "members": members, "published": published,
        "conservation": conservation,
        "adjustments": cell_adjustments,
        "frozen_note": frozen_note,
    }
