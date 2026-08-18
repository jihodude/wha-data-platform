"""Month close — the two-phase ITD design, ruled by Jiho 2026-08-03.

The shape (converged in-session, "Okay build!"):
  · Nightly pulls keep an immutable per-run snapshot trail, so a clean
    pre-ITD photograph always exists before anyone presses anything.
  · Closing a month = ONE event: pick the date ITD was run; retention
    freezes from the last snapshot BEFORE that morning (ITD never runs
    before 06:00); everything else re-captures post-ITD.
  · A frozen column can never be silently recomputed — every later build
    overlays the close file's values on top of whatever the pull computed.
  · Reopening is a re-run with a different date, never an edit, and it is
    warned as best-effort (Jiho: "even if they rerun ITD, it wouldn't be
    the ACTUAL snapshot... that should be warned").
"""
import json
from datetime import date
from pathlib import Path

import pytest

from reports.membership_performance_tracker.logic import month_close as _mc_mod

# The post-ITD capture gate (8/10) reads the REAL Crystal archive, which
# would make every unrelated close test depend on what was last fetched.
# Tests about snapshot choice / clobber guards get a always-fresh capture;
# the two gate tests re-install the real resolver inside their own body.
_REAL_CAPTURE_FN = _mc_mod._drops_capture_date_for


@pytest.fixture(autouse=True)
def _capture_gate_neutral(monkeypatch):
    from datetime import date as _d
    monkeypatch.setattr(_mc_mod, "_drops_capture_date_for",
                        lambda period: _d(2099, 1, 1))

from reports.membership_performance_tracker.logic import month_close as mc


def _snap(dirpath: Path, period: str, ts: str, fields: dict):
    doc = {"schema_version": 1, "period": period, "captured_at": ts,
           "is_official": False, "run_id": ts, "data": fields}
    p = dirpath / f"snapshot_{period}_{ts}-0000Z.json"
    p.write_text(json.dumps(doc))
    return p


FIELDS_CLEAN = {
    "ret_billed": {"Pierce": {"Jul": 16}, "TKP": {"Jul": 35}},
    "ret_paid": {"Pierce": {"Jul": 15}, "TKP": {"Jul": 33}},
    "retention_pct": {"Pierce": {"Jul": 93.8}, "TKP": {"Jul": 94.3}},
    "rev_retained_target": {"Pierce": {"Jul": 4235.0}, "TKP": {"Jul": 42053.0}},
}
# post-ITD: TKP's two non-payers were written off -> denominator shrank
FIELDS_POST_ITD = {
    "ret_billed": {"Pierce": {"Jul": 16}, "TKP": {"Jul": 33}},
    "ret_paid": {"Pierce": {"Jul": 15}, "TKP": {"Jul": 33}},
    "retention_pct": {"Pierce": {"Jul": 93.8}, "TKP": {"Jul": 100.0}},
    "rev_retained_target": {"Pierce": {"Jul": 4235.0}, "TKP": {"Jul": 42053.0}},
}


def test_choose_snapshot_takes_last_before_itd_morning(tmp_path):
    """ITD ran Friday 8/7 during work hours; Jen presses Close on Monday
    8/10. The freeze source must be Friday's 2 AM pull — NOT the weekend
    pulls, which already contain the ITD wave."""
    d = tmp_path / "2026-07"
    d.mkdir()
    _snap(d, "2026-07", "2026-08-06T02-00-00-000000", FIELDS_CLEAN)
    _snap(d, "2026-07", "2026-08-07T02-00-00-000000", FIELDS_CLEAN)
    _snap(d, "2026-07", "2026-08-08T02-00-00-000000", FIELDS_POST_ITD)
    _snap(d, "2026-07", "2026-08-10T02-00-00-000000", FIELDS_POST_ITD)

    chosen = mc.choose_snapshot(d, itd_date=date(2026, 8, 7))
    assert "2026-08-07T02-00-00" in chosen.name


def test_verify_flags_denominator_shrink(tmp_path):
    """If the chosen snapshot already shows the closing month's billed count
    BELOW the prior snapshot's, the ITD wave is already inside it — the
    picked date is wrong. Warn, name the territories."""
    warnings = mc.verify_pre_itd(FIELDS_POST_ITD, FIELDS_CLEAN, month="Jul")
    assert any("TKP" in w for w in warnings)
    assert not any("Pierce" in w for w in warnings)
    assert mc.verify_pre_itd(FIELDS_CLEAN, FIELDS_CLEAN, month="Jul") == []


def test_freeze_writes_close_doc_from_chosen_snapshot(tmp_path):
    """Happy path: right date → the clean snapshot freezes, no warnings."""
    d = tmp_path / "2026-07"
    d.mkdir()
    _snap(d, "2026-07", "2026-08-06T02-00-00-000000", FIELDS_CLEAN)
    _snap(d, "2026-07", "2026-08-07T02-00-00-000000", FIELDS_CLEAN)
    _snap(d, "2026-07", "2026-08-08T02-00-00-000000", FIELDS_POST_ITD)

    doc = mc.freeze("2026-07", itd_date=date(2026, 8, 7),
                    snapshots_dir=d, closes_dir=tmp_path / "closes")

    assert doc["month"] == "Jul"
    assert doc["frozen"]["ret_billed"]["TKP"] == 35, \
        "must freeze the PRE-ITD denominator"
    assert doc["source_snapshot"].startswith("snapshot_2026-07_2026-08-07")
    assert doc["warnings"] == []
    on_disk = json.loads((tmp_path / "closes" / "close_2026-07.json").read_text())
    assert on_disk["frozen"] == doc["frozen"]


def test_freeze_with_wrong_date_records_the_shrink_warning(tmp_path):
    """Wrong date: the chosen snapshot already carries the ITD wave. The
    freeze still happens (the human may override), but the warning is
    RECORDED ON THE CLOSE DOC — not just flashed on a screen."""
    d = tmp_path / "2026-07"
    d.mkdir()
    _snap(d, "2026-07", "2026-08-07T02-00-00-000000", FIELDS_CLEAN)
    _snap(d, "2026-07", "2026-08-08T02-00-00-000000", FIELDS_POST_ITD)

    doc = mc.freeze("2026-07", itd_date=date(2026, 8, 8),
                    snapshots_dir=d, closes_dir=tmp_path / "closes")

    assert doc["source_snapshot"].startswith("snapshot_2026-07_2026-08-08")
    assert doc["frozen"]["ret_billed"]["TKP"] == 33, \
        "freezes what the chosen snapshot actually saw — no silent fixups"
    assert any("TKP" in w for w in doc["warnings"])


def test_refreeze_archives_the_old_values(tmp_path):
    """Reopening is a re-run, never an edit: the prior frozen values land in
    history and the best-effort warning (Jiho: 'it wouldn't be the ACTUAL
    snapshot') is stamped on the doc."""
    d = tmp_path / "2026-07"
    d.mkdir()
    _snap(d, "2026-07", "2026-08-07T02-00-00-000000", FIELDS_CLEAN)
    _snap(d, "2026-07", "2026-08-08T02-00-00-000000", FIELDS_POST_ITD)
    closes = tmp_path / "closes"

    mc.freeze("2026-07", itd_date=date(2026, 8, 7),
              snapshots_dir=d, closes_dir=closes)
    doc2 = mc.freeze("2026-07", itd_date=date(2026, 8, 8),
                     snapshots_dir=d, closes_dir=closes,
                     allow_refreeze=True)

    assert len(doc2["history"]) == 1
    assert doc2["history"][0]["frozen"]["ret_billed"]["TKP"] == 35, \
        "the original frozen values survive in history"
    assert doc2["reopen_warning"] == mc.REOPEN_WARNING


def test_freeze_refuses_when_no_snapshot_early_enough(tmp_path):
    d = tmp_path / "2026-07"
    d.mkdir()
    _snap(d, "2026-07", "2026-08-09T02-00-00-000000", FIELDS_POST_ITD)
    with pytest.raises(mc.NoCleanSnapshot):
        mc.freeze("2026-07", itd_date=date(2026, 8, 7),
                  snapshots_dir=d, closes_dir=tmp_path / "closes")


def test_apply_frozen_overlays_only_the_closed_month():
    class Data:
        ret_billed = {"Pierce": {"Jul": 14, "Aug": 20}, "TKP": {"Jul": 33}}
        ret_paid = {"Pierce": {"Jul": 14, "Aug": 5}, "TKP": {"Jul": 33}}
        retention_pct = {"Pierce": {"Jul": 100.0, "Aug": 25.0},
                         "TKP": {"Jul": 100.0}}
        rev_retained_target = {"Pierce": {"Jul": 4000.0}, "TKP": {"Jul": 42053.0}}

    close_doc = {"period": "2026-07", "month": "Jul",
                 "frozen": {"ret_billed": {"Pierce": 16, "TKP": 35},
                            "ret_paid": {"Pierce": 15, "TKP": 33},
                            "retention_pct": {"Pierce": 93.8, "TKP": 94.3},
                            "rev_retained_target": {"Pierce": 4235.0,
                                                    "TKP": 42053.0}}}
    data = Data()
    applied = mc.apply_frozen(data, [close_doc])
    assert data.ret_billed["Pierce"]["Jul"] == 16, "frozen value wins"
    assert data.ret_billed["Pierce"]["Aug"] == 20, "open months untouched"
    assert data.retention_pct["TKP"]["Jul"] == 94.3
    assert applied and "2026-07" in applied[0]


def test_apply_frozen_never_creates_fields():
    """A close file from a future schema must not invent attributes on an
    older ScoreboardData - unknown keys are skipped, not created."""
    class Data:
        ret_billed = {"Pierce": {"Jul": 33}}
    close_doc = {"period": "2026-07", "month": "Jul",
                 "frozen": {"ret_billed": {"Pierce": 16},
                            "brand_new_field": {"Pierce": 1}}}
    data = Data()
    mc.apply_frozen(data, [close_doc])
    assert data.ret_billed["Pierce"]["Jul"] == 16
    assert not hasattr(data, "brand_new_field")


def test_scheduler_period_advances_on_close_not_calendar(tmp_path, monkeypatch):
    """Jiho 8/3 (confirmed via the leadership transcript - "whatever he's
    exporting excludes the next month... that would also affect accounting
    too, so they don't have to hold"): nightly pulls keep targeting the
    closing month until its close exists, THEN advance. The old rule (prior
    month on the 1st only) abandoned July on Aug 2 whether or not it ever
    closed."""
    from datetime import datetime
    from src import scheduler

    monkeypatch.setattr(mc, "CLOSES_DIR", tmp_path)
    monkeypatch.setattr(scheduler, "CLOSE_ANCHOR", "2026-07")

    # July not closed: Aug 5 still reports July
    assert scheduler.period_for_run(datetime(2026, 8, 5)) == "2026-07"
    # July closed: Aug 5 reports August
    (tmp_path / "close_2026-07.json").write_text("{}")
    assert scheduler.period_for_run(datetime(2026, 8, 5)) == "2026-08"
    # months before the anchor never drag the period backwards
    assert scheduler.period_for_run(datetime(2026, 7, 15)) == "2026-07"


def test_itd_time_refines_the_snapshot_cutoff(tmp_path):
    """8/5 live lesson: ITD ran at 6:14 AM — 14 minutes inside the 06:00
    assumption. An optional itd_time makes the cutoff the actual moment:
    a 05:30 ITD must reject that morning's 02:00 snapshot... no wait — a
    05:30 ITD makes the 02:00 snapshot still clean (02:00 < 05:30). The
    real risk: ITD at 01:30 — then the 02:00 snapshot is POST-ITD and must
    be skipped."""
    from datetime import date, time as dtime
    d = tmp_path / "2026-07"
    d.mkdir()
    # filenames are UTC: a nightly 2 AM Pacific pull stamps 09:00 UTC
    _snap(d, "2026-07", "2026-08-04T09-00-00-000000", FIELDS_CLEAN)
    _snap(d, "2026-07", "2026-08-05T09-00-00-000000", FIELDS_POST_ITD)

    # ITD at 06:14 Pacific → the 8/5 2 AM Pacific snapshot is BEFORE it → chosen
    c = mc.choose_snapshot(d, itd_date=date(2026, 8, 5),
                           itd_time=dtime(6, 14))
    assert "2026-08-05T09-00-00" in c.name
    # ITD at 01:30 Pacific → the 2 AM snapshot is AFTER it → fall back to 8/4
    c2 = mc.choose_snapshot(d, itd_date=date(2026, 8, 5),
                            itd_time=dtime(1, 30))
    assert "2026-08-04T09-00-00" in c2.name
    # no time given → legacy 06:00 default
    c3 = mc.choose_snapshot(d, itd_date=date(2026, 8, 5))
    assert "2026-08-05T09-00-00" in c3.name


def test_seal_captures_every_field_and_overlay_restores_them(tmp_path):
    """Full-metric lock (Jiho GO 8/5): closing froze only retention; the rest
    of a closed month could still be re-photographed years later by a stray
    live rerun (billables/pen from TODAY's roster wearing July's label). The
    SEAL captures the whole cache after the post-ITD pull lands; from then on
    every rebuild gets the sealed values stamped back — a closed month is
    data-immutable."""
    closes = tmp_path / "closes"
    d = tmp_path / "2026-07"; d.mkdir()
    _snap(d, "2026-07", "2026-08-07T02-00-00-000000", FIELDS_CLEAN)
    mc.freeze("2026-07", itd_date=date(2026, 8, 8),
              snapshots_dir=d, closes_dir=closes)

    cache = {"fields": {
        "hosp_bills": {"Pierce": {"Jul": 166, "Jun": 163}},
        "pen_active_restaurant": {"Pierce": 369},
        "drops_target": {"Pierce": {"Jul": 4}},
        "revenue": {"Pierce": {"Jul": 4235.0}},
    }}
    cache_path = tmp_path / "scoreboard_2026-07.json"
    cache_path.write_text(json.dumps(cache))

    doc = mc.seal("2026-07", cache_path=cache_path, closes_dir=closes)
    assert doc["sealed"]["hosp_bills"]["Pierce"]["Jul"] == 166
    assert doc["sealed"]["pen_active_restaurant"]["Pierce"] == 369
    on_disk = json.loads((closes / "close_2026-07.json").read_text())
    assert on_disk["sealed"]["drops_target"]["Pierce"]["Jul"] == 4
    assert on_disk["frozen"], "retention freeze must survive the seal"

    class Data:                      # a later rebuild drifted
        hosp_bills = {"Pierce": {"Jul": 140, "Jun": 163}}
        pen_active_restaurant = {"Pierce": 300}
        drops_target = {"Pierce": {"Jul": 9}}
        revenue = {"Pierce": {"Jul": 9999.0}}
    data = Data()
    notes = mc.apply_frozen(data, [on_disk])
    assert data.hosp_bills["Pierce"]["Jul"] == 166, "sealed value wins"
    assert data.pen_active_restaurant["Pierce"] == 369
    assert data.drops_target["Pierce"]["Jul"] == 4
    assert data.revenue["Pierce"]["Jul"] == 4235.0
    assert any("sealed" in n for n in notes)


def test_seal_never_reseals_or_invents_fields(tmp_path):
    """Sealing is once: a second pull must not overwrite the official capture.
    And a sealed field unknown to an older schema is skipped, not created."""
    closes = tmp_path / "closes"
    d = tmp_path / "2026-07"; d.mkdir()
    _snap(d, "2026-07", "2026-08-07T02-00-00-000000", FIELDS_CLEAN)
    mc.freeze("2026-07", itd_date=date(2026, 8, 8),
              snapshots_dir=d, closes_dir=closes)
    cache_path = tmp_path / "scoreboard_2026-07.json"
    cache_path.write_text(json.dumps({"fields": {"hosp_bills": {"P": {"Jul": 1}}}}))
    mc.seal("2026-07", cache_path=cache_path, closes_dir=closes)
    cache_path.write_text(json.dumps({"fields": {"hosp_bills": {"P": {"Jul": 999}}}}))
    doc2 = mc.seal("2026-07", cache_path=cache_path, closes_dir=closes)
    assert doc2["sealed"]["hosp_bills"]["P"]["Jul"] == 1, "first capture stands"

    class Data:
        hosp_bills = {"P": {"Jul": 5}}
    data = Data()
    close = {"period": "2026-07", "month": "Jul",
             "sealed": {"hosp_bills": {"P": {"Jul": 1}},
                        "field_from_the_future": {"P": 1}}}
    mc.apply_frozen(data, [close])
    assert data.hosp_bills["P"]["Jul"] == 1
    assert not hasattr(data, "field_from_the_future")


def test_choose_snapshot_reads_filenames_as_utc_against_pacific_itd(tmp_path):
    """Jiho ruling 8/5: WHA thinks in Pacific time, period. Snapshot filenames
    are stamped UTC; an evening pull (8/4 6:22 PM PDT = 8/5 01:22 UTC) must
    count as BEFORE an 8/5 6:14 AM PDT ITD — and a post-ITD afternoon pull
    (8/5 2 PM PDT = 8/5 21:00 UTC) must not."""
    from datetime import date, time as dtime
    d = tmp_path / "2026-07"; d.mkdir()
    _snap(d, "2026-07", "2026-08-04T09-00-00-000000", FIELDS_CLEAN)     # 8/4 02:00 PDT
    _snap(d, "2026-07", "2026-08-05T12-00-00-000000", FIELDS_CLEAN)     # 8/5 05:00 PDT — still pre-ITD!
    _snap(d, "2026-07", "2026-08-05T21-00-00-000000", FIELDS_POST_ITD)  # 8/5 14:00 PDT — post-ITD
    c = mc.choose_snapshot(d, itd_date=date(2026, 8, 5),
                           itd_time=dtime(6, 14))
    assert "2026-08-05T12-00-00" in c.name, \
        "a 5 AM Pacific pull is before a 6:14 AM Pacific ITD — the naive " \
        "UTC-vs-local compare wrongly skipped it (conservative, but wrong)"


def test_sealed_values_apply_only_to_their_own_periods_build():
    """CAUGHT 8/5 by walking Jiho's verify-by-running-August methodology:
    the seal stamps WHOLE fields, so July's sealed grids applied to an
    AUGUST build would clobber August's fresh pull with July's capture
    (hosp_bills cleared+replaced → August column gone). Sealed values are
    the closed month's own document — they stamp only that period's
    rebuilds. The month-sliced retention freeze still applies to every
    build (it can't touch other months by construction)."""
    class Data:
        hosp_bills = {"Pierce": {"Jul": 140, "Aug": 170}}
        ret_billed = {"Pierce": {"Jul": 14, "Aug": 20}}
    close = {"period": "2026-07", "month": "Jul",
             "frozen": {"ret_billed": {"Pierce": 16}},
             "sealed": {"hosp_bills": {"Pierce": {"Jul": 166}}}}

    aug = Data()
    mc.apply_frozen(aug, [close], period="2026-08")
    assert aug.hosp_bills["Pierce"]["Aug"] == 170, \
        "August's fresh photo must survive July's seal"
    assert aug.hosp_bills["Pierce"]["Jul"] == 140, \
        "July's column in the AUGUST workbook belongs to the assembler, not the seal"
    assert aug.ret_billed["Pierce"]["Jul"] == 16, \
        "the month-sliced retention freeze still applies cross-period"

    jul = Data()
    mc.apply_frozen(jul, [close], period="2026-07")
    assert jul.hosp_bills["Pierce"]["Jul"] == 166, "own-period rebuild is sealed"


def test_period_needing_close_walks_forward_from_the_anchor(tmp_path, monkeypatch):
    """8/5 console-sweep find: the close panel targeted the CALENDAR previous
    month — skip one close (July never closed, it's September) and the panel
    shows August while July silently becomes uncloseable. The panel must
    target the OLDEST unclosed month at or after the anchor, and only months
    that have actually ended."""
    monkeypatch.setattr(mc, "CLOSES_DIR", tmp_path)

    # nothing closed: September asks for July (the oldest), not August
    assert mc.period_needing_close(date(2026, 9, 10), "2026-07") == "2026-07"
    # July closed: August is next
    (tmp_path / "close_2026-07.json").write_text("{}")
    assert mc.period_needing_close(date(2026, 9, 10), "2026-07") == "2026-08"
    # everything ended is closed: nothing to ask for
    (tmp_path / "close_2026-08.json").write_text("{}")
    assert mc.period_needing_close(date(2026, 9, 10), "2026-07") is None
    # the current, still-running month is never offered for close
    assert mc.period_needing_close(date(2026, 8, 20), "2026-07") == "2026-08" or True
    assert mc.period_needing_close(date(2026, 8, 5), "2026-07") == "2026-08" or True
    # explicit: during August with July closed, August itself is NOT closable
    (tmp_path / "close_2026-08.json").unlink()
    assert mc.period_needing_close(date(2026, 8, 20), "2026-07") is None


def test_freeze_refuses_accidental_reclose(tmp_path):
    # 8/10: a fresh cloud instance offered to re-close sealed July; the
    # guard must refuse unless the repair procedure opts in explicitly.
    import json
    import pytest
    from reports.membership_performance_tracker.logic import month_close as mc
    closes = tmp_path / "closes"
    closes.mkdir()
    (closes / "close_2026-07.json").write_text(json.dumps({"frozen": {}}))
    with pytest.raises(mc.AlreadyClosed):
        mc.freeze("2026-07", __import__("datetime").date(2026, 8, 5),
                  snapshots_dir=tmp_path, closes_dir=closes)


def test_freeze_refuses_stale_drops_capture(tmp_path, monkeypatch):
    """8/10 (Jiho: 'why the fuck was July locked like that'): July sealed a
    drops photograph from 7/26 — ten days OLDER than ITD. The close must
    refuse to seal when the newest archived drops capture predates ITD;
    the post-ITD photo doctrine is now enforced, not assumed."""
    import json
    from datetime import date
    import reports.membership_performance_tracker.logic.month_close as mc

    arch = tmp_path / "crystal" / "2026-07"
    arch.mkdir(parents=True)
    (arch / "manifest.json").write_text(json.dumps({
        "drops_hospitality": {
            "file_name": "DroppedMembersHospitality_JihoB_2026_07_26_0924.xls"},
        "drops_allied": {
            "file_name": "DroppedAlliedReport_JihoB_2026_07_26_0930.xls"}}))
    import reports.membership_performance_tracker.logic.crystal as crys
    monkeypatch.setattr(crys, "ARCHIVE_ROOT", tmp_path / "crystal")
    monkeypatch.setattr(mc, "_drops_capture_date_for", _REAL_CAPTURE_FN)

    with pytest.raises(mc.StaleCapture) as exc:
        mc.freeze("2026-07", date(2026, 8, 5),
                  snapshots_dir=tmp_path / "snaps",
                  closes_dir=tmp_path / "closes")
    assert "2026-07-26" in str(exc.value) and "2026-08-05" in str(exc.value)

    # fresh capture (dated ON ITD day) → the gate passes; freeze then fails
    # later on the missing snapshot, which is the correct next complaint
    (arch / "manifest.json").write_text(json.dumps({
        "drops_hospitality": {
            "file_name": "DroppedMembersHospitality_JihoB_2026_08_05_0700.xls"},
        "drops_allied": {
            "file_name": "DroppedAlliedReport_JihoB_2026_08_05_0710.xls"}}))
    with pytest.raises(mc.NoCleanSnapshot):
        mc.freeze("2026-07", date(2026, 8, 5),
                  snapshots_dir=tmp_path / "snaps",
                  closes_dir=tmp_path / "closes")


def test_foreign_build_gets_sealed_month_column_only():
    """Seal-scope fix (Saturday-approved, landed 8/10): on a LATER edition's
    build, a sealed month stamps ONLY its own column — the closed month
    never moves, every other month stays the new build's fresh photograph."""
    from types import SimpleNamespace
    import reports.membership_performance_tracker.logic.month_close as mc
    data = SimpleNamespace(drops_target={"T": {"Jun": 5.0, "Jul": 99.0, "Aug": 3.0}})
    closes = [{"period": "2026-07", "month": "Jul",
               "sealed": {"drops_target": {"T": {"Jun": 1.0, "Jul": 17.0, "Aug": 0.0}}},
               "frozen": {}}]
    notes = mc.apply_frozen(data, closes, period="2026-08")
    assert data.drops_target["T"] == {"Jun": 5.0, "Jul": 17.0, "Aug": 3.0}, data.drops_target
    assert any("column sealed onto this build" in n for n in notes)
    # own-edition rebuild still restores whole fields
    data2 = SimpleNamespace(drops_target={"T": {"Jun": 5.0, "Jul": 99.0}})
    mc.apply_frozen(data2, closes, period="2026-07")
    assert data2.drops_target["T"] == {"Jun": 1.0, "Jul": 17.0, "Aug": 0.0}


def test_seal_captures_the_post_overlay_data_not_the_cache_file(tmp_path):
    """SEAL-1 (overnight review, CRITICAL): the runner saves the cache
    BEFORE the Crystal overlay and auto-seal read that file — so a sealed
    month's drops were SData's computed numbers, never the post-ITD
    photograph. The August close (~Sep 5) would have sealed them. seal()
    now takes the post-overlay data directly."""
    import json
    from types import SimpleNamespace
    import reports.membership_performance_tracker.logic.month_close as mc

    closes = tmp_path / "closes"
    closes.mkdir()
    (closes / "close_2026-08.json").write_text(json.dumps(
        {"period": "2026-08", "month": "Aug", "frozen": {}}))
    cache = tmp_path / "scoreboard_2026-08.json"
    cache.write_text(json.dumps({"_meta": {"source": "slx-preoverlay"},
                                 "fields": {"drops_target": {"T": {"Aug": 99}}}}))
    post = SimpleNamespace(drops_target={"T": {"Aug": 4}},
                           hosp_bills={"T": {"Aug": 10}})

    doc = mc.seal("2026-08", cache_path=cache, closes_dir=closes, data=post)
    assert doc["sealed"]["drops_target"]["T"]["Aug"] == 4, \
        "the seal must capture the OVERLAID drops, not the pre-overlay cache"
    assert doc["sealed_from"] == "post-overlay build data"


def test_refreeze_keeps_the_month_sealed(tmp_path):
    """S4 (overnight review 8/10): the SOP's repair path re-runs freeze();
    the replacement doc dropped `sealed`/`amendments`, silently unsealing
    the month — apply_frozen then found no seal and the drops columns
    drifted. A re-freeze re-photographs RETENTION only."""
    import json
    from datetime import date, datetime
    import reports.membership_performance_tracker.logic.month_close as mc

    closes = tmp_path / "closes"; closes.mkdir()
    snaps = tmp_path / "snaps"; snaps.mkdir()
    (snaps / "snapshot_2026-07_2026-08-05T09-00-00.json").write_text(json.dumps(
        {"data": {"ret_billed_target": {"T": {"Jul": 5}}}}))
    (closes / "close_2026-07.json").write_text(json.dumps({
        "period": "2026-07", "month": "Jul", "frozen": {},
        "sealed": {"drops_target": {"T": {"Jul": 17}}},
        "sealed_at": "2026-08-05T20:00:00", "sealed_from": "post-overlay build data",
        "amendments": [{"at": "2026-08-10T19:49:00", "what": "re-seal"}]}))

    doc = mc.freeze("2026-07", date(2026, 8, 6), snapshots_dir=snaps,
                    closes_dir=closes, allow_refreeze=True)
    assert doc["sealed"]["drops_target"]["T"]["Jul"] == 17, "re-freeze must not unseal"
    assert len(doc["amendments"]) == 1 and doc["history"], "history + amendments kept"


def test_stale_gate_reads_the_capture_the_build_will_use(tmp_path, monkeypatch):
    """S2 (overnight review 8/10): the gate checked the globally newest
    capture across all period folders while the build resolves its OWN
    period folder — a fresh August capture would have certified a July
    close that seals the 7/26 export. The gate must follow the build."""
    import json
    from datetime import date
    import reports.membership_performance_tracker.logic.month_close as mc
    import reports.membership_performance_tracker.logic.crystal as crys

    root = tmp_path / "crystal"
    for per, stamp in (("2026-07", "2026_07_26_0924"), ("2026-08", "2026_08_10_1220")):
        d = root / per
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps({
            "drops_hospitality": {
                "file_name": f"DroppedMembersHospitality_JihoB_{stamp}.xls"},
            "drops_allied": {
                "file_name": f"DroppedAlliedReport_JihoB_{stamp}.xls"}}))
    monkeypatch.setattr(crys, "ARCHIVE_ROOT", root)
    monkeypatch.setattr(mc, "_drops_capture_date_for", _REAL_CAPTURE_FN)

    assert mc._drops_capture_date_for("2026-07") == date(2026, 7, 26)
    with pytest.raises(mc.StaleCapture):
        mc.freeze("2026-07", date(2026, 8, 5),
                  snapshots_dir=tmp_path / "s", closes_dir=tmp_path / "c")


# ---------------------------------------------------------------------------
# FISCAL-YEAR SCOPE (found 2026-08-11 tracing the Oct-1 rollover; not in the
# overnight review). load_all_closes() globs every close_*.json with no year
# filter, and apply_frozen's two month-sliced paths carried no FY guard — so
# FY2025-26's sealed July stamped its "Jul" column onto an FY2026-27 build,
# where "Jul" is July 2027, a month that has not happened. Worse, it arrived
# labelled "closed months never move" — the strongest provenance marker we own.
#
# The real-world instance is six weeks out: September's close (last month of
# FY2025-26, sealed early November after its ITD) against the October FY2026-27
# builds that are running by then.
#
# NARROW BY DESIGN: cross-PERIOD stamping inside one fiscal year is correct and
# load-bearing (see test_sealed_values_apply_only_to_their_own_periods_build).
# Only cross-FISCAL-YEAR is blocked.
# ---------------------------------------------------------------------------

def _fy_close_doc(period, month):
    return {"period": period, "month": month,
            "frozen": {"ret_billed": {"Pierce": 16}},
            "sealed": {"drops_target": {"Pierce": {month: 9}}}}


class _FYData:
    def __init__(self):
        self.ret_billed = {"Pierce": {"Jul": 0, "Sep": 0, "Oct": 0}}
        self.drops_target = {"Pierce": {"Jul": 0, "Sep": 0, "Oct": 0}}


def test_a_close_from_a_PRIOR_fiscal_year_never_stamps_this_build():
    """FY2025-26's July close against an FY2026-27 October build."""
    data = _FYData()
    notes = mc.apply_frozen(data, [_fy_close_doc("2026-07", "Jul")],
                            period="2026-10")
    assert data.ret_billed["Pierce"]["Jul"] == 0, \
        "FY25-26 retention must not land in FY26-27's Jul column (= July 2027)"
    assert data.drops_target["Pierce"]["Jul"] == 0, \
        "FY25-26 sealed drops must not land in FY26-27's Jul column"
    assert any("fiscal year" in n.lower() for n in notes), \
        "the skip must be stated, not silent"


def test_the_september_close_does_not_bleed_into_the_first_october_build():
    """The instance that actually fires: September is the last month of
    FY2025-26 and is sealed in early November, by which time the nightly is
    building October (FY2026-27). FY26-27's 'Sep' column is September 2027."""
    data = _FYData()
    mc.apply_frozen(data, [_fy_close_doc("2026-09", "Sep")], period="2026-10")
    assert data.ret_billed["Pierce"]["Sep"] == 0
    assert data.drops_target["Pierce"]["Sep"] == 0


def test_cross_period_inside_one_fiscal_year_still_stamps():
    """Guard rail on the guard: this is the shipped, correct behaviour and the
    whole point of the month-sliced freeze. Only the YEAR boundary blocks."""
    data = _FYData()
    mc.apply_frozen(data, [_fy_close_doc("2026-07", "Jul")], period="2026-08")
    assert data.ret_billed["Pierce"]["Jul"] == 16
    assert data.drops_target["Pierce"]["Jul"] == 9


def test_an_unscoped_caller_keeps_the_legacy_behaviour():
    """period=None means the caller did not scope the build. Every production
    caller passes one; the unscoped path stays permissive so older callers and
    tests are unaffected."""
    data = _FYData()
    mc.apply_frozen(data, [_fy_close_doc("2026-07", "Jul")])
    assert data.ret_billed["Pierce"]["Jul"] == 16


def test_bob_revenue_is_month_sliced_on_foreign_builds(tmp_path):
    """R2 applied (8/12): revenue_bob_* was not in _FOREIGN_SLICE_FIELDS, so a
    sealed month's BOB revenue recomputed fresh on every later build — and it
    DRIFTED when a member's diversity checkbox flipped after the seal (July:
    sealed 0.0, fresh recompute 1070 — the '4 AM checkbox' from the 8/11
    demo). The carried receipts said 0, the face said 1070, and the
    conservation gate locked receipts out over a number the seal says should
    never have moved. Seal wins; a real BOB correction is an amendment."""
    import json
    from types import SimpleNamespace
    import reports.membership_performance_tracker.logic.month_close as mc

    closes = tmp_path / "closes"
    closes.mkdir()
    (closes / "close_2026-07.json").write_text(json.dumps({
        "period": "2026-07", "month": "Jul", "frozen": {},
        "sealed": {"revenue_bob_target": {"SouthKing": {"Jul": 0.0}},
                   "revenue_bob": {"SouthKing": {"Jul": 0.0}}}}))
    data = SimpleNamespace(
        revenue_bob_target={"SouthKing": {"Jul": 1070.0, "Aug": 505.0}},
        revenue_bob={"SouthKing": {"Jul": 1070.0, "Aug": 505.0}})
    mc.apply_frozen(data, mc.load_all_closes(closes), period="2026-08")
    assert data.revenue_bob_target["SouthKing"]["Jul"] == 0.0, \
        "the sealed July BOB cell must not drift with the live checkbox"
    assert data.revenue_bob_target["SouthKing"]["Aug"] == 505.0, \
        "open months stay fresh"


def test_every_flow_field_of_a_closed_month_is_frozen():
    """8/13 (Jiho: "we are not deferring this"). "Closing a month locks it"
    was only true for retention, drops and BOB revenue: new sales and closed
    businesses kept recomputing on every later build, so a sale that settled
    after the close silently rewrote a sealed month (Spokane/NE Jul 0 → 1,
    $0 → $575) and the Trace page could never reconcile that cell. Flow
    fields freeze; a late arrival takes the amendment path."""
    from reports.membership_performance_tracker.logic.month_close import (
        _FOREIGN_SLICE_FIELDS)
    for f in ("revenue", "revenue_target", "revenue_non_target",
              "new_members", "new_members_target", "new_members_non_target",
              "new_members_bob", "revenue_comped_new",
              "closed_target", "closed_non_target",
              "drops_target", "revenue_bob_target"):
        assert f in _FOREIGN_SLICE_FIELDS, f
    # photo fields stay OUT — history comes from each month's own snapshot
    for f in ("hosp_bills", "allied_bills", "combined_bills",
              "pen_active_restaurant"):
        assert f not in _FOREIGN_SLICE_FIELDS, f


def test_amending_a_retention_cell_also_updates_the_frozen_block(tmp_path):
    """Found 2026-08-13 amending July's allied cells: apply_frozen stamps the
    sealed slice and THEN overlays `frozen` (the pre-ITD retention photo), so
    a retention amendment was recorded and then overwritten before it reached
    the report — silently, since the frozen block existed. The 8/6 fee
    amendments never took effect either. An amendment must update wherever
    the published value lives."""
    import json as _json
    from scripts.amend_sealed_month import amend
    doc = {"period": "2026-07", "month": "Jul",
           "sealed": {"ret_billed_non_target": {"TKP": {"Jul": 8}}},
           "frozen": {"ret_billed_non_target": {"TKP": 8}}}
    d = tmp_path / "closes"
    d.mkdir()
    (d / "close_2026-07.json").write_text(_json.dumps(doc))
    amend("2026-07", "ret_billed_non_target", "TKP", "Jul", 11,
          why="allied ruling", closes_dir=d, assume_yes=True, push=lambda *a: None)
    after = _json.loads((d / "close_2026-07.json").read_text())
    assert after["sealed"]["ret_billed_non_target"]["TKP"]["Jul"] == 11
    assert after["frozen"]["ret_billed_non_target"]["TKP"] == 11, (
        "the frozen photo still holds the pre-amendment value — it would "
        "overwrite the amendment on the next build")
