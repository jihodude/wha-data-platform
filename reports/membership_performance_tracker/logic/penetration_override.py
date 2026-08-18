"""
penetration_override.py — Extension point for plugging external research data
(Hannah's published report, market census, third-party feeds) into the
restaurant-penetration metric WITHOUT editing the engine.

The DEFAULT source of penetration counts is SLX, computed by
`billables.compute_penetration_by_segment`. If a caller passes a
`PenetrationOverride` adapter to the engine, the engine applies it AFTER the
SLX pass and substitutes per-(territory, segment) values.

This is the documented replacement for the legacy in-engine CSV / admin-xlsx
ingestion paths that were removed in the cleanup commit. To re-enable the
old "Hannah CSV" workflow without resurrecting the dead code, ship an adapter
implementing this Protocol and pass it through `ScoreboardEngine.run(...,
penetration_override=...)`.

See `docs/EXTENSION_POINTS.md` for a worked Hannah-CSV adapter example.

Contract:
    name() -> str
        A short, stable identifier (e.g. "hannah_csv"). Recorded in
        `source_map` so downstream audits know which override applied.

    overrides_for(territory: str) -> dict | None
        Return either None (defer to SLX for this territory entirely), or
        a dict shaped like compute_penetration_by_segment's per-territory
        output:
            {
              "restaurant": {"active": N, "market": M},
              "lodging":    {"active": N, "market": M},
            }
        A partial dict is fine — return only the segment you have data for;
        unspecified segments fall through to SLX. Returning {"restaurant": None,
        ...} also falls through (treated as "no override for this segment").

Merge rules (see apply_override + tests):
    1. None override → every cell sourced "slx", values unchanged.
    2. Override returns None for a territory → fall through to SLX.
    3. Override returns a segment dict → substitute that segment, mark source
       "override:<name>". Other segments stay SLX.
    4. Override returns None FOR a segment within a territory dict → that
       segment falls through to SLX (no half-substitutions).
"""

from typing import Protocol, Optional, Dict, Tuple, runtime_checkable


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

Segment       = str                       # "restaurant" or "lodging"
Counts        = Dict[str, int]            # {"active": N, "market": M}
SegmentCounts = Dict[Segment, Counts]     # {"restaurant": {...}, "lodging": {...}}


@runtime_checkable
class PenetrationOverride(Protocol):
    """Adapter contract — see module docstring for full rules."""

    def name(self) -> str: ...

    def overrides_for(self, territory: str) -> Optional[SegmentCounts]: ...


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def apply_override(
    slx_segments: Dict[str, SegmentCounts],
    override: Optional[PenetrationOverride] = None,
) -> Tuple[Dict[str, SegmentCounts], Dict[str, Dict[Segment, str]]]:
    """
    Combine SLX-computed per-territory segment counts with an optional override.

    Args:
        slx_segments: Output of compute_penetration_by_segment — per-territory
                      {"restaurant": {"active", "market"}, "lodging": {...}}.
        override:     Optional PenetrationOverride adapter. Pass None to skip.

    Returns:
        (merged, sources):
            merged   — same shape as slx_segments, with override values
                       substituted in per-(territory, segment) where the
                       override provided them.
            sources  — per-(territory, segment) string: "slx" if the value
                       came from SLX, "override:<name>" if from the override.
                       Stable for audit / display in the tracker.
    """
    merged: Dict[str, SegmentCounts] = {}
    sources: Dict[str, Dict[Segment, str]] = {}

    for territory, slx_seg in slx_segments.items():
        ov_seg = override.overrides_for(territory) if override is not None else None
        territory_merged: SegmentCounts = dict(slx_seg)
        territory_src: Dict[Segment, str] = {seg: "slx" for seg in slx_seg}

        if ov_seg:
            ov_name = override.name()
            for seg in slx_seg:
                seg_ov = ov_seg.get(seg)
                if seg_ov:                                    # None / missing → fall through
                    territory_merged[seg] = seg_ov
                    territory_src[seg]    = f"override:{ov_name}"

        merged[territory]  = territory_merged
        sources[territory] = territory_src

    return merged, sources
