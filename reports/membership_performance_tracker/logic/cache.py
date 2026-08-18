"""
cache.py — Serialize / deserialize ScoreboardData to/from JSON on disk.

Purpose:
    Running the engine against live SLX takes 15-25 minutes (600-800 calls).
    Iterating on mappers, writers, or architecture should not require re-running
    SLX every time. This module dumps a fully populated ScoreboardData to a
    JSON file after a successful engine run, then loads it back instantly.

Round-trip contract:
    save_scoreboard(data, path)  → JSON file
    load_scoreboard(path)        → ScoreboardData equivalent to the original

Why JSON (not pickle):
    - Human-readable: open the file and inspect what got cached
    - Version-portable: no Python version lock-in
    - Diff-friendly: spot changes between two snapshots with git/diff
    - Forward-compatible: missing fields in older snapshots default to None

What gets cached:
    Every dataclass field on ScoreboardData. Detail lists (drops_detail,
    closed_detail) are preserved as-is. None values stay None.

What doesn't get cached:
    Anything not a dataclass field. The cache is tied to the ScoreboardData
    schema — when new fields are added, regenerate the cache.

Usage:
    from reports.membership_performance_tracker.logic.cache import save_scoreboard, load_scoreboard

    # After engine.run() succeeds:
    save_scoreboard(data, Path("data/cache/scoreboard_2026-03.json"))

    # Later — skip SLX entirely:
    data = load_scoreboard(Path("data/cache/scoreboard_2026-03.json"))
"""

import json
import os
from dataclasses import fields
from datetime import date, datetime
from pathlib import Path
from typing import Any

from reports.membership_performance_tracker.logic.model import ScoreboardData


CACHE_SCHEMA_VERSION = 1


def save_scoreboard(data: ScoreboardData, path: Path, saved_at: str = None,
                    source: str = None) -> Path:
    """
    Serialize a ScoreboardData to JSON on disk.

    The output includes a tiny metadata header (`_meta`) describing when the
    snapshot was taken and which schema version it was written with. This makes
    future schema migrations possible without breaking older cache files.

    Args:
        data: Populated ScoreboardData (typically from ScoreboardEngine.run()).
        path: Destination .json file path. Parent dirs created if needed.
        source: What this snapshot HOLDS — e.g. 'slx-preoverlay' (a live
            pull's own numbers, saved before the Crystal overlay) or
            'sp-published' (the post-overlay snapshot materialized from
            SharePoint). Required honesty (2026-07-30): the same filename was
            written by both writers with nothing marking which, and comparing
            the two produced a false drops-regression alarm. Omitted →
            'unknown', never a silent guess.

    Returns:
        path (for chaining / logging).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # pulled_at = when SLX was actually pulled — ONLY a live save may set
    # it; every other save carries it forward untouched (Jiho 8/6: a
    # cosmetic rebuild re-stamped the timestamp and the console claimed a
    # fresh pull that never happened). saved_at = last file write, honest
    # about being just that.
    prior_pulled = None
    if path.exists():
        try:
            import json as _json
            _m = _json.loads(path.read_text()).get("_meta") or {}
            prior_pulled = _m.get("pulled_at") or _m.get("saved_at")
        except Exception:
            pass
    now = datetime.now().isoformat(timespec="seconds")
    is_live = bool(source and str(source).startswith("slx"))
    payload: dict = {
        "_meta": {
            "schema_version":  CACHE_SCHEMA_VERSION,
            "saved_at":        saved_at or now,
            "pulled_at":       (now if is_live else (prior_pulled or saved_at or now)),
            "dataclass":       "ScoreboardData",
            "source":          source or "unknown",
        },
        "fields": {},
    }

    for f in fields(data):
        payload["fields"][f.name] = getattr(data, f.name)

    # Atomic write (P1-7, 7/16): the cache is the contract for ~10 reports —
    # a crash mid-write must never leave a half-written scoreboard. Temp
    # sibling in the SAME directory (os.replace is only atomic same-filesystem).
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=_json_default))
    os.replace(tmp, path)
    return path


def scoreboard_from_dict(field_dict: dict) -> ScoreboardData:
    """
    Rebuild a ScoreboardData from a plain dict keyed by field name.

    Useful when the source is not a save_scoreboard() output but some other
    serialization that already contains the field map — e.g. the `data` key of
    an archive_snapshot envelope (SP-cached snapshots). Fields missing from the
    dict stay at their dataclass defaults.

    This is the shared deserializer behind both load_scoreboard (legacy local
    cache format) and DataHub.load_data's SP-snapshot path (2026-06-05 PM).
    """
    data = ScoreboardData()
    for f in fields(data):
        if f.name in field_dict:
            setattr(data, f.name, field_dict[f.name])
    return data


def load_scoreboard(path: Path) -> ScoreboardData:
    """
    Deserialize a JSON cache file back into a ScoreboardData instance.

    Fields present in the cache get applied to a fresh ScoreboardData. Fields
    on ScoreboardData that don't exist in the cache (e.g. new fields added
    after the cache was written) stay at their dataclass defaults.

    Args:
        path: Cache file written by save_scoreboard().

    Returns:
        ScoreboardData populated from the cache.

    Raises:
        FileNotFoundError: If `path` doesn't exist.
        ValueError:        If the cache is corrupt or has an incompatible schema.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Cache not found: {path}")

    payload = json.loads(path.read_text())
    meta = payload.get("_meta") or {}
    version = meta.get("schema_version")
    if version != CACHE_SCHEMA_VERSION:
        # The cache is the contract for ~10 reports (2026-07-17 gold-plate): only
        # an OLDER, integer version is forward-compatible — scoreboard_from_dict
        # defaults the fields it doesn't find, so an older snapshot rehydrates
        # safely (with a warning). A NEWER version was written by code that knows
        # fields/shapes this code does not, and a missing/non-int version means
        # the file is unversioned or corrupt — in both cases the field shapes are
        # unknowable, so we FAIL LOUD rather than silently load wrong-shaped data.
        if isinstance(version, int) and version < CACHE_SCHEMA_VERSION:
            import warnings
            warnings.warn(
                f"[cache] schema version {version} is older than code "
                f"{CACHE_SCHEMA_VERSION}; loading forward-compatibly (missing "
                f"fields default) — regenerate the cache to silence this."
            )
        else:
            raise ValueError(
                f"[cache] refusing to load {path}: schema version {version!r} is "
                f"incompatible with code version {CACHE_SCHEMA_VERSION} (newer than "
                f"this code, or unversioned/corrupt). Regenerate the cache with a "
                f"live run, or check out the code that wrote this snapshot."
            )

    cached = payload.get("fields") or {}
    return scoreboard_from_dict(cached)


# ---------------------------------------------------------------------------
# Internal — JSON encoders for non-standard types
# ---------------------------------------------------------------------------

def _json_default(obj: Any):
    """
    Encoder for values JSON doesn't handle natively.

    Currently only datetime/date make it into ScoreboardData (via drops_detail
    rows), and even those are pre-formatted as strings by drops.py. Kept here
    as a safety net for future fields.
    """
    if isinstance(obj, (datetime, date)):  # datetime ⊂ date; both isoformat() (#26)
        return obj.isoformat()
    if isinstance(obj, set):
        return list(obj)
    raise TypeError(f"Cannot JSON-encode {type(obj).__name__}: {obj!r}")
