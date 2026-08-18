"""The publish step must be identical on both paths.

2026-07-28: `_apply_crystal_overlay` had exactly ONE call site, inside the
`--from-cache` branch. A LIVE pull therefore published SData's billables
(2,137) and SData's drops instead of Crystal's — the two families Crystal owns
were only correct on a cache replay. Since the nightly schedule and every
console "Full Refresh" take the live path, the shipping number was the wrong
one; the cache replay that everyone eyeballed was right, which is exactly why
it survived.

The fix is structural, not another call: ONE finalize step both paths run.
"""
from reports.membership_performance_tracker import runner


class _Data:
    def __init__(self):
        self.hosp_bills_target = {"TKP": {"Jul": 1}}
        self.drops_target = {"TKP": {"Jul": 1}}


class _Engine:
    """Records the order of operations — overlay MUST precede the derived
    layers, or L1/L2/L3 compute on numbers that are about to be replaced."""
    def __init__(self):
        self.data = _Data()
        self.calls = []

    def _compute_layer1(self): self.calls.append("L1")
    def _compute_layer2(self): self.calls.append("L2")
    def _compute_layer3(self): self.calls.append("L3")


def test_finalize_overlays_then_recomputes_the_derived_layers(monkeypatch):
    seen = {}

    def fake_overlay(engine, period):
        engine.calls.append("overlay")
        seen["period"] = period
        engine.data.hosp_bills_target = {"TKP": {"Jul": 9}}

    monkeypatch.setattr(runner, "_apply_crystal_overlay", fake_overlay)
    engine = _Engine()

    out = runner._finalize_for_publish(engine, "2026-07")

    assert engine.calls == ["overlay", "L1", "L2", "L3"]
    assert seen["period"] == "2026-07"
    assert out.hosp_bills_target["TKP"]["Jul"] == 9
    assert out is engine.data, "callers keep using the returned data object"


def test_both_paths_use_the_one_finalize_step():
    """Guard against the regression re-appearing as a second, divergent call
    site: the overlay is invoked ONCE in the module, from _finalize_for_publish.
    """
    import inspect
    src = inspect.getsource(runner)
    calls = [ln.strip() for ln in src.splitlines()
             if "_apply_crystal_overlay(" in ln and not ln.strip().startswith("def ")]
    finalize_calls = [ln.strip() for ln in src.splitlines()
                      if "_finalize_for_publish(engine" in ln and not ln.strip().startswith("def ")]

    assert len(calls) == 1, f"overlay must have ONE call site (finalize); found {calls}"
    assert len(finalize_calls) == 2, (
        f"both the cache and live paths must finalize; found {finalize_calls}")
