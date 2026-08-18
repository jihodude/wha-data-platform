"""
audit.py — Audit and history layer for the WHA Data Hub.

Three components built here:

  1. Snapshot archive — dated, frozen copies of ScoreboardData per reporting period.
     These are the YoY/MoM baseline: when the main session reconstructs historical data
     (e.g. from a full SLX re-pull), it deposits the result here so future reports can
     compare against it without re-querying SLX.

  2. Run changelog — produced after each SLX re-pull. Diffs the current data against
     the previous snapshot and records every delta. This is also the discrepancy-checker:
     it surfaces things like "Pierce billables 184 → 186 (Δ+2)" or a member that vanished
     between two consecutive pulls.

  3. Input changelog — append-only JSONL log recording admin input changes: who changed
     what, when, with the old value and new value (e.g. a goal amount was revised, a
     territory rep name was corrected).

────────────────────────────────────────────────────────────────────────────────
SharePoint paths (all relative to SP_HUB_FOLDER = "Internal Dept Files/Membership Data Hub")
────────────────────────────────────────────────────────────────────────────────

  Audit & History Log/Snapshots/<period>/
      snapshot_<period>_official.json    ← monthly baseline (overwritten each close)
      snapshot_<period>_<run_ts>.json    ← per-run records (pruned to keep_n latest)

  Audit & History Log/Run Changelogs/
      changelog_<period>_<run_ts>.json   ← delta report for a single re-pull

  Audit & History Log/Input Changelogs/
      input_changelog.jsonl              ← append-only log of admin input changes

────────────────────────────────────────────────────────────────────────────────
Primary interface for the main session (SLX reconstruction)
────────────────────────────────────────────────────────────────────────────────

    from src.hub.datahub import DataHub

    hub = DataHub.connect()

    # Deposit reconstructed historical data (called by the main session):
    hub.archive_snapshot("2026-03", scoreboard_data)              # per-run record
    hub.archive_snapshot("2026-03", scoreboard_data,
                         is_official=True)                         # lock the baseline

    # Check what changed vs the previous pull (discrepancy-checker):
    changelog = hub.create_run_changelog("2026-03", scoreboard_data)
    print(changelog["summary"])  # e.g. "3 numeric delta(s), 1 vanished key(s)"

    # Log an admin input change:
    hub.record_input_change("territory_map.yaml", "territories.Pierce.rep_name",
                            "Jane Smith", "John Doe", user="<sp_username>")

    # Prune old per-run snapshots (keep 5 most recent):
    hub.prune_run_snapshots("2026-03", keep_n=5)

────────────────────────────────────────────────────────────────────────────────
Or call the module-level functions directly (each takes `hub` as a parameter):
────────────────────────────────────────────────────────────────────────────────

    from src.hub.audit import archive_snapshot, create_run_changelog

    path = archive_snapshot("2026-03", scoreboard_data, hub)
    cl   = create_run_changelog("2026-03", scoreboard_data, hub)
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

# ── SharePoint sub-path constants ─────────────────────────────────────────────
# All paths are relative to SP_HUB_FOLDER (defined in datahub.py).
# Pass them to hub.read_hub_file() / hub.write_hub_file().

AUDIT_ROOT            = "Audit & History Log"
SNAPSHOTS_ROOT        = f"{AUDIT_ROOT}/Snapshots"
RUN_CHANGELOGS_ROOT   = f"{AUDIT_ROOT}/Run Changelogs"
INPUT_CHANGELOGS_ROOT = f"{AUDIT_ROOT}/Input Changelogs"

INPUT_CHANGELOG_FILE  = f"{INPUT_CHANGELOGS_ROOT}/input_changelog.jsonl"


# ── Path helpers ──────────────────────────────────────────────────────────────

def snapshot_folder(period: str) -> str:
    """Hub sub-path for the snapshot folder of a given period, e.g. 'Audit & History Log/Snapshots/2026-03'."""
    return f"{SNAPSHOTS_ROOT}/{period}"


def snapshot_filename(
    period: str, is_official: bool = False, run_ts: Optional[str] = None
) -> str:
    """Return just the filename (no folder prefix) for a snapshot file."""
    if is_official:
        return f"snapshot_{period}_official.json"
    ts = run_ts or _now_ts()
    return f"snapshot_{period}_{ts}.json"


def snapshot_path(
    period: str, is_official: bool = False, run_ts: Optional[str] = None
) -> str:
    """Full hub sub-path for a snapshot file (folder + filename)."""
    return f"{snapshot_folder(period)}/{snapshot_filename(period, is_official, run_ts)}"


def run_changelog_path(period: str, run_ts: Optional[str] = None) -> str:
    """Full hub sub-path for a run-changelog file."""
    ts = run_ts or _now_ts()
    return f"{RUN_CHANGELOGS_ROOT}/changelog_{period}_{ts}.json"


# ── Internal utilities ────────────────────────────────────────────────────────

def _now_ts() -> str:
    """
    UTC timestamp safe for filenames: YYYY-MM-DDTHH-MM-SS-mmmmmm-XXXXZ
    (colons replaced; microsecond + 4-char hex tail to collision-proof
    concurrent runs from different machines).

    Microsecond precision alone covers same-machine same-instant collisions
    (very rare). The 4-char random suffix covers the genuinely concurrent
    case where two laptops happen to start a refresh in the same wall-clock
    microsecond, which is improbable but not zero — and now impossible to
    silently lose an audit-trail entry to.

    Verify-fix 2026-06-05 PM (PROBE 4 of edge-case audit). Snapshot filenames
    historically collided at second precision; the audit trail is meant to be
    immutable per-run.
    """
    import secrets
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H-%M-%S-%f") + "-" + secrets.token_hex(2) + "Z"


def _to_dict(data: Any) -> dict:
    """
    Normalize `data` to a plain dict for JSON serialization.

    Accepts:
      - dict       → returned as-is
      - bytes      → decoded as UTF-8 JSON
      - dataclass  → converted via dataclasses.asdict()
    """
    if isinstance(data, dict):
        return data
    if isinstance(data, bytes):
        return json.loads(data.decode("utf-8"))
    try:
        import dataclasses
        if dataclasses.is_dataclass(data) and not isinstance(data, type):
            return dataclasses.asdict(data)
    except Exception:
        pass
    raise TypeError(
        f"Cannot convert {type(data).__name__} to dict. "
        "Pass a dict, bytes (JSON), or a dataclass instance."
    )


def _flatten_dict(d: Any, prefix: str = "", sep: str = ".") -> Dict[str, Any]:
    """
    Recursively flatten a nested dict/list to {dotted.path: leaf_value}.

    Used by diff_data() to compare two arbitrarily-nested data structures
    by turning them into flat {path: value} maps.

    Example:
        {"a": {"b": 1, "c": [2, 3]}}
        → {"a.b": 1, "a.c.0": 2, "a.c.1": 3}
    """
    items: Dict[str, Any] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            key = f"{prefix}{sep}{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                items.update(_flatten_dict(v, key, sep))
            else:
                items[key] = v
    elif isinstance(d, list):
        for i, v in enumerate(d):
            key = f"{prefix}{sep}{i}" if prefix else str(i)
            if isinstance(v, (dict, list)):
                items.update(_flatten_dict(v, key, sep))
            else:
                items[key] = v
    else:
        items[prefix] = d
    return items


# ── Public API ────────────────────────────────────────────────────────────────

def archive_snapshot(
    period: str,
    data: Union[bytes, dict],
    hub,
    is_official: bool = False,
    run_ts: Optional[str] = None,
) -> str:
    """
    Write a frozen snapshot of the current data for the given reporting period.

    Call this after every SLX pull to keep a per-run record, and once per month
    (is_official=True) to lock in the official baseline for YoY/MoM calculations.

    Args:
        period:      Reporting period string, e.g. "2026-03".
        data:        Snapshot content. Accepts:
                       • dict               — serialized to JSON as-is.
                       • bytes              — treated as already-serialized JSON.
                       • dataclass instance — converted via dataclasses.asdict()
                         (e.g. pass a ScoreboardData instance directly).
        hub:         Connected DataHub instance (provides write_hub_file).
        is_official: True  → writes snapshot_<period>_official.json.
                            The official snapshot is the YoY/MoM anchor; calling
                            with is_official=True overwrites any previous official
                            for this period.
                     False → writes snapshot_<period>_<run_ts>.json (per-run record).
        run_ts:      Override the run timestamp (ISO string, colons → hyphens).
                     Defaults to current UTC time. Ignored when is_official=True.

    Returns:
        Hub sub-path of the written file (relative to SP_HUB_FOLDER), e.g.:
        "Audit & History Log/Snapshots/2026-03/snapshot_2026-03_official.json"

    SharePoint full paths (relative to drive root):
        {SP_HUB_FOLDER}/Audit & History Log/Snapshots/<period>/snapshot_<period>_official.json
        {SP_HUB_FOLDER}/Audit & History Log/Snapshots/<period>/snapshot_<period>_<run_ts>.json

    Local mirror (in data/hub/ relative to project root):
        data/hub/Audit & History Log/Snapshots/<period>/snapshot_<period>_official.json
        data/hub/Audit & History Log/Snapshots/<period>/snapshot_<period>_<run_ts>.json
    """
    ts = run_ts or _now_ts()
    data_dict = _to_dict(data)

    envelope: Dict[str, Any] = {
        "schema_version": 1,
        "period": period,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "is_official": is_official,
        "run_id": ts,
        "data": data_dict,
    }

    path = snapshot_path(period, is_official=is_official, run_ts=ts)
    hub.write_hub_file(path, json.dumps(envelope, indent=2, default=str).encode("utf-8"))
    return path


def _load_latest_snapshot(period: str, hub) -> Optional[Dict]:
    """
    Load the most recent snapshot for the given period from the hub.

    Prefers the official snapshot; falls back to the newest per-run snapshot
    (sorted lexicographically on ISO-timestamp filenames).

    Returns None if no snapshots exist for this period.
    """
    folder = snapshot_folder(period)
    try:
        items = hub.list_hub_folder(folder)
    except Exception:
        return None

    json_files = sorted(
        [it for it in items if it.get("name", "").endswith(".json")],
        key=lambda it: it["name"],
        reverse=True,
    )

    # Prefer official snapshot
    for it in json_files:
        if "_official" in it["name"]:
            try:
                raw = hub.read_hub_file(f"{folder}/{it['name']}")
                return json.loads(raw.decode("utf-8"))
            except Exception as e:
                # A found-but-unreadable snapshot must not be silently skipped
                # (2026-07-17 fail-loud): warn, then try the next candidate.
                print(f"  [snapshot] WARNING: official snapshot {it['name']} for "
                      f"{period} unreadable/corrupt ({type(e).__name__}: {e}) — "
                      f"trying per-run snapshots.", flush=True)

    # Fall back to newest per-run
    for it in json_files:
        if "_official" not in it["name"]:
            try:
                raw = hub.read_hub_file(f"{folder}/{it['name']}")
                return json.loads(raw.decode("utf-8"))
            except Exception as e:
                print(f"  [snapshot] WARNING: per-run snapshot {it['name']} for "
                      f"{period} unreadable/corrupt ({type(e).__name__}: {e}) — "
                      f"trying older snapshots.", flush=True)

    return None


def diff_data(prev_dict: dict, curr_dict: dict) -> List[Dict]:
    """
    Compare two serializable dicts and return a list of change entries.

    Both dicts are flattened to {dotted.path: leaf_value} before comparison.
    Only keys that differ between prev and curr are returned (no-change keys
    are omitted for readability).

    This is the core of the discrepancy-checker: pass the previous snapshot's
    "data" dict and the current SLX pull's dict to surface things like:
        "Pierce billables: 184 → 186 (Δ+2)"
        "member 12345 vanished"
        "King.new_members: 14 → 17 (Δ+3)"

    Each entry dict contains:
        path:   str        — dotted key path (e.g. "territories.Pierce.billables")
        before: Any        — value in prev_dict (None if newly appeared)
        after:  Any        — value in curr_dict (None if vanished)
        delta:  float|None — curr − prev for numeric changes; None otherwise
        note:   str|None   — "appeared" | "vanished" | None

    Returns an empty list if the two dicts are identical (after flattening).
    """
    prev_flat = _flatten_dict(prev_dict)
    curr_flat = _flatten_dict(curr_dict)

    all_keys = set(prev_flat) | set(curr_flat)
    changes: List[Dict] = []

    for key in sorted(all_keys):
        in_prev = key in prev_flat
        in_curr = key in curr_flat
        prev_val = prev_flat.get(key)
        curr_val = curr_flat.get(key)

        if not in_prev:
            changes.append({
                "path": key, "before": None, "after": curr_val,
                "delta": None, "note": "appeared",
            })
        elif not in_curr:
            changes.append({
                "path": key, "before": prev_val, "after": None,
                "delta": None, "note": "vanished",
            })
        elif prev_val != curr_val:
            delta = None
            if isinstance(prev_val, (int, float)) and isinstance(curr_val, (int, float)):
                delta = curr_val - prev_val
            changes.append({
                "path": key, "before": prev_val, "after": curr_val,
                "delta": delta, "note": None,
            })

    return changes


def create_run_changelog(
    period: str,
    current_data: Union[bytes, dict],
    hub,
    run_ts: Optional[str] = None,
) -> Dict:
    """
    Archive a per-run snapshot and produce a changelog vs the previous snapshot.

    This is the primary discrepancy-checker. Call it after each SLX re-pull to
    surface exactly what changed since the last snapshot.

    Steps performed internally:
    1. Load the most recent snapshot for `period` (official preferred, else newest).
    2. Archive `current_data` as a new per-run snapshot.
    3. Diff prev vs current — every changed leaf path is reported.
    4. Write the changelog JSON to Run Changelogs/.
    5. Return the changelog dict.

    Args:
        period:       Reporting period, e.g. "2026-03".
        current_data: Current data — dict, bytes (JSON), or dataclass instance.
        hub:          Connected DataHub (provides read_hub_file / write_hub_file).
        run_ts:       Override the run timestamp. Defaults to now UTC.

    Returns:
        Changelog dict with keys:
            schema_version, period, generated_at, run_id,
            prev_snapshot (filename or null), curr_snapshot (filename),
            change_count, summary, changes (list of change entries)

        Also written to SharePoint/local at:
            Audit & History Log/Run Changelogs/changelog_<period>_<run_ts>.json
    """
    ts = run_ts or _now_ts()
    curr_dict = _to_dict(current_data)

    # Load previous snapshot and extract its data payload
    prev_snapshot = _load_latest_snapshot(period, hub)
    if prev_snapshot is not None:
        prev_dict = prev_snapshot.get("data", prev_snapshot)
        if prev_snapshot.get("is_official"):
            prev_filename = f"snapshot_{period}_official.json"
        else:
            prev_run_id = prev_snapshot.get("run_id", "unknown")
            prev_filename = f"snapshot_{period}_{prev_run_id}.json"
    else:
        prev_dict = {}
        prev_filename = None

    # Archive the current state as a per-run snapshot
    curr_path = archive_snapshot(period, curr_dict, hub, is_official=False, run_ts=ts)
    curr_filename = curr_path.split("/")[-1]

    # Compute delta
    changes = diff_data(prev_dict, curr_dict)

    # Build a human-readable summary
    numeric_deltas = [c for c in changes if c["delta"] is not None]
    vanished       = [c for c in changes if c["note"] == "vanished"]
    appeared       = [c for c in changes if c["note"] == "appeared"]
    other          = [c for c in changes
                      if c["delta"] is None and c["note"] not in ("vanished", "appeared")]
    parts = []
    if numeric_deltas:
        parts.append(f"{len(numeric_deltas)} numeric delta(s)")
    if vanished:
        parts.append(f"{len(vanished)} vanished key(s)")
    if appeared:
        parts.append(f"{len(appeared)} appeared key(s)")
    if other:
        parts.append(f"{len(other)} other change(s)")
    summary = ", ".join(parts) if parts else "no changes detected"

    changelog = {
        "schema_version": 1,
        "period": period,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": ts,
        "prev_snapshot": prev_filename,
        "curr_snapshot": curr_filename,
        "change_count": len(changes),
        "summary": summary,
        "changes": changes,
    }

    cl_path = run_changelog_path(period, run_ts=ts)
    hub.write_hub_file(cl_path, json.dumps(changelog, indent=2, default=str).encode("utf-8"))
    return changelog


def record_input_change(
    filename: str,
    field_path: str,
    old_value: Any,
    new_value: Any,
    user: Optional[str] = None,
    hub=None,
) -> Dict:
    """
    Append an entry to the input changelog recording an admin input change.

    Call this whenever a shared or report-specific input is modified — e.g. a
    revenue goal in admin_inputs.xlsx was revised, a territory rep name changed
    in territory_map.yaml, or a market size was corrected.

    The changelog is an append-only JSONL file (one JSON object per line). Reading
    it gives the full audit trail: what changed, when, from what value, to what value.

    Args:
        filename:   Input file that changed (e.g. "territory_map.yaml").
        field_path: Dotted path to the changed field (e.g. "territories.Pierce.rep_name").
        old_value:  Value before the change.
        new_value:  Value after the change.
        user:       Username who made the change (optional, for the audit trail).
        hub:        Connected DataHub. If provided, the entry is appended to
                    SharePoint/local. If None, the entry dict is returned without
                    being persisted (useful for dry-run / testing).

    Returns:
        The log entry dict (whether or not it was persisted).

    SharePoint target (append-only JSONL):
        Audit & History Log/Input Changelogs/input_changelog.jsonl
    """
    entry: Dict[str, Any] = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "file": filename,
        "field": field_path,
        "before": old_value,
        "after": new_value,
        "user": user,
    }

    if hub is not None:
        new_line = json.dumps(entry, default=str) + "\n"
        try:
            existing = hub.read_hub_file(INPUT_CHANGELOG_FILE).decode("utf-8")
        except Exception:
            existing = ""
        hub.write_hub_file(INPUT_CHANGELOG_FILE, (existing + new_line).encode("utf-8"))

    return entry


def prune_run_snapshots(
    period: str,
    hub,
    keep_n: int = 5,
) -> List[str]:
    """
    Prune old per-run snapshots for a period, keeping only the N most recent.

    Official snapshots (snapshot_<period>_official.json) are NEVER pruned.
    Per-run snapshots are sorted by filename (ISO timestamp suffix), and the
    oldest beyond keep_n are deleted from both SharePoint and the local mirror.

    Args:
        period:  Reporting period, e.g. "2026-03".
        hub:     Connected DataHub (provides list_hub_folder / delete_hub_file).
        keep_n:  Number of per-run snapshots to retain (default 5).

    Returns:
        List of filenames (not full paths) that were deleted.
        Returns an empty list if there is nothing to prune or the folder doesn't exist.
    """
    folder = snapshot_folder(period)
    try:
        items = hub.list_hub_folder(folder)
    except Exception:
        return []

    run_files = sorted(
        [it["name"] for it in items
         if it.get("name", "").endswith(".json") and "_official" not in it["name"]],
        reverse=True,  # newest first (ISO timestamps sort lexicographically)
    )

    to_delete = run_files[keep_n:]
    deleted: List[str] = []
    for name in to_delete:
        subpath = f"{folder}/{name}"
        try:
            hub.delete_hub_file(subpath)
            deleted.append(name)
        except Exception:
            pass

    return deleted
