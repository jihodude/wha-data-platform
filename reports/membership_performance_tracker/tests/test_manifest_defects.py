"""A capture we cannot date is a guard we cannot run.

2026-08-12: `data/raw/crystal/2026-08/manifest.json` carries `drops_allied` with
`file_name` ALONE — no run_date, no sha256, no size — while every other entry in
every other month carries all six. `crystal.py:245` is the only writer and it
always writes six, so that entry never came from the fetcher.

Nothing complained. With no run_date the freshness check cannot evaluate that
export at all, so an arbitrarily stale allied capture would publish unnoticed.
No damage this time (both allied files on disk parse to identical data), but the
program accepting an undatable entry in silence is our defect, not Crystal's.

Scope, ruled by Jiho 8/12: only four exports feed a published number —
billables, billables_fte, drops_hospitality, drops_allied. The other six are
SData-computed or comparison-only, so flagging them is noise. And drops are
*expected* to lag: they are the post-ITD capture taken after the month closes
(July's drops ran 08-06 for a July close on 08-05, by design). So staleness is
judged on the billables pair only, while undatability is judged on all four.
"""
import pytest

from reports.membership_performance_tracker.logic.crystal_feed import (
    manifest_defects)


def _entry(run_date="2026-08-10", **over):
    e = {"file_name": "X.xls", "report": "R", "run_by": "JihoBae",
         "run_date": run_date, "sha256": "abc", "size": 10}
    e.update(over)
    return e


def _full(**over):
    m = {k: _entry() for k in
         ("billables", "billables_fte", "drops_hospitality", "drops_allied",
          "new_member_sales", "retention", "drops_by_type",
          "pen_restaurant", "pen_lodging", "pen_rooms")}
    m.update(over)
    return m


def test_a_healthy_manifest_has_no_defects():
    assert manifest_defects(_full()) == []


def test_the_real_drops_allied_shape_is_caught():
    """The exact 2026-08 entry: file_name and nothing else."""
    d = manifest_defects(_full(drops_allied={"file_name": "DroppedAllied.xls"}))
    assert len(d) == 1
    assert d[0]["key"] == "drops_allied"
    assert d[0]["kind"] == "undatable"
    assert "run_date" in d[0]["defect"]


def test_an_undatable_export_we_do_not_consume_is_ignored():
    """pen_rooms feeds nothing published — flagging it is noise (Jiho 8/12)."""
    assert manifest_defects(_full(pen_rooms={"file_name": "P.xls"})) == []


def test_a_missing_entry_for_a_consumed_export_is_a_defect():
    m = _full()
    del m["billables"]
    d = manifest_defects(m)
    assert [x["key"] for x in d] == ["billables"]
    assert d[0]["kind"] == "absent"


def test_billables_lagging_the_newest_capture_is_stale():
    d = manifest_defects(_full(billables=_entry("2026-08-01")))
    assert len(d) == 1
    assert d[0]["kind"] == "stale"
    assert d[0]["days_behind"] == 9


def test_drops_lagging_is_NOT_stale_because_they_are_the_post_ITD_capture():
    """July's real manifest: drops ran 08-06 for a month that closed 08-05.
    That is the two-phase close working, not a defect."""
    m = _full(drops_hospitality=_entry("2026-07-19"),
              drops_allied=_entry("2026-07-19"))
    assert manifest_defects(m) == []


def test_a_small_lag_inside_tolerance_is_not_flagged():
    assert manifest_defects(_full(billables=_entry("2026-08-08"))) == []


def test_defects_are_reported_for_every_offending_export():
    d = manifest_defects(_full(billables=_entry("2026-07-30"),
                               billables_fte={"file_name": "F.xls"}))
    assert {x["key"] for x in d} == {"billables", "billables_fte"}


def test_an_empty_manifest_reports_every_consumed_export_absent():
    assert {x["key"] for x in manifest_defects({})} == {
        "billables", "billables_fte", "drops_hospitality", "drops_allied"}


def test_the_post_ITD_drops_capture_is_not_the_yardstick():
    """July's REAL manifest shape: the nightly set ran 07-26/27 and the drops
    were re-captured 08-06 after the 08-05 close. Measuring billables against
    the drops date reported it "11 days stale" when it was one day behind its
    own cohort. The late-by-design capture must not become the baseline."""
    m = _full(pen_rooms=_entry("2026-07-19"),
              billables=_entry("2026-07-26"),
              new_member_sales=_entry("2026-07-26"),
              pen_lodging=_entry("2026-07-26"),
              pen_restaurant=_entry("2026-07-26"),
              retention=_entry("2026-07-26"),
              billables_fte=_entry("2026-07-27"),
              drops_hospitality=_entry("2026-08-06"),
              drops_allied=_entry("2026-08-06"),
              drops_by_type=_entry("2026-08-06"))
    assert manifest_defects(m) == []
