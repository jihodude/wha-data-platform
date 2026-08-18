"""crystal_compile.py — parsed Crystal rows → the two cache families Crystal owns.

SCOPE (narrowed 2026-07-27 after the hybrid was decided from evidence — see
docs/THE-PLAN.md Part 3). Crystal owns exactly two families, because those are
the two where it beat SData:

    · BILLABLES  — its FTE report is Jennifer's own statewide figure (2,143)
                   with native FTE bands, so no size inference of ours
    · DROPS      — the list, the dues and 19 real status reasons, with none of
                   the billable-gate / closure-union / status-flip machinery
                   SData needed (and which hid two bugs until 7/27)

Everything else — new members, revenue, BOB, retention, penetration — stays on
the SData ledger, which is the only source that can answer a past month.
Compilers for those families lived here briefly and were deleted; recover them
from git before 2026-07-27 if that decision is ever revisited.


This is the layer between "we parsed the exports" and "the workbook has
numbers". It does five mechanical things and no business reasoning:

    1. take the parsed rows,
    2. scope them (ledger → the fiscal year by each row's own date;
       snapshot → the period's own archived export),
    3. band each row Target / Non-Target,
    4. bucket by territory × month, summing counts and dollars,
    5. write the cache field shapes the mapper already expects.

Because step 5 keeps the existing shapes, the mapper, writer, template and
SharePoint publish are untouched — the cache is the contract.

WHAT THIS DELIBERATELY DOES NOT DO. No first-payment anchoring, no
count⟺dollar invariant, no valuation cascade, no renewal screening. That
composition logic is what the pivot retires. This layer transcribes and
buckets, so that when a number is questioned the answer is "that is what the
report says" — with the archived file to show.

THE MONTH AXIS. Every membership metric now lands on the same bill-month grid:

    retention  →  "up for renewal in BM x" / "retained in BM x"
    drops      →  "N members are no longer billed in BM x"  (Jiho, 2026-07-27)
    new sales  →  the enrolment month the report itself reports

Drops carry no per-row date — only a bill month — and the ruled definition
makes that the correct basis rather than a fallback: the metric is about which
billing CYCLE lost members, not the day somebody quit.
"""
from collections import defaultdict
from datetime import date
from typing import Callable, Dict, Iterable, List, Optional

from reports.membership_performance_tracker.logic import target as target_logic

# Bill month 1–12 are calendar months (verified: the export's Red Twig row
# carries enroll date 2026-06-19 alongside Bill Month 6).
MONTH_ABB = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
             7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}

# The fiscal year runs Oct → Sep, and the tracker's grids are in that order.
FY_MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
             "Apr", "May", "Jun", "Jul", "Aug", "Sep"]

Bander = Callable[[object], str]


def _grid() -> Dict[str, Dict[str, float]]:
    return defaultdict(lambda: defaultdict(float))


def _plain(grid) -> Dict[str, Dict[str, float]]:
    """defaultdicts → plain dicts, DENSE across territories AND months.

    Every canonical territory carries all twelve months, zero-filled. Sparse
    grids read fine in JSON and break every consumer that walks the year or
    the territory list — the engine raised KeyError('Feb'), then
    KeyError('Majors/NRA'). A zero is also the honest value: no drops in
    February means zero drops, not unknown. Territories the exports mention
    but the report does not list (Retro Coordinator, EF School) are carried
    through rather than dropped, so nothing disappears silently.
    """
    from reports.membership_performance_tracker.logic.model import TERRITORY_ORDER

    territories = list(TERRITORY_ORDER) + [t for t in grid if t not in TERRITORY_ORDER]
    return {t: {m: float((grid.get(t) or {}).get(m, 0.0)) for m in FY_MONTHS}
            for t in territories}


def _suffix(band: str) -> Optional[str]:
    """Which band a row is counted in. Size-less members count Non-Target.

    Established by experiment against Jennifer's published editions
    (2026-07-27): her Hospitality billables run 2,090–2,151 across the year,
    and Crystal's FTE report totals 2,143 WITH its unbanded 'Others' bucket
    against 2,036 without — below every month she published. Those members are
    billable members with no size on file.

    So they cannot be dropped from the count, and they cannot be Target:
    Target means clearing a threshold (10 FTE, 40 rooms), and a member with no
    size on file has not been shown to clear it. Counting them Non-Target
    keeps every total whole and claims only what the data supports.
    `crystal_banding.warn_on_unknowns` still reports how many there were.
    """
    if band == target_logic.TARGET:
        return "target"
    return "non_target"


def assert_drops_export_scope(export_fy_start: int, period_fy_start: int) -> None:
    """The drops export cannot be scoped in code — only by its report parameter.

    Its rows carry a bill month and no date, so nothing in the file says which
    fiscal year a drop belongs to; the only scope is the StatusDate range set
    in the CRM. That range must be moved to the new FY every October, and this
    turns forgetting it into a loud failure rather than two fiscal years
    quietly stacking in one twelve-cell grid.
    """
    if export_fy_start != period_fy_start:
        raise ValueError(
            f"Drops export is scoped to FY{export_fy_start}-{str(export_fy_start + 1)[2:]} but "
            f"this run is FY{period_fy_start}-{str(period_fy_start + 1)[2:]}. Move the "
            f"StatusDate parameter on the three drops schedules to "
            f"10/1/{period_fy_start}, then update the configured export FY. Until both "
            f"match, the export holds more than one fiscal year and its rows cannot be "
            f"told apart.")


# DELETED 2026-08-14: `compile_drops` and `compile_drops_by_reason` lived here
# as a THIRD implementation of the drops loop. They knew none of the rulings —
# no RRO exclusion, no admin reasons, no hygiene amendment, no event axis, and
# they never received the 2026-08-14 allied change — yet their tests passed, so
# they read as a working path. Nothing in production imported them (only tests
# did), and leaving a superseded rule-set lying next to the real one is exactly
# the trap the single-path build exists to remove. The rules live in
# `crystal_feed.classify_drop`; the grids come from `crystal_feed.aggregate_drops`.
# The grid-shape invariants those tests protected are now asserted against that
# real path in test_crystal_compile.py.


def compile_billables(fte_split: Dict[str, Dict[str, float]],
                      snapshot_month: str) -> Dict[str, Dict]:
    """Billables from the CRM's own FTE bands — a SNAPSHOT, one month only.

    Target = 10 FTE and up, straight from the report. The CRM's unbanded
    'Others' members count Non-Target so the territory total matches what
    Jennifer published (2,143 statewide includes them; 2,036 without is below
    every month she ever reported). Their count is retained in bills_unbanded
    for diagnosis — it is not a row on the report.
    """
    target, non_target, unbanded = _grid(), _grid(), _grid()
    for territory, cell in fte_split.items():
        target[territory][snapshot_month] = cell.get("target", 0.0)
        # The CRM's own 'Others' bucket folds into Non-Target for the same
        # reason as any size-less member — see _suffix. Kept separately in
        # bills_unbanded so the size-less count stays visible for diagnosis,
        # but it is NOT a reported row.
        non_target[territory][snapshot_month] = cell.get("non_target", 0.0) + cell.get("unbanded", 0.0)
        unbanded[territory][snapshot_month] = cell.get("unbanded", 0.0)
    return {
        "hosp_bills_target": _plain(target),
        "hosp_bills_non_target": _plain(non_target),
        "bills_unbanded": _plain(unbanded),
    }

