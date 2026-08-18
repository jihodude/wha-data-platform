"""month_close.py — the two-phase ITD close (designed with Jiho 2026-08-03).

The month a report covers is only DONE after two photographs taken at
different times (Jen's SOP, ruled 8/3 + leadership-endorsed):

  · RETENTION is true BEFORE the ITD utility runs — ITD writes off
    non-payers' bills (proven: 10/10 BM5 adjustments were backdated
    write-offs), which shrinks the billed denominator and inflates the %.
  · BILLABLES / DROPS / PENETRATION are true AFTER ITD — they describe the
    cleaned-up roster.

Because the nightly pull archives an immutable per-run snapshot, a clean
pre-ITD photograph always exists. Closing a month is ONE human event:

    "Close July — ITD was run on <date>"

which (1) freezes the retention family from the last snapshot taken BEFORE
that morning (ITD never runs before {ITD_EARLIEST_HOUR}:00), (2) verifies
the choice against the prior snapshot (an ITD wave shows as the closing
month's billed count shrinking — wrong date picked), (3) writes
close_<period>.json locally + to the hub, and (4) lets the caller trigger
the post-ITD pull. Every later build overlays the close file's values via
apply_frozen(), so a frozen column can never be silently recomputed — not
by a nightly pull, not by a code change.

Reopening = re-running freeze() with a different date. It is NEVER an
edit, and it is best-effort by definition (Jiho: "even if they rerun ITD,
it wouldn't be the ACTUAL snapshot... that should be warned") — see
REOPEN_WARNING, which the console must show verbatim.
"""
import json
import re
from datetime import date, datetime, time as dt_time, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from src.config.period import parse_period


def _fy_start_of(period: Optional[str]) -> Optional[int]:
    """Fiscal year a 'YYYY-MM' period belongs to, or None when not knowable.

    Delegates to `src/config/period.py`, which AGENTS.md names as the single
    source of truth for fiscal-year math. That derivation is already copied by
    hand in four places in this repo; this module deliberately does not become
    the fifth.
    """
    if not period:
        return None
    try:
        return parse_period(period).fy_start
    except (ValueError, AttributeError, TypeError):
        return None


def _fy_label(fy_start: int) -> str:
    return f"FY{fy_start}-{str(fy_start + 1)[2:]}"

# WHA thinks in Pacific time, period (Jiho ruling 8/5 — the association will
# never operate outside Washington). Snapshot FILENAMES stay UTC-stamped;
# every human-facing comparison translates.
WHA_TZ = ZoneInfo("America/Los_Angeles")

_ROOT = Path(__file__).resolve().parents[3]
CLOSES_DIR = _ROOT / "data" / "closes"
SNAPSHOTS_ROOT = _ROOT / "data" / "hub" / "Audit & History Log" / "Snapshots"
HUB_CLOSE_SUBPATH = "Reports/Membership Performance Report/Data/closes"

# ITD is run by a human during the workday; the nightly pull lands ~02:00.
# A snapshot from the ITD day itself, taken before this hour, is pre-ITD.
ITD_EARLIEST_HOUR = 6

# The retention family — every field the freeze covers, month-sliced.
# (goal_retention is an admin input, not a computed number: not frozen.)
RETENTION_MONTH_KEYS = [
    "ret_paid", "ret_billed",
    "ret_paid_target", "ret_paid_non_target",
    "ret_billed_target", "ret_billed_non_target",
    "retention_pct", "retention_str", "ret_status",
    "rev_retained_target", "rev_retained_non_target",
    "rev_up_target", "rev_up_non_target",
]

MONTH_OF_PERIOD = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May",
                   6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct",
                   11: "Nov", 12: "Dec"}

REOPEN_WARNING = (
    "Re-freezing is BEST-EFFORT, not a time machine: the CRM has moved on "
    "since the original pre-ITD morning, so even re-running ITD cannot "
    "recreate the actual pre-ITD state. The new freeze uses whatever the "
    "chosen snapshot saw at the time. The previous frozen numbers are kept "
    "in this close file's history."
)


def _drops_capture_date_for(period: str):
    """Run date of the capture THIS PERIOD'S BUILD WILL ACTUALLY READ.

    S2 (overnight review 8/10): this used to return the globally newest
    capture across every period folder, while the overlay resolves
    period-folder-first with an in-FY walk-back — so a fresh capture filed
    under a DIFFERENT month satisfied the gate while the build sealed an
    old one. It now mirrors crystal_feed's own resolution, and takes the
    OLDER of the hospitality and allied captures (both feed the grids, and
    the allied vintage was never checked at all).
    """
    import json as _j
    from reports.membership_performance_tracker.logic import crystal as _c
    from reports.membership_performance_tracker.logic.crystal_feed import (
        _manifest, _latest_in_same_fy)
    dates = []
    try:
        for key in ("drops_hospitality", "drops_allied"):
            folder, manifest = _manifest(period, _c.ARCHIVE_ROOT)
            if key not in (manifest or {}):
                folder, manifest = _latest_in_same_fy(key, _c.ARCHIVE_ROOT, period)
            entry = (manifest or {}).get(key) or {}
            stamp = _c.parse_export_stamp(entry.get("file_name") or "")
            if stamp:
                dates.append(stamp[0])
            else:
                return None          # a family with no readable capture
    except Exception:
        return None
    return min(dates) if dates else None


def _drops_capture_moment_for(period: str):
    """Same capture `_drops_capture_date_for` resolves, keeping the clock time.

    The export filename carries HHMM (…_202608_13_0312.xls = 03:12) and the
    date-only gate threw it away, so an export pulled at 03:12 satisfied a
    06:00 ITD: same date, and `2026-08-13 < 2026-08-13` is false. That is a
    genuinely PRE-ITD drops photograph passing the post-ITD gate — the exact
    thing the gate exists to stop.
    """
    from reports.membership_performance_tracker.logic import crystal as _c
    from reports.membership_performance_tracker.logic.crystal_feed import (
        _manifest, _latest_in_same_fy)
    moments = []
    try:
        for key in ("drops_hospitality", "drops_allied"):
            folder, manifest = _manifest(period, _c.ARCHIVE_ROOT)
            if key not in (manifest or {}):
                folder, manifest = _latest_in_same_fy(key, _c.ARCHIVE_ROOT, period)
            entry = (manifest or {}).get(key) or {}
            m = _c._STAMP_RE.match(entry.get("file_name") or "")
            if not m:
                return None
            hm = m.group("hm")
            moments.append(datetime(int(m.group("y")), int(m.group("m")),
                                    int(m.group("d")), int(hm[:2]), int(hm[2:])))
    except Exception:
        return None
    return min(moments) if moments else None


class StaleCapture(Exception):
    """The close would seal a drops photograph OLDER than ITD.

    2026-08-10: July sealed the 7/26 export — ten days before ITD ran —
    and published 1 July drop where the post-ITD photograph shows 16.
    The two-photo doctrine (drops captured AFTER ITD) is enforced here,
    not assumed."""


class AlreadyClosed(Exception):
    """freeze() refused: the month already has a close record (locally or on
    SharePoint). Found 8/10 — a fresh cloud instance with un-hydrated closes
    offered to re-close sealed July; pressing it would have overwritten the
    real close doc. The guard restores the SP record locally and refuses."""


class NoCleanSnapshot(Exception):
    """No archived snapshot exists from before the given ITD morning."""


_TS_RE = re.compile(r"snapshot_\d{4}-\d{2}_(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})")


def _snapshot_ts(path: Path) -> Optional[datetime]:
    m = _TS_RE.search(path.name)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y-%m-%dT%H-%M-%S")


def _snapshot_ts_pacific(path: Path) -> Optional[datetime]:
    """Filename timestamp (UTC) as a naive Pacific-time moment."""
    ts = _snapshot_ts(path)
    if ts is None:
        return None
    return ts.replace(tzinfo=timezone.utc).astimezone(WHA_TZ).replace(tzinfo=None)


def month_label(period: str) -> str:
    return MONTH_OF_PERIOD[int(period[5:7])]


def list_snapshots(snapshots_dir: Path) -> List[Path]:
    """Snapshot files in the dir, oldest → newest by embedded timestamp."""
    out = [(ts, p) for p in snapshots_dir.glob("snapshot_*.json")
           if (ts := _snapshot_ts(p)) is not None]
    return [p for _, p in sorted(out)]


def choose_snapshot(snapshots_dir: Path, itd_date: date,
                    itd_time=None, hub=None) -> Path:
    """The last snapshot taken BEFORE the ITD morning.

    Pass `hub` so a machine with no local snapshots can fetch from the
    archive — a deploy empties the local dir, the archive is the record.

    ITD ran on `itd_date` during work hours; anything captured on that date
    before ITD_EARLIEST_HOUR (the nightly 02:00 pull) is still clean. A
    daytime manual pull from the same date is NOT trusted — it may have run
    after ITD.
    """
    # itd_time (added 8/5 after ITD ran at 6:14 AM — 14 minutes inside the
    # 06:00 assumption): when the actual run time is known, the cutoff is
    # that moment; otherwise the legacy conservative default. The cutoff is
    # PACIFIC (the human's clock); filenames are UTC and get translated —
    # before 8/5 the naive compare skipped genuinely-clean early-morning
    # pulls (5 AM PDT stamps as noon UTC).
    if itd_time is not None:
        cutoff = datetime(itd_date.year, itd_date.month, itd_date.day,
                          itd_time.hour, itd_time.minute)
    else:
        cutoff = datetime(itd_date.year, itd_date.month, itd_date.day,
                          ITD_EARLIEST_HOUR)
    candidates = [p for p in list_snapshots(snapshots_dir)
                  if _snapshot_ts_pacific(p) < cutoff]
    if not candidates and hub is not None:
        # THE SNAPSHOTS LIVE ON SHAREPOINT (8/13). This only ever read local
        # disk — which Cloud Run wipes on every deploy. The archive had 31
        # clean pre-ITD snapshots for August and the console could see none
        # of them, so closing a month was impossible on a fresh container and
        # the operator was told the photograph "was never taken". Fetch the
        # one we need; the local dir is a cache, not the record.
        fetched = _fetch_snapshot_before(period_of(snapshots_dir), cutoff,
                                         snapshots_dir, hub)
        if fetched is not None:
            candidates = [fetched]
    if not candidates:
        raise NoCleanSnapshot(
            f"No snapshot exists from before {itd_date} "
            f"{ITD_EARLIEST_HOUR:02d}:00 — cannot freeze retention for a "
            f"pre-ITD state that was never photographed.")
    return candidates[-1]


def period_of(snapshots_dir: Path) -> str:
    """The period a snapshots dir belongs to — its folder name ('2026-08')."""
    return Path(snapshots_dir).name


def _fetch_snapshot_before(period: str, cutoff: datetime, snapshots_dir: Path,
                           hub) -> Optional[Path]:
    """Download the newest archived snapshot older than `cutoff`, or None.

    Names carry their own UTC timestamp, so the choice is made from the
    listing alone and exactly one file is downloaded.
    """
    try:
        items = hub.list_hub_folder(f"Audit & History Log/Snapshots/{period}")
    except Exception as exc:
        print(f"  [close] snapshot archive unreachable ({type(exc).__name__}: "
              f"{exc})", flush=True)
        return None
    usable = []
    for it in items:
        name = it.get("name", "")
        if not name.startswith("snapshot_") or "official" in name:
            continue
        ts = _snapshot_ts_pacific(Path(name))
        if ts is not None and ts < cutoff:
            usable.append((ts, name))
    if not usable:
        return None
    _, newest = max(usable)
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    local = snapshots_dir / newest
    if not local.exists():
        try:
            local.write_bytes(
                hub.read_hub_file(f"Audit & History Log/Snapshots/{period}/{newest}"))
        except Exception as exc:
            print(f"  [close] could not fetch {newest} ({type(exc).__name__}: "
                  f"{exc})", flush=True)
            return None
        print(f"  [close] fetched {newest} from the archive", flush=True)
    return local


def verify_pre_itd(chosen_fields: dict, prev_fields: dict, month: str) -> List[str]:
    """Fingerprint check: did the ITD wave already hit the chosen snapshot?

    ITD writes off non-payers, so the closing month's billed count SHRINKS.
    If the chosen snapshot's denominator is below the previous snapshot's
    for any territory, the picked date is probably wrong — warn, naming the
    territory. (Payments can only grow the paid side; billed never shrinks
    for a legitimate reason once the cycle closed.)
    """
    warnings = []
    chosen_b = chosen_fields.get("ret_billed") or {}
    prev_b = prev_fields.get("ret_billed") or {}
    for terr, months in chosen_b.items():
        cur = (months or {}).get(month)
        old = (prev_b.get(terr) or {}).get(month)
        if cur is not None and old is not None and cur < old:
            warnings.append(
                f"{terr}: billed {month} shrank {old} → {cur} between the "
                f"prior snapshot and the chosen one — the ITD wave may "
                f"already be inside the chosen snapshot (wrong date?).")
    return warnings


def _load_fields(snapshot_path: Path) -> dict:
    doc = json.loads(snapshot_path.read_text())
    return doc.get("data") or {}


def freeze(period: str, itd_date: date,
           snapshots_dir: Optional[Path] = None,
           closes_dir: Optional[Path] = None,
           hub=None, itd_time=None, allow_refreeze: bool = False) -> dict:
    """Freeze the period's retention column from the pre-ITD snapshot.

    Returns the close doc (also written to closes_dir and, when a hub is
    given, to the SP hub). Re-freezing an already-closed period archives
    the prior frozen values into `history` — nothing is ever overwritten
    silently.
    """
    snapshots_dir = snapshots_dir or (SNAPSHOTS_ROOT / period)
    closes_dir = closes_dir or CLOSES_DIR
    # POST-ITD PHOTO GATE (8/10): drops seal from the newest archived
    # Crystal capture — which must be dated ON or AFTER ITD, or the close
    # seals a stale photograph (July sealed 7/26's export and published
    # 1 drop where the real class had 16).
    if not allow_refreeze:
        cap = _drops_capture_date_for(period)
        if cap is None or cap < itd_date:
            raise StaleCapture(
                f"Refusing to close {period}: the newest archived drops "
                f"capture is {cap.isoformat() if cap else 'MISSING'} but "
                f"ITD is {itd_date.isoformat()}. Close after the next nightly "
                f"run, once the post-ITD picture exists.")
        # SAME DAY, BUT WHAT TIME? (8/13, caught live recording the SOP.)
        # The nightly lands ~02:00-03:00 and ITD runs in the morning, so the
        # capture that passes the date check above is routinely from BEFORE
        # ITD on the ITD date itself. Only refines the day the date check
        # already accepted, so a caller that stubs the date helper is not
        # second-guessed by the real archive.
        moment = _drops_capture_moment_for(period)
        if moment is not None and moment.date() == cap:
            itd_moment = datetime.combine(
                itd_date, itd_time or dt_time(ITD_EARLIEST_HOUR))
            if moment < itd_moment:
                raise StaleCapture(
                    f"Refusing to close {period}: the newest archived drops "
                    f"capture ran at {moment.strftime('%H:%M')} on "
                    f"{cap.isoformat()}, before ITD at "
                    f"{itd_moment.strftime('%H:%M')}. That photograph is "
                    f"pre-ITD. Close after the next nightly run.")
    # CLOBBER GUARD (8/10): never create a second close for a closed month.
    # A fresh machine may simply not have hydrated the record yet — check
    # SharePoint too, restore it locally, and refuse.
    _guard = closes_dir / f"close_{period}.json"
    if _guard.exists() and not allow_refreeze:
        raise AlreadyClosed(
            f"{period} is already closed — its record exists on this "
            f"machine. Repairs go through the amendment procedure (SOP).")
    if hub is not None and not allow_refreeze:
        try:
            _b = hub.read_hub_file(f"{HUB_CLOSE_SUBPATH}/close_{period}.json")
        except Exception:
            _b = None                # no SP record — a genuine first close
        if _b:
            _guard.parent.mkdir(parents=True, exist_ok=True)
            _guard.write_bytes(_b)
            raise AlreadyClosed(
                f"{period} is already closed — the record was on SharePoint "
                f"and has been restored to this machine. Nothing was changed.")
    month = month_label(period)

    chosen = choose_snapshot(snapshots_dir, itd_date, itd_time=itd_time,
                             hub=hub)
    all_snaps = list_snapshots(snapshots_dir)
    prev = all_snaps[all_snaps.index(chosen) - 1] if all_snaps.index(chosen) > 0 else None

    fields = _load_fields(chosen)
    warnings = verify_pre_itd(fields, _load_fields(prev), month) if prev else []

    frozen: Dict[str, Dict[str, object]] = {}
    for key in RETENTION_MONTH_KEYS:
        per_terr = fields.get(key)
        if not isinstance(per_terr, dict):
            continue
        slice_ = {}
        for terr, months in per_terr.items():
            if isinstance(months, dict) and month in months:
                slice_[terr] = months[month]
        if slice_:
            frozen[key] = slice_

    doc = {
        "period": period,
        "month": month,
        "itd_date": itd_date.isoformat(),
        "itd_time": itd_time.isoformat(timespec="minutes") if itd_time else None,
        "source_snapshot": chosen.name,
        "frozen": frozen,
        "warnings": warnings,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "history": [],
    }

    closes_dir.mkdir(parents=True, exist_ok=True)
    out = closes_dir / f"close_{period}.json"
    if out.exists():
        try:
            prior = json.loads(out.read_text())
            old = dict(prior)
            old.pop("history", None)
            doc["history"] = (prior.get("history") or []) + [old]
            doc["reopen_warning"] = REOPEN_WARNING
            # S4 (overnight review 8/10): the replacement doc used to drop
            # `sealed`/`amendments`, so the SOP's own repair path silently
            # UNSEALED the month — apply_frozen then found no seal, the
            # drops columns drifted, and auto-seal could not re-fire. A
            # re-freeze changes the RETENTION photograph only; everything
            # the month had already locked carries forward.
            for k in ("sealed", "sealed_at", "sealed_from", "amendments"):
                if k in prior:
                    doc[k] = prior[k]
        except Exception:
            pass
    out.write_text(json.dumps(doc, indent=2, default=str))

    if hub is not None:
        try:
            hub.write_hub_file(f"{HUB_CLOSE_SUBPATH}/close_{period}.json",
                               out.read_bytes())
        except Exception:
            pass  # local close is authoritative; SP copy is redundancy
    return doc


def seal(period: str, cache_path: Optional[Path] = None,
         closes_dir: Optional[Path] = None, hub=None, data=None) -> dict:
    """Capture EVERY metric of a closed month into the close doc (Jiho GO
    8/5: "every metric gets locked... the month becomes untouchable").

    freeze() protects retention from the pre-ITD snapshot; seal() runs when
    the POST-ITD capture pull lands and copies the whole cache into the
    close doc. apply_frozen() stamps sealed values on every later rebuild,
    so a closed month can never be re-photographed by a stray live rerun
    (a July rebuilt in March would otherwise publish March's roster wearing
    July's label). Sealing is ONCE — a second call returns the original
    capture untouched.
    """
    closes_dir = closes_dir or CLOSES_DIR
    out = closes_dir / f"close_{period}.json"
    doc = json.loads(out.read_text())        # freeze must have happened first
    if doc.get("sealed"):
        return doc
    # SEAL-1 (overnight review 8/10, CRITICAL): the runner writes the cache
    # BEFORE the Crystal overlay ('slx-preoverlay'), so sealing FROM THE FILE
    # captured SData's drops — never the post-ITD photograph the two-photo
    # close promises. Callers pass the post-overlay build data; the file is
    # the fallback, and a pre-overlay file is refused outright.
    if data is not None:
        from dataclasses import fields as _dc_fields
        try:
            names = [f.name for f in _dc_fields(data)]
        except TypeError:                       # plain object (tests)
            names = [k for k in vars(data)]
        fields = {n: getattr(data, n) for n in names}
        src = "post-overlay build data"
    else:
        cache_path = cache_path or (_ROOT / "data" / "cache" /
                                    f"scoreboard_{period}.json")
        raw = json.loads(cache_path.read_text())
        if (raw.get("_meta") or {}).get("source") == "slx-preoverlay":
            raise ValueError(
                f"Refusing to seal {period} from {cache_path.name}: that file "
                f"is the PRE-overlay cache (source 'slx-preoverlay'), so its "
                f"drops never saw the Crystal photograph. Seal from the "
                f"post-overlay build data.")
        fields = raw.get("fields") or {}
        src = cache_path.name
    doc["sealed"] = {k: v for k, v in fields.items() if isinstance(v, dict)}
    doc["sealed_at"] = datetime.now(WHA_TZ).isoformat(timespec="seconds")
    doc["sealed_from"] = src
    out.write_text(json.dumps(doc, indent=2, default=str))
    if hub is not None:
        try:
            hub.write_hub_file(f"{HUB_CLOSE_SUBPATH}/close_{period}.json",
                               out.read_bytes())
        except Exception:
            pass  # local close is authoritative; SP copy is redundancy
    return doc


def is_closed(period: str, closes_dir: Optional[Path] = None) -> bool:
    return ((closes_dir or CLOSES_DIR) / f"close_{period}.json").exists()


def period_needing_close(today: date, anchor: str) -> Optional[str]:
    """The OLDEST month that has ended but has no close record, from the
    anchor forward — what the console's close panel should offer.

    8/5 console-sweep find: the panel used the calendar previous month, so a
    skipped close (July never closed, it's September) left July uncloseable
    and offered August out of order. Months close oldest-first; the current,
    still-running month is never offered.
    """
    y, m = int(anchor[:4]), int(anchor[5:7])
    while True:
        period = f"{y}-{m:02d}"
        # has this period's month fully ended?
        ended = (y, m) < (today.year, today.month)
        if not ended:
            return None
        if not is_closed(period):
            return period
        m += 1
        if m > 12:
            m, y = 1, y + 1


def load_close(period: str, closes_dir: Optional[Path] = None) -> Optional[dict]:
    p = (closes_dir or CLOSES_DIR) / f"close_{period}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def load_all_closes(closes_dir: Optional[Path] = None) -> List[dict]:
    d = closes_dir or CLOSES_DIR
    if not d.exists():
        return []
    docs = []
    for p in sorted(d.glob("close_*.json")):
        try:
            docs.append(json.loads(p.read_text()))
        except Exception:
            continue
    return docs


# Foreign-build month-slice scope: the drops grids (crystal_feed.DROPS_FIELDS)
# — the one family recomputed whole-FY from the newest archive each build.
_FOREIGN_SLICE_FIELDS = frozenset({
    "drops_target", "drops_non_target", "drops_revenue_target",
    "drops_revenue_non_target", "drops_by_category",
    # BOB revenue joined 2026-08-12 (R2 applied): these recompute whole-FY
    # from the live diversity checkbox, so a sealed month's BOB cell drifted
    # when the checkbox flipped after the seal (July: sealed 0.0, fresh 1070
    # — the '4 AM checkbox' from the 8/11 demo). Seal wins; a genuine BOB
    # correction to a closed month is a notated amendment, never drift.
    "revenue_bob", "revenue_bob_target", "revenue_bob_non_target",
    # NEW SALES + CLOSED BUSINESSES joined 2026-08-13 (Jiho: "we are not
    # deferring this"). Every FLOW field of a closed month is now frozen, so
    # "closing a month locks it" is true as written in the SOP — it was only
    # true for retention, drops and BOB revenue before. Measured drift on
    # the August build: Spokane/NE Jul new sales 0 → 1 / $0 → $575 (Tommy's
    # Car Wash paid 7/15, after July's own build) and SouthKing closed 1 → 0.
    # Two members, silently rewriting a sealed month on every later build,
    # and the reason the Trace page could not reconcile that cell. A sale
    # that settles after a close now reaches the month the ONLY sanctioned
    # way: a human, notated amendment (R2) — see scripts/amend_sealed_month.py.
    # PHOTO fields (billables/locations/penetration) stay out on purpose:
    # they are point-in-time counts, and the workbook assembles their history
    # from each month's own snapshot rather than this overlay.
    "revenue", "revenue_target", "revenue_non_target",
    "revenue_comped_new",
    "new_members", "new_members_target", "new_members_non_target",
    "new_members_bob",
    "closed_target", "closed_non_target"})


def apply_frozen(data, closes: Iterable[dict], period: Optional[str] = None) -> List[str]:
    """Overlay every close file's frozen retention values onto `data`.

    `data` is a ScoreboardData (attribute dicts) or anything shaped like
    one. Only the closed month's column is touched; open months and unknown
    keys are left alone (a future-schema close file must not invent fields
    on an older build). Returns human-readable notes of what was applied.
    """
    applied: List[str] = []
    # FISCAL-YEAR SCOPE (2026-08-11). A close doc's `month` is a bare month
    # NAME. In another fiscal year that same name is a different calendar
    # month — FY2025-26's sealed "Sep" is September 2026, but in an FY2026-27
    # build the "Sep" column is September 2027, which has not happened.
    # `load_all_closes()` globs every close file on disk with no year filter,
    # so without this guard each prior-FY close stamped a future column and
    # labelled it "closed months never move". Narrow on purpose: cross-PERIOD
    # inside one fiscal year is correct and load-bearing, and only the YEAR
    # boundary blocks. `period=None` means the caller did not scope the build,
    # and stays permissive.
    build_fy = _fy_start_of(period)
    foreign_fy: List[str] = []
    for doc in closes:
        doc_fy = _fy_start_of(doc.get("period"))
        if build_fy is not None and doc_fy is not None and doc_fy != build_fy:
            foreign_fy.append(f"{doc.get('period')} ({_fy_label(doc_fy)})")
            continue
        month = doc.get("month")
        frozen = doc.get("frozen") or {}
        # SEALED values stamp first (whole fields — the closed month's cache
        # is the document of record), then the retention freeze wins on top:
        # the cache is saved PRE-overlay, so its retention family carries the
        # post-ITD wave and must never be the last word.
        # PERIOD-SCOPED (8/5, caught walking the run-August verification):
        # whole-field stamps are only valid for the sealed period's OWN
        # rebuild — applied to a later month's build they would clobber the
        # fresh pull with the old capture. When the caller names the period
        # being built, foreign seals are skipped; the month-sliced retention
        # freeze below still applies to every build.
        sealed = doc.get("sealed") or {}
        own_build = (period is None or doc.get("period") == period)
        stamped = sliced = 0
        for key, value in sealed.items():
            target = getattr(data, key, None)
            if not (isinstance(target, dict) and isinstance(value, dict)):
                continue
            if own_build:
                target.clear()
                target.update(value)
                stamped += 1
            else:
                # FOREIGN build (8/10 seal-scope fix, Saturday-approved):
                # DROPS fields only — they are recomputed whole-FY from the
                # newest archive on every build, so a sealed month's column
                # drifts with the vintage unless its own column is stamped.
                # Photo families (billables/locations/penetration) stay with
                # the photo-history assembler on foreign builds (8/5 ruling,
                # test_sealed_values_apply_only_to_their_own_periods_build);
                # retention has its own month-sliced freeze below.
                if key not in _FOREIGN_SLICE_FIELDS:
                    continue
                mon = doc.get("month")
                if not mon:
                    continue
                for terr, months in value.items():
                    if not isinstance(months, dict) or mon not in months:
                        continue
                    slot = target.get(terr)
                    if isinstance(slot, dict):
                        slot[mon] = months[mon]
                        sliced += 1
        if stamped:
            applied.append(
                f"{doc.get('period')}: {stamped} field(s) restored from the "
                f"sealed close — the month is data-immutable")
        if sliced:
            applied.append(
                f"{doc.get('period')}: {doc.get('month')} column sealed onto "
                f"this build ({sliced} cells) — closed months never move")
        if not month or not frozen:
            continue
        touched = 0
        for key, per_terr in frozen.items():
            target = getattr(data, key, None)
            if not isinstance(target, dict):
                continue
            for terr, value in per_terr.items():
                slot = target.get(terr)
                if isinstance(slot, dict):
                    slot[month] = value
                    touched += 1
        if touched:
            applied.append(
                f"{doc.get('period')}: {month} retention overlaid from "
                f"close file ({touched} cells, source "
                f"{doc.get('source_snapshot', '?')})")
    if foreign_fy:
        applied.append(
            f"{len(foreign_fy)} close file(s) skipped — a different fiscal "
            f"year to this {_fy_label(build_fy)} build "
            f"({', '.join(sorted(foreign_fy))}). A closed month's column "
            f"names a different calendar month in another year.")
    return applied
