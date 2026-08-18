"""GATES — objective checks that stop a run. No judgement, no human needed.

Written 2026-07-28 after drops shipped silently wrong: on the --from-cache path
`_build_crystal_band` has no SLX client, so it returned UNKNOWN for every row,
the feed folded UNKNOWN into Non-Target, and the workbook published
Target 0 / Non-Target 135 without a word. A number nobody can defend reached
the report because nothing objected.

The doctrine (ROADMAP "GATES vs VALIDATION"): if it can be settled by
arithmetic or by a file's presence, it belongs in the product.
"""
import json

import pytest

from reports.membership_performance_tracker.logic import crystal_feed as cf
from reports.membership_performance_tracker.logic import crystal_parsers as cp
from reports.membership_performance_tracker.logic import target as tl


def _drop(name, territory, bm, dues, reason="Sold"):
    return cp.DropRow(mid="0000001", name=name, territory=territory, dues=dues,
                      bill_month=bm, status_reason=reason)


def _archive(tmp_path, period="2026-07", files=("drops_hospitality",)):
    folder = tmp_path / period
    folder.mkdir(parents=True)
    manifest = {}
    for key in files:
        (folder / f"{key}.xls").write_bytes(b"stub")
        manifest[key] = {"file_name": f"{key}.xls", "run_date": "2026-07-27", "sha256": "abc"}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path


# --- GATE A: the split must account for every banded row --------------------

def test_drops_split_must_equal_the_reason_total(monkeypatch, tmp_path):
    """Target + Non-Target and the per-reason grid come from one loop over one
    export, so they must agree exactly. If they ever diverge, a row was counted
    into one view and lost from the other — publish nothing."""
    root = _archive(tmp_path)
    rows = [_drop("A", "Pierce", 4, 100.0), _drop("B", "TKP", 5, 200.0)]
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality", lambda _b: rows)

    fields = cf.feed_drops("2026-07", root, lambda _r: tl.TARGET)

    t = sum(v for g in fields["drops_target"].values() for v in g.values())
    nt = sum(v for g in fields["drops_non_target"].values() for v in g.values())
    cats = sum(v for grid in fields["drops_by_category"].values()
               for g in grid.values() for v in g.values())
    assert t + nt == cats == 2


def test_a_split_that_loses_a_row_raises(monkeypatch, tmp_path):
    """Simulate the divergence directly: the gate must fire, not warn."""
    root = _archive(tmp_path)
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality",
                        lambda _b: [_drop("A", "Pierce", 4, 100.0)])
    real_grid = cf._grid

    def leaky_grid():
        g = real_grid()
        g["Pierce"]["Apr"] = -1          # a row silently vanishing from the split
        return g
    monkeypatch.setattr(cf, "_grid", leaky_grid)

    with pytest.raises(ValueError, match="drops split"):
        cf.feed_drops("2026-07", root, lambda _r: tl.TARGET)


# --- GATE B: an unbanded family must not be published -----------------------

def test_drops_are_skipped_when_banding_is_unavailable(monkeypatch, tmp_path):
    """THE 2026-07-28 BUG. With no client there is no Target/Non-Target
    knowledge at all — every row reads UNKNOWN and lands in Non-Target, which
    looks exactly like a real answer ("Target: 0"). An unbandable drops family
    must keep SData's numbers and say so, never publish a fabricated split."""
    root = _archive(tmp_path)
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality",
                        lambda _b: [_drop("A", "Pierce", 4, 100.0)])
    sdata = {"drops_target": {"Pierce": {"Apr": 7}},
             "drops_non_target": {"Pierce": {"Apr": 3}}}

    with pytest.warns(UserWarning, match="falling back to SData"):
        merged, report = cf.overlay(dict(sdata), "2026-07", root, band=None)

    assert merged["drops_target"]["Pierce"]["Apr"] == 7, "SData's split survives"
    assert "drops" in report.skipped
    assert "band" in report.skipped["drops"].lower()


def test_a_working_band_still_publishes(monkeypatch, tmp_path):
    root = _archive(tmp_path)
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality",
                        lambda _b: [_drop("A", "Pierce", 4, 100.0)])

    merged, report = cf.overlay({"drops_target": {"Pierce": {"Apr": 7}}},
                                "2026-07", root, band=lambda _r: tl.TARGET)

    assert report.applied == ["drops"]
    # dateless bm4 files at its May close under the event axis (2026-07-31)
    assert merged["drops_target"]["Pierce"]["May"] == 1
    assert merged["drops_target"]["Pierce"]["Apr"] == 0.0   # replaced wholesale


# --- the runner must not hand over a bander that cannot band ----------------

def test_runner_returns_no_bander_when_there_is_no_client():
    """--from-cache has no SLX connection by design. Returning a
    lambda->UNKNOWN there is what manufactured 'Target: 0'; returning None lets
    GATE B keep SData's numbers instead."""
    from reports.membership_performance_tracker import runner

    class _NoClient:
        client = None
        territory_user_map = {"U1": "TKP"}

    assert runner._build_crystal_band(_NoClient()) is None


def test_runner_returns_no_bander_when_every_bridge_failed():
    """A client that exists but whose bridges all blew up is the same
    situation wearing a disguise."""
    from reports.membership_performance_tracker import runner

    class _Boom:
        client = object()
        territory_user_map = {"U1": "TKP"}

    with pytest.warns(UserWarning):
        assert runner._build_crystal_band(_Boom()) is None


# --- GATE C: a cohort that empties itself is a broken anchor, not a fact ----

def test_an_empty_cohort_is_allowed_when_a_rule_explains_it():
    """NOT a gate: a one-member territory whose member is genuinely first-cycle
    really does report 0/0. Deciding whether an exclusion was MEANT needs
    judgement, which makes it validation, not a gate."""
    from reports.membership_performance_tracker.logic import retention as R

    class _FirstCycleSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            if entity == "dlInvoiceHistoryHeader":
                return [{"Accountid": "A1", "Invoice_Type": "IN", "Comment": "5",
                         "Invoice_number": "I1", "Balance": 0.0, "Net_invoice": 730.0,
                         "Invoice_Date": "/Date(1775001600000)/"}]
            if entity == "cMemberGens":
                return [{"Account": {"$key": "A1"},
                         "EnrolledDate": "/Date(1775001600000)/",
                         "Duesbillmonth": 5, "MemrsProductID": "P1"}]
            return []

    paid, billed, *_ = R._retention_counts(_FirstCycleSLX(), "U1", "5",
                                           "2026-02-01", "2026-07-31", 2025)
    assert (paid, billed) == (0, 0)


def test_retention_raises_when_an_account_is_lost_rather_than_excluded():
    """CONSERVATION is the objective invariant: an invoiced account must end up
    either counted or claimed by a named rule. One that vanishes with no rule
    owning it was LOST — and a denominator nobody can explain account by
    account is exactly what we spent three days chasing."""
    from reports.membership_performance_tracker.logic import retention as R

    real_group = R._group_invoice_rows

    def lossy_group(records, cohort_comment=None, extra_anchor_ids=None):
        grouped = real_group(records, cohort_comment, extra_anchor_ids)
        grouped.pop("A2", None)          # silently dropped by no rule at all
        return grouped

    class _TwoMemberSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            if entity == "dlInvoiceHistoryHeader":
                return [{"Accountid": a, "Invoice_Type": "IN", "Comment": "5",
                         "Invoice_number": f"I{a}", "Balance": 0.0,
                         "Net_invoice": 730.0, "Invoice_Date": "/Date(1775001600000)/"}
                        for a in ("A1", "A2")]
            if entity == "cMemberGens":
                return [{"Account": {"$key": a}, "EnrolledDate": "/Date(1000000000000)/",
                         "Duesbillmonth": 5, "MemrsProductID": "P1"}
                        for a in ("A1", "A2")]
            return []

    R._group_invoice_rows = lossy_group
    try:
        with pytest.raises(RuntimeError, match="lost 1 account"):
            R._retention_counts(_TwoMemberSLX(), "U1", "5",
                                "2026-02-01", "2026-07-31", 2025)
    finally:
        R._group_invoice_rows = real_group


def test_skipped_drop_rows_are_announced_not_silently_discarded(monkeypatch, tmp_path):
    """The live July export carries 264 rows; 107 of them (40%) never reach the
    grid because they have no usable bill month — 104 are bill month 14, a
    retro/L&I special group (REFERENCE: BMs 13-16 are not dues months), all
    filed under the 'Retro Coordinator' user.

    Skipping them is CORRECT. Doing it in silence is how a 40% discard goes
    unnoticed for weeks, so the feed must say what it dropped and why.
    """
    root = _archive(tmp_path)
    rows = [_drop("Real", "Pierce", 4, 100.0),
            _drop("Retro A", "Retro Coordinator", 14, 500.0),
            _drop("Retro B", "Retro Coordinator", 14, 500.0),
            _drop("NoMonth", "TKP", None, 300.0)]
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality", lambda _b: rows)

    with pytest.warns(UserWarning, match="3 of 4 drop rows"):
        fields = cf.feed_drops("2026-07", root, lambda _r: tl.TARGET)

    assert sum(v for g in fields["drops_target"].values() for v in g.values()) == 1
