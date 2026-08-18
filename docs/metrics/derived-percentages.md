# Derived values — the percentages, ratios, YTD and status flags

**Family:** cross-cutting (Layers 1–3) · **Status:** ⚪ derived — no source of their own
**Last updated:** 2026-07-29 · **Sources read:** `logic/engine.py` · THE-PLAN · DECISIONS · STATE

Not catalog rows in their own right — these are computed **from** the metric
rows after every source has been read. They appear on the report as
percentages, YTD figures, status flags and trends.

**They have no source to reconcile against.** If one is wrong, either its inputs
are wrong or the formula is — never the data.

---

## The four-layer order (`engine.run()`)

Layers must run in this sequence; each depends on the one before.

| Layer | What | Examples |
|---|---|---|
| **L0** | Query SLX · parse external files | billables, retention, new members, goals, penetration |
| **L1** | **Elementwise** derived — one cell from cells in the same (territory, month) | `combined_bills`, `attainment_pct`, `retention_pct`, `retention_str`, `pen_pct` |
| **L2** | **Aggregations** | YTD sums, statewide sums, `avg_retention`, `statewide_avg_pen` |
| **L3** | **Season-level** | attainment, status flags, month-over-month, trend, $/member |

**Why the order matters:** a cache replay recomputes **all three derived layers**
from the cached raw counts, so a fix to an L2 formula (say `avg_retention`) takes
effect **without an 80-minute re-pull**. Every raw input those layers need is in
the cache. This is only true because the layers are pure functions of L0.

**The overlay runs between L0 and L1** — Crystal's two families replace SData's
*before* the derived layers, so percentages are computed on the numbers that will
actually be published.

---

## L1 rules worth knowing

### `combined_bills` = hospitality + allied, but null-tolerant

If either side is missing, the other is used alone; only when **both** are
missing is the cell `None`. So a combined figure can be quietly hospitality-only.

### `retention_pct` — Majors/NRA is hard-excluded

`NO_RETENTION_TERRITORY = "Majors/NRA"` renders as **`—`**, not 0% and not blank.
NRA chains pay national WRA, so there is no local renewal to measure.

### `attainment_pct` returns `None` where there is no goal

The three zero-goal territories (**NorthKing · Pierce · Spokane-NE**) are
commissioned on total revenue rather than graded to a monthly target, so
`_attainment()` returns `None` and the cell renders **blank** — correct, not a
gap. See [`goals.md`](goals.md).

### Penetration combined — a missing segment contributes zero, it does not veto

**Fixed 2026-07-16.** A territory with no lodging segment previously produced a
**blank** combined ratio; the handmade report shows restaurant-only (Majors/NRA
at 87.5%). A missing segment now contributes zero instead of vetoing the whole
value.

---

## L2 — `avg_retention` is Σpaid ÷ Σbilled, not a mean of percentages

Averaging the monthly percentages would weight a 3-member month equally with a
300-member month. The cached raw counts make the correct form available, which is
why cache replay recomputes rather than reusing stored averages.

---

## ⚠️ Known-unverified derived values

From the completeness audit, still listed among the **~25 candidate gaps**:

- **statewide-penetration aggregation**
- **negative-drop credits**
- **combined-% summing**

These have never been checked against anything. They are derived, so an error
here is invisible to every source comparison — the inputs would all reconcile
while the published percentage is wrong.

**The 3-year trend sections (T6/T7/N5/N6) are empty** — the prior-FY backfill
never ran (~80 min per year).

---

## The failure mode this layer is prone to

Derived cells are where **display bugs hide from numeric gates.**

The clearest case: the **entire TM-Snohomish sheet showed East King's numbers**
(2026-07-16). The sheet had been cloned from TM - E KING and its **376 formula
cells kept `"East King"`** as the territory criterion. Every numeric gate passed
— **the data layer was correct and the display wiring lied.** It was caught by
eye, on a stale file.

The permanent guard is `scripts/wiring_check.py`, which validates territory,
month and metric-name criteria against sheet identity across **8,610 formulas**
(0 mismatches after the fix). One of the five things THE-PLAN's gate list
requires is *"the workbook must recalculate with zero formula errors."*

> **Rule 5, THE-PLAN Part 7:** *"A green pipeline is not a working product. Open
> the workbook. If a month shows members joining and $0 revenue, the run failed
> regardless of exit code."*
