"""The auto-seal has never actually fired in production — prove it will.

July was sealed by HAND through the console close panel on 2026-08-05, and the
file it read happened to be post-overlay ('frozen-stamped') because the last
completed run left it that way. So the SEAL-1 bug never bit July (verified
2026-08-12: seal and published face agree on every drops and retention cell).

That also means the auto-seal path inside runner.py has never run for real.
Its first live exercise is the AUGUST close, around 2026-09-05 — after the
handoff, with nobody watching. Jiho 8/12: don't put it in the SOP, test it.

Same technique as the fiscal-year rollover work: drive future periods
mechanically instead of waiting for the calendar. The gate under test is the
runner's, verbatim (runner.py:1063):

    if is_closed(PERIOD) and not (load_close(PERIOD) or {}).get("sealed"):
        seal(PERIOD, hub=..., data=data)      # post-overlay data, never the file
"""
import json
from types import SimpleNamespace

import pytest

import reports.membership_performance_tracker.logic.month_close as mc


# Aug -> Jan, so the run crosses the FY2025-26 -> FY2026-27 boundary.
FUTURE = [("2026-08", "Aug"), ("2026-09", "Sep"), ("2026-10", "Oct"),
          ("2026-11", "Nov"), ("2026-12", "Dec"), ("2027-01", "Jan")]


def _close_doc(closes, period, month, sealed=False):
    doc = {"period": period, "month": month, "frozen": {}}
    if sealed:
        doc["sealed"] = {"drops_target": {"TKP": {month: 1}}}
    (closes / f"close_{period}.json").write_text(json.dumps(doc))


def _post_overlay(month, drops, bills):
    """What the build ACTUALLY holds in memory after the Crystal overlay.

    A real ScoreboardData, not a stand-in. seal() branches on the type:

        try:    names = [f.name for f in dataclasses.fields(data)]
        except TypeError:  names = [k for k in vars(data)]   # "plain object (tests)"

    A SimpleNamespace takes the SECOND branch — the one the comment marks as
    test-only — so a test built on one never executes the line August will.
    Caught 2026-08-12 when Jiho asked whether this test reflects real close
    conditions. It did not; it does now.
    """
    from reports.membership_performance_tracker.logic.model import ScoreboardData
    d = ScoreboardData()
    d.drops_target = {"TKP": {month: drops}}
    d.hosp_bills = {"TKP": {month: bills}}
    return d


def _gate_fires(period, closes):
    """The runner's auto-seal condition, copied exactly."""
    return (mc.is_closed(period, closes_dir=closes)
            and not (mc.load_close(period, closes_dir=closes) or {}).get("sealed"))


@pytest.mark.parametrize("period,month", FUTURE)
def test_future_month_autoseals_from_post_overlay_data(tmp_path, period, month):
    """Every future close must seal the OVERLAID numbers, not the cache file.

    The cache on disk is deliberately left in the pre-overlay state the runner
    writes at runner.py:1048 — if the seal ever reads it again, the sealed
    drops are SData's and the month is locked to a number nobody published.
    """
    closes = tmp_path / "closes"
    closes.mkdir()
    _close_doc(closes, period, month)

    cache = tmp_path / f"scoreboard_{period}.json"
    cache.write_text(json.dumps({"_meta": {"source": "slx-preoverlay"},
                                 "fields": {"drops_target": {"TKP": {month: 99}}}}))

    assert _gate_fires(period, closes), f"{period}: auto-seal gate never opened"

    doc = mc.seal(period, cache_path=cache, closes_dir=closes,
                  data=_post_overlay(month, drops=4, bills=10))

    assert doc["sealed"]["drops_target"]["TKP"][month] == 4, (
        f"{period}: sealed the PRE-overlay 99 instead of the published 4")
    assert doc["sealed_from"] == "post-overlay build data"


@pytest.mark.parametrize("period,month", FUTURE)
def test_autoseal_is_once_only(tmp_path, period, month):
    """A month seals exactly once. A later rerun must not re-photograph it —
    that is what makes 'closed months never move' true."""
    closes = tmp_path / "closes"
    closes.mkdir()
    _close_doc(closes, period, month, sealed=True)
    assert not _gate_fires(period, closes), (
        f"{period}: gate re-opened on an already-sealed month")


@pytest.mark.parametrize("period,month", FUTURE)
def test_a_month_with_no_close_doc_never_seals(tmp_path, period, month):
    """Sealing is a consequence of closing. A month nobody closed must never
    be frozen by a nightly that happens to run."""
    closes = tmp_path / "closes"
    closes.mkdir()
    assert not _gate_fires(period, closes)


def test_the_preoverlay_file_is_still_refused_without_data(tmp_path):
    """The belt to the braces: if a caller ever drops the `data` argument, the
    seal must fail loudly rather than silently freeze SData's numbers."""
    closes = tmp_path / "closes"
    closes.mkdir()
    _close_doc(closes, "2026-08", "Aug")
    cache = tmp_path / "scoreboard_2026-08.json"
    cache.write_text(json.dumps({"_meta": {"source": "slx-preoverlay"},
                                 "fields": {"drops_target": {"TKP": {"Aug": 99}}}}))
    with pytest.raises(ValueError, match="PRE-overlay"):
        mc.seal("2026-08", cache_path=cache, closes_dir=closes)


def test_runner_passes_post_overlay_data_to_seal():
    """Source-level gate. The wiring is the whole fix — a behavioural test of
    month_close.py cannot see the runner reverting to `cache_path=`."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "runner.py").read_text()
    assert "_mclose.seal(PERIOD, hub=_hub, data=data)" in src, (
        "the runner must seal from post-overlay build data (SEAL-1)")


# --- fidelity to the real August close --------------------------------------
# Everything below exists because "the test passes" and "the test resembles
# September 5th" are different claims (Jiho 8/12).

def test_seal_captures_the_whole_dataclass_not_a_stub(tmp_path):
    """August seals a real ScoreboardData: 83 fields, of which 76 are dicts.

    seal() keeps `isinstance(v, dict)` only, so the 7 non-dict fields —
    drops_detail, closed_detail, statewide_avg_pen and the four change
    detectors — are dropped by design. July's live seal carried 75 keys, so
    this is the shape to expect, not a stub with two.
    """
    from dataclasses import fields as dc_fields
    from reports.membership_performance_tracker.logic.model import ScoreboardData

    closes = tmp_path / "closes"
    closes.mkdir()
    _close_doc(closes, "2026-08", "Aug")
    doc = mc.seal("2026-08", closes_dir=closes, data=_post_overlay("Aug", 4, 10))

    blank = ScoreboardData()
    expect = {f.name for f in dc_fields(blank)
              if isinstance(getattr(blank, f.name), dict)}
    assert set(doc["sealed"]) == expect
    assert len(doc["sealed"]) == 77
    for dropped in ("drops_detail", "statewide_avg_pen", "bill_month_changes"):
        assert dropped not in doc["sealed"]


def test_seal_preserves_the_pre_ITD_retention_freeze(tmp_path):
    """The real close doc is not empty when seal() runs.

    The two-phase close freezes 12 retention fields BEFORE ITD, then seals
    after. August's doc will carry that freeze, and seal() must leave it
    alone — apply_frozen lets the retention freeze win on top of the seal, so
    losing it would silently re-open retention on a closed month.
    """
    closes = tmp_path / "closes"
    closes.mkdir()
    frozen = {"ret_paid": {"TKP": 33}, "retention_pct": {"TKP": 0.942857}}
    (closes / "close_2026-08.json").write_text(json.dumps(
        {"period": "2026-08", "month": "Aug", "frozen": frozen,
         "amendments": [{"at": "2026-09-01T00:00:00", "what": "prior fix"}]}))

    doc = mc.seal("2026-08", closes_dir=closes, data=_post_overlay("Aug", 4, 10))

    assert doc["frozen"] == frozen, "the pre-ITD retention freeze was lost"
    assert len(doc["amendments"]) == 1, "amendment history was lost"


def test_a_second_seal_returns_the_original_capture(tmp_path):
    """Sealing is once. The gate is one guard; seal() itself is the other,
    because the console close panel can call it independently of the runner."""
    closes = tmp_path / "closes"
    closes.mkdir()
    _close_doc(closes, "2026-08", "Aug")
    first = mc.seal("2026-08", closes_dir=closes, data=_post_overlay("Aug", 4, 10))
    at = first["sealed_at"]
    again = mc.seal("2026-08", closes_dir=closes, data=_post_overlay("Aug", 999, 999))
    assert again["sealed"]["drops_target"]["TKP"]["Aug"] == 4
    assert again["sealed_at"] == at, "a re-seal re-photographed the month"


def test_a_failing_sharepoint_push_still_seals_locally(tmp_path):
    """August seals with hub= wired to SharePoint. The local close doc is
    authoritative and a SP outage must not cost us the seal."""
    closes = tmp_path / "closes"
    closes.mkdir()
    _close_doc(closes, "2026-08", "Aug")

    class _Boom:
        def write_hub_file(self, *a, **k):
            raise RuntimeError("SharePoint down")

    doc = mc.seal("2026-08", closes_dir=closes, hub=_Boom(),
                  data=_post_overlay("Aug", 4, 10))
    assert doc["sealed"]["drops_target"]["TKP"]["Aug"] == 4
    on_disk = json.loads((closes / "close_2026-08.json").read_text())
    assert on_disk["sealed"]["drops_target"]["TKP"]["Aug"] == 4
