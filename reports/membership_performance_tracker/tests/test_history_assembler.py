"""History assembler (Jiho 2026-07-22): each prior month's photo metrics
(penetration, billables) come from THAT month's own stored snapshot; months
never photographed stay absent — blank on the report, never fabricated."""
import json
from datetime import date
from pathlib import Path

from reports.membership_performance_tracker.history import (
    PHOTO_METRICS, assemble_photo_history)
from reports.membership_performance_tracker.logic.model import empty_scoreboard
from reports.membership_performance_tracker.logic.cache import save_scoreboard

_FY = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
       "Apr", "May", "Jun", "Jul", "Aug", "Sep"]


def _snapshot(cache_dir, period, pen_active_rest):
    data = empty_scoreboard(_FY)
    data.pen_active_restaurant["Pierce"] = pen_active_rest
    data.pen_market_restaurant["Pierce"] = 400
    data.hosp_bills["Pierce"]["Jun"] = 163   # tm_current photo field
    path = cache_dir / f"scoreboard_{period}.json"
    save_scoreboard(data, path)
    # save_scoreboard stamps saved_at = now(), which drifts past the 35-day
    # freshness window once the real calendar moves on (bit us 2026-08-05:
    # a "June" fixture saved in August is correctly rejected). Pin a capture
    # date that is always plausible for the labeled period.
    payload = json.loads(path.read_text())
    payload["_meta"]["saved_at"] = f"{period}-28T02:00:00"
    path.write_text(json.dumps(payload))


def test_prior_month_photo_comes_from_its_own_snapshot(tmp_path):
    _snapshot(tmp_path, "2026-06", 369)
    rows = assemble_photo_history("Jul", 2025, tmp_path)
    jun = [r for r in rows if r["month"] == "Jun"
           and r["metric"] == "Target Members - Restaurant (#)"
           and r["territory"] == "Pierce"]
    assert jun and jun[0]["value"] == 369, "June photo must come from June's snapshot"
    assert jun[0]["year"] == 2026
    assert all(r["metric"] in PHOTO_METRICS for r in rows), \
        "assembler must never touch transactional metrics"


def test_unphotographed_months_stay_absent(tmp_path):
    _snapshot(tmp_path, "2026-06", 369)   # only June exists
    rows = assemble_photo_history("Jul", 2025, tmp_path)
    months = {r["month"] for r in rows}
    assert months == {"Jun"}, f"only captured months may appear, got {months}"


def test_current_month_not_reassembled(tmp_path):
    _snapshot(tmp_path, "2026-07", 999)
    rows = assemble_photo_history("Jul", 2025, tmp_path)
    assert not [r for r in rows if r["month"] == "Jul"], \
        "the current month's photo belongs to the live pull, not the assembler"


def test_stale_snapshot_rejected(tmp_path):
    """A March-period cache pulled in July is July's state wearing a March
    label — the assembler must reject it, leaving March honestly blank."""
    import json
    _snapshot(tmp_path, "2026-03", 300)
    p = tmp_path / "scoreboard_2026-03.json"
    payload = json.loads(p.read_text())
    payload["_meta"]["saved_at"] = "2026-07-16T19:10:29"
    p.write_text(json.dumps(payload))
    rows = assemble_photo_history("Jul", 2025, tmp_path)
    assert not [r for r in rows if r["month"] == "Mar"], \
        "stale photos must be rejected, not relabeled"


def test_photo_freshness_uses_the_photograph_clock_not_the_file_write_clock(tmp_path):
    """S6 (overnight review 8/10): every rebuild re-stamps saved_at, so a
    sealed month rebuilt >35 days after it ended failed its own freshness
    test and its billables/penetration photo vanished from all later
    editions. pulled_at is the photograph's own clock."""
    import json
    from reports.membership_performance_tracker import history as H
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "scoreboard_2026-07.json").write_text(json.dumps({
        "_meta": {"schema_version": 1,
                  "dataclass": "ScoreboardData",
                  "pulled_at": "2026-08-05T02:00:00",     # the real photo
                  "saved_at": "2026-11-20T09:00:00"},     # a much later rebuild
        "fields": {"hosp_bills": {"Pierce": {"Jul": 166}}}}))
    snap = H._load_snapshot("2026-07", cache)
    assert snap is not None, "a July photo taken 8/5 must survive a November rebuild"
    assert snap.hosp_bills["Pierce"]["Jul"] == 166


# ── the second apply door (2026-08-14) ───────────────────────────────────────
# A past month's photo metrics reach a later report through this assembler,
# re-mapped from that month's OWN cache. The cache is deliberately kept as the
# program's own numbers, so without applying corrections here a hand-adjusted
# penetration count would show on its own month's report and then silently
# revert in every later month's column.

def test_a_past_months_correction_survives_into_a_later_report(tmp_path, monkeypatch):
    from reports.membership_performance_tracker.logic import adjustments as adj

    _snapshot(tmp_path, "2026-06", 369)
    store = tmp_path / "adjustments"
    store.mkdir()
    monkeypatch.setattr(adj, "ADJUSTMENTS_DIR", store)
    adj.post("2026-06", "pen_active_restaurant", "Pierce", None, 4,
             "Four members the June photo missed.", "SuzAnne", store_dir=store)

    rows = assemble_photo_history("Jul", 2025, tmp_path)
    jun = [r for r in rows if r["month"] == "Jun"
           and r["metric"] == "Target Members - Restaurant (#)"
           and r["territory"] == "Pierce"]
    assert jun and jun[0]["value"] == 373, (
        "369 + 4 — a correction to a past month must not evaporate when a "
        "later month's report re-reads that month's photo")


def test_a_correction_to_one_month_does_not_touch_another(tmp_path, monkeypatch):
    from reports.membership_performance_tracker.logic import adjustments as adj

    _snapshot(tmp_path, "2026-05", 100)
    _snapshot(tmp_path, "2026-06", 369)
    store = tmp_path / "adjustments"
    store.mkdir()
    monkeypatch.setattr(adj, "ADJUSTMENTS_DIR", store)
    adj.post("2026-06", "pen_active_restaurant", "Pierce", None, 4,
             "June only.", "SuzAnne", store_dir=store)

    rows = assemble_photo_history("Jul", 2025, tmp_path)
    by_month = {r["month"]: r["value"] for r in rows
                if r["metric"] == "Target Members - Restaurant (#)"
                and r["territory"] == "Pierce"}
    assert by_month["Jun"] == 373
    assert by_month["May"] == 100, "each month carries only its own corrections"


def test_corrections_are_stored_per_period_so_they_cannot_cross_a_fiscal_year(tmp_path):
    """The FY-rollover guard, satisfied by construction.

    `apply_frozen` needs an explicit fiscal-year check because it globs EVERY
    close doc and a close doc's month is a bare name — so a FY25-26 seal could
    stamp FY26-27's same-named column. Corrections cannot: they are stored and
    loaded per period, so a July 2026 entry is unreachable from a July 2027
    build. This test exists so that stays true if the storage ever moves.
    """
    from reports.membership_performance_tracker.logic import adjustments as adj

    store = tmp_path / "adjustments"
    store.mkdir()
    adj.post("2026-07", "ret_paid_target", "TKP", "Jul", 5,
             "FY25-26.", "SuzAnne", store_dir=store)

    assert adj.load("2026-07", store_dir=store), "its own period sees it"
    assert adj.load("2027-07", store_dir=store) == [], (
        "the same month one fiscal year later must not inherit it")
    assert adj.load("2026-10", store_dir=store) == [], (
        "the next fiscal year's first month must not inherit it either")
