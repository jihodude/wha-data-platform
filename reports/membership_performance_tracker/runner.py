"""
runner.py — End-to-end runner for the Membership Performance Report (MPR).

Runs the full SLX → engine → mapper → writer chain, producing a populated
MPR xlsx in data/output/. On success, dumps ScoreboardData to a JSON cache
so subsequent iterations don't need to re-run the slow SLX queries.

Note: internal Python identifiers (TrackerV4Mapper, TrackerV4Writer, the
package directory reports/membership_performance_tracker/) retain the v4
"tracker" name because the rename to MPR (2026-06-05) was scoped to
user-visible strings only — SP folder, output filename, console labels.

This is the v4-tracker-specific runner. Sibling reports (e.g. dues_analysis)
live in their own folders under `reports/` and use the F5 plugin interface
(`src/hub/`).

Usage:
    python reports/membership_performance_tracker/runner.py              # full SLX (~3 hours)
    python reports/membership_performance_tracker/runner.py --from-cache # instant, applies admin
"""

import datetime as _dt
import json
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path

# Quiet the urllib3 LibreSSL warning — it's noise in an otherwise clean log.
warnings.filterwarnings("ignore", message=".*OpenSSL.*")

import yaml
from dotenv import load_dotenv

# This file is reports/membership_performance_tracker/runner.py
# (3 levels deep — parent.parent.parent gets to the project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Explicit path so .env loads regardless of CWD (Streamlit, pytest, cron).
load_dotenv(PROJECT_ROOT / ".env")

from reports.membership_performance_tracker.logic.cache import save_scoreboard, load_scoreboard
from reports.membership_performance_tracker.logic.engine import ScoreboardEngine, MONTH_ABB_TO_INT
from reports.membership_performance_tracker.logic.retention import retention_goal_for
from reports.membership_performance_tracker.mapper import TrackerV4Mapper
from reports.membership_performance_tracker.writer import TrackerV4Writer
from src.slx.client import SLXClient


# ---- Reporting period -------------------------------------------------------
# Set MPR_PERIOD=YYYY-MM to report any month. Default 2026-03 preserves the
# prior pinned behavior EXACTLY (FY 2025-26, months Oct..Mar).
from src.config.period import parse_period as _parse_period
_PERIOD       = _parse_period(os.environ.get("MPR_PERIOD", "2026-03"))
PERIOD        = _PERIOD.period          # "2026-03"
FY_START      = _PERIOD.fy_start        # 2025
MONTHS        = _PERIOD.months          # ["Oct",...,"Mar"]
CURRENT_MONTH = _PERIOD.current_month   # "Mar"
FISCAL_YEAR   = _PERIOD.fiscal_year     # "2025-26"

USERNAME = os.environ["SLX_USERNAME"]
PASSWORD = os.environ["SLX_PASSWORD"]

TEMPLATE_PATH = Path(__file__).resolve().parent / "template.xlsx"
OUTPUT_DIR    = PROJECT_ROOT / "data" / "output"
CACHE_DIR     = PROJECT_ROOT / "data" / "cache"
SCHEDULE_FILE = PROJECT_ROOT / "data" / "schedule.json"

# Captured by main() after _publish_to_hub returns, consumed by the __main__
# wrapper's `finally` clause when updating schedule.json. Module-level because
# main() returns an int (rc), not a tuple — and we want the wrapper to call
# _update_schedule_status(status, warnings=...) exactly once on every exit path.
_LAST_PUBLISH_WARNINGS: list = []
# HONEST ESTIMATE (Jiho, 2026-08-13): the console advertised "~80 min" for a
# live pull since the early days; measured reality that morning was 3h05m and
# it grows with the program (C11's lost-cohort sweep alone added ~20 min).
# Each live run records what it ACTUALLY took, and the console quotes that
# instead of a number nobody re-measures.
_RUN_START_TS: float = 0.0
_RUN_IS_LIVE: bool = False
# ---------------------------------------------------------------------------


def _datahub_factory():
    """
    Indirection so tests can swap in a stub. Production: DataHub.connect() —
    which actually instantiates SharePointClient.from_env() and verifies the
    connection, populating `_sp` so the publish path is live.

    require_sharepoint=False preserves the dev-environment fallback: when SP
    credentials are absent, `connect()` returns a hub with `_sp=None` instead
    of raising, and `_publish_to_hub` silently no-ops as before.

    BUG FIX 2026-06-05 PM: this used to be `return DataHub()`, which is the
    bare constructor that NEVER touches SharePoint — `__init__` just assigns
    `self._sp = sharepoint_client` (default None). That made the entire SP
    push path permanently dead code in production. Adversarial verify caught
    it before the team message went out. The unit tests in
    test_runner_publish_to_hub.py passed because they stubbed _datahub_factory
    directly, bypassing this bug.
    """
    from src.hub.datahub import DataHub
    return DataHub.connect(require_sharepoint=False)


def _publish_to_hub(data, output_path, period: str, is_live_slx: bool = True) -> dict:
    """
    Push the freshly-pulled cache + finished xlsx to SharePoint.

    STRUCTURAL FIX 2026-06-06: cache-mode runs no longer overwrite the
    canonical `_official` snapshot. Reasoning: when Railway (or any read-only
    deploy) starts with no local cache, it materializes-from-SP, processes
    derived values via the engine, then ran _publish_to_hub which OVERWROTE
    the official snapshot with the freshly-rehydrated-then-reserialized data.
    Any field that wasn't fully populated in the source SP snapshot (e.g.,
    penetration fields that were None for some territories) would be silently
    cemented as the new canonical, creating a feedback loop where bad SP →
    bad cache → bad SP. Now ONLY live SLX runs (is_live_slx=True) update the
    official pointer; cache-mode runs still write the per-run audit record
    and the xlsx, but leave the canonical snapshot alone.

    Two artifacts always uploaded:
      • **Per-run audit trail** — `snapshot_<period>_<run_ts>.json`, immutable
        history of every refresh (live OR cache-mode).
      • **Finished xlsx** — `Reports/<REPORT_NAME>/Output/<date>/...`

    Conditional artifact:
      • **Canonical current cache** — `snapshot_<period>_official.json`,
        written ONLY when is_live_slx=True. Cache-mode runs skip this.

    Idempotent — callable from any runner path. Silently no-ops if no SP
    client is available (dev environment with no creds). Partial failures
    surface in `result["errors"]` instead of raising, so the runner's exit code
    stays clean.

    NOTE on "is_official": semantically still overloaded; the `_official`
    filename was originally the curated monthly baseline. Treating it as
    "live-SLX-only canonical" is closer to the original intent and prevents
    the cache-mode feedback loop. The reconstruction design doc tracks a
    future cleanup (separate `_latest` from `_official`).

    Args:
        data:         ScoreboardData (in memory) to archive.
        output_path:  Path to the xlsx report on local disk.
        period:       Period string like "2026-03".
        is_live_slx:  True for a live SLX refresh (writes official + per-run +
                      xlsx). False for cache-mode (writes per-run + xlsx only).
                      Default True to preserve the safer behavior on bare calls.

    Returns:
        Dict with keys:
          - `cache_snapshot_path`: SP hub-subpath of the official snapshot, or None
                                   (None for cache-mode runs even on success)
          - `xlsx_sp_path`:        SP hub-subpath of the uploaded xlsx, or None
          - `errors`:              list of error strings (empty if all clean)
    """
    result = {"cache_snapshot_path": None, "xlsx_sp_path": None, "errors": []}

    try:
        hub = _datahub_factory()
    except Exception as exc:
        result["errors"].append(f"hub init: {type(exc).__name__}: {exc}")
        return result

    if getattr(hub, "_sp", None) is None:
        # Dev environment — no SP credentials. Not an error.
        return result

    # Single run_ts shared by both snapshot writes below. The official file
    # embeds run_id=X; the per-run sibling file embeds run_id=X. Same X by
    # construction so the audit trail can trace "which per-run produced the
    # current official". Format mirrors src/hub/audit.py:_now_ts (kept private).
    # Verify Med #8 / QA chip task_f770f709.
    import secrets
    from datetime import timezone
    _now = datetime.now(timezone.utc)
    shared_run_ts = (
        _now.strftime("%Y-%m-%dT%H-%M-%S-%f") + "-" + secrets.token_hex(2) + "Z"
    )

    # 1) Canonical current cache snapshot — LIVE SLX ONLY.
    # Cache-mode runs skip this to prevent the feedback loop where a partial
    # snapshot gets cemented as canonical after re-processing on Railway.
    if is_live_slx:
        try:
            result["cache_snapshot_path"] = hub.archive_snapshot(
                period, data, is_official=True, run_ts=shared_run_ts
            )
        except Exception as exc:
            result["errors"].append(f"snapshot (official): {type(exc).__name__}: {exc}")

    # 2) Per-run audit trail entry — always written, including cache-mode.
    # These per-run files are immutable history; they document what each
    # refresh produced regardless of source. The official pointer is what
    # downstream readers follow.
    try:
        hub.archive_snapshot(period, data, is_official=False, run_ts=shared_run_ts)
    except Exception as exc:
        result["errors"].append(f"snapshot (per-run): {type(exc).__name__}: {exc}")

    # 3) Finished xlsx → versioned Reports folder.
    # CACHE-MODE GUARD (2026-08-03, Jiho — a stray March workbook my
    # verification build auto-uploaded landed in the SP Output folder during
    # the Jen-comparison hold): a from-cache build is a local verification
    # artifact; publishing is a deliberate act. Cache-mode uploads the xlsx
    # ONLY when MPR_PUBLISH=1. The per-run audit snapshot above still writes
    # (immutable history in Data/, not the user-visible Output).
    # MPR_PUBLISH=0 is an explicit HOLD: even a live pull keeps its workbook
    # off the user-visible SP Output folder (2026-08-04 — verification pulls
    # with untested numbers stay local; snapshots/audit still upload).
    publish_xlsx = (is_live_slx or os.environ.get("MPR_PUBLISH") == "1") \
        and os.environ.get("MPR_PUBLISH") != "0"
    try:
        if publish_xlsx and output_path is not None and output_path.exists():
            result["xlsx_sp_path"] = hub.publish_report_versioned(
                data=output_path.read_bytes(),
                report_name="Membership Performance Report",
                filename=output_path.name,
            )
    except Exception as exc:
        result["errors"].append(f"xlsx upload: {type(exc).__name__}: {exc}")

    return result


def _update_schedule_status(status: str, warnings=None) -> None:
    """
    Mark this run's terminal status in data/schedule.json — but ONLY if our PID
    matches the schedule's current_pid. Bug 3 fix (2026-06-05).

      • If the scheduler launched us, we own the status slot and write 'done' /
        'error: …' plus clear current_pid so the console UI no longer shows
        'running'.
      • If we're a manual CLI invocation (PID doesn't match), we leave
        schedule.json alone — another scheduled run might be queued there.
      • `warnings` (new 2026-06-05 PM verify High #3): non-fatal post-run
        issues like "SP publish failed but local data is fine". Surfaced as
        `last_run_warnings` so the console UI can show a "completed with
        warnings" badge without misclassifying the run as a hard error.

    Defensive: never raise. Any I/O error here is logged-and-swallowed because
    schedule.json hygiene must not block the runner's exit code.
    """
    if not SCHEDULE_FILE.exists():
        return
    try:
        state = json.loads(SCHEDULE_FILE.read_text())
    except Exception:
        return  # corrupt schedule.json — leave it for the scheduler thread to fix
    if state.get("current_pid") != os.getpid():
        return  # we weren't started by the scheduler, don't touch its state
    state["last_run_status"]   = status
    state["last_run_warnings"] = list(warnings or [])
    state["current_pid"]       = None
    if (_RUN_IS_LIVE and _RUN_START_TS
            and str(status).lower().startswith("done")):
        import time as _t
        state["last_live_minutes"] = max(
            1, int((_t.time() - _RUN_START_TS) / 60))
    try:
        SCHEDULE_FILE.write_text(json.dumps(state, indent=2))
    except Exception:
        pass


def progress(pct: int, msg: str) -> None:
    print(f"  [{pct:3d}%] {msg}", flush=True)


def build_alerts_dict(data, month: str, fiscal_year: str, rep_name_map: dict) -> dict:
    """
    Surface flagged items for the Streamlit UI to render after a run.

    Categories:
      - bob_accounts:   {territory: [accounts...]} — BOB members needing manual
                        revenue credit (comped dues, count toward rep goal)
      - retention_watch: territories with avg retention below their Retention Goal
                        (admin per-territory goal; DEFAULT_RETENTION_GOAL fallback)
      - no_goal:        (territory, month) pairs that booked revenue but have
                        no goal set in Admin Inputs
      - warnings:       free-form strings (e.g. missing revenue for current month)
    """
    alerts: dict = {
        "meta": {
            "month": month,
            "fy": fiscal_year,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
        "bob_accounts": {},
        "retention_watch": [],
        "no_goal": [],
        "warnings": [],
    }

    for t, accts in (data.bob_new_accounts or {}).items():
        if accts:
            alerts["bob_accounts"][t] = accts

    for t, avg in (data.avg_retention or {}).items():
        # Honor the admin per-territory Retention Goal, not a hardcoded 0.92 (#16).
        if avg is not None and avg < retention_goal_for(data.goal_retention, t):
            paid   = data.ret_paid.get(t, {}).get(month)
            billed = data.ret_billed.get(t, {}).get(month)
            alerts["retention_watch"].append({
                "territory": t,
                "rep":       rep_name_map.get(t, ""),
                "pct":       round(avg * 100, 1),
                "paid":      paid,
                "billed":    billed,
            })

    for t in (data.goal or {}):
        g = (data.goal.get(t) or {}).get(month)
        if g is None or g == 0:
            rev = (data.revenue.get(t) or {}).get(month)
            if rev is not None and rev > 0:
                alerts["no_goal"].append({
                    "territory": t,
                    "rep":       rep_name_map.get(t, ""),
                    "month":     month,
                    "revenue":   rev,
                })

    for t in (data.revenue or {}):
        if (data.revenue.get(t) or {}).get(month) is None:
            alerts["warnings"].append(
                f"{t}: no new-sales revenue for {month} (SLX invoices) — verify the "
                f"pull captured this territory's sales (revenue is SLX-derived, not admin)."
            )

    return alerts


def build_rep_name_map(territory_map: dict) -> dict:
    """Invert rep_to_territory: {rep_name: territory} → {territory: rep_name}."""
    rep_to_territory = territory_map.get("rep_to_territory") or {}
    out = {}
    for rep, terr in rep_to_territory.items():
        if terr:
            out[terr] = rep
    return out



def sync_admin_from_sharepoint(admin_xlsx) -> None:
    """Pull the goals workbook from SharePoint before reading it (2026-07-22,
    Jiho: "they use SP more than the console"). The team edits the ROOT copy
    via Teams links, so root is read first; the shared-subfolder copy is the
    fallback. Best-effort: any SP failure keeps the local file and says so —
    a report with yesterday's goals beats no report."""
    try:
        from src.sharepoint.client import SharePointClient
        client = SharePointClient.from_env()
        hub = "Internal Dept Files/Membership Data Hub"
        for sp_path in (f"{hub}/Inputs/admin_inputs.xlsx",):
            try:
                data = client.read_file(sp_path)
                if data:
                    admin_xlsx.parent.mkdir(parents=True, exist_ok=True)
                    admin_xlsx.write_bytes(data)
                    print(f"  ✓ Goals workbook synced from SharePoint "
                          f"({sp_path.rsplit('/', 2)[-2]}/…)")
                    return
            except Exception:
                continue
        print("  · SharePoint goals copy unavailable — using the local workbook")
    except Exception as exc:
        print(f"  · SharePoint sync skipped ({type(exc).__name__}) — using the local workbook")


def acquire_pull_lock(lock_path) -> bool:
    """ONE SLX session at a time (hard rule #5), enforced mechanically (P1-7c).
    True = lock acquired. False = another live pull owns it. Stale locks
    (dead pid) self-clear."""
    from pathlib import Path
    lock_path = Path(lock_path)
    if lock_path.exists():
        try:
            pid = int(lock_path.read_text().strip())
            os.kill(pid, 0)          # raises if the process is gone
            return False             # alive → refuse
        except PermissionError:
            # os.kill raising PermissionError means the process EXISTS but is
            # another user's — the exact "someone else's live pull" case this
            # lock guards (finding #25). Refuse; do NOT clear the lock.
            return False
        except (ValueError, ProcessLookupError):
            lock_path.unlink(missing_ok=True)   # stale/garbage pid → clear
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(str(os.getpid()))
    return True


def release_pull_lock(lock_path) -> None:
    from pathlib import Path
    Path(lock_path).unlink(missing_ok=True)





def _build_crystal_band(engine):
    """A Target/Non-Target callable for Crystal drop rows, keyed by account name.

    Returns None when banding is IMPOSSIBLE (no client, or every bridge failed)
    so the overlay's GATE B keeps SData's split instead of publishing a
    fabricated one. Returning a lambda->UNKNOWN here is what shipped
    "Target: 0 / Non-Target: 135" from the cache path on 2026-07-28: with no
    client, every row read UNKNOWN and folded into Non-Target, and nothing
    could tell that apart from a real answer.

    Within a WORKING bridge, an individual unresolvable member still returns
    UNKNOWN and counts Non-Target — no member is dropped from a total, the rule
    established against Jennifer's published billables.
    """
    from reports.membership_performance_tracker.logic import crystal_banding
    from reports.membership_performance_tracker.logic import target as _target

    # PREFERRED SOURCE (2026-07-28): SData's own drops detail. It carries
    # is_target per member from the SAME target logic every other family uses,
    # it travels in the cache, and it bands 263 of 264 live rows (99.6%) — so
    # the split no longer depends on whether the run has an SLX client. The
    # name-bridge below stays as the fallback for a run whose detail is empty.
    detail = getattr(getattr(engine, "data", None), "drops_detail", None)
    from_detail = crystal_banding.band_from_detail(detail)
    if from_detail is not None:
        return from_detail

    client = getattr(engine, "client", None)
    users = {t: u for u, t in (getattr(engine, "territory_user_map", None) or {}).items() if t}
    if client is None or not users:
        return None

    bridges, maps = {}, {}
    for territory, user_id in users.items():
        try:
            bridges[territory] = crystal_banding.build_name_bridge(client, user_id)
            maps[territory] = _target.build_target_map(client, user_id, status=None)
        except Exception as exc:
            warnings.warn(f"[crystal-overlay] no banding for {territory}: {exc}")

    if not bridges:
        warnings.warn("[crystal-overlay] banding unavailable for EVERY territory — "
                      "drops will keep SData's split rather than publish Target 0")
        return None

    def band(row):
        territory = getattr(row, "territory", "")
        if territory not in bridges:
            return _target.UNKNOWN
        return crystal_banding.band_member(getattr(row, "name", ""),
                                           bridges[territory], maps[territory])
    return band


def _apply_crystal_overlay(engine, period: str) -> None:
    """Lay Crystal's DROPS over SData's, before the derived layers.

    Drops is the one family Crystal still owns: the export simply IS the
    answer (FY-windowed, dues on every row, 19 real reasons, and — since
    2026-07-30 — the status groups that separate real drops from RRO FYI
    rows). Billables left the overlay on 2026-07-30 (Jiho: "drop the crystal
    overlay, sdata computes billables"); every other family stays on the
    ledger, which is the only source that can answer a past month.

    A missing export leaves SData's numbers in place and says so on stdout —
    valid numbers, just not the CRM report's, and the difference is announced
    rather than left to be inferred from a silent success.
    """
    from reports.membership_performance_tracker.logic import crystal_feed
    from reports.membership_performance_tracker.logic import target as _target

    data = engine.data
    fields = {name: getattr(data, name) for name in crystal_feed.DROPS_FIELDS
              if hasattr(data, name)}
    if not fields:
        return

    # Drops need a Target/Non-Target call per member; billables arrive banded.
    # The bridge is the account NAME within a territory (Crystal has no member
    # id we can join on — cMemberGens.Membernum is empty database-wide), and it
    # resolved 1,978/1,978 members across every territory on 2026-07-27. The
    # target maps are already cached on the client by the engine's own run, so
    # this costs one accounts query per territory.
    band = _build_crystal_band(engine)
    from reports.membership_performance_tracker.logic import drops_hygiene as _dh
    fy_start = int(period.split("-")[0]) if int(period.split("-")[1]) >= 10 \
        else int(period.split("-")[0]) - 1
    hygiene = _dh.build_checker(getattr(engine, "client", None), fy_start,
                                CACHE_DIR / f"drops_hygiene_FY{fy_start}.json")
    # Flip dates for the event-axis filing (2026-07-31): same detail bridge
    # the bander uses — the export carries no year, the detail carries the date.
    from reports.membership_performance_tracker.logic import crystal_banding as _cb
    drop_date_of = _cb.drop_dates_from_detail(
        getattr(getattr(engine, "data", None), "drops_detail", None))
    merged, report = crystal_feed.overlay(fields, period, band=band,
                                          hygiene=hygiene,
                                          drop_date_of=drop_date_of)

    for name, value in merged.items():
        if hasattr(data, name):
            setattr(data, name, value)

    if report.applied:
        runs = ", ".join(sorted({v["run_date"] for src in report.sources.values()
                                 for v in src.values()}))
        print(f"     ✓ Crystal overlay applied to {', '.join(report.applied)} "
              f"(export run {runs})")
    for name, why in sorted(report.skipped.items()):
        print(f"     ! {name}: kept SData's numbers — {why}")

    # A REVENUE CELL THAT SHRINKS ANNOUNCES ITSELF (2026-08-18). New-sales
    # revenue is paid-basis and only grows as money arrives; the CRM is edited
    # continuously, so a legitimate decrease (a refund, a reversal) exists but
    # is rare. On 8/18 NorthKing Aug fell 4,678.50 → 2,924.00 between two
    # nightlies — a real published understatement the CRM's own export
    # contradicted — and nothing said so; it surfaced only because the
    # conservation gate happened to refuse the receipts. Compare against the
    # prior run's official snapshot and flag every decrease, per Jen's
    # standing rule: "if it happens, I want to know about it." A flag, never
    # a block. Best-effort: no snapshot, no check.
    try:
        import json as _json2
        from src.hub.datahub import DataHub as _DH2
        _hub2 = _DH2.connect(require_sharepoint=False)
        if getattr(_hub2, "_sp", None) is not None:
            _prev = _json2.loads(_hub2.read_hub_file(
                f"Audit & History Log/Snapshots/{period}/snapshot_{period}_official.json"))
            _prev_fields = _prev.get("data") or {}
            for _fld in ("revenue", "revenue_target", "revenue_non_target"):
                _old_grid = _prev_fields.get(_fld) or {}
                _new_grid = getattr(engine.data, _fld, None) or {}
                for _terr, _months in _old_grid.items():
                    if not isinstance(_months, dict):
                        continue
                    for _m, _old_v in _months.items():
                        _new_v = (_new_grid.get(_terr) or {}).get(_m)
                        if (isinstance(_old_v, (int, float))
                                and isinstance(_new_v, (int, float))
                                and _new_v < _old_v - 0.51):
                            engine.flags.setdefault(
                                "revenue_decreased_since_last_run", []).append(
                                {"field": _fld, "territory": _terr,
                                 "month": _m, "previous_run": _old_v,
                                 "this_run": _new_v,
                                 "delta": round(_new_v - _old_v, 2),
                                 "note": "paid-basis revenue normally only "
                                         "grows; a decrease is either a real "
                                         "refund/reversal or a data problem "
                                         "— worth eyes either way"})
    except Exception as _dgexc:
        print(f"     (revenue decrease check skipped: {type(_dgexc).__name__})")

    _write_flags(engine, period, report.flags, _timing(period))


def _timing(period: str) -> dict:
    """State the run's timing assumption — it cannot be enforced, only said.

    The order (Jen, 2026-07-30): Accounting posts → retention → ITD →
    billables + penetration. Running outside that window produces numbers that
    look fine and are not; the failure Jiho named on the call was that this ran
    silently on the 1st of every month.
    """
    from reports.membership_performance_tracker.logic.run_timing import timing_note
    note = timing_note(period)
    if note["risk"]:
        print(f"     ⏰ TIMING [{note['risk']}] {note['message']}")
    else:
        print(f"     ⏰ timing OK — {note['message']}")
    return note


def _attach_transparency_sheets(output_path, period: str):
    """AFTER the writer saves: re-attach the transparency layer.

    2026-08-04 (found during the flags build): the writer rebuilds the
    workbook from the template, so the Members sheet only existed until the
    next rebuild — every runner rebuild silently dropped it. Now both tabs
    are re-rendered from their per-period artifacts on every build:
      · 'Data - MPR Members' from data/receipts/receipts_<period>.json
      · 'Data - MPR Flags'   from data/cache/flags_<period>.json
    Best-effort: a missing artifact skips its tab, never blocks the report.
    """
    # WORKBOOK CLEANUP (Jiho 8/12 night): the Members and Flags tabs are
    # retired from the workbook — the Trace page (with its Excel download)
    # IS the member-level surface, and the team never asked for the flags
    # tab (R2 already ruled the flag sheet irrelevant). The per-period JSON
    # artifacts still publish to SP unchanged; only the in-workbook mirrors
    # go. Ref - Metrics stays (Jiho keeps it, wording review pending).
    from openpyxl import load_workbook
    from reports.membership_performance_tracker.logic import receipts_sheet as _rs
    try:
        wb = load_workbook(output_path)
        for stale in ("Data - MPR Members", "Data - MPR Flags"):
            if stale in wb.sheetnames:
                wb.remove(wb[stale])
        _rs.build_metric_reference(wb)
        wb.save(output_path)
        print("     ⚑ metric reference attached (Members/Flags tabs retired)")
    except Exception as exc:
        print(f"  ⚠ transparency sheet pass failed (report intact): "
              f"{type(exc).__name__}: {exc}")


def _rebuild_receipts(period: str) -> None:
    """Render this run's raw capture into the receipts the Trace page reads.

    Best-effort by design: the report is the deliverable, receipts are its
    explanation. A failure here degrades transparency for one run and says so
    loudly with the exact command to recover; it never fails the build.
    """
    import importlib
    _prev = os.environ.get("MPR_PERIOD")
    try:
        os.environ["MPR_PERIOD"] = period
        rc = importlib.import_module("scripts.build_receipts").main()
        if rc == 0:
            print(f"     ✓ receipts rebuilt for {period}")
        else:
            # DON'T NAME THE WRONG CAUSE (2026-08-18). This printed "SP push
            # failed" for EVERY non-zero return, but build_receipts returns 1
            # from two very different places: the conservation gate refusing
            # cells, and an actual SharePoint write failure. The 8/18 nightly
            # returned 1 and the log said "SP push failed" — which was
            # unfalsifiable from outside the container and sent the diagnosis
            # in the wrong direction. build_receipts prints the real reason
            # directly above this line, and a gate failure now also lands on
            # SharePoint as receipts_gate_failure_<period>.json.
            print(f"     ⚠ receipts NOT published for {period} — see the reason "
                  f"printed directly above (conservation gate, or a SharePoint "
                  f"write failure). The report itself is unaffected; the Trace "
                  f"page keeps the previous run's member lists until a build "
                  f"succeeds.")
    except Exception as exc:
        print(f"     ⚠ receipts NOT rebuilt ({type(exc).__name__}: {exc}). The "
              f"Trace page will show the PREVIOUS run's member lists until "
              f"`MPR_PERIOD={period} PYTHONPATH=$PWD python3 "
              f"scripts/build_receipts.py` is run.")
        # A CRASH MUST LEAVE ITS TRACEBACK SOMEWHERE DURABLE (2026-08-20).
        # The 8/19 and 8/20 nightlies both died in this step, and the only
        # evidence — this very message plus the traceback — lived in
        # scheduled_run.log on the container's ephemeral disk. The gate path
        # already writes its failures to SharePoint; the crash path was the
        # remaining blind spot. Best-effort, like everything in this function.
        try:
            import json as _cj
            import traceback as _tb
            from datetime import datetime as _cdt
            from src.hub.datahub import DataHub as _cDH
            _chub = _cDH.connect(require_sharepoint=False)
            if getattr(_chub, "_sp", None) is not None:
                _chub.write_hub_file(
                    "Reports/Membership Performance Report/Data/"
                    f"receipts_build_error_{period}.json",
                    _cj.dumps({
                        "period": period,
                        "at": _cdt.now().isoformat(timespec="seconds"),
                        "reason": "exception (crashed before/after the gate)",
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback": _tb.format_exc(),
                        "note": "The published report is unaffected; the "
                                "Trace page keeps the previous run's member "
                                "lists until a receipts build succeeds.",
                    }, indent=1).encode())
                print(f"     ↑ crash detail written to SharePoint: "
                      f"Data/receipts_build_error_{period}.json")
        except Exception as _cexc:
            print(f"     (could not record the crash to SharePoint: "
                  f"{type(_cexc).__name__})")
    finally:
        if _prev is None:
            os.environ.pop("MPR_PERIOD", None)
        else:
            os.environ["MPR_PERIOD"] = _prev


def _write_flags(engine, period: str, crystal_flags: dict, timing: dict = None):
    """The FLAG LIST — rows the rulings exclude from the counts but a human
    must SEE (Jen, 2026-07-30, on unpaid actives: "if it happens, I want to
    know about it"; on RRO rows: they are on the export "just as FYI").

    v1 shape: one JSON artifact per period beside the cache. Flat, named,
    self-describing — polish (a workbook sheet) comes later.
    """
    import json as _json
    flags = dict(crystal_flags or {})
    for key, values in getattr(engine, "flags", {}).items():
        flags.setdefault(key, []).extend(values)
    if not flags and not timing:
        return
    out = CACHE_DIR / f"flags_{period}.json"
    # PRESERVE (2026-07-31): a --from-cache rebuild has no SLX client, so the
    # engine-computed families (e.g. active_without_payment) come back empty —
    # and overwriting the file dropped them silently, twice today. A family
    # the current run cannot recompute is carried from the previous artifact,
    # marked so a reader knows its vintage.
    carried = []
    if out.exists():
        try:
            prev = _json.loads(out.read_text()).get("flags") or {}
            for key, values in prev.items():
                if key not in flags and values and not key.startswith("_"):
                    flags[key] = values
                    carried.append(key)
        except Exception:
            pass
    if carried:
        flags["_carried_from_previous_run"] = sorted(carried)
    out.write_text(_json.dumps(
        {"period": period, "written": _dt.datetime.now().isoformat(timespec="seconds"),
         "timing": timing, "flags": flags}, indent=1, default=str))
    counts = ", ".join(f"{k}: {len(v)}" for k, v in sorted(flags.items()))
    print(f"     ⚑ flag list written ({counts}) → {out.name}")

    # 2026-08-04 (Jiho): flags are a per-generation artifact — ship the JSON
    # to the report's SP Data folder (beside the receipts JSON) and render
    # the "Data - MPR Flags" tab into the workbook. Off the report face.
    try:
        from src.hub.datahub import DataHub
        hub = DataHub.connect(require_sharepoint=False)
        if getattr(hub, "_sp", None) is not None:
            hub.write_hub_file(
                f"Reports/Membership Performance Report/Data/flags_{period}.json",
                out.read_bytes())
    except Exception as exc:
        print(f"  · flags SP push skipped ({type(exc).__name__})")
    # (the workbook tab is rendered AFTER the writer saves — see
    # _attach_transparency_sheets, called from main.)


def _finalize_for_publish(engine, period: str):
    """The ONE publish step both paths run: Crystal's two families laid over
    SData's, then every derived layer recomputed on the numbers that will
    actually be printed.

    Both halves must live here together. Until 2026-07-28 the overlay was
    called only on the `--from-cache` branch, so a LIVE pull — which is what
    the nightly schedule and the console's Full Refresh both take — published
    SData's billables and drops. The replay everyone eyeballed was the correct
    one, which is precisely why the gap survived.

    Order matters: overlay BEFORE L1/L2/L3, or the derived layers compute
    percentages and attainment from numbers that are about to be replaced.
    """
    _apply_crystal_overlay(engine, period)
    engine._compute_layer1()
    engine._compute_layer2()
    engine._compute_layer3()
    return engine.data


def _cache_source(cache_path) -> str:
    """What the cache file HOLDS: 'slx-preoverlay', 'sp-published', or
    'unknown' (a file older than the 2026-07-30 marker, or unreadable).

    Read straight from the file rather than the loaded model, so the answer
    does not depend on ScoreboardData carrying a field for it. Until
    2026-07-30 this read a key no writer set and silently answered 'slx' —
    which is how a materialized SP snapshot (post-overlay) and a live pull's
    pre-overlay save became indistinguishable and produced a false
    drops-regression alarm. 'unknown' is the honest answer, never a guess.
    """
    try:
        import json as _json
        meta = _json.loads(Path(cache_path).read_text()).get("_meta") or {}
        return str(meta.get("source") or "unknown").lower()
    except Exception:
        return "unknown"


def _hydrate_sp_inputs() -> None:
    """Pull every SP-durable input the build reads but this machine
    lacks (fresh cloud instance): close docs, prior-month snapshots,
    the Crystal archive + hygiene cache (durable mirror), receipts.
    MUST run before ANY computation — the 8/8 D1 diff caught drops
    diverging because hydration ran after the drops feed."""
    # CLOSE-DOC HYDRATION (2026-08-08, cloud sweep): a fresh instance has an
    # empty data/closes — apply_frozen below would silently no-op, and a
    # LIVE pull would then publish a closed month's retention without its
    # frozen overlay. SharePoint holds every close doc; hydrate any missing
    # ones first. Local files always win (a close is never overwritten).
    try:
        from src.hub.datahub import DataHub as _DH
        _closes_dir = PROJECT_ROOT / "data" / "closes"
        _closes_dir.mkdir(parents=True, exist_ok=True)
        _h2 = _DH.connect(require_sharepoint=False)
        if getattr(_h2, "_sp", None) is not None:
            _y, _m = int(PERIOD[:4]), int(PERIOD[5:7])
            for _i in range(14):
                _p = f"{_y}-{_m:02d}"
                _dst = _closes_dir / f"close_{_p}.json"
                if not _dst.exists():
                    try:
                        _dst.write_bytes(_h2.read_hub_file(
                            "Reports/Membership Performance Report/Data/closes/"
                            f"close_{_p}.json"))
                        print(f"  ⌄ close doc hydrated from SP: close_{_p}.json")
                    except Exception:
                        pass            # month simply has no close yet
                # PRIOR-MONTH SNAPSHOTS (8/8 D1 diff): photo history reads
                # each month's own stored snapshot — hydrate the ones SP has.
                if _i > 0:              # current period's cache handled above
                    _sp_dst = CACHE_DIR / f"scoreboard_{_p}.json"
                    if not _sp_dst.exists():
                        try:
                            from src.hub.audit import _load_latest_snapshot
                            from reports.membership_performance_tracker.logic.cache import (
                                save_scoreboard, scoreboard_from_dict)
                            _env = _load_latest_snapshot(_p, _h2)
                            if _env and "data" in _env:
                                save_scoreboard(
                                    scoreboard_from_dict(_env["data"]), _sp_dst,
                                    saved_at=_env.get("captured_at"),
                                    source="sp-published")
                                print(f"  ⌄ snapshot hydrated from SP: {_p}")
                        except Exception:
                            pass
                _m -= 1
                if _m == 0:
                    _y, _m = _y - 1, 12
            # DURABLE INPUTS (8/8 D1 diff — 259 drops cells diverged): the
            # Crystal export archive ("the archived file is the receipt")
            # and hygiene cache are mirrored on the hub by
            # scripts/push_durable_inputs.py; a fresh instance pulls any
            # file it lacks. Local files always win.
            try:
                import json as _json
                _idx = _json.loads(_h2.read_hub_file(
                    "Reports/Membership Performance Report/Data/durable/index.json"))
                _n = 0
                for _f in _idx.get("files", []):
                    _d = PROJECT_ROOT / _f["dst"]
                    if not _d.exists():
                        _d.parent.mkdir(parents=True, exist_ok=True)
                        _d.write_bytes(_h2.read_hub_file(
                            "Reports/Membership Performance Report/Data/durable/"
                            + _f["rel"]))
                        _n += 1
                if _n:
                    print(f"  ⌄ durable inputs hydrated from SP: {_n} files")
            except Exception:
                pass                    # index not pushed yet — local-only dev
            # RECEIPTS (8/8: cloud workbook was 577 KB vs 1.8 MB — the
            # Members tab and Trace page read these): hub holds the rendered
            # receipts; pull current + prior period if missing.
            _y2, _m2 = int(PERIOD[:4]), int(PERIOD[5:7])
            for _ in range(2):
                for _name in (f"receipts_{_y2}-{_m2:02d}.json",
                              f"receipts_raw_{_y2}-{_m2:02d}.json"):
                    _d = PROJECT_ROOT / "data" / "receipts" / _name
                    if not _d.exists():
                        try:
                            _d.parent.mkdir(parents=True, exist_ok=True)
                            _d.write_bytes(_h2.read_hub_file(
                                "Reports/Membership Performance Report/Data/"
                                + _name))
                            print(f"  ⌄ receipts hydrated from SP: {_name}")
                        except Exception:
                            pass
                _m2 -= 1
                if _m2 == 0:
                    _y2, _m2 = _y2 - 1, 12
        else:
            return False                # no SP connection
        return True
    except Exception as _exc:
        print(f"  ⚠ SP input hydration skipped: {type(_exc).__name__}: {_exc}")
        return False


def main() -> int:
    use_cache = "--from-cache" in sys.argv

    if not TEMPLATE_PATH.exists():
        print(f"ERROR: template missing at {TEMPLATE_PATH}", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # before ANY read — see _hydrate_sp_inputs docstring
    _sp_hydrated = _hydrate_sp_inputs()
    # ABORT-WHEN-BLIND (D2 finding 3iii): a LIVE pull that cannot see the
    # close records — no SP and no local close docs — could publish a
    # closed month's retention without its frozen overlay. Refuse instead.
    if not use_cache and not _sp_hydrated \
            and not list((PROJECT_ROOT / "data" / "closes").glob("close_*.json")):
        print("ERROR: live pull refused — SharePoint unreachable and no "
              "local close records; a closed month could publish unfrozen. "
              "Retry when SharePoint is reachable.", file=sys.stderr)
        return 3

    # ONE SLX session at a time — mechanically enforced (P1-7c). Cache-mode
    # runs don't touch SLX, so they're exempt.
    if not use_cache:
        _lock = CACHE_DIR / ".runner.pid"
        if not acquire_pull_lock(_lock):
            print(f"ERROR: another live pull is running (lock {_lock}). "
                  f"One SLX session at a time.", file=sys.stderr)
            return 2
        import atexit
        atexit.register(release_pull_lock, _lock)

    fy_month_int = MONTH_ABB_TO_INT[CURRENT_MONTH]
    cal_year = FY_START if fy_month_int >= 10 else FY_START + 1
    cache_path = CACHE_DIR / f"scoreboard_{cal_year}-{fy_month_int:02d}.json"

    print(f"\nMembership Performance Report — generating report")
    print(f"Fiscal year {FISCAL_YEAR}, reporting through {CURRENT_MONTH}")
    global _RUN_START_TS, _RUN_IS_LIVE
    import time as _t
    _RUN_START_TS, _RUN_IS_LIVE = _t.time(), (not use_cache)
    print(f"Mode: {'Fast (using saved membership data)' if use_cache else 'Full refresh (pulling live from SLX — about 3 hours)'}\n")

    if use_cache:
        # Blocker #2 fix (2026-06-05 PM verify): if local cache is missing,
        # try to pull the latest SP snapshot before giving up. This is what
        # makes a fresh laptop able to use --from-cache against User A's push.
        period_str = f"{cal_year}-{fy_month_int:02d}"
        if not cache_path.exists():
            try:
                hub = _datahub_factory()
                if getattr(hub, "_sp", None) is not None:
                    print(f"  ⌄ Local cache missing — pulling latest SP snapshot for {period_str}...")
                    sp_data = hub.load_data(period_str)
                    # The SP snapshot is the PUBLISHED (post-overlay) data —
                    # not the same thing as a live pull's pre-overlay save.
                    save_scoreboard(sp_data, cache_path, source="sp-published")
                    print(f"  ✓ SP snapshot materialized → {cache_path}")
            except Exception as exc:
                print(f"  ⚠ SP cache pull failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            # Re-check after attempted pull
            if not cache_path.exists():
                print(f"ERROR: cache file not found at {cache_path} and SP pull failed", file=sys.stderr)
                print("Run without --from-cache first to generate it.", file=sys.stderr)
                return 1
        progress(50, "Loading saved membership data...")
        data = load_scoreboard(cache_path)
        # Say what this cache HOLDS. A pre-overlay pull and a materialized SP
        # snapshot share a filename; replaying one is not replaying the other
        # (the 2026-07-30 false drops-regression came from conflating them).
        print(f"     ✓ Loaded — no need to contact SLX "
              f"(cache holds: {_cache_source(cache_path)})")

        # Re-apply admin inputs from YAML — these are cheap and the user may
        # have edited them between runs. This way YAML edits reflect instantly
        # without needing a full SLX re-run.
        progress(55, "Applying the latest admin inputs...")
        territory_map_path = PROJECT_ROOT / "config" / "territory_map.yaml"
        with open(territory_map_path) as f:
            territory_map = yaml.safe_load(f)
        territory_user_map = {
            uid: t for uid, t in territory_map["slx_user_to_territory"].items() if t
        }
        rep_name_map = build_rep_name_map(territory_map)

        # Build a stub engine just for the admin-input loader — no SLX client needed
        engine = ScoreboardEngine(
            client=None,                    # not used in admin-input path
            territory_user_map=territory_user_map,
            fiscal_year_start=FY_START,
            months=MONTHS,
            current_month=CURRENT_MONTH,
            rep_name_map=rep_name_map,
        )
        engine.data = data

        # Prefer the unified xlsx (admins edit this directly); fall back to YAML.
        # Freshest goals come from SharePoint (the team edits there).
        admin_xlsx = PROJECT_ROOT / "data" / "raw" / "admin_inputs.xlsx"
        sync_admin_from_sharepoint(admin_xlsx)
        if admin_xlsx.exists():
            engine.load_admin_inputs_xlsx(admin_xlsx)
            source = "admin_inputs.xlsx"
        else:
            engine._load_admin_inputs(FISCAL_YEAR, PROJECT_ROOT / "config" / "admin_inputs.yaml")
            engine._load_goals(FISCAL_YEAR, PROJECT_ROOT / "config" / "goals.yaml")
            source = "YAML fallback"

        # Re-aggregate drops/closed buckets from cached detail lists. Required
        # because past cache snapshots may have stale buckets (e.g. before the
        # Y/N is_target bucketing bug was fixed). The detail lists themselves
        # are correct in the cache; only the bucketed counts needed re-running.
        engine.aggregate_drops_buckets()
        # Recomputing the derived layers here (inside finalize) is what lets a
        # cache replay pick up L1/L2/L3 bug fixes without an 80-minute re-pull:
        # every raw input those layers need is in the cache.
        data = _finalize_for_publish(engine, PERIOD)
        print(f"     ✓ Admin inputs applied\n")
    else:
        # Load territory map
        territory_map_path = PROJECT_ROOT / "config" / "territory_map.yaml"
        with open(territory_map_path) as f:
            territory_map = yaml.safe_load(f)
        territory_user_map = {
            uid: t for uid, t in territory_map["slx_user_to_territory"].items() if t
        }
        rep_name_map = build_rep_name_map(territory_map)
        print(f"Loaded {len(territory_user_map)} territories")

        # Freshest goals from SharePoint before the engine reads them
        sync_admin_from_sharepoint(PROJECT_ROOT / "data" / "raw" / "admin_inputs.xlsx")

        # Connect to SLX
        progress(2, "Connecting to SLX...")
        client = SLXClient(username=USERNAME, password=PASSWORD)
        print(f"  ✓ Connected as {USERNAME}\n")

        # CAPTURE FETCH (8/10, Jiho: "prevent it from going wrong again"):
        # archive today's scheduled Crystal exports BEFORE the overlay, so
        # the drops photograph is never stale and the close gate always has
        # a fresh capture to accept. Degrades loudly, never fatally.
        try:
            from datetime import date as _cdate, timedelta as _ctd
            from reports.membership_performance_tracker.logic import crystal as _cry
            _floor = _cdate.today() - _ctd(days=1)
            try:
                _fetched = _cry.fetch_period(client, PERIOD, min_run_date=_floor)
            except _cry.MissingExports as _me:
                # ALL-OR-NOTHING FIX (overnight review): fetch_period refuses
                # wholesale if ANY of the 10 is stale, so one dead schedule
                # archived NOTHING — including the drops capture the close
                # gate needs. Take everything that IS fresh, name the rest.
                _stale = set(getattr(_me, "missing", {}) or {})
                _ok = [k for k in _cry.REPORTS if k not in _stale]
                _fetched = (_cry.fetch_period(client, PERIOD, required=_ok,
                                              min_run_date=_floor)
                            if _ok else {})
                for _k, _why in (getattr(_me, "missing", {}) or {}).items():
                    print(f"  ⚠ capture NOT fresh — {_k}: {_why}")
            print(f"  ⇩ crystal captures archived: {len(_fetched)} exports")
            try:
                import json as _cjs
                from datetime import datetime as _cdt
                _hub = _datahub_factory()
                if getattr(_hub, "_sp", None) is not None:
                    _base = ("Reports/Membership Performance Report/"
                             "Data/durable")
                    try:
                        _idx = _cjs.loads(
                            _hub.read_hub_file(f"{_base}/index.json").decode())
                    except Exception:
                        _idx = {"files": []}
                    _known = {e.get("rel") for e in _idx.get("files", [])}
                    _croot = PROJECT_ROOT / "data" / "raw" / "crystal"
                    _added = 0
                    for _f in sorted(_croot.rglob("*")):
                        if not _f.is_file():
                            continue
                        _rel = f"crystal/{_f.relative_to(_croot)}"
                        if _rel in _known:
                            continue
                        _hub.write_hub_file(f"{_base}/{_rel}", _f.read_bytes())
                        _idx["files"].append(
                            {"rel": _rel,
                             "dst": f"data/raw/crystal/{_f.relative_to(_croot)}"})
                        _added += 1
                    if _added:
                        _idx["pushed_at"] = _cdt.now().astimezone().isoformat(
                            timespec="seconds")
                        _hub.write_hub_file(f"{_base}/index.json",
                                            _cjs.dumps(_idx, indent=1).encode())
                        print(f"  ↑ durable mirror: +{_added} capture file(s)")
            except Exception as _exc:
                print(f"  ⚠ durable capture mirror failed "
                      f"(archive stays local): {type(_exc).__name__}: {_exc}")
        except Exception as _exc:
            print(f"  ⚠ CAPTURE FETCH INCOMPLETE — the overlay will use the "
                  f"newest existing archive and the close gate refuses stale "
                  f"seals: {type(_exc).__name__}: {_exc}")

        # ANNUAL OCT-1 OBLIGATION, MADE VISIBLE (ruled 2026-08-11, Jiho).
        # The drops exports are scheduled with a StatusDate range; when it no
        # longer starts at the reported FY's Oct 1 the export spans more than
        # one year, and DATELESS rows — which fall back to a bill month that
        # carries no year — can land in the wrong column. This reports; it
        # never refuses (see crystal.check_drops_window for why).
        _window_problems = []
        try:
            from reports.membership_performance_tracker.logic import crystal as _cryw
            _window_problems = _cryw.check_drops_window(client, FY_START)
            for _p in _window_problems:
                print(f"  ⚑ drops schedule window — {_p}")
        except Exception as _exc:                    # never fatal
            print(f"  ⚠ drops schedule window check skipped: "
                  f"{type(_exc).__name__}: {_exc}")

        # Run engine
        engine = ScoreboardEngine(
            client=client,
            territory_user_map=territory_user_map,
            fiscal_year_start=FY_START,
            months=MONTHS,
            current_month=CURRENT_MONTH,
            rep_name_map=rep_name_map,
            drops_detail_only_users=territory_map.get("drops_detail_only_users") or {},
            drops_extra_users=territory_map.get("drops_extra_users") or {},
        )
        if _window_problems:
            # Plain strings on purpose: this is a schedule-level note, not a
            # member, so it renders into "What happened" with the member
            # columns blank (receipts_sheet.build_flags_sheet).
            engine.flags.setdefault(_cryw.DROPS_WINDOW_FLAG,
                                    []).extend(_window_problems)
        t0 = datetime.now()
        data = engine.run(
            territory_map=territory_map,
            fiscal_year=FISCAL_YEAR,
            goals_config_path=PROJECT_ROOT / "config" / "goals.yaml",
            admin_inputs_path=PROJECT_ROOT / "config" / "admin_inputs.yaml",
            progress_callback=progress,
        )
        elapsed = (datetime.now() - t0).total_seconds()
        print(f"\nEngine completed in {elapsed:.1f}s")

        # Save snapshot to cache for instant subsequent iterations.
        # Wrapped 2026-06-05 PM (verify High #6): a local-disk hiccup
        # (disk full, permission, read-only FS) MUST NOT lose the 80-min
        # SLX result. SP push at end-of-main is the durable store; local
        # cache is just a fast-iter convenience.
        try:
            from reports.membership_performance_tracker.logic import receipts_capture
            from reports.membership_performance_tracker.logic import month_close as _mc_r
            _close_doc = _mc_r.load_close(PERIOD) or {}
            if _close_doc.get("sealed"):
                # a SEALED month's receipts are part of its locked record —
                # a later live rerun must not overwrite the member lists the
                # sealed numbers were verified against (8/6, step 2)
                print("     ⚑ receipts NOT rewritten — this month is sealed; "
                      "its member lists are part of the locked record")
            elif receipts_capture.captured_families():
                rp = receipts_capture.save(PERIOD)
                print(f"     ⚑ receipts raw captured ({', '.join(f'{k}:{v}' for k,v in sorted(receipts_capture.captured_families().items()))}) → {rp.name}")
                # THE CAPTURE MUST OUTLIVE THE CONTAINER (2026-08-18). When the
                # 8/18 receipts build failed, the one artifact that could have
                # reproduced it — this file — existed only on Cloud Run's
                # ephemeral disk and was gone by morning. The diagnosis took an
                # hour of reconstruction instead of five minutes of reading.
                # Push it to SharePoint every run, best-effort.
                try:
                    from src.hub.datahub import DataHub as _DHrc
                    _hubrc = _DHrc.connect(require_sharepoint=False)
                    if getattr(_hubrc, "_sp", None) is not None:
                        _hubrc.write_hub_file(
                            "Reports/Membership Performance Report/Data/"
                            f"receipts_raw_{PERIOD}.json", rp.read_bytes())
                        print(f"     ↑ raw capture pushed to SP ({rp.stat().st_size/1e6:.1f} MB)")
                except Exception as _rcexc:
                    print(f"     (raw-capture SP push skipped: {type(_rcexc).__name__}: {_rcexc})")
        except Exception as exc:
            print(f"  ⚠ receipts capture save failed (numbers unaffected): {type(exc).__name__}: {exc}")

        progress(92, "Saving snapshot to local cache...")
        # The cache holds SData's OWN numbers, saved BEFORE the overlay: that is
        # what keeps SData underneath as a free cross-check, and it makes the
        # replay path meaningful (it re-applies the overlay itself). Saving
        # overlaid values would quietly make the two paths disagree about what a
        # "cached" number even is.
        try:
            save_scoreboard(data, cache_path, source="slx-preoverlay")
            print(f"Cache saved → {cache_path}")
        except Exception as exc:
            print(f"  ⚠ Local cache save failed (data still in memory; SP push will rescue): "
                  f"{type(exc).__name__}: {exc}", flush=True)

        # Same publish step as the replay path — Crystal's two families, then
        # the derived layers. Missing before 2026-07-28: every live pull shipped
        # SData's billables and drops.
        data = _finalize_for_publish(engine, PERIOD)

        # AUTO-SEAL (Jiho GO 8/5): the first live pull after a period closes
        # IS the official post-ITD capture — copy the whole cache into the
        # close doc, once. From here on the month is data-immutable: any
        # later rebuild gets these values stamped back by apply_frozen.
        from reports.membership_performance_tracker.logic import month_close as _mclose
        if _mclose.is_closed(PERIOD) and not (_mclose.load_close(PERIOD) or {}).get("sealed"):
            _hub = None
            try:
                from src.hub.datahub import DataHub
                _h = DataHub.connect(require_sharepoint=False)
                _hub = _h if getattr(_h, "_sp", None) is not None else None
            except Exception:
                pass
            try:
                # post-overlay `data` — never the pre-overlay cache
                # file (SEAL-1, overnight review 8/10)
                _mclose.seal(PERIOD, hub=_hub, data=data)
                print(f"  🔒 {PERIOD} sealed — every metric locked from this "
                      f"post-ITD capture; the month can no longer be changed "
                      f"by a rerun")
            except Exception as exc:
                print(f"  ⚠ seal failed (close doc unchanged): "
                      f"{type(exc).__name__}: {exc}")

    # Map → write
    progress(96, "Organizing the numbers into the report layout...")

    # MONTH-CLOSE OVERLAY (2026-08-03, designed with Jiho): closed months'
    # retention was photographed pre-ITD and frozen in close_<period>.json —
    # a later pull recomputes it from post-ITD data (write-offs shrink the
    # denominator), so the frozen values are overlaid here, on EVERY build,
    # live or cache. A frozen column cannot be moved by a pull or a code
    # change; only a deliberate re-freeze (loud, archived) changes it.
    from reports.membership_performance_tracker.logic import month_close as _mclose
    for note in _mclose.apply_frozen(data, _mclose.load_all_closes(), period=PERIOD):
        print(f"  🔒 {note}")

    # SEAL CONVERGENCE (2026-08-06, amendment-#3 forensics): the overlay
    # above heals the in-memory build, but the cache FILE keeps whatever a
    # materialize or the console's SP-sync last wrote — twice an amended
    # sealed value survived in the workbook while dying in the cache (band
    # comps 8/5, fee-invoice dollars 8/6). Re-saving the stamped data makes
    # every build converge the cache file to the seal. Non-slx source →
    # pulled_at is carried, so the freshness badge stays honest.
    try:
        save_scoreboard(data, cache_path, source="frozen-stamped")
    except Exception as exc:
        print(f"  ⚠ post-overlay cache save failed: {type(exc).__name__}: {exc}")

    # ADJUSTMENTS OVERLAY (2026-08-14). Hand corrections are replayed onto a
    # COPY of the build, never onto `data` itself, and only here — after the
    # seal and after apply_frozen, before the mapper. Every other position is
    # wrong, and each is wrong in a way that hides itself:
    #   · before the Crystal overlay (~1068): drops fields are rebound, the
    #     adjustment is discarded;
    #   · before seal() (~1086): the seal photographs adjusted values and
    #     apply_frozen stamps them back forever — the overlay then adds again
    #     on every build. Permanent, silent doubling, and the seal is
    #     write-once so it cannot be undone;
    #   · before apply_frozen (~1104): `target.clear()` wipes it;
    #   · onto `data` at all: `_publish_to_hub` archives `data` to the snapshot
    #     archive, and `freeze()` later reads a snapshot to build a month's
    #     pre-ITD retention photograph — so an adjustment would silently
    #     contaminate a LATER month's close, three weeks on, through a
    #     different file.
    # The copy keeps the cache, the seal and the archive as the program's own
    # numbers; the workbook shows the corrected ones. Both stay recoverable.
    import copy as _copy
    from reports.membership_performance_tracker.logic import adjustments as _adj
    # FY-wide: every later report shows the same earlier columns, so a
    # correction must follow its MONTH, not the report it was filed from.
    _adjustments = _adj.for_build(_adj.load_fy(FY_START), PERIOD)
    if _adjustments:
        data_for_report = _copy.deepcopy(data)
        for note in _adj.apply_to(data_for_report, _adjustments,
                                  recompute=_adj.recompute):
            print(f"  ✏️  {note}")
    else:
        data_for_report = data

    mapper = TrackerV4Mapper(fiscal_year_start=FY_START, current_month=CURRENT_MONTH)
    rows = mapper.map(data_for_report)

    # History assembler (Jiho 2026-07-22): photo metrics (penetration,
    # billables) are only true for their own pull day — fill each PRIOR
    # month's columns from THAT month's stored snapshot so trends read real
    # captured history. Months never photographed stay blank (honest).
    from reports.membership_performance_tracker.history import assemble_photo_history
    rows.extend(assemble_photo_history(CURRENT_MONTH, FY_START,
                                       PROJECT_ROOT / "data" / "cache",
                                       sp_fallback=True))
    print(f"     Prepared {len(rows):,} data points across all territories")
    print(f"     Dropped accounts logged:  {len(data.drops_detail):,}")
    print(f"     Closed businesses logged: {len(data.closed_detail):,}")

    progress(98, "Writing the report spreadsheet...")
    output_path = OUTPUT_DIR / f"Membership_Performance_Report_{cal_year}-{fy_month_int:02d}.xlsx"
    TrackerV4Writer(template_path=TEMPLATE_PATH).write(
        output_path=output_path,
        metric_rows=rows,
        dashboard_month=CURRENT_MONTH, dashboard_year=(FY_START if MONTH_ABB_TO_INT[CURRENT_MONTH] >= 10 else FY_START + 1),
            drops_rows=data.drops_detail,
        closed_rows=data.closed_detail,
    )
    progress(100, "Done")

    # RECEIPTS ARE PART OF THE RUN, NOT A CHORE (wired 2026-08-11).
    # `scripts/build_receipts.py` had ZERO callers — the nightly rebuilt the
    # REPORT and never the receipts, so the Trace page's member lists drifted
    # from the published face on every rebuild with no error anywhere.
    # Measured that day: 36 cells disagreed purely on capture vintage (the
    # receipts held the 16:44 Crystal capture, the cache the 11:00 one).
    # Trace is the "where did this number come from" promise; on a decay timer
    # it quietly stops being true, and the next operator has no way to know.
    # Must run BEFORE _attach_transparency_sheets, which reads receipts to
    # build the Members tab. LIVE ONLY (it needs SLX and this run's own raw
    # capture) and best-effort — receipts must never take the nightly down.
    if not use_cache:
        _rebuild_receipts(PERIOD)

    _attach_transparency_sheets(output_path, PERIOD)

    print(f"\n✓ Report ready: {output_path.name}  ({output_path.stat().st_size/1024:.0f} KB)")
    # Marker line for the UI to capture (not shown to users)
    print(f"OUTPUT:{output_path}", flush=True)

    # Push cache snapshot + finished xlsx to SharePoint so any team member
    # (and any future report engine) can read the same data without local
    # access. Wired 2026-06-05 PM — see _publish_to_hub docstring. Best-effort:
    # SP failures surface in result["errors"] but never block runner exit.
    # The error list is captured into the module-level _LAST_PUBLISH_WARNINGS
    # so the __main__ wrapper can forward it to _update_schedule_status —
    # otherwise a silent SP failure would write status="done" with no signal
    # to the console UI (High #3 verify fix 2026-06-05 PM).
    global _LAST_PUBLISH_WARNINGS
    period_str = f"{cal_year}-{fy_month_int:02d}"
    # is_live_slx = NOT use_cache. Cache-mode runs publish per-run audit + xlsx
    # but leave the canonical _official snapshot alone, so a partial cached
    # state can't get cemented as canonical (structural fix 2026-06-06 —
    # see _publish_to_hub docstring).
    publish_result = _publish_to_hub(
        data=data, output_path=output_path, period=period_str,
        is_live_slx=not use_cache,
    )
    _LAST_PUBLISH_WARNINGS = list(publish_result.get("errors") or [])
    if publish_result["cache_snapshot_path"]:
        print(f"  ↑ Cache snapshot pushed to SP: {publish_result['cache_snapshot_path']}")
    elif use_cache:
        print(f"  · Cache-mode run — official snapshot intentionally NOT overwritten")
    if publish_result["xlsx_sp_path"]:
        print(f"  ↑ Report pushed to SP: {publish_result['xlsx_sp_path']}")
    for err in publish_result["errors"]:
        print(f"  ⚠ SP publish: {err}", flush=True)

    # Build the findings JSON for the UI's "Findings from last run" section.
    alerts_path = OUTPUT_DIR / "last_run_alerts.json"
    try:
        import json
        alerts = build_alerts_dict(data, CURRENT_MONTH, FISCAL_YEAR, rep_name_map)
        alerts_path.write_text(json.dumps(alerts, indent=2, default=str))
    except Exception as exc:
        import warnings as _warnings
        _warnings.warn(f"Could not write findings file: {exc}")

    # ----- Quick sanity check (one territory, for confidence) -------
    def _fmt(v):
        return "—" if v is None else v
    p_paid  = data.ret_paid.get("Pierce", {}).get(CURRENT_MONTH)
    p_bill  = data.ret_billed.get("Pierce", {}).get(CURRENT_MONTH)
    p_ht    = data.hosp_bills_target.get("Pierce", {}).get(CURRENT_MONTH)
    p_hnt   = data.hosp_bills_non_target.get("Pierce", {}).get(CURRENT_MONTH)
    p_all   = data.allied_bills.get("Pierce", {}).get(CURRENT_MONTH)
    p_rt    = data.revenue_target.get("Pierce", {}).get(CURRENT_MONTH)
    p_rnt   = data.revenue_non_target.get("Pierce", {}).get(CURRENT_MONTH)
    print(f"\nQuick check — Pierce, {CURRENT_MONTH}:")  # label matches the data shown (2026-07-14)
    print(f"     Retention:  {_fmt(p_paid)} of {_fmt(p_bill)} renewed")
    print(f"     Billables:  {_fmt(p_ht)} target + {_fmt(p_hnt)} non-target + {_fmt(p_all)} allied")
    print(f"     New sales:  ${_fmt(p_rt):,.0f} target + ${_fmt(p_rnt):,.0f} non-target"
          if isinstance(p_rt, (int, float)) and isinstance(p_rnt, (int, float))
          else f"     New sales:  {_fmt(p_rt)} target + {_fmt(p_rnt)} non-target")

    return 0


if __name__ == "__main__":
    # Bug 3 fix (2026-06-05): if the scheduler launched us, write our terminal
    # status back to data/schedule.json so the console UI no longer reads
    # 'running (pid N)' after we exit. Manual invocations (PID mismatch) are
    # left alone by _update_schedule_status.
    rc = 1
    status = "error: unknown"
    try:
        rc = main()
        status = "done" if rc == 0 else f"error (exit {rc})"
    except KeyboardInterrupt:
        status = "error: interrupted"
        raise
    except SystemExit as se:
        # SystemExit derives from BaseException, so it bypasses `except Exception`
        # below. Without explicit handling, a `sys.exit(0)` inside main() (or any
        # imported lib at import time) would leave status='error: unknown' for a
        # successful run — finding #3 (2026-06-05). Translate the exit code into
        # an honest status, then re-raise so the process exits with the intended rc.
        code = se.code
        if code is None or code == 0:
            status = "done"
        else:
            status = f"error (exit {code})"
        raise
    except Exception as exc:
        status = f"error: {type(exc).__name__}: {exc}"
        raise
    finally:
        _update_schedule_status(status, warnings=_LAST_PUBLISH_WARNINGS)
    sys.exit(rc)
