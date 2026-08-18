"""
datahub.py — DataHub: the single access point to the central data cache.

This is the interface every report engine should use to reach the shared
membership data and the SharePoint Data Hub. New engines (e.g. the Dues
Analysis engine) plug in through here instead of re-implementing SLX scraping,
cache loading, or SharePoint plumbing.

Mental model (matches the architecture diagram):

    SLX ─► Engine ─┐
                   ├─► CENTRAL DATA CACHE ◄── DataHub ──► Report Engines
    Admin input ───┘   (cache JSON + SharePoint)          (tracker, dues, ...)

What a report engine gets from DataHub:
  • load_data()        → the latest ScoreboardData (every scraped + computed metric)
  • read_admin_inputs()→ parsed admin Excel (goals, market sizes, activities, ...)
  • read_file/write_file → raw file access to the SharePoint Data Hub folder
  • publish_report()   → write a finished report to the Data Hub + locally

What a report engine should NOT do:
  • Talk to SLX directly (that's the scraping Engine's job — it already ran and
    populated the cache). Reading stale-but-consistent cached data is correct;
    re-scraping per report would hammer SLX.

Usage (in a new report engine):

    from src.hub.datahub import DataHub
    hub = DataHub.connect()
    data = hub.load_data()                 # ScoreboardData
    admin = hub.read_admin_inputs()        # dict of admin inputs
    # ... build your report bytes ...
    hub.publish_report("Dues Analysis 2026-03.xlsx", report_bytes)
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Local mirrors of the central cache (SharePoint is the shared source of truth;
# these local paths are the working copies the engine reads/writes).
CACHE_DIR  = PROJECT_ROOT / "data" / "cache"
RAW_DIR    = PROJECT_ROOT / "data" / "raw"
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"

ADMIN_XLSX = RAW_DIR / "admin_inputs.xlsx"

# SharePoint Data Hub folder (within the "Documents" drive)
SP_HUB_FOLDER = "Internal Dept Files/Membership Data Hub"

# ── New folder structure (added in hub-restructure) ───────────────────────────
# Mirrors the target SharePoint hierarchy:
#
#   Membership Data Hub/
#     Reports/<Report Name>/{ Data/  Inputs/  Output/ }   ← one per report
#     Inputs/                                     ← territory map, FY config, etc.
#     Audit & History Log/
#       Snapshots/<period>/     ← dated frozen data per run (YoY/MoM baseline)
#       Run Changelogs/         ← per SLX re-pull: diff vs previous snapshot
#       Input Changelogs/       ← who/when/what changed in any input (old → new)
#
# All paths below are absolute SharePoint paths (relative to the drive root).
# Use hub.write_hub_file(subpath, ...) / hub.read_hub_file(subpath) for
# anything under the Data Hub; these strip SP_HUB_FOLDER automatically so
# callers only pass the sub-path.
SP_REPORTS_FOLDER           = f"{SP_HUB_FOLDER}/Reports"
SP_SHARED_INPUTS_FOLDER     = f"{SP_HUB_FOLDER}/Inputs"
SP_AUDIT_FOLDER             = f"{SP_HUB_FOLDER}/Audit & History Log"
SP_SNAPSHOTS_FOLDER         = f"{SP_AUDIT_FOLDER}/Snapshots"
SP_RUN_CHANGELOGS_FOLDER    = f"{SP_AUDIT_FOLDER}/Run Changelogs"
SP_INPUT_CHANGELOGS_FOLDER  = f"{SP_AUDIT_FOLDER}/Input Changelogs"

# Local mirror root for the new structure (data/raw/ is kept for legacy paths)
HUB_LOCAL_DIR = PROJECT_ROOT / "data" / "hub"

# Default reporting period — the cache file is named scoreboard_<cal_year>-<mm>.json.
# Honors MPR_PERIOD so the whole stack (runner, app, hub) can switch months together.
import os as _os
DEFAULT_PERIOD = _os.environ.get("MPR_PERIOD", "2026-03")


def resolve_first_available(read_fn, candidates):
    """
    Try each candidate path in order; return (bytes, path) for the first that
    reads successfully, or (None, None) if every candidate fails.

    Used for the backward-compatible SharePoint migration: callers pass the NEW
    structured location first and the OLD flat location as a fallback, so reads
    keep working before, during, and after the folder restructure.

    `read_fn(path)` must return the file bytes or raise on a miss. Any exception
    (FileNotFoundError or a transient SharePoint/auth error) makes us fall
    through to the next candidate rather than abort.
    """
    for path in candidates:
        try:
            return read_fn(path), path
        except Exception:
            continue
    return None, None


def get_or_fetch(store, key, fetch_fn, force=False):
    """
    Return a cached value from `store[key]`, fetching + caching it on a miss.

    `store` is any dict-like cache (e.g. Streamlit's session_state). On the first
    call — or when `force=True` — `fetch_fn()` is invoked and its result stored
    under `key`; subsequent calls return the cached value without re-fetching.

    Used to stop the admin console re-downloading admin_inputs.xlsx from
    SharePoint on every render; the cache is force-refreshed after an upload or a
    manual "refresh" click.
    """
    if not force and key in store:
        return store[key]
    value = fetch_fn()
    store[key] = value
    return value


class DataHub:
    """
    Facade over the central data cache + SharePoint Data Hub.

    Construct with `DataHub.connect()`. SharePoint is optional — if credentials
    aren't available, file operations fall back to the local data/ folders so
    development still works offline.
    """

    def __init__(self, sharepoint_client=None):
        self._sp = sharepoint_client

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def connect(cls, require_sharepoint: bool = False) -> "DataHub":
        """
        Build a DataHub. Attempts a SharePoint connection; if it fails and
        require_sharepoint is False, returns a hub that uses local files only.

        Args:
            require_sharepoint: if True, raise when SharePoint can't connect.
        """
        sp = None
        try:
            from src.sharepoint.client import SharePointClient
            sp = SharePointClient.from_env()
            sp.verify_connection()
        except Exception as exc:
            if require_sharepoint:
                raise
            sp = None
        return cls(sharepoint_client=sp)

    @property
    def sharepoint_connected(self) -> bool:
        return self._sp is not None

    # ------------------------------------------------------------------
    # Generic per-report cache (reconstruction P6 — the report-agnostic API)
    # ------------------------------------------------------------------
    # Design decision confirmed 2026-07-22: shared SLX client + GENERIC
    # per-(report, period) cache. New reports (dues_analysis onward) use these
    # two methods; ScoreboardData is MPR-internal and never appears here.

    def save_report_data(self, report: str, period: str, payload: dict,
                         hub_folder: Optional[str] = None) -> Path:
        """
        Persist a report's computed data for a period as an opaque JSON payload.

        Writes BOTH:
          local cache : data/cache/<report>_<period>.json   (the working copy)
          hub mirror  : Reports/<hub_folder or report>/Data/<report>_<period>.json
                        (SharePoint when connected, data/hub/ mirror always)

        `hub_folder` lets the SharePoint Reports/ folder use a human display
        name (e.g. "Dues Analysis") while the local cache filename keeps the
        code identifier (`dues_analysis`) — so one report never spawns two SP
        folders (2026-07-22: the code-name mirror had created a duplicate).

        Envelope: {"_meta": {"saved_at", "report", "period"}, "data": payload}
        — same `_meta.saved_at` convention as the MPR cache so the freshness
        guard works unchanged. Returns the local cache path.
        """
        import json
        from datetime import datetime, timezone
        envelope = {
            "_meta": {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "report": report,
                "period": period,
            },
            "data": payload,
        }
        blob = json.dumps(envelope, indent=2, default=str).encode("utf-8")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        local = CACHE_DIR / f"{report}_{period}.json"
        local.write_bytes(blob)
        folder = hub_folder or report
        self.write_hub_file(f"Reports/{folder}/Data/{report}_{period}.json", blob)
        return local

    def load_report_data(self, report: str, period: str,
                         hub_folder: Optional[str] = None) -> dict:
        """
        Load a report's payload for a period (the generic counterpart of the
        MPR-specific load_data()).

        Lookup order mirrors load_data(): hub first (SharePoint when connected,
        else the data/hub/ local mirror — the shared source of truth), then the
        local data/cache/ working copy. Raises FileNotFoundError naming both
        locations when neither has it. `hub_folder` must match the value passed
        to save_report_data (SP display-name folder).
        """
        import json
        folder = hub_folder or report
        hub_sub = f"Reports/{folder}/Data/{report}_{period}.json"
        try:
            envelope = json.loads(self.read_hub_file(hub_sub).decode("utf-8"))
            return envelope["data"]
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"  [datahub] WARNING: hub copy of {report} {period} could not "
                  f"be used ({type(e).__name__}: {e}) — falling back to LOCAL "
                  f"cache, which may be staler.", flush=True)
        local = CACHE_DIR / f"{report}_{period}.json"
        if local.exists():
            envelope = json.loads(local.read_text(encoding="utf-8"))
            return envelope["data"]
        raise FileNotFoundError(
            f"No cached data for report '{report}' period {period}. Checked hub "
            f"path '{hub_sub}' and local {CACHE_DIR / (report + '_' + period + '.json')}. "
            f"Run that report's pull first to populate."
        )

    # ------------------------------------------------------------------
    # Membership data (the MPR's computed cache — MPR-specific compat API)
    # ------------------------------------------------------------------

    def load_data(self, period: str = DEFAULT_PERIOD):
        """
        Load the latest computed membership data as a ScoreboardData object.

        MPR-SPECIFIC (P6 note): ScoreboardData and its snapshot format belong to
        reports/membership_performance_tracker; this method stays for the MPR
        and the console. New reports use load_report_data()/save_report_data().

        2026-06-05 PM: SP-first with local fallback. The lookup order is:

          1. SharePoint snapshot at
             `Audit & History Log/Snapshots/<period>/snapshot_<period>_official.json`
             (or the newest per-run snapshot if no official exists). This is
             the canonical "current cache" populated by every SLX refresh — see
             runner._publish_to_hub.
          2. Local cache file at `data/cache/scoreboard_<period>.json` (legacy
             save_scoreboard format). Used when SP is offline OR the SP folder
             has no snapshot yet.
          3. Raise FileNotFoundError citing both paths.

        Reports calling this never need to know which path won; they get a
        rehydrated ScoreboardData either way. The two on-disk formats differ
        (snapshot envelope vs `{_meta, fields}`), so this method unwraps each
        appropriately before rehydration.

        Raises FileNotFoundError if no cache exists yet (run the Engine first).
        """
        from reports.membership_performance_tracker.logic.cache import load_scoreboard, scoreboard_from_dict

        # 1) SP path — try the latest snapshot for this period
        if self._sp is not None:
            try:
                from src.hub.audit import _load_latest_snapshot
                envelope = _load_latest_snapshot(period, self)
                if envelope is not None and "data" in envelope:
                    return scoreboard_from_dict(envelope["data"])
            except Exception as e:
                # _load_latest_snapshot / list_hub_folder already warn on SP
                # listing + read/parse errors; this catches a LATER failure (e.g.
                # a snapshot envelope whose 'data' won't rehydrate). Warn rather
                # than silently downgrade to a possibly-staler local cache
                # (2026-07-17 fail-loud). Fallback itself is still correct.
                print(f"  [datahub] WARNING: SharePoint snapshot for {period} "
                      f"could not be used ({type(e).__name__}: {e}) — falling back "
                      f"to LOCAL cache, which may be staler.", flush=True)

        # 2) Local fallback
        cache_path = CACHE_DIR / f"scoreboard_{period}.json"
        if cache_path.exists():
            return load_scoreboard(cache_path)

        # 3) Nothing anywhere
        raise FileNotFoundError(
            f"No cached data found for period {period}. Checked SharePoint "
            f"snapshot path and local {cache_path}. Run the scraping engine first "
            f"(reports/membership_performance_tracker/runner.py) to populate."
        )

    def read_admin_inputs(self) -> Dict[str, Any]:
        """
        Return parsed admin inputs (goals, market sizes, activities, etc.).

        Pulls the admin Excel from SharePoint if connected (shared latest),
        else the local copy.
        """
        from src.parsers.admin_inputs import parse as parse_admin
        # Prefer SharePoint copy
        if self._sp is not None:
            try:
                import tempfile
                data = self._sp.read_file(f"{SP_HUB_FOLDER}/admin_inputs.xlsx")
                # NamedTemporaryFile, not the race-prone deprecated mktemp (P1-7)
                with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
                    f.write(data)
                    tmp = Path(f.name)
                try:
                    return parse_admin(tmp)
                finally:
                    tmp.unlink(missing_ok=True)
            except Exception as e:
                # Fall back to the local copy, but NEVER silently (P1-7 —
                # a stale local admin file quietly shipping wrong goals is
                # exactly the failure class this project exists to kill).
                print(f"  [datahub] WARNING: SharePoint admin_inputs read failed "
                      f"({type(e).__name__}: {e}) — using LOCAL copy, which may "
                      f"be stale.", flush=True)
        return parse_admin(ADMIN_XLSX)

    # ------------------------------------------------------------------
    # Raw file access to the Data Hub
    # ------------------------------------------------------------------

    def read_file(self, name: str) -> bytes:
        """Read a file from the Data Hub folder (SharePoint, else local raw/)."""
        if self._sp is not None:
            return self._sp.read_file(f"{SP_HUB_FOLDER}/{name}")
        local = RAW_DIR / name
        return local.read_bytes()

    def write_file(self, name: str, data: bytes) -> None:
        """Write a file to the Data Hub folder (SharePoint + local mirror)."""
        # Always write a local copy
        (RAW_DIR / name).parent.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / name).write_bytes(data)
        if self._sp is not None:
            self._sp.write_file(f"{SP_HUB_FOLDER}/{name}", data)

    def list_files(self) -> List[Dict]:
        """List the Data Hub folder contents (empty list if local-only)."""
        if self._sp is not None:
            return self._sp.list_folder(SP_HUB_FOLDER)
        return [{"name": p.name} for p in RAW_DIR.iterdir() if p.is_file()]

    # ------------------------------------------------------------------
    # Publishing reports
    # ------------------------------------------------------------------

    def publish_report(self, filename: str, data: bytes) -> Path:
        """
        Publish a finished report: write it locally (data/output/) and to the
        SharePoint Data Hub. Returns the local path.

        This is what a report engine calls at the end of generate().
        """
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        local_path = OUTPUT_DIR / filename
        local_path.write_bytes(data)
        if self._sp is not None:
            self._sp.write_file(f"{SP_HUB_FOLDER}/{filename}", data)
        return local_path

    # ------------------------------------------------------------------
    # Hub sub-folder infrastructure (new folder structure)
    # ------------------------------------------------------------------

    def _hub_local(self, subpath: str) -> Path:
        """Local mirror path for a hub sub-path, rooted at data/hub/."""
        return HUB_LOCAL_DIR / subpath

    def write_hub_file(self, subpath: str, data: bytes) -> None:
        """
        Write a file to any path within the Data Hub folder.

        Prefer this over write_file() for paths nested under the hub root
        (reports, audit, snapshots, etc.). write_file() is kept for backward
        compatibility with callers that pass top-level hub filenames.

        SharePoint: {SP_HUB_FOLDER}/{subpath}
        Local:      data/hub/{subpath}
        """
        local = self._hub_local(subpath)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data)
        if self._sp is not None:
            self._sp.write_file(f"{SP_HUB_FOLDER}/{subpath}", data)

    def read_hub_file(self, subpath: str) -> bytes:
        """Read a file from any path within the Data Hub folder."""
        if self._sp is not None:
            return self._sp.read_file(f"{SP_HUB_FOLDER}/{subpath}")
        return self._hub_local(subpath).read_bytes()

    def hub_file_exists(self, subpath: str) -> bool:
        """Check whether a file exists in the Data Hub."""
        if self._sp is not None:
            return self._sp.file_exists(f"{SP_HUB_FOLDER}/{subpath}")
        return self._hub_local(subpath).exists()

    def list_hub_folder(self, subpath: str) -> List[Dict]:
        """
        List items in a Data Hub sub-folder.

        Returns an empty list if the folder doesn't exist (never raises).
        Each entry is a dict with at least {"name": str}; SharePoint entries also
        include "id", "size", "lastModifiedDateTime", and optionally "file" or
        "folder" keys. Local-only entries include {"name": str, "is_folder": bool}.
        """
        if self._sp is not None:
            try:
                return self._sp.list_folder(f"{SP_HUB_FOLDER}/{subpath}")
            except Exception as e:
                # Keep the never-raise contract (callers treat [] as "absent"),
                # but NEVER silently: a network/auth error returning [] is
                # indistinguishable from an empty folder, which silently
                # downgrades the cache read to a possibly-staler LOCAL copy
                # (2026-07-17 fail-loud — same class as read_admin_inputs).
                print(f"  [datahub] WARNING: SharePoint listing failed for "
                      f"'{subpath}' ({type(e).__name__}: {e}) — treating as EMPTY; "
                      f"any read that relied on it falls back to LOCAL, which may "
                      f"be staler than SharePoint.", flush=True)
                return []
        local = self._hub_local(subpath)
        if not local.exists():
            return []
        return [
            {"name": p.name, "is_folder": p.is_dir()}
            for p in sorted(local.iterdir())
        ]

    def delete_hub_file(self, subpath: str) -> None:
        """Delete a file OR folder from the Data Hub (SharePoint + local
        mirror). Directories broke the 2026-07-22 SP folder cleanup —
        Path.unlink() raises on them (task #17); trees are removed whole."""
        local = self._hub_local(subpath)
        if local.is_dir():
            import shutil
            shutil.rmtree(local, ignore_errors=True)
        elif local.exists():
            local.unlink(missing_ok=True)
        if self._sp is not None:
            self._sp.delete_file(f"{SP_HUB_FOLDER}/{subpath}")

    # ------------------------------------------------------------------
    # Report-specific and shared input folders
    # ------------------------------------------------------------------

    def publish_report_versioned(
        self, report_name: str, filename: str, data: bytes, dated: bool = True
    ) -> Path:
        """
        Publish a finished report to the versioned Reports folder structure.

        Stores the file under:
          SharePoint: Reports/<report_name>/Output/<YYYY-MM-DD>/<filename>
          Local hub:  data/hub/Reports/<report_name>/Output/<YYYY-MM-DD>/<filename>
          Local out:  data/output/<filename>  (backward-compatible copy)

        Args:
            report_name: Human-readable report name, e.g. "Dues Analysis".
            filename:    Output filename, e.g. "Dues Analysis 2026-03.xlsx".
            data:        File content as bytes.
            dated:       If True (default), nests output under a YYYY-MM-DD sub-folder.
                         Set to False if you want a single always-current file instead.

        Returns:
            Local path to the primary output file (data/output/<filename>).
        """
        # LAYOUT 2026-08-10 (Jiho): Output/<period>/Runs/<file>_<runstamp>
        # for every generation, and Output/<period>/FINAL/<file> maintained
        # automatically for CLOSED months (a sealed build always reproduces
        # the sealed numbers, so FINAL is self-healing and amendments
        # refresh it). Closed-ness is detected from the report's own close
        # record on the hub — no import from reports/ (src/ stays pure).
        import re
        from datetime import datetime
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        local_path = OUTPUT_DIR / filename
        local_path.write_bytes(data)

        m = re.search(r"(\d{4}-\d{2})(?=\.[A-Za-z]+$)", filename)
        period = m.group(1) if m else "unperioded"
        stem, dot, ext = filename.rpartition(".")
        now = datetime.now()
        stamp = now.strftime("%Y%m%d-%H%M%S")
        # Jiho 8/10: one folder per run DAY inside Runs/ — the flat pile was
        # unreadable; deleting history was rejected (past runs are the
        # audit/rollback trail).
        self.write_hub_file(
            f"Reports/{report_name}/Output/{period}/Runs/"
            f"{now.strftime('%Y-%m-%d')}/{stem}_{stamp}.{ext}", data)

        closed = False
        try:
            # closes moved to Data/closes in the 8/10 restructure — the old
            # Closes/ probe silently disabled FINAL's self-healing
            closed = self.hub_file_exists(
                f"Reports/{report_name}/Data/closes/close_{period}.json")
        except Exception:
            pass
        if closed:
            self.write_hub_file(
                f"Reports/{report_name}/Output/{period}/FINAL/{filename}", data)
        return local_path

    def write_report_data(self, report_name: str, filename: str, data: bytes) -> None:
        """Write a data file to Reports/<report_name>/Data/<filename>."""
        self.write_hub_file(f"Reports/{report_name}/Data/{filename}", data)

    def write_report_input(self, report_name: str, filename: str, data: bytes) -> None:
        """Write a report-specific input to Reports/<report_name>/Inputs/<filename>."""
        self.write_hub_file(f"Reports/{report_name}/Inputs/{filename}", data)

    def read_report_input(self, report_name: str, filename: str) -> bytes:
        """Read a report-specific input from Reports/<report_name>/Inputs/<filename>."""
        return self.read_hub_file(f"Reports/{report_name}/Inputs/{filename}")

    def write_shared_input(self, filename: str, data: bytes) -> None:
        """Write a shared input to Inputs/<filename>."""
        self.write_hub_file(f"Inputs/{filename}", data)

    def read_shared_input(self, filename: str) -> bytes:
        """Read a shared input from Inputs/<filename>."""
        return self.read_hub_file(f"Inputs/{filename}")

    # ------------------------------------------------------------------
    # Audit and history layer (delegates to src.hub.audit)
    # ------------------------------------------------------------------

    def archive_snapshot(
        self,
        period: str,
        data: Union[bytes, dict],
        is_official: bool = False,
        run_ts: Optional[str] = None,
    ) -> str:
        """
        Archive a frozen snapshot of the current data for a reporting period.

        PRIMARY INTERFACE FOR THE MAIN SESSION: call this after each SLX
        reconstruction pass to deposit historical data into the Audit layer.

            hub.archive_snapshot("2026-03", scoreboard_data)            # per-run
            hub.archive_snapshot("2026-03", scoreboard_data,
                                 is_official=True)                       # monthly baseline

        Args:
            period:      Reporting period string, e.g. "2026-03".
            data:        Snapshot content — dict, bytes (JSON), or a dataclass
                         instance (e.g. ScoreboardData — converted automatically
                         via dataclasses.asdict()).
            is_official: True  → writes the designated monthly baseline:
                                  snapshot_<period>_official.json
                                  Overwrites any previous official for this period.
                                  This is the YoY/MoM anchor for the whole season.
                         False → writes a per-run record (default):
                                  snapshot_<period>_<run_ts>.json
            run_ts:      Override the run timestamp. Defaults to now (UTC).
                         Format: "YYYY-MM-DDTHH-MM-SSZ" (colons replaced with hyphens
                         to be filename-safe).

        Returns:
            Hub sub-path of the written file (relative to SP_HUB_FOLDER):
            "Audit & History Log/Snapshots/<period>/snapshot_<period>_official.json"
            "Audit & History Log/Snapshots/<period>/snapshot_<period>_<run_ts>.json"

        Exact SharePoint target (full path, relative to drive root):
            {SP_HUB_FOLDER}/Audit & History Log/Snapshots/<period>/
                snapshot_<period>_official.json    (is_official=True)
                snapshot_<period>_<run_ts>.json    (is_official=False)

        Exact local mirror (relative to project root):
            data/hub/Audit & History Log/Snapshots/<period>/snapshot_<period>_*.json
        """
        from src.hub.audit import archive_snapshot as _archive
        return _archive(period=period, data=data, hub=self,
                        is_official=is_official, run_ts=run_ts)

    def create_run_changelog(
        self,
        period: str,
        current_data: Union[bytes, dict],
        run_ts: Optional[str] = None,
    ) -> Dict:
        """
        Archive a per-run snapshot and diff it against the previous snapshot.

        This is the discrepancy-checker. Run it after each SLX re-pull to
        surface exactly what changed, e.g.:
            "Pierce billables: 184 → 186 (Δ+2)"
            "member 12345 vanished"
            "King.new_members: 14 → 17 (Δ+3)"

        Args:
            period:       Reporting period, e.g. "2026-03".
            current_data: Current data — dict, bytes (JSON), or dataclass instance.
            run_ts:       Override the run timestamp. Defaults to now UTC.

        Returns:
            Changelog dict with keys: period, generated_at, prev_snapshot,
            curr_snapshot, change_count, summary, changes.
            Written to:
            "Audit & History Log/Run Changelogs/changelog_<period>_<run_ts>.json"
        """
        from src.hub.audit import create_run_changelog as _cl
        return _cl(period=period, current_data=current_data, hub=self, run_ts=run_ts)

    def record_input_change(
        self,
        filename: str,
        field_path: str,
        old_value: Any,
        new_value: Any,
        user: Optional[str] = None,
    ) -> Dict:
        """
        Append an entry to the input changelog recording a change to an admin input.

        Use when a shared or report-specific input is modified — e.g. a revenue goal
        was revised, a territory rep name was corrected.

        Args:
            filename:   Input file that changed (e.g. "territory_map.yaml").
            field_path: Dotted path to the changed field
                        (e.g. "territories.Pierce.rep_name").
            old_value:  Value before the change.
            new_value:  Value after the change.
            user:       Username who made the change (optional).

        Returns:
            The log entry dict appended to:
            "Audit & History Log/Input Changelogs/input_changelog.jsonl"
        """
        from src.hub.audit import record_input_change as _ric
        return _ric(filename=filename, field_path=field_path,
                    old_value=old_value, new_value=new_value,
                    user=user, hub=self)

    def prune_run_snapshots(self, period: str, keep_n: int = 5) -> List[str]:
        """
        Prune old per-run snapshots for a period, keeping the N most recent.

        Official snapshots (snapshot_<period>_official.json) are NEVER pruned.

        Args:
            period: Reporting period, e.g. "2026-03".
            keep_n: Number of per-run snapshots to keep (default 5).

        Returns:
            List of filenames that were deleted.
        """
        from src.hub.audit import prune_run_snapshots as _prune
        return _prune(period=period, hub=self, keep_n=keep_n)
