"""Compile layer: the two families Crystal owns — billables and drops.

Tests for the new-members / retention / penetration compilers were removed
with those compilers on 2026-07-27: SData owns those families because only
the ledger can answer a past month (THE-PLAN Part 3).

The drops tests below no longer call this module. `crystal_compile.compile_drops`
was a third implementation of the drops loop that knew none of the rulings, and
these tests passing against it made it look alive; it was deleted 2026-08-14 and
they now run `crystal_feed.classify_drop` + `aggregate_drops` — the code that
actually publishes. The invariants they protect (dense grids, every canonical
territory, size-less members counted Non-Target) are unchanged.
"""
from datetime import date

import pytest

from reports.membership_performance_tracker.logic import crystal_compile as cc
from reports.membership_performance_tracker.logic import crystal_feed as cf
from reports.membership_performance_tracker.logic import crystal_parsers as cp
from reports.membership_performance_tracker.logic import target as target_logic

T, NT, UNK = target_logic.TARGET, target_logic.NON_TARGET, target_logic.UNKNOWN


def band_by_name(mapping):
    return lambda row: mapping.get(row.name, UNK)


def _drop(name, territory, bill_month, dues, reason="Sold"):
    return cp.DropRow(mid="0000002", name=name, territory=territory, dues=dues,
                      bill_month=bill_month, status_reason=reason,
                      status="Inactive")


def compile_drops(rows, band):
    """The REAL drops path, run on plain rows with no Crystal archive.

    `crystal_compile.compile_drops` used to be a third implementation of this
    loop that knew none of the rulings; it was deleted 2026-08-14 and these
    tests re-pointed at what actually ships — `classify_drop` for the rules,
    `aggregate_drops` for the grids.

    Each row is given the flip date its bill month implies, which is what the
    detail export supplies in real life. Without one the row would file at the
    class close (bill month + 1) by the 2026-07-31 event-axis ruling — correct,
    but a different question from the one these tests ask.
    """
    def flip_date(row):
        if not row.bill_month:
            return None
        return date(2025 if row.bill_month >= 10 else 2026, row.bill_month, 15)

    entries = [cf.classify_drop(r, False, band, drop_date_of=flip_date,
                                fy_start=2025, today=date(2026, 9, 30))
               for r in rows]
    return cf.aggregate_drops(entries, {})


def test_drops_land_on_the_bill_month_because_that_is_what_the_row_means():
    """A drop in month M = N members are no longer billed in cycle M.

    (Jiho 2026-07-27.) The export carries no date per row, and under this
    definition it does not need one — the metric is about the billing cycle
    that lost members, not the day somebody quit.
    """
    rows = [_drop("A", "Pierce", 4, 1070.0), _drop("B", "Pierce", 4, 510.0),
            _drop("C", "Pierce", 7, 730.0)]

    out = compile_drops(rows, band_by_name({"A": T, "B": T, "C": NT}))

    assert out["drops_target"]["Pierce"]["Apr"] == 2
    assert out["drops_revenue_target"]["Pierce"]["Apr"] == 1580.0
    assert out["drops_non_target"]["Pierce"]["Jul"] == 1


def test_no_member_is_dropped_from_the_count_for_lacking_a_size():
    """SUPERSEDES an earlier rule that left size-less members in neither band.

    That rule was disproved on 2026-07-27: Jennifer's published billables
    include those members (2,143 with them, 2,036 without — below every month
    she reported), so excluding them makes the report come up short. They
    count Non-Target; `warn_on_unknowns` still surfaces how many.
    """
    rows = [_drop("A", "Pierce", 4, 1070.0), _drop("MYSTERY", "Pierce", 4, 999.0)]

    out = compile_drops(rows, band_by_name({"A": T}))

    assert out["drops_target"]["Pierce"]["Apr"] == 1
    assert out["drops_non_target"]["Pierce"]["Apr"] == 1


def test_a_drop_with_no_bill_month_is_skipped_rather_than_guessed():
    """An unattributable drop must not silently inflate some month."""
    rows = [_drop("A", "Pierce", None, 1070.0)]

    out = compile_drops(rows, band_by_name({"A": T}))

    assert all(v == 0 for v in out["drops_target"].get("Pierce", {}).values())


def test_drops_by_reason_uses_crystals_own_vocabulary():
    rows = [_drop("A", "Pierce", 4, 0, reason="Out of Business"),
            _drop("B", "Pierce", 4, 0, reason="Out of Business"),
            _drop("C", "TKP", 5, 0, reason="Non-Payment"),
            _drop("D", "TKP", 5, 0, reason="")]

    out = compile_drops(rows, band_by_name({}))["drops_by_category"]

    assert out["Out of Business"]["Pierce"]["Apr"] == 2
    assert out["Non-Payment"]["TKP"]["May"] == 1
    assert out["Unspecified"]["TKP"]["May"] == 1


def test_billables_are_written_for_the_snapshot_month_only():
    """Point-in-time: a billables figure describes the day it was run."""
    split = {"EastKing": {"target": 129.0, "non_target": 28.0, "unbanded": 13.0}}

    out = cc.compile_billables(split, "Jul")

    assert out["hosp_bills_target"]["EastKing"]["Jul"] == 129.0
    assert out["bills_unbanded"]["EastKing"]["Jul"] == 13.0
    # a snapshot describes ONE month; the other cells stay zero, not repeated
    assert out["hosp_bills_target"]["EastKing"]["Jun"] == 0


def test_drops_export_scope_guard_fires_at_the_fiscal_year_rollover():
    """The drops export has NO per-row date, so code cannot scope it.

    Its only scope is the report's StatusDate parameter, which a human must
    move each October. This guard makes forgetting that a loud failure instead
    of two fiscal years quietly stacking in one bill-month grid.
    """
    cc.assert_drops_export_scope(export_fy_start=2025, period_fy_start=2025)

    with pytest.raises(ValueError, match="StatusDate parameter"):
        cc.assert_drops_export_scope(export_fy_start=2025, period_fy_start=2026)


def test_size_less_members_are_counted_non_target_so_totals_stay_whole():
    """Jennifer's published billables INCLUDE the members with no recorded size.

    Experiment (2026-07-27): her Hospitality row runs 2,090–2,151 across the
    year. Crystal's FTE report totals 2,143 with its 'Others' bucket included
    and 2,036 without — below every month she ever published. So those members
    are billable members; they simply have no size on file.

    They therefore cannot be dropped, and they cannot be Target either: Target
    means clearing a size threshold (10 FTE, 40 rooms) and a member with no
    size on file has not been shown to clear it. Non-Target keeps the total
    whole and is the only claim the data supports.
    """
    rows = [_drop("known", "Pierce", 4, 1070.0), _drop("sizeless", "Pierce", 4, 510.0)]

    out = compile_drops(rows, band_by_name({"known": T}))   # "sizeless" → Unknown

    assert out["drops_target"]["Pierce"]["Apr"] == 1
    assert out["drops_non_target"]["Pierce"]["Apr"] == 1
    assert out["drops_revenue_non_target"]["Pierce"]["Apr"] == 510.0


def test_billables_fold_the_crms_own_others_bucket_into_non_target():
    """Same rule, same reason — and the territory total must survive it."""
    split = {"EastKing": {"target": 129.0, "non_target": 28.0, "unbanded": 13.0}}

    out = cc.compile_billables(split, "Jul")

    assert out["hosp_bills_target"]["EastKing"]["Jul"] == 129.0
    assert out["hosp_bills_non_target"]["EastKing"]["Jul"] == 41.0     # 28 + 13
    assert (out["hosp_bills_target"]["EastKing"]["Jul"]
            + out["hosp_bills_non_target"]["EastKing"]["Jul"]) == 170.0


def test_grids_are_dense_across_the_fiscal_year():
    """Sparse grids break every consumer that walks the year.

    The engine raised KeyError('Feb') on the first month with no drops. Zero
    is also the honest value: no drops in February means zero, not unknown.
    """
    out = compile_drops([_drop("A", "Pierce", 4, 1070.0)], band_by_name({"A": T}))

    assert set(out["drops_target"]["Pierce"]) == set(cc.FY_MONTHS)
    assert out["drops_target"]["Pierce"]["Apr"] == 1
    assert out["drops_target"]["Pierce"]["Feb"] == 0


def test_grids_cover_every_canonical_territory_not_just_the_populated_ones():
    """Sparse TERRITORIES break consumers exactly like sparse months did.

    The engine raised KeyError('Feb') first, then KeyError('Majors/NRA') — a
    territory with no rows in the export still has to exist in the grid.
    """
    from reports.membership_performance_tracker.logic.model import TERRITORY_ORDER

    out = compile_drops([_drop("A", "Pierce", 4, 1070.0)], band_by_name({"A": T}))

    assert set(TERRITORY_ORDER) <= set(out["drops_target"])
    assert out["drops_target"]["Majors/NRA"]["Apr"] == 0
