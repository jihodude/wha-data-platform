"""The adjustments store — corrections as append-only, replayable entries.

Storage only: nothing here reaches a published number yet. These tests pin the
guarantees the rest of the feature will stand on.
"""
import json
from pathlib import Path

import pytest

from reports.membership_performance_tracker.logic import adjustments as adj


@pytest.fixture()
def closes(tmp_path):
    """The sidecar store. Named `closes` for history; it is NOT the close doc.

    Storing adjustments in close_<period>.json would make an OPEN month report
    as closed — `is_closed()` is just "does that file exist" — and the next
    live pull would auto-seal a month still collecting.
    """
    d = tmp_path / "adjustments"
    d.mkdir()
    return d


def _post(closes, **kw):
    args = dict(period="2026-07", field="ret_paid_non_target",
                territory="EastKing", month="Jul", delta=1,
                why="Sebris Busto paid; found after the close.",
                who="Jen Hurley", store_dir=closes)
    args.update(kw)
    return adj.post(**args)


# ── the record ───────────────────────────────────────────────────────────────

def test_a_posted_adjustment_is_readable_back(closes):
    _post(closes)
    got = adj.load("2026-07", store_dir=closes)
    assert len(got) == 1
    e = got[0]
    assert e["field"] == "ret_paid_non_target" and e["delta"] == 1.0
    assert e["who"] == "Jen Hurley" and e["why"].startswith("Sebris")
    assert e["at"], "every entry is stamped with when it was made"


def test_the_store_is_a_sidecar_and_never_the_close_doc(closes, tmp_path):
    _post(closes)
    assert (closes / "adjustments_2026-07.json").exists()
    assert not list(tmp_path.glob("**/close_*.json")), (
        "an adjustment must never create or touch a close doc: is_closed() is "
        "just 'does that file exist', so it would seal an open month")


def test_the_store_is_append_only(closes):
    _post(closes, delta=1, why="first")
    _post(closes, delta=-1, why="reversing the first")
    got = adj.load("2026-07", store_dir=closes)
    assert len(got) == 2, "a reversal ADDS an entry; it never removes one"
    assert adj.total_for(got, "ret_paid_non_target", "EastKing", "Jul") == 0.0


def test_an_open_month_with_no_prior_file_accepts_the_post(closes):
    # Jiho ruled 8/14 that OPEN months are in scope. The sidecar is created on
    # demand and says nothing about whether the month is closed.
    e = _post(closes, period="2026-05", month="May")
    assert e["month"] == "May"
    got = adj.load("2026-05", store_dir=closes)
    assert len(got) == 1 and got[0]["why"] == e["why"] and got[0]["delta"] == e["delta"]
    assert got[0]["_period"] == "2026-05", (
        "load stamps which file an entry came from — a month-less correction "
        "belongs to one period's photograph and must stay findable")


def test_total_is_not_a_place_to_post_to(closes):
    with pytest.raises(adj.AdjustmentRefused, match="every territory"):
        _post(closes, territory="Total")


def test_a_penetration_count_is_posted_without_a_month(closes):
    # Per-territory photo fields are field[territory], not field[t][month].
    e = _post(closes, field="pen_active_restaurant", month=None, delta=2)
    assert e["month"] is None
    assert adj.total_for(adj.load("2026-07", store_dir=closes),
                         "pen_active_restaurant", "EastKing", None) == 2.0


def test_a_move_group_is_unique_even_within_one_second(closes):
    a = adj.post_move("2026-07", "drops_target", "TKP", "Apr", "Jul", 1,
                      "first", "SuzAnne", store_dir=closes, now="2026-09-01T10:00:00")
    b = adj.post_move("2026-07", "drops_target", "TKP", "Apr", "Jul", 1,
                      "second", "SuzAnne", store_dir=closes, now="2026-09-01T10:00:00")
    assert a[0]["group"] != b[0]["group"], (
        "two moves on the same cell in the same second must stay two actions")


# ── what it refuses ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("kw, expect", [
    ({"why": "   "},                     "reason"),
    ({"who": ""},                        "name"),
    ({"delta": 0},                       "nothing"),
    ({"delta": "banana"},                "not a number"),
    ({"month": "Smarch"},                "not a month"),
    ({"field": "retention_pct"},         "calculated from other numbers"),
    ({"field": "goal_retention"},        "goal"),
    ({"territory": ""},                  "territory"),
])
def test_refusals(closes, kw, expect):
    with pytest.raises(adj.AdjustmentRefused, match=expect):
        _post(closes, **kw)


def test_a_derived_number_cannot_be_adjusted_directly(closes):
    # Guarding the specific way this goes wrong: "48/58" and the percentage
    # are two views of the same two numbers. Editing the view lets them
    # disagree with each other on the same row.
    for derived in ("retention_pct", "retention_str", "ret_status", "pen_pct"):
        with pytest.raises(adj.AdjustmentRefused):
            _post(closes, field=derived)


def test_goals_are_out_of_scope(closes):
    # Goals live in Admin Inputs and already recompute past months'
    # percentages by design (ruled 8/14). Two mechanisms on one cell would
    # fight, and the Admin Inputs one is the documented route.
    for g in ("goal", "goal_members", "goal_penetration", "ytd_goal"):
        with pytest.raises(adj.AdjustmentRefused, match="goal"):
            _post(closes, field=g)


# ── moves are atomic ─────────────────────────────────────────────────────────

def test_a_move_posts_both_sides_under_one_group(closes):
    out = adj.post_move("2026-07", "drops_target", "TKP", "Apr", "Jul", 1,
                        "Files at its cycle close; no end date on the record.",
                        "SuzAnne", store_dir=closes)
    assert len(out) == 2
    assert {e["month"] for e in out} == {"Apr", "Jul"}
    assert out[0]["delta"] == -1.0 and out[1]["delta"] == 1.0
    assert out[0]["group"] and out[0]["group"] == out[1]["group"], (
        "both sides carry one group id so the pair reads as a pair")
    entries = adj.load("2026-07", store_dir=closes)
    assert adj.total_for(entries, "drops_target", "TKP", "Apr") == -1.0
    assert adj.total_for(entries, "drops_target", "TKP", "Jul") == 1.0


def test_a_move_to_the_same_month_is_refused(closes):
    with pytest.raises(adj.AdjustmentRefused, match="two different months"):
        adj.post_move("2026-07", "drops_target", "TKP", "Jul", "Jul", 1,
                      "why", "SuzAnne", store_dir=closes)


def test_a_move_conserves_the_total(closes):
    adj.post_move("2026-07", "drops_revenue_target", "TKP", "Apr", "Jul", 510,
                  "moved", "SuzAnne", store_dir=closes)
    entries = adj.load("2026-07", store_dir=closes)
    net = sum(e["delta"] for e in entries)
    assert net == 0.0, (
        "a move must not create or destroy anything — the 8/13 near-miss was "
        "exactly a one-sided move")


# ── reading for the overlay and for Trace ────────────────────────────────────

def test_totals_are_per_cell(closes):
    _post(closes, delta=2, month="Jul")
    _post(closes, delta=3, month="Jun")
    _post(closes, delta=5, territory="TKP")
    entries = adj.load("2026-07", store_dir=closes)
    assert adj.total_for(entries, "ret_paid_non_target", "EastKing", "Jul") == 2
    assert adj.total_for(entries, "ret_paid_non_target", "EastKing", "Jun") == 3
    assert adj.total_for(entries, "ret_paid_non_target", "TKP", "Jul") == 5
    assert adj.total_for(entries, "ret_paid_non_target", "Pierce", "Jul") == 0


def test_by_cell_lists_every_touched_cell(closes):
    _post(closes, delta=2)
    _post(closes, delta=-1)
    _post(closes, delta=4, territory="TKP")
    cells = adj.by_cell(adj.load("2026-07", store_dir=closes))
    assert cells[("ret_paid_non_target", "EastKing", "Jul")] == 1.0
    assert cells[("ret_paid_non_target", "TKP", "Jul")] == 4.0
    assert len(cells) == 2


def test_for_cell_returns_the_entries_trace_will_show(closes):
    _post(closes, delta=1, why="first reason")
    _post(closes, delta=1, why="second reason", territory="TKP")
    rows = adj.for_cell(adj.load("2026-07", store_dir=closes),
                        "ret_paid_non_target", "EastKing", "Jul")
    assert len(rows) == 1 and rows[0]["why"] == "first reason"


def test_load_is_empty_and_quiet_for_an_unknown_period(closes):
    assert adj.load("2029-01", store_dir=closes) == []


def test_load_is_quiet_when_the_store_is_unreadable(tmp_path):
    d = tmp_path / "adjustments"
    d.mkdir()
    (d / "adjustments_2026-07.json").write_text("{ not json")
    assert adj.load("2026-07", store_dir=d) == [], (
        "a damaged store must not take the report down")


def test_posting_over_an_unreadable_store_is_refused(tmp_path):
    d = tmp_path / "adjustments"
    d.mkdir()
    (d / "adjustments_2026-07.json").write_text("{ not json")
    with pytest.raises(adj.AdjustmentRefused, match="unreadable"):
        adj.post("2026-07", "drops_target", "TKP", "Jul", 1, "why", "me",
                 store_dir=d)


# ── the overlay (mechanical layer only — not yet wired into a build) ─────────

class _Data:
    """Stands in for ScoreboardData: attribute dicts of territory -> month."""

    def __init__(self, **grids):
        for k, v in grids.items():
            setattr(self, k, v)


def _grid(value=10.0):
    return {"EastKing": {"Jun": value, "Jul": value}, "TKP": {"Jul": value}}


def test_the_overlay_adds_the_net_delta_to_the_right_cell():
    d = _Data(ret_paid_non_target=_grid(10.0))
    entries = [
        {"field": "ret_paid_non_target", "territory": "EastKing",
         "month": "Jul", "delta": 2},
        {"field": "ret_paid_non_target", "territory": "EastKing",
         "month": "Jul", "delta": -1},
    ]
    adj.apply_to(d, entries)
    assert d.ret_paid_non_target["EastKing"]["Jul"] == 11.0, "10 + 2 - 1"
    assert d.ret_paid_non_target["EastKing"]["Jun"] == 10.0, "other months untouched"
    assert d.ret_paid_non_target["TKP"]["Jul"] == 10.0, "other territories untouched"


def test_applying_twice_to_the_same_data_compounds():
    # THE reason adjustments are never written into the scoreboard cache: the
    # overlay is not idempotent against already-adjusted input, and cache mode
    # would feed it its own previous output on every --from-cache rebuild.
    d = _Data(ret_paid_non_target=_grid(10.0))
    e = [{"field": "ret_paid_non_target", "territory": "EastKing",
          "month": "Jul", "delta": 1}]
    adj.apply_to(d, e)
    adj.apply_to(d, e)
    assert d.ret_paid_non_target["EastKing"]["Jul"] == 12.0, (
        "documents the hazard — the cache must stay the program's own numbers")


def test_a_negative_result_is_refused_not_written():
    d = _Data(drops_target=_grid(1.0))
    notes = adj.apply_to(d, [{"field": "drops_target", "territory": "TKP",
                              "month": "Jul", "delta": -5}])
    assert d.drops_target["TKP"]["Jul"] == 1.0, "the cell must not go negative"
    assert any("REFUSED" in n for n in notes), "and it must say so"


def test_an_unknown_field_or_cell_is_reported_never_invented():
    d = _Data(ret_paid_non_target=_grid(10.0))
    notes = adj.apply_to(d, [
        {"field": "no_such_field", "territory": "EastKing", "month": "Jul",
         "delta": 1},
        {"field": "ret_paid_non_target", "territory": "Atlantis",
         "month": "Jul", "delta": 1},
    ])
    assert not hasattr(d, "no_such_field")
    assert "Atlantis" not in d.ret_paid_non_target
    assert len([n for n in notes if "skipped" in n]) == 2


def test_a_none_cell_is_treated_as_zero_not_a_crash():
    d = _Data(revenue_target={"EastKing": {"Jul": None}})
    adj.apply_to(d, [{"field": "revenue_target", "territory": "EastKing",
                      "month": "Jul", "delta": 500}])
    assert d.revenue_target["EastKing"]["Jul"] == 500.0


def test_the_recompute_pass_is_handed_exactly_what_moved():
    d = _Data(ret_paid_non_target=_grid(10.0))
    seen = []

    def _recompute(data, touched):
        seen.extend(touched)
        return ["recomputed"]

    notes = adj.apply_to(d, [{"field": "ret_paid_non_target",
                              "territory": "EastKing", "month": "Jul",
                              "delta": 1}], recompute=_recompute)
    assert seen == [("ret_paid_non_target", "EastKing", "Jul")]
    assert "recomputed" in notes


def test_recompute_is_not_called_when_nothing_moved():
    d = _Data(ret_paid_non_target=_grid(10.0))
    called = []
    adj.apply_to(d, [{"field": "nope", "territory": "EastKing",
                      "month": "Jul", "delta": 1}],
                 recompute=lambda *a: called.append(1))
    assert not called


# ── the derivation pass ──────────────────────────────────────────────────────
# Combined counts come from SLX independently of their splits, so adjusting a
# split leaves the combined figure disagreeing with its own parts. pen_pct is
# the one derived field the mapper reads. Both are FRACTIONS, verified against
# the live cache (EastKing pen_pct 0.5166 = (251+29)/(489+53)).

def _ret_data():
    return _Data(
        ret_paid_target={"EastKing": {"Jul": 8.0}},
        ret_paid_non_target={"EastKing": {"Jul": 3.0}},
        ret_paid={"EastKing": {"Jul": 11.0}},
        ret_billed_target={"EastKing": {"Jul": 10.0}},
        ret_billed_non_target={"EastKing": {"Jul": 3.0}},
        ret_billed={"EastKing": {"Jul": 13.0}},
    )


def test_adjusting_a_split_brings_the_combined_count_with_it():
    d = _ret_data()
    adj.apply_to(d, [{"field": "ret_paid_non_target", "territory": "EastKing",
                      "month": "Jul", "delta": 1}], recompute=adj.recompute)
    assert d.ret_paid_non_target["EastKing"]["Jul"] == 4.0
    assert d.ret_paid["EastKing"]["Jul"] == 12.0, (
        "combined must follow its splits — SLX supplies it independently, so "
        "nothing else would fix this")
    assert d.ret_billed["EastKing"]["Jul"] == 13.0, "untouched families stay put"


def test_the_combined_count_is_rebuilt_from_both_splits_not_incremented():
    d = _ret_data()
    d.ret_paid["EastKing"]["Jul"] = 999.0          # already wrong
    adj.apply_to(d, [{"field": "ret_paid_target", "territory": "EastKing",
                      "month": "Jul", "delta": 1}], recompute=adj.recompute)
    assert d.ret_paid["EastKing"]["Jul"] == 12.0, "9 + 3, rebuilt from the parts"


def test_pen_pct_recomputes_as_a_fraction_of_the_adjusted_counts():
    d = _Data(
        pen_active_restaurant={"EastKing": 251.0},
        pen_active_lodging={"EastKing": 29.0},
        pen_market_restaurant={"EastKing": 489.0},
        pen_market_lodging={"EastKing": 53.0},
        pen_pct={"EastKing": 280 / 542},
    )
    adj.apply_to(d, [{"field": "pen_active_restaurant", "territory": "EastKing",
                      "month": None, "delta": 2}], recompute=adj.recompute)
    assert d.pen_active_restaurant["EastKing"] == 253.0
    assert d.pen_pct["EastKing"] == 282 / 542, "a fraction, never a percentage"


def test_pen_pct_is_none_rather_than_a_divide_by_zero():
    d = _Data(pen_active_restaurant={"TKP": 1.0}, pen_active_lodging={"TKP": 0.0},
              pen_market_restaurant={"TKP": 1.0}, pen_market_lodging={"TKP": 0.0},
              pen_pct={"TKP": 1.0})
    adj.apply_to(d, [{"field": "pen_market_restaurant", "territory": "TKP",
                      "month": None, "delta": -1}], recompute=adj.recompute)
    assert d.pen_pct["TKP"] is None


def test_combined_bills_follows_hospitality_and_allied():
    d = _Data(
        hosp_bills_target={"TKP": {"Jul": 100.0}},
        hosp_bills_non_target={"TKP": {"Jul": 20.0}},
        hosp_bills={"TKP": {"Jul": 120.0}},
        allied_bills={"TKP": {"Jul": 5.0}},
        combined_bills={"TKP": {"Jul": 125.0}},
    )
    adj.apply_to(d, [{"field": "hosp_bills_target", "territory": "TKP",
                      "month": "Jul", "delta": 3}], recompute=adj.recompute)
    assert d.hosp_bills["TKP"]["Jul"] == 123.0
    assert d.combined_bills["TKP"]["Jul"] == 128.0


def test_recompute_leaves_untouched_cells_alone():
    d = _ret_data()
    d.ret_paid_target["EastKing"]["Jun"] = 5.0
    d.ret_paid["EastKing"]["Jun"] = 99.0        # deliberately inconsistent
    adj.apply_to(d, [{"field": "ret_paid_target", "territory": "EastKing",
                      "month": "Jul", "delta": 1}], recompute=adj.recompute)
    assert d.ret_paid["EastKing"]["Jun"] == 99.0, (
        "the pass fixes what an adjustment touched, not the whole grid")


# ── a correction follows its MONTH, not the report it was filed from ─────────
# Found by Jiho 8/14. Correct July's column while the August report is open and
# the entry is filed under August. Every later report shows that same July
# column, so loading only the built period's file made the correction visible
# on August's report and invisible on September's — the same number, corrected,
# reverting the moment the calendar moved.

def test_a_correction_filed_from_one_report_reaches_the_others(closes):
    _post(closes, period="2026-08", month="Jul", delta=100,
          field="rev_retained_target", territory="Snohomish")
    fy = adj.load_fy(2025, store_dir=closes)
    assert len(fy) == 1, "a build of ANY month in the fiscal year must see it"
    assert fy[0]["month"] == "Jul", "and it still names the column it corrects"


def test_a_correction_cannot_reach_the_next_fiscal_year(closes):
    _post(closes, period="2026-08", month="Jul", delta=100,
          field="rev_retained_target", territory="Snohomish")
    assert adj.load_fy(2025, store_dir=closes), "its own fiscal year sees it"
    assert adj.load_fy(2026, store_dir=closes) == [], (
        "FY26-27 must start clean — this is the guard apply_frozen needs "
        "explicitly, and here it comes from only reading that year's periods")


def test_a_fiscal_year_runs_october_to_september():
    p = adj.periods_of_fy(2025)
    assert p[0] == "2025-10" and p[-1] == "2026-09" and len(p) == 12
    assert adj.fy_start_of("2026-07") == 2025, "July 2026 is in FY25-26"
    assert adj.fy_start_of("2026-10") == 2026, "October 2026 starts FY26-27"


def test_entries_from_several_periods_come_back_in_time_order(closes):
    _post(closes, period="2026-08", month="Jul", delta=1, now="2026-08-14T06:00:00")
    _post(closes, period="2026-07", month="Jun", delta=1, now="2026-07-02T06:00:00")
    fy = adj.load_fy(2025, store_dir=closes)
    assert [e["month"] for e in fy] == ["Jun", "Jul"], "oldest first, across files"


# ── SharePoint is the record; local disk is a working copy ───────────────────
# Cloud Run wipes a container on every deploy. A correction that exists only
# locally dies at the next deploy and the number silently reverts — so the
# push must be fail-loud, unlike every other close-doc writer in this codebase.

def test_a_failed_push_warns_instead_of_reporting_success(tmp_path, monkeypatch):
    from reports.membership_performance_tracker.logic import adjustments as a

    class _Hub:
        def write_hub_file(self, *_a, **_k):
            raise RuntimeError("SharePoint said no")

    monkeypatch.setattr(a, "ADJUSTMENTS_DIR", tmp_path)
    monkeypatch.setattr(a, "_hub", lambda: _Hub())
    with pytest.raises(a.AdjustmentSavedLocallyOnly, match="NOT safe"):
        a.post("2026-08", "drops_target", "TKP", "Jul", 1, "why", "me")
    # the entry still exists locally — a failed push must not lose the work
    assert len(a.load("2026-08")) == 1


def test_a_missing_local_copy_is_pulled_from_sharepoint(tmp_path, monkeypatch):
    from reports.membership_performance_tracker.logic import adjustments as a
    payload = json.dumps({"period": "2026-08", "entries": [
        {"field": "drops_target", "territory": "TKP", "month": "Jul",
         "delta": 1, "why": "from SP", "who": "SuzAnne"}]}).encode()

    class _Hub:
        def read_hub_file(self, path):
            assert path.endswith("adjustments_2026-08.json")
            return payload

    monkeypatch.setattr(a, "ADJUSTMENTS_DIR", tmp_path)
    monkeypatch.setattr(a, "_hub", lambda: _Hub())
    got = a.load("2026-08")
    assert len(got) == 1 and got[0]["why"] == "from SP", (
        "a fresh container must recover corrections it never had")
    assert (tmp_path / "adjustments_2026-08.json").exists(), "and cache them"


def test_a_corrupt_sharepoint_copy_is_not_cached(tmp_path, monkeypatch):
    from reports.membership_performance_tracker.logic import adjustments as a

    class _Hub:
        def read_hub_file(self, path):
            return b"{ not json"

    monkeypatch.setattr(a, "ADJUSTMENTS_DIR", tmp_path)
    monkeypatch.setattr(a, "_hub", lambda: _Hub())
    assert a.load("2026-08") == []
    assert not (tmp_path / "adjustments_2026-08.json").exists()


def test_an_explicit_store_dir_never_reaches_the_network(tmp_path, monkeypatch):
    from reports.membership_performance_tracker.logic import adjustments as a

    def _boom():
        raise AssertionError("a sandboxed store must not touch SharePoint")

    monkeypatch.setattr(a, "_hub", _boom)
    assert a.load("2026-08", store_dir=tmp_path) == []
    a.post("2026-08", "drops_target", "TKP", "Jul", 1, "why", "me",
           store_dir=tmp_path)


# ── every family with a stored combined must recombine ──────────────────────
# Jiho, 8/14: "new sales for Snohomish worked, but retention comped $ for
# NorthKing did not." The Target row moved; the COMBINED row read its own
# stored field and stayed stale. The report shows both rows, so both must move.

@pytest.mark.parametrize("combined, target, non_target", [
    ("ret_comped", "ret_comped_target", "ret_comped_non_target"),
    ("ret_comped_dollars", "ret_comped_dollars_target",
     "ret_comped_dollars_non_target"),
    ("revenue_bob", "revenue_bob_target", "revenue_bob_non_target"),
    ("ret_paid", "ret_paid_target", "ret_paid_non_target"),
    ("revenue", "revenue_target", "revenue_non_target"),
])
def test_correcting_a_band_moves_its_combined_line(combined, target, non_target):
    d = _Data(**{combined: {"NorthKing": {"Jul": 300.0}},
                 target: {"NorthKing": {"Jul": 200.0}},
                 non_target: {"NorthKing": {"Jul": 100.0}}})
    adj.apply_to(d, [{"field": target, "territory": "NorthKing",
                      "month": "Jul", "delta": 50}], recompute=adj.recompute)
    assert getattr(d, target)["NorthKing"]["Jul"] == 250.0
    assert getattr(d, combined)["NorthKing"]["Jul"] == 350.0, (
        f"{combined} is its own stored field and feeds its own report row")


def test_every_stored_combined_with_a_band_pair_is_covered():
    """A new T/NT pair with a stored combined must be added to SPLIT_SUMS.

    This is the check that would have caught the comped miss before Jiho did.
    """
    from reports.membership_performance_tracker.mapper import METRIC_FIELD_MAP
    fields = {f for _m, (_k, f) in METRIC_FIELD_MAP.items()}
    missed = []
    for f in sorted(fields):
        if f.endswith("_target") and f[: -len("_target")] in fields:
            base = f[: -len("_target")]
            if f"{base}_non_target" in fields and base not in adj.SPLIT_SUMS:
                missed.append(base)
    assert not missed, (
        f"these have a stored combined and a Target/Non-Target pair but do not "
        f"recombine after a correction: {missed}")
