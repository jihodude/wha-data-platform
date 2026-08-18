"""
test_mapper_current_month.py — billables emit current_month only (Bug 1, 2026-06-05).

Penetration counts/% were already moved to current-month-only in commit 4e5dcec
(via kind="t" and kind="derived" + snapshot_month). This file pins the remaining
half: hosp_bills_target / hosp_bills_non_target / allied_bills / nra_bills must
also emit ONLY for the snapshot month, regardless of whether the engine writes
prior months in the future.

Why this matters: even though _emit_tm_rows already skips None values, the engine
guarantee is only "current_month is populated" — nothing prevents a future
backfill or accidental engine change from writing 0 / non-None values into prior
months. The "tm" path would then emit them, the trend sheet would surface them as
real data, and exec readers would interpret them as billables history. Pinning
the mapper to current_month only makes the contract explicit: trend sheet shows
the snapshot, not whatever the engine happened to write.

See reports/membership_performance_tracker/mapper.py — kind="tm_current".
"""

from reports.membership_performance_tracker.mapper import TrackerV4Mapper
from reports.membership_performance_tracker.logic.model import empty_scoreboard


# Match the writer's FY ordering — Oct starts the WHA fiscal year (Oct 1 → Sep 30)
FY_MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
             "Apr", "May", "Jun", "Jul", "Aug", "Sep"]


BILLABLES_METRICS = {
    "Billables - Hospitality Target (#)",
    "Billables - Hospitality Non-Target (#)",
    "Billables - Allied (#)",
    # "Billables - NRA (#)" removed 2026-07-17 (meaning audit) — folded into Majors/NRA.
}


def _fill_all_months_with(data, field_name, value):
    """Force-populate a [t][m] field for EVERY territory and month — simulates
    a future engine that backfills prior months. The mapper must still emit
    only current_month."""
    field = getattr(data, field_name)
    for terr in field:
        for m in FY_MONTHS:
            field[terr][m] = value


def test_billables_emit_only_for_current_month():
    """Even if every month is populated, billables rows only land for current_month."""
    data = empty_scoreboard(FY_MONTHS)
    _fill_all_months_with(data, "hosp_bills_target",     7)
    _fill_all_months_with(data, "hosp_bills_non_target", 3)
    _fill_all_months_with(data, "allied_bills",          5)

    mapper = TrackerV4Mapper(fiscal_year_start=2025, current_month="Mar")
    rows = mapper.map(data)

    bill_rows = [r for r in rows if r["metric"] in BILLABLES_METRICS]
    assert bill_rows, "expected at least one billables row to be emitted"

    months_emitted = {r["month"] for r in bill_rows}
    assert months_emitted == {"Mar"}, (
        f"billables emitted for months {months_emitted}; expected only {{'Mar'}}"
    )


def test_billables_skipped_when_current_month_value_is_none():
    """If the engine never populated current_month for a territory, no row emits
    for that (territory, billables) pair — same None-skip behavior as before."""
    data = empty_scoreboard(FY_MONTHS)
    # Only populate one territory's current_month; others stay None
    data.hosp_bills_target["Pierce"]["Mar"] = 42

    mapper = TrackerV4Mapper(fiscal_year_start=2025, current_month="Mar")
    rows = mapper.map(data)

    hosp_t_rows = [r for r in rows
                   if r["metric"] == "Billables - Hospitality Target (#)"]
    assert len(hosp_t_rows) == 1
    assert hosp_t_rows[0]["territory"] == "Pierce"
    assert hosp_t_rows[0]["month"]     == "Mar"
    assert hosp_t_rows[0]["value"]     == 42


def test_non_billables_tm_metrics_still_emit_all_populated_months():
    """Regression guard: the new 'tm_current' kind must not affect revenue,
    retention, drops, etc. Those still need to emit every populated month."""
    data = empty_scoreboard(FY_MONTHS)
    _fill_all_months_with(data, "revenue_target",     1000.0)
    _fill_all_months_with(data, "drops_target",       4)
    _fill_all_months_with(data, "ret_paid_target",    50)

    mapper = TrackerV4Mapper(fiscal_year_start=2025, current_month="Mar")
    rows = mapper.map(data)

    rev_months   = {r["month"] for r in rows
                    if r["metric"] == "New Sales Revenue - Target ($)"}
    drop_months  = {r["month"] for r in rows
                    if r["metric"] == "Drops - Target (#)"}
    ret_months   = {r["month"] for r in rows
                    if r["metric"] == "Members Retained - Target (#)"}

    # Every fiscal month should appear for these "tm" fields
    expected_all_months = {"Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
                           "Apr", "May", "Jun", "Jul", "Aug", "Sep"}
    assert rev_months  == expected_all_months
    assert drop_months == expected_all_months
    assert ret_months  == expected_all_months


def test_billables_emit_at_most_one_month_even_when_current_month_unset():
    """Hardens the invariant: regardless of current_month being set, billables
    must NEVER fan out across multiple months. The exact fallback month is an
    implementation detail of snapshot_month; what matters is that the trend
    sheet only ever sees one billables row per (territory, metric) pair."""
    data = empty_scoreboard(FY_MONTHS)
    _fill_all_months_with(data, "hosp_bills_target", 7)

    mapper = TrackerV4Mapper(fiscal_year_start=2025, current_month=None)
    rows = mapper.map(data)

    hosp_t_rows = [r for r in rows
                   if r["metric"] == "Billables - Hospitality Target (#)"]
    months_emitted = {r["month"] for r in hosp_t_rows}
    assert len(months_emitted) <= 1, (
        f"billables emitted for {months_emitted}; should be at most one month"
    )
