"""crystal_feed.py — the two cache families Crystal owns, laid over SData's.

Crystal earned exactly two jobs by beating SData at them (docs/THE-PLAN.md
Part 3, decided from both experiments' failures):

  · BILLABLES — the FTE report's statewide total is Jennifer's own published
    figure (2,143 vs our 2,137) and its FTE bands give Target/Non-Target with
    no size inference of ours.
  · DROPS — the report simply *is* the answer: FY-windowed, dues on every row,
    and 19 real status reasons. SData needed a billable gate, a closure union,
    an invented reason vocabulary and a status-flip history parser to answer
    the same question, and two bugs hid in that machinery until 2026-07-27.

Everything else stays on the SData ledger, because only the ledger can answer a
past month. Overwriting a family Crystal cannot answer retroactively is exactly
what produced retention 0/10 and $0 revenue for five months on 7/27.

The overlay REPLACES those fields in the in-memory data (`fields.update`) —
SData's version does NOT survive underneath. What survives is the local cache
file, which a live pull writes BEFORE the overlay runs (see runner.py, and
`_meta.source = 'slx-preoverlay'`). That file is the cross-check; the
published workbook carries only Crystal's values for these families.
"""
import json
import warnings
from dataclasses import dataclass, field as _field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from reports.membership_performance_tracker.logic import crystal as _crystal
from reports.membership_performance_tracker.logic import crystal_parsers as cp
from reports.membership_performance_tracker.logic.crystal_compile import (
    FY_MONTHS, MONTH_ABB, _grid, _plain, _suffix,
)

# ---------------------------------------------------------------------------
# Temporal semantics, DECLARED per family — never decided per month.
# ---------------------------------------------------------------------------
# The program must behave identically for any period. What differs between
# families is not the calendar but what their report MEANS:
#
#   SNAPSHOT    the export describes the day it ran, so only an export from
#               that period can answer it. Borrowing another month's would be
#               a lie about when the count was true.
#   FY_WINDOWED the export's parameter window spans a whole fiscal year and
#               every row carries its own month, so ANY export from the SAME
#               fiscal year answers any month inside it — but never one from a
#               different FY, whose window excludes these rows entirely.
#
# Where the preferred export is absent, the family falls back to SData, which
# can always answer. That is a precedence chain, not a special case: it holds
# for every month, past and future, with no period named anywhere in the code.
SNAPSHOT = "snapshot"
FY_WINDOWED = "fy_windowed"
FAMILY_SEMANTICS = {"billables": SNAPSHOT, "drops": FY_WINDOWED}

# The families Crystal owns. Anything not listed here is SData's and must not
# be touched by this module.
BILLABLES_FIELDS = ("hosp_bills_target", "hosp_bills_non_target", "allied_bills")
DROPS_FIELDS = ("drops_target", "drops_non_target", "drops_revenue_target",
                "drops_revenue_non_target", "drops_by_category")


@dataclass
class OverlayReport:
    """What the overlay actually did — printed by the runner, never inferred."""
    applied: List[str] = _field(default_factory=list)
    skipped: Dict[str, str] = _field(default_factory=dict)
    sources: Dict[str, dict] = _field(default_factory=dict)
    # Rows the rulings exclude from the counts but Jen wants VISIBLE — the
    # flag list is the contract with her ("if it happens, I want to know").
    flags: Dict[str, list] = _field(default_factory=dict)


def _manifest(period: str, root) -> Tuple[Path, dict]:
    folder = Path(root) / period
    path = folder / "manifest.json"
    if not path.exists():
        return folder, {}
    return folder, json.loads(path.read_text())


# Only these four exports feed a published number (Jiho 8/12); the other six
# are SData-computed or comparison-only, so their vintage is not a defect.
_CONSUMED = ("billables", "billables_fte", "drops_hospitality", "drops_allied")
# Drops are the POST-ITD capture, taken after the month closes — July's ran
# 08-06 for an 08-05 close. Lagging is the two-phase close working, not rot.
_STALENESS_CHECKED = ("billables", "billables_fte")
_STALE_DAYS = 3


def manifest_defects(manifest: dict) -> List[dict]:
    """Consumed captures that cannot be trusted, with the reason.

    A capture we cannot DATE is a guard we cannot run: 2026-08's `drops_allied`
    entry carried `file_name` alone, so the freshness check could not evaluate
    it at all and an arbitrarily stale allied export would have published in
    silence. `crystal.py:245` always writes six fields, so such an entry never
    came from the fetcher — but nothing noticed it either, and that part is
    ours.

    Staleness is judged RELATIVE to the newest capture in the same manifest
    rather than against today, so reading an old period's manifest does not
    cry wolf about a month that is legitimately finished.
    """
    from datetime import date
    out: List[dict] = []
    dated = {}
    for key, entry in (manifest or {}).items():
        raw = (entry or {}).get("run_date")
        if raw:
            try:
                dated[key] = date(*(int(x) for x in str(raw)[:10].split("-")))
            except (ValueError, TypeError):
                pass
    # BASELINE EXCLUDES DROPS (caught on July's real manifest): drops are the
    # post-ITD capture and land days after the rest — July's ran 08-06 against
    # a nightly set from 07-26/27. Using the overall newest made the late-by-
    # design capture the yardstick and reported billables as "11 days stale"
    # when it was one day behind its own cohort. Compare like with like.
    newest = max((d for k, d in dated.items() if not k.startswith("drops")),
                 default=None)

    for key in _CONSUMED:
        entry = (manifest or {}).get(key)
        if not entry:
            out.append({"key": key, "kind": "absent",
                        "defect": "no manifest entry — this month's numbers "
                                  "come from an older export by fallback"})
            continue
        if key not in dated:
            out.append({"key": key, "kind": "undatable",
                        "file_name": entry.get("file_name"),
                        "defect": "manifest entry has no run_date, so the "
                                  "freshness check cannot evaluate it"})
            continue
        if key in _STALENESS_CHECKED and newest is not None:
            behind = (newest - dated[key]).days
            if behind > _STALE_DAYS:
                out.append({"key": key, "kind": "stale",
                            "file_name": entry.get("file_name"),
                            "run_date": dated[key].isoformat(),
                            "days_behind": behind,
                            "defect": f"{behind} days older than this month's "
                                      f"newest capture"})
    return out


def _fy_of(period: str) -> int:
    """Fiscal year start for a YYYY-MM period. WHA FY runs Oct 1 → Sep 30."""
    year, month = (int(x) for x in period.split("-")[:2])
    return year if month >= 10 else year - 1


def _latest_in_same_fy(key: str, root, period: str) -> Tuple[Optional[Path], dict]:
    """Newest archived period in the SAME fiscal year that holds `key`.

    For FY_WINDOWED families only. Staying inside the fiscal year is the whole
    point: the drops StatusDate window moves each October, so an export from
    the next FY contains none of this year's rows and would quietly yield an
    empty grid for every historical month — a failure that would first appear
    in October and look like data loss rather than a lookup bug.
    """
    root = Path(root)
    if not root.exists():
        return None, {}
    want_fy = _fy_of(period)
    for folder in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
        try:
            if _fy_of(folder.name) != want_fy:
                continue
        except (ValueError, IndexError):
            continue
        path = folder / "manifest.json"
        if not path.exists():
            continue
        manifest = json.loads(path.read_text())
        if key in manifest:
            return folder, manifest
    return None, {}


def _snapshot_month(period: str) -> str:
    return MONTH_ABB[int(period.split("-")[1])]


def _billables_fields(fte_split: Dict[str, Dict[str, float]],
                      allied: Dict[str, float], snapshot_month: str) -> Dict[str, Dict]:
    """Billables are a SNAPSHOT — they describe the day the report ran.

    Only the snapshot month is written; the other cells stay zero rather than
    repeating a count across months it never described.
    """
    target, non_target, allied_grid = _grid(), _grid(), _grid()
    for territory, cell in fte_split.items():
        target[territory][snapshot_month] = cell.get("target", 0.0)
        # The CRM's own unbanded 'Others' ride in Non-Target: Jennifer's
        # published total includes them (2,143 with, 2,036 without — below
        # every month she ever reported), and Target means clearing a size
        # threshold a size-less member has not been shown to clear.
        non_target[territory][snapshot_month] = (cell.get("non_target", 0.0)
                                                 + cell.get("unbanded", 0.0))
    for territory, count in allied.items():
        allied_grid[territory][snapshot_month] = count
    return {
        "hosp_bills_target": _plain(target),
        "hosp_bills_non_target": _plain(non_target),
        "allied_bills": _plain(allied_grid),
    }


def feed_billables(period: str, root=None) -> Dict[str, Dict]:
    """Billables from the FTE report, plus Allied from the by-BM summary."""
    root = root or _crystal.ARCHIVE_ROOT
    folder, manifest = _manifest(period, root)
    split = cp.fte_target_split(
        cp.parse_billables_fte((folder / manifest["billables_fte"]["file_name"]).read_bytes()))
    allied: Dict[str, float] = {}
    if "billables" in manifest:
        for cell in cp.parse_billables((folder / manifest["billables"]["file_name"]).read_bytes()):
            if cell.category.startswith("Allied"):
                allied[cell.territory] = allied.get(cell.territory, 0.0) + cell.count
    return _billables_fields(split, allied, _snapshot_month(period))


def _file_month(bill_month: Optional[int], drop_date, fy_start_year: int,
                today) -> Tuple[Optional[str], Optional[str]]:
    """Which column a counted drop belongs in: (month_label, fallback_reason).

    THE AXIS IS THE EVENT (ratified 2026-07-31, Jiho): a drop files in the
    month its status actually changed — Jen's own SOP counts drops with a
    1st-to-last-of-month date range, and a real date carries its own YEAR,
    which the bare bill-month axis never did (it filed nine-month-old
    September-class failures under NEXT September's column).

    The date must be PLAUSIBLE — inside this FY window and not in the future.
    The 41-stale-dates class (2026-07-27: 2012–2024 flip dates on members
    billed in FY25/26) is treated as dateless, never trusted.

    Fallback for the dateless (conditional, ratified same day):
      · class window already CLOSED (close = end of bill month + 1) → file at
        the close month — the non-payer shape;
      · window still open → they cannot have failed a collectible bill, so we
        learned of the loss NOW: file in the current month.
    Every fallback filing carries a reason so it can be flagged, not silent.
    """
    from datetime import date as _d
    import calendar as _c
    # BOTH edges of "this FY window" (the upper one was missing until 8/11).
    # `today` alone does not bound the year: rebuilding a CLOSED fiscal year —
    # amendments, repair-from-archive — puts the wall clock past the FY end,
    # and the drops schedule's own window runs to 2030-12-31, so the export
    # genuinely carries later-FY rows. A next-FY date is not a fact about this
    # year; it is as unusable here as the 41 stale dates, and falls back the
    # same way rather than filing silently into the matching month name.
    fy_lo = _d(fy_start_year, 10, 1)
    fy_hi = _d(fy_start_year + 1, 9, 30)
    if drop_date is not None and fy_lo <= drop_date <= min(fy_hi, today):
        return MONTH_ABB.get(drop_date.month), None
    if not bill_month or bill_month not in MONTH_ABB:
        return None, None
    close_m = 1 if bill_month == 12 else bill_month + 1
    close_y = fy_start_year if close_m >= 10 else fy_start_year + 1
    close = _d(close_y, close_m, _c.monthrange(close_y, close_m)[1])
    if close <= today:
        why = ("end date on record is stale or unusable — filed at the class close"
               if drop_date is not None else
               "no end date on record at capture — filed at the class close")
        return MONTH_ABB.get(close_m), why
    return MONTH_ABB.get(today.month), ("class window still open — loss "
                                        "learned this month, filed now")


def _ADMIN_REASONS() -> set:
    """The ruled admin/housekeeping reasons, read from their ONE definition.

    Imported lazily and by reference rather than copied: two lists of the same
    rule drift apart on the first edit, and this rule already spent months
    applying on one path and not the other.
    """
    from reports.membership_performance_tracker.logic.drops import ADMIN_REASONS
    return ADMIN_REASONS


def drop_ledger(period: str, root=None, band: Optional[Callable] = None,
                hygiene: Optional[Callable] = None,
                drop_date_of: Optional[Callable] = None,
                today=None) -> List[dict]:
    """THE drops loop. One pass over the export; one entry per exported row.

    ONE PATH FOR THE NUMBER AND ITS EXPLANATION (ruled 2026-08-14, Jiho — see
    docs/superpowers/specs/2026-08-14-receipts-single-path.md). Until today the
    published drop counts and the member list that explains them were produced
    by two separate loops over the same export: `feed_drops` here and
    `render_drops` in receipts_render. Every rule had to be written twice, and
    twice this month one loop learned a rule the other did not — the allied
    ruling, and the admin-reason exclusion — which made the conservation gate
    refuse every receipt for two runs running.

    So neither of them holds a rule any more. This does, once, and they became
    two projections of it:
      · `feed_drops`  sums the counted entries into the published grids;
      · `render_drops` renders every entry as a member row for the Trace page.
    A cell and the rows behind it can no longer disagree, because they are the
    same objects read twice.

    TOTALITY IS THE POINT. Every exported row leaves here with exactly one
    entry, counted or not, carrying the reason it was or was not counted. A row
    that vanishes is a row nobody can ask about.

    Entry shape:
      row       the parsed export row (name, mid, territory, dues, ...)
      counted   True only if it lands in a published cell
      month     the FY month abbreviation it files under ("" when uncounted)
      band      "Target" / "Non-Target" ("" when uncounted)
      reason    Crystal's OWN status reason, raw — `drops_by_category` is keyed
                on it, so it must survive un-decorated
      explain   the same fact in plain words, for a human reading the Trace
      key_date  the flip date used for filing, when there was one
      flag      (family, payload) for the flag list, or None

    THE TWO EXCLUSIONS FROM THE 2026-07-30 RECORDED CALL (Jen + Shannon):
      · RRO / RRO LNI Active rows are NEVER drops — "They're not a dropped.
        RRO is not a dropped." They sit on the export "just as FYI".
      · Bill month 14 moves the row out REGARDLESS of status — "if it's 14, it
        moves completely out of the calculation" (Shannon's synthesis, Jen
        confirming). That falls out of the month lookup below.
    """
    root = root or _crystal.ARCHIVE_ROOT
    folder, manifest = _manifest(period, root)
    if "drops_hospitality" not in manifest:
        # FY_WINDOWED: any export from the SAME fiscal year still holds these rows.
        folder, manifest = _latest_in_same_fy("drops_hospitality", root, period)
    rows = cp.parse_drops_hospitality(
        (folder / manifest["drops_hospitality"]["file_name"]).read_bytes())
    band = band or (lambda _r: "Unknown")
    from datetime import date as _date_cls
    _today = today or _date_cls.today()

    # Allied drops are read and listed, never counted (ruled 2026-08-14; see
    # the allied branch below). Same FY-window fallback; absence degrades
    # loudly — it costs the detail list, not the totals.
    allied_rows: List[cp.DropRow] = []
    a_folder, a_manifest = folder, manifest
    if "drops_allied" not in a_manifest:
        a_folder, a_manifest = _latest_in_same_fy("drops_allied", root, period)
    if a_manifest and "drops_allied" in a_manifest:
        allied_rows = cp.parse_drops_allied(
            (a_folder / a_manifest["drops_allied"]["file_name"]).read_bytes())
    else:
        warnings.warn("[crystal-drops] no Allied drops export archived this FY "
                      "— the published drop totals are UNAFFECTED (allied is "
                      "not counted, ruled 2026-08-14), but allied losses "
                      "cannot be listed in the drop detail until one is "
                      "captured.")

    allied_ids = {id(r) for r in allied_rows}
    return [classify_drop(row, id(row) in allied_ids, band, hygiene,
                          drop_date_of, _fy_of(period), _today)
            for row in rows + allied_rows]


def classify_drop(row, allied: bool, band: Optional[Callable] = None,
                  hygiene: Optional[Callable] = None,
                  drop_date_of: Optional[Callable] = None,
                  fy_start: int = 0, today=None) -> dict:
    """ONE exported row in, ONE ledger entry out. Every drop rule lives here.

    Split out of `drop_ledger` so the rules can be exercised on plain row
    objects with no Crystal archive behind them — the tests used to keep their
    own copy of these branches for that, which is the same duplication this
    build exists to end. See `drop_ledger` for the entry shape.
    """
    from datetime import date as _date_cls
    band = band or (lambda _r: "Unknown")
    today = today or _date_cls.today()

    def _entry(counted=False, month="", band_name="", reason="",
               explain="", key_date="", flag=None):
        return {"row": row, "allied": allied,
                "counted": counted, "month": month or "", "band": band_name,
                "reason": reason, "explain": explain,
                "key_date": key_date, "flag": flag}

    if allied:
        if not row.territory or not row.status_reason:
            # 8/10: rows the export prints outside every group header (house
            # accounts) can never land in a territory column.
            return _entry(
                explain="printed outside every territory and status group in "
                        "the Dropped Allied export — there is no territory to "
                        "put it in; not counted",
                flag=("ungrouped_export_rows",
                      {"name": row.name, "mid": row.mid, "dues": row.dues,
                       "reason": "printed outside every territory/status "
                                 "group in the Dropped Allied export — "
                                 "cannot be attributed to a territory; "
                                 "not counted"}))
        # RULED 2026-08-14 (Jiho, following the same meeting's retention
        # ruling): allied leaves the DROP COUNTS too. A member who was never
        # counted as retained cannot count against a TM on the way out — that
        # asymmetry is worth real money on a commission line. They stay fully
        # visible: flagged here and rendered as an uncounted row with the same
        # reason, which is what Steven asked for ("we'll see which one is an
        # allied, which one is a hospitality member").
        return _entry(
            reason=row.status_reason or "",
            explain="allied member — tracked separately, not counted as a "
                    "hospitality drop (ruled 2026-08-14)",
            flag=("allied_drops",
                  {"name": row.name, "mid": row.mid,
                   "territory": row.territory, "dues": row.dues,
                   "reason": row.status_reason,
                   "note": "allied member — tracked separately, not counted "
                           "as a hospitality drop (ruled 2026-08-14)"}))
    if str(row.status or "").startswith("RRO"):
        return _entry(
            reason=row.status_reason or "",
            explain="record moved to retro",
            flag=("rro_fyi",
                  {"name": row.name, "mid": row.mid,
                   "territory": row.territory, "dues": row.dues,
                   "reason": row.status_reason}))
    if str(row.status_reason or "").strip() in _ADMIN_REASONS():
        # ADMIN / RECORD-HOUSEKEEPING REASONS ARE NOT MEMBER LOSSES (ratified
        # 13:40; the rule has always lived in drops.ADMIN_REASONS). It was
        # only ever applied on the SData path — the Crystal overlay, which is
        # what actually publishes, never consulted it. Found 2026-08-11:
        # Cheeky Noodles ("New Lead", Southwest, $730) and Gill Brothers ("New
        # Record from a Closed/ Sold", NorthCentral, $510) were both published
        # as drops. A lead that never became a member cannot be a member loss.
        return _entry(
            reason=row.status_reason or "",
            explain=(str(row.status_reason).strip()
                     + " — the CRM record was replaced, not a member leaving. "
                       "Not counted as a drop."),
            flag=("admin_reason_excluded",
                  {"name": row.name, "mid": row.mid,
                   "territory": row.territory, "dues": row.dues,
                   "reason": row.status_reason,
                   "defect": "record housekeeping, not a member loss — "
                             "excluded from the drop counts by rule"}))
    if row.status not in ("", "Inactive", "Closed"):
        # An unknown status group is a NEW report vocabulary — exclude from the
        # headline and surface it, never silently absorb (the unclassified-
        # charge-code pattern). It gets a row of its own like everything else:
        # an export row with no receipt is a row nobody can ask about.
        return _entry(
            reason=row.status_reason or "",
            explain=(f"the record's status is '{row.status}', which is not one "
                     f"of this export's closure statuses — not counted as a "
                     f"drop"),
            flag=("unknown_status",
                  {"name": row.name, "mid": row.mid, "status": row.status}))
    if not (row.bill_month and MONTH_ABB.get(row.bill_month)):
        # A row with no usable bill month cannot be attributed to a cycle — and
        # per the 2026-07-30 ruling, bill month 14 is OUT by design.
        return _entry(
            reason=row.status_reason or "",
            explain="no billing cycle on the record — cannot tell which month "
                    "it belongs to",
            flag=("no_cycle",
                  {"name": row.name, "mid": row.mid,
                   "bill_month": row.bill_month, "status": row.status,
                   "dues": row.dues}))
    _drop_date = drop_date_of(row) if drop_date_of else None
    _key_date = str(_drop_date or "")
    why = hygiene(row) if hygiene else None
    if why:
        # D2 AMENDMENT (approved 2026-08-04): stale billing no longer excludes
        # a REAL closure. If the status flip carries a plausible date inside
        # this FY, the drop COUNTS in its flip month, valued at Dues Level (the
        # export's dues column) — Jen's convention. Without a plausible flip
        # date (Brooklyn Bros 2003 class) the row stays excluded: the D4
        # window-leak guard survives.
        _fm, _fb = _file_month(row.bill_month, _drop_date, fy_start, today)
        if _fm and not _fb:
            return _entry(
                counted=True, month=_fm, band_name=_band_name(band, row),
                reason=row.status_reason or "Unspecified",
                explain=((row.status_reason or "Unspecified")
                         + " (counted on the date the CRM marked them "
                           "inactive — the billing record was out of date)"),
                key_date=_key_date,
                flag=("hygiene_counted",
                      {"name": row.name, "mid": row.mid,
                       "territory": row.territory, "dues": row.dues,
                       "filed": _fm, "billing_note": why,
                       "defect": "counted at status-flip date; billing is "
                                 "stale — fix the record"}))
        return _entry(
            reason=row.status_reason or "",
            explain="no current dues on this record — nothing to count as lost",
            flag=("hygiene",
                  {"name": row.name, "mid": row.mid,
                   "territory": row.territory, "dues": row.dues,
                   "bill_month": row.bill_month, "reason": why}))
    # EVENT AXIS (2026-07-31): file by flip date, not by the year-less bill
    # month — see _file_month. The bm-validity gate above still guarantees a
    # fallback target exists.
    month, fb = _file_month(row.bill_month, _drop_date, fy_start, today)
    return _entry(
        counted=True, month=month, band_name=_band_name(band, row),
        reason=row.status_reason or "Unspecified",
        explain=((row.status_reason or "Unspecified")
                 + (" (date estimated)" if fb else "")),
        key_date=_key_date,
        flag=(("drop_date_fallback",
               {"name": row.name, "mid": row.mid, "territory": row.territory,
                "bill_month": row.bill_month, "filed": month,
                "reason": fb}) if fb else None))


def _band_name(band: Callable, row) -> str:
    """Target/Non-Target for a COUNTED row — allied never reaches here."""
    return "Target" if _suffix(band(row)) == "target" else "Non-Target"


def feed_drops(period: str, root=None, band: Optional[Callable] = None,
               flags_out: Optional[Dict[str, list]] = None,
               hygiene: Optional[Callable] = None,
               drop_date_of: Optional[Callable] = None,
               today=None) -> Dict[str, Dict]:
    """The published drop grids — a SUM over `drop_ledger`, nothing more.

    A drop in month M means N members are no longer billed in cycle M — which
    is why a bill month is all the row needs and why rows without one are
    excluded rather than guessed into a cell.

    Every rule this function used to carry now lives in `drop_ledger`, which
    also feeds the receipts. Keep this a projection: a rule added here and not
    there is exactly the divergence the single-path build removed.
    """
    entries = drop_ledger(period, root, band, hygiene, drop_date_of, today)
    return aggregate_drops(entries, flags_out)


def aggregate_drops(entries: List[dict],
                    flags_out: Optional[Dict[str, list]] = None) -> Dict[str, Dict]:
    """Ledger entries → the five published grids, plus the flag list.

    The counted entries and the member rows on the Trace page are the same
    objects; this is the only place they become numbers.
    """
    flags = flags_out if flags_out is not None else {}
    counts = {"target": _grid(), "non_target": _grid()}
    dollars = {"target": _grid(), "non_target": _grid()}
    reasons: Dict[str, Dict] = {}
    skipped: Dict[str, int] = {}
    total_rows = 0
    for e in entries:
        row = e["row"]
        total_rows += 1
        if e["flag"]:
            family, payload = e["flag"]
            flags.setdefault(family, []).append(payload)
            if family == "no_cycle":
                key = (f"bill month {row.bill_month!r}" if row.bill_month
                       else "no bill month")
                skipped[key] = skipped.get(key, 0) + 1
        if not e["counted"]:
            continue
        suffix = "target" if e["band"] == "Target" else "non_target"
        counts[suffix][row.territory][e["month"]] += 1
        dollars[suffix][row.territory][e["month"]] += row.dues
        grid = reasons.setdefault(e["reason"] or "Unspecified", _grid())
        grid[row.territory][e["month"]] += 1
    if skipped:
        total = sum(skipped.values())
        warnings.warn(
            f"[crystal-drops] skipped {total} of {total_rows} drop rows with no "
            f"usable bill month — they cannot be attributed to a billing cycle: "
            + "; ".join(f"{v}× {k}" for k, v in sorted(skipped.items())))

    # GATE A (2026-07-28): the split and the per-reason grid are two views of
    # ONE loop over ONE export, so they must agree exactly. A divergence means a
    # row was counted into one view and lost from the other — that is a number
    # nobody can defend, so refuse rather than publish it.
    split_total = sum(v for g in counts.values() for terr in g.values()
                      for v in terr.values())
    reason_total = sum(v for g in reasons.values() for terr in g.values()
                       for v in terr.values())
    if abs(split_total - reason_total) > 0.005:
        raise ValueError(
            f"[gate] drops split does not account for every row: "
            f"Target+Non-Target={split_total:g} but the reason grid holds "
            f"{reason_total:g}. One view lost rows the other kept — refusing "
            f"to publish an unexplainable drops figure.")

    return {
        "drops_target": _plain(counts["target"]),
        "drops_non_target": _plain(counts["non_target"]),
        "drops_revenue_target": _plain(dollars["target"]),
        "drops_revenue_non_target": _plain(dollars["non_target"]),
        "drops_by_category": {r: _plain(g) for r, g in reasons.items()},
    }




def overlay(fields: Dict, period: str, root=None,
            band: Optional[Callable] = None,
            hygiene: Optional[Callable] = None,
            drop_date_of: Optional[Callable] = None) -> Tuple[Dict, OverlayReport]:
    """Lay Crystal's two families over SData's fields. Everything else untouched.

    A missing or unparsable export leaves SData's value in place and says so
    loudly. SData's numbers are valid — just not preferred — so the run
    continues, but a silent pass must never be mistakable for a Crystal run.
    """
    root = root or _crystal.ARCHIVE_ROOT
    report = OverlayReport()
    _, manifest = _manifest(period, root)

    # SAY SO WHEN A CAPTURE CANNOT BE TRUSTED (2026-08-12). A stale or
    # undatable export used to reach a human only as a print() into
    # scheduled_run.log, which nobody reads, while the overlay quietly fell
    # back to an older month's file. These land on the Flags sheet instead.
    for _d in manifest_defects(manifest):
        report.flags.setdefault("capture_not_trustworthy", []).append(_d)

    # 2026-07-30 (Jiho): "drop the crystal overlay, sdata computes billables."
    # Reconciling billables against Crystal would assert the report is more
    # accurate than the computation. `feed_billables` remains importable as a
    # reference reader; the overlay no longer applies it.
    for name, needs, fn in (("drops", ("drops_hospitality",), feed_drops),):
        available = dict(manifest)
        if FAMILY_SEMANTICS[name] == FY_WINDOWED and needs[0] not in available:
            _f, _m = _latest_in_same_fy(needs[0], root, period)
            available = _m or available
        missing = [k for k in needs if k not in available]
        if missing:
            report.skipped[name] = f"no archived export for {', '.join(missing)}"
            continue
        # GATE B (2026-07-28): drops carry no size on the row, so the
        # Target/Non-Target split exists ONLY through the banding bridge.
        # Without it every row reads UNKNOWN and folds into Non-Target, which
        # is indistinguishable from a real answer ("Target: 0") — exactly what
        # shipped on the cache path. No bander ⇒ keep SData's split and say so.
        if name == "drops" and band is None:
            report.skipped[name] = ("no banding available (needs an SLX client) — "
                                    "an unbanded split would read as Target 0")
            continue
        try:
            produced = fn(period, root, band, flags_out=report.flags,
                          hygiene=hygiene, drop_date_of=drop_date_of)
        except Exception as exc:                     # parser gates raise here
            report.skipped[name] = f"{type(exc).__name__}: {exc}"
            continue
        fields.update(produced)
        report.applied.append(name)
        # From the manifest actually READ — an FY-windowed family may have
        # resolved to a different period's archive, and recording the
        # requested period's manifest instead raises KeyError mid-run.
        report.sources[name] = {k: available[k] for k in needs}

    if report.skipped:
        warnings.warn(
            "[crystal-overlay] falling back to SData for: "
            + "; ".join(f"{k} ({why})" for k, why in sorted(report.skipped.items()))
            + ". These numbers are SData's, not the CRM report's.")
    return fields, report
