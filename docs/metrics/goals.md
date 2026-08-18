# Goal — New Sales Revenue ($) / New Members (#) / Retention %

**Family:** Goals · **Engine fields:** `goal`, `goal_members`, `goal_retention`
**Status:** ⚪ pass-through — typed by admin, read as-is, no computation to verify
**Last updated:** 2026-07-29 · **Sources read:** REFERENCE · DECISIONS (full) · STATE · PROBLEMS · `logic/engine.py` · `logic/retention.py`

*Covers all three goal rows — one source, one mechanism.*

---

## Source

**`admin_inputs.xlsx`**, synced from SharePoint (`Inputs/`) before every
run. The report reads it verbatim; there is nothing to compute and therefore
nothing to reconcile against SLX.

**Entered only by Jiho or the administrator** (ratified 2026-07-20).

**Under the Crystal pivot: BOB and goals stay admin inputs** — goals are not
sourced from any Crystal report.

---

## Graded on Target / Non-Target

> **2026-06-17 · department leadership:** goals are graded against **Target / Non-Target**, not
> Hospitality / Allied — *"so reps focus on harder Target accounts."*
> **Supersedes** the goals workbook's H/A default.

department leadership is the decision-maker here. The instruction allowed for the admin sheet
holding both if cheap, **but T/NT is the graded one**.

---

## The workbook was slimmed to goals only (2026-07-20)

Jiho reviewed the SharePoint tabs and ruled: *"the penetration sheets, sales
activities, benefit reviews, needs to go… delete those, and either delete or keep
yoy target, and modify the export summary."*

**The workbook now contains exactly:** README · Sales Goals · Member Goals ·
Retention Goal · Penetration Goal · **Change Log** (audit sheet).

Everything else was deleted, with evidence per sheet:

| Deleted | Why |
|---|---|
| **Export Summary** | An Apple-Numbers export receipt ("This document was exported from Numbers" + a sheet-name mapping table). Never read by any code |
| **Penetration Market / Active** | Counts have come from SLX since 2026-06-05 |
| **Sales Activities** | Ingestion removed earlier — no output consumer |
| **YoY Targets** | Its only calculation (`latest_vs_target`) had **zero output consumers** — dead end to end. Deleted with its parser, model and engine plumbing |
| **Benefit Reviews** | Real manual tracking (the previous analyst/a member-success specialist/a member-success specialist) but **off the report since 7/13**, so collecting them fed nothing. Retired fully: parser, model field, engine ingest, writer plumbing, template sheet, and the Sep→Oct migration utility. **Reversal path: git history** |

`scripts/rebuild_admin_inputs.py` regenerates the clean workbook
value-preservingly.

---

## The new-member goal rule (SOURCED — the membership administrator's call 2026-07-22 [J 57:44–58:20])

The transcript's own heading is *"off-topic but ratified **(for the MPR)**"*:

| Territory penetration | New-member goal |
|---|---|
| **Under 75%** | **4 new members / month** |
| **75% and above** | **No goal** — just replace losses |

**Vacation exception:** 5+ consecutive vacation days in a month → the goal drops
**25%** (4 → 3), **and the revenue goal drops the same way.**

**All manual today.**

> This is the rule *behind* the zero-goal territories below — they are not an
> arbitrary exemption, they are the 75%+ band. It also means the goal is
> **derivable from penetration**, which the report already computes, rather than
> being purely a typed input.

**Not implemented.** The vacation adjustment in particular has no input surface —
nothing records who took 5+ consecutive days.

---

## Zero-goal territories are intentional

**NorthKing · Pierce · Spokane-NE have null goals on purpose** — they are
high-penetration territories whose reps are **commissioned on total revenue**
rather than graded to a monthly target.

`_attainment()` returns `None` → the % cell renders **blank**. That is correct
behaviour, **not a gap**. PROBLEMS lists "fix the null territories" under P2;
that phrasing is misleading — the nulls are the design.

---

## Retention goal default

`DEFAULT_RETENTION_GOAL = 0.92` (`logic/retention.py`).

`retention_goal_for(territory)` returns the territory's admin Retention Goal if
set — **constant across months per territory** — otherwise the 92% default. The
92% status threshold is a carried-forward banked decision (pre-2026-06-17).

**Loading mechanism** (`engine._load_admin_inputs`): a per-FY block supplies
`goal_retention_default` applied to every (territory, month), plus
`goal_retention_overrides[territory]` as a static override across all months.

---

## The month-axis bug — fixed, and the lesson stuck

**2026-07-14:** goals and "% to Goal" were shifted **one month late on every TM
sheet**.

**Root cause:** the live `admin_inputs.xlsx` still carried the legacy **Sep-first
header** on the Sales Goals and Member Goals sheets — the 6/28 axis fix had
migrated only the Benefit Reviews sheet — while the parser mapped columns
**positionally**, assuming Oct-first. So the report's month M showed the file's
month **M−1**. The Southwest screenshot showing January = 2,400 was actually the
file's December.

**The file's values were RIGHT** — its June column matched the administrator's handmade sheet
exactly.

**Fix (TDD):** `_parse_territory_month_grid` now maps columns **by HEADER NAME**,
layout-proof for both legacy and regenerated sheets. **Re-render-only — no pull
needed.**

**Bonus finding:** Member Goals **do** exist in `admin_inputs` — the earlier "no
member-count goals anywhere" note was wrong for this source.

**⚠️ Related standing rule:** the writer's `BENEFIT_MONTH_ORDER` is calendar
Jan–Dec **on purpose** and name-keyed — **do NOT "fix" it to Oct-first**; that
would misplace every value. It survives the Benefit Reviews retirement as a
guard on the goals grids.

---

## Verification

**One of the five P1 ground-truth gates: Goals vs the workbook.** That gate has
not been run since the period engine landed — it needs the fresh live run that
is P1's master blocker.

Because goals are a pass-through, "verification" means *the number in the cell
equals the number in the workbook* — an axis and parsing check, not an accuracy
check. The 7/14 bug was exactly that class, which is why the round-trip
regression test exists.

---

## Open items

| # | Item | Owner |
|---|---|---|
| 1 | **Goals fill-in into the T/NT structure** — load the 25-26 workbook numbers into the now-T/NT goals (PROBLEMS P2, issue 11) | Jiho / the administrator |
| 2 | Run the Goals gate on a fresh live pull | — |
| 3 | PROBLEMS' "fix the null territories" wording implies a bug where there is a decision — the three zero-goal territories are intentional | doc fix |
