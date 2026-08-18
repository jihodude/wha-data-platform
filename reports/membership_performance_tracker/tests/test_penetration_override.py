"""
test_penetration_override.py — extension-point contract for replacing
SLX-computed restaurant penetration with externally-sourced research data.

This pins the contract devs writing a new override adapter (e.g. a Hannah-CSV
adapter, a market-census adapter) must satisfy, and the engine-side merge
rules that turn (slx_segments, override) into (final_segments, source_map).
"""

from reports.membership_performance_tracker.logic.penetration_override import (
    PenetrationOverride,
    apply_override,
)


# ---------- shared fixture ----------

SLX = {
    "Pierce":    {"restaurant": {"active": 273, "market": 340},
                  "lodging":    {"active":  8,  "market":  21}},
    "Snohomish": {"restaurant": {"active": 163, "market": 409},
                  "lodging":    {"active": 36,  "market":  76}},
}


class _FakeOverride:
    """Minimal adapter satisfying the PenetrationOverride protocol."""
    def __init__(self, name, table):
        self._name, self._table = name, table

    def name(self) -> str:
        return self._name

    def overrides_for(self, territory):
        return self._table.get(territory)


# ---------- contract tests ----------

def test_none_override_returns_slx_unchanged():
    merged, src = apply_override(SLX, override=None)
    assert merged == SLX
    assert src == {
        "Pierce":    {"restaurant": "slx", "lodging": "slx"},
        "Snohomish": {"restaurant": "slx", "lodging": "slx"},
    }


def test_override_substitutes_named_segments_only():
    # Override only the Pierce restaurant cell; everything else stays SLX.
    ov = _FakeOverride("hannah_csv", {
        "Pierce": {"restaurant": {"active": 358, "market": 454}},
    })
    merged, src = apply_override(SLX, override=ov)

    assert merged["Pierce"]["restaurant"] == {"active": 358, "market": 454}
    assert merged["Pierce"]["lodging"]    == SLX["Pierce"]["lodging"]
    assert merged["Snohomish"]             == SLX["Snohomish"]

    assert src["Pierce"]["restaurant"] == "override:hannah_csv"
    assert src["Pierce"]["lodging"]    == "slx"
    assert src["Snohomish"]            == {"restaurant": "slx", "lodging": "slx"}


def test_override_can_replace_both_segments():
    ov = _FakeOverride("census", {
        "Snohomish": {
            "restaurant": {"active": 200, "market": 500},
            "lodging":    {"active":  40, "market":  90},
        },
    })
    merged, src = apply_override(SLX, override=ov)

    assert merged["Snohomish"]["restaurant"] == {"active": 200, "market": 500}
    assert merged["Snohomish"]["lodging"]    == {"active":  40, "market":  90}
    assert src["Snohomish"] == {
        "restaurant": "override:census",
        "lodging":    "override:census",
    }


def test_override_missing_territory_falls_through_to_slx():
    # Override only covers Pierce; Snohomish must come from SLX.
    ov = _FakeOverride("partial", {
        "Pierce": {"restaurant": {"active": 999, "market": 1000}},
    })
    merged, src = apply_override(SLX, override=ov)

    assert merged["Snohomish"] == SLX["Snohomish"]
    assert src["Snohomish"]    == {"restaurant": "slx", "lodging": "slx"}


def test_override_returning_none_for_a_segment_falls_through():
    # An adapter that returns the territory key but None for a segment must
    # not erase SLX for that segment.
    ov = _FakeOverride("sparse", {
        "Pierce": {"restaurant": None, "lodging": {"active": 99, "market": 100}},
    })
    merged, src = apply_override(SLX, override=ov)

    assert merged["Pierce"]["restaurant"] == SLX["Pierce"]["restaurant"]
    assert merged["Pierce"]["lodging"]    == {"active": 99, "market": 100}
    assert src["Pierce"] == {"restaurant": "slx", "lodging": "override:sparse"}


def test_protocol_is_satisfied_by_duck_typing():
    # PenetrationOverride is a structural Protocol — any class with name() and
    # overrides_for() satisfies it without inheriting.
    ov = _FakeOverride("duck", {})
    # isinstance() check requires runtime_checkable (which we set in the
    # Protocol); proves we'll catch missing methods at adapter-load time.
    assert isinstance(ov, PenetrationOverride)
