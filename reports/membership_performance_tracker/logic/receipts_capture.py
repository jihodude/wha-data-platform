"""receipts_capture.py — record the per-member raw material behind each metric.

The transparency layer's substrate (ruled 2026-07-31, Jiho). The engine
computes every member-level fact and historically threw it away, keeping only
sums. This module RECORDS — it never computes, never alters, never filters.
The renderer (a separate post-landing step) re-derives display rows from this
raw capture using the same pure functions the pipeline used, so the receipts
can never drift from the published numbers without the conservation gate
(Σ member amounts == published cell) catching it.

Shape on disk — data/receipts/receipts_raw_<period>.json:
    {"period": ..., "captured_at": ..., "families": {
        "retention": {"<user_id>|<bill_month>": {"by_account": ..., "removed_by": ...,
                       "as_of": ..., "payments": {...}}},
        "revenue":   {...}, "billables": {...}}}

Capture is additive and fail-quiet at write sites (a capture hiccup must
never take down an 80-minute pull) but fail-LOUD at save if nothing was
captured — silence indistinguishable from success is how families go missing.
"""
import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict

RECEIPTS_DIR = Path(__file__).resolve().parents[3] / "data" / "receipts"

_RAW: Dict[str, Dict] = {"families": {}}


def reset() -> None:
    _RAW["families"] = {}


def record(family: str, key: str, payload) -> None:
    """Stash one raw payload under families[family][key]. Never raises."""
    try:
        _RAW["families"].setdefault(family, {})[str(key)] = payload
    except Exception:
        pass


def captured_families() -> Dict[str, int]:
    return {k: len(v) for k, v in _RAW["families"].items()}


def _json_default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return str(o)


def save(period: str) -> Path:
    """Write the raw capture for the period. Loud when empty."""
    if not _RAW["families"]:
        raise RuntimeError(
            "[receipts] nothing was captured this run — the capture hooks did "
            "not fire. Refusing to write an empty receipts file that would "
            "read as 'no members behind any number'.")
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RECEIPTS_DIR / f"receipts_raw_{period}.json"
    payload = {
        "period": period,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "families": _RAW["families"],
    }
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, default=_json_default))
    tmp.replace(out)
    return out


def load_raw(period: str) -> dict:
    return json.loads((RECEIPTS_DIR / f"receipts_raw_{period}.json").read_text())
