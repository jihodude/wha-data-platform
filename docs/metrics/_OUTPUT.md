# From cache to workbook — how a metric reaches the page

**Sources read:** `mapper.py` · `writer.py` · `history.py` (via ARCHITECTURE-MAP) · ISSUELOG

The metric files say what a number *means*. This says how it gets onto the sheet
— because several bugs lived here, invisible to every numeric check.

```
scoreboard_YYYY-MM.json  ──►  mapper.py  ──►  writer.py  ──►  template.xlsx  ──►  SharePoint
                                   │
                         long-form rows:
                    (Year · Month · Territory · Metric · Value)
```

---

## The shape: one row per (Year, Month, Territory, Metric)

The workbook's `Data - Monthly Metrics` sheet is a **long-form store**, not a
grid. Everything visible — the Summary Dashboard, the 11 TM sheets, the Ref
sheets — is **Excel formulas reading from three data sheets**.

**We never write to the display sheets.** Touching them would clobber formatting
and formulas.

| Sheet | Written how | Header row |
|---|---|---|
| `Data - Monthly Metrics` | **UPSERT** — a row matching the same (Year, Month, Territory, Metric) is overwritten in place; new rows append | 4 (data from 5) |
| `Data - Drops` | **REPLACE** — cleared and rewritten every run | 3 (data from 4) |
| `Data - Closed Businesses` | **REPLACE** | 3 (data from 4) |

**Why upsert matters:** re-running with refreshed SLX data updates existing rows;
historical backfills for other years append without conflict; a partial run
touches only the rows it owns.

**The template is never modified** — every write goes to a copy at the output
path.

---

## Three naming/shape rules that silently break things

### 1. Metric strings must not drift from the template

Every key in `METRIC_FIELD_MAP` matches an **exact** string in the template's
`Ref - Metrics` sheet, column A. **A mismatch means a broken lookup in the TM
sheet formulas** — the cell resolves to nothing, and no numeric gate notices
because the data row exists and is correct.

### 2. Territory names are translated at the boundary

Internal canonical → v4 display: `EastKing` → **East King**, `SouthKing` →
**South King**, `NorthKing` → **North King**. Others pass through.
`CANONICAL_TO_TRACKER` (in `drops.py`) is the single source of truth.

*This is why the workbook shows "East King" while every doc and query says
`EastKing`.*

### 3. Percentages are stored as **decimals**

`0.917`, not `91.7` — the template applies the % format. Storing the wrong one
is off by 100×, which looks like a data error rather than a units error.

---

## Year resolution

Oct/Nov/Dec belong to `fiscal_year_start`; Jan–Sep to `fiscal_year_start + 1`.
The tracker stores multiple calendar years, so the mapper takes a `year`
parameter that can be overridden for historical backfills.

---

## Point-in-time metrics are written for ONE month only

**Penetration and billables are snapshots.** The engine queries them once, for
`current_month`; prior months have no data.

**The mapper writes them only for `current_month`** — deliberately — so the trend
sheet shows the actual snapshot month rather than repeating one value (or zero)
across every column.

**Historical months are filled by a different path:** `history.py` reads *each
prior month's own stored snapshot*, so trend lines show real captured history.
Months never photographed **stay blank — honestly.**

> This is the mechanism behind the snapshot/ledger split described in
> [`_SHARED.md`](_SHARED.md). It is also why the 3-year trend sections
> (T6/T7/N5/N6) are empty: the prior-FY backfill never ran (~80 min per year).

---

## ⚠️ This layer is where display bugs hide

Two of the project's worst bugs lived here, and **both passed every numeric
gate** because the data was correct and the wiring lied.

### The Snohomish sheet showed East King's numbers (2026-07-16)

The sheet had been **cloned from TM - E KING** during template construction, and
its **376 formula cells kept `"East King"`** as the territory criterion.

**Caught by Jiho's eyeball on a stale file.** Now guarded permanently by
`scripts/wiring_check.py`, which validates territory, month and metric-name
criteria against sheet identity across **8,610 formulas** (0 mismatches after the
fix).

### The console served a fresh-looking March file (2026-07-17)

Three faults compounding: the period defaulted to `2026-03` for any env-less
process; each console session re-downloaded and rewrote the local cache, giving
the March file **today's mtime**; and the freshness badge read **file mtime, not
`_meta.saved_at`**. Result: *"updated 30m ago"* on June-era March data.

**Caught by Jiho downloading from the console.**

> **THE-PLAN rule 5:** *"A green pipeline is not a working product. Open the
> workbook. If a month shows members joining and $0 revenue, the run failed
> regardless of exit code."*

---

## Operational constraints when handling the workbook

*Not bugs — properties of SharePoint and Excel that will waste a day if unknown.*

- **SharePoint re-packs Office files server-side**, so byte counts change on a
  round trip (16 KB → 25 KB). The re-packed file is still valid.
  **Verify SharePoint files by PARSING them, never by byte-equality.**
- **Open-in-place locks the file** → programmatic writes get **HTTP 423**. The
  client retries transient locks for up to 14 s, but a genuinely open file must
  be closed by hand. *(Hit live on 2026-07-29 — a publish failed with 423 while
  the workbook was open.)*
- **The rule for staff: download, don't open-in-place.**
- **Negative drop revenue** — ✅ CLOSED 2026-07-29: not a team question. Our own
  ratified valuation rule ("credits never value a drop") already decides it; the
  negative cells come from the pre-rule detail path, which retires with it.

---

## Outstanding work in this layer

| Item | State |
|---|---|
| **B4** — Crystal's 19 drop reasons replace our 5 invented buckets *(retired 2026-07-29 — all 19 Crystal reasons wire straight through)* | ❌ mapper + template. **LOCKED 2026-07-29 (Jiho): direct wire, no re-bucketing** |
| **B5** — Closed Businesses sheet | **REVISED 2026-07-29 PM (Jiho): KEEP if the old MPR has it** — *"as long as it doesn't make anything insanely complicated."* It doesn't: the drops export's own `Closed` status group can feed it. ⚠️ Unverified whether the membership administrator's workbook actually has the section — the official SOP's four-source list doesn't mention it (nor drops at all). **Check her workbook before the B4 template surgery** |
| **M7** — the engine still populates `closed_*` fields and the template still has the sheet (396 cells/metric) | ❌ needs B5 |
| 3-year trend backfill (T6/T7/N5/N6) | ❌ ~80 min per prior FY |
| Formula-recalc scan (zero `#REF!`/`#DIV/0!`…) | listed in the SOP's open items; needs LibreOffice or an Excel-open step |
