# `docs/metrics/` — one file per catalog row

[`../METRIC-CATALOG.md`](../METRIC-CATALOG.md) is the **source of truth**. Every
row in it names a metric and links here from its **Notes** cell (📄).

## Why this exists

Before this, finding what was known about a metric meant searching every doc with
no tag — and the same question got re-derived, or answered two different ways in
two places. The catalog forces the tag: **each fact has exactly one home.**

## Rules

1. **A fact lives in the file for the metric it governs.** If it governs no single
   metric, it goes in [`_SHARED.md`](_SHARED.md) (our own rules) or
   [`_EXTERNAL.md`](_EXTERNAL.md) (something SLX or Crystal does to us).
   **External defects are tagged with the metrics they affect** — that is the
   whole point: "what breaks retention?" must be answerable without a search.
2. **Contradictions are KEPT, both sides, marked ⚠️.** Never silently resolved.
   Two ratified rulings that disagree are a finding, not a mess to tidy.
3. **Duplicates are removed** — two copies of one fact carry no more meaning than
   one, and drift apart on the first edit.
4. **Sibling rows share a file.** Target and Non-Target variants are one
   definition with a band filter; both rows point at the same document.
5. **Nothing is judged for being right or wrong on the way in.** Capture first;
   decide in the catalog afterwards.

## Files

| File | Covers |
|---|---|
| [`_CONVENTIONS.md`](_CONVENTIONS.md) | **How to change a metric and how to write about one** — the sourcing gate, the verification bar, operating rules, and per-audience writing corrections |
| [`_STALE.md`](_STALE.md) | **The doc-cleanup worklist** — every place a superseded rule is still written down, sorted by blast radius. 16 items, 3 critical |
| [`_EXTERNAL.md`](_EXTERNAL.md) | **SLX and Crystal defects**, each tagged to the metrics it hits — platform behaviour (15) · data-quality records (12) · CRM report semantics (12) — plus **every open question consolidated by owner** (24) |
| [`_SHARED.md`](_SHARED.md) | Fiscal calendar · billing cycle · ITD ordering · T/NT classification · Majors/NRA · territory map · SData gotchas · consolidations · Benefit Reviews · the truth hierarchy · precedence rules · the Crystal pivot · CAPTURE AND FREEZE · the Oct 1 deadline · payAllocationViews |
| [`retention-members-up-for-renewal-target.md`](retention-members-up-for-renewal-target.md) | Retention member counts — the cohort, both halves |
| [`retention-revenue.md`](retention-revenue.md) | Retention dollars — netting, write-offs, the Unknown bucket |
| [`billables-hospitality-target.md`](billables-hospitality-target.md) | Billables — all three rows |
| [`drops-target-count.md`](drops-target-count.md) | Drops — counts, dollars, the 19 reasons |
| [`new-members-target.md`](new-members-target.md) | New member counts |
| [`new-sales-revenue-target.md`](new-sales-revenue-target.md) | New sales revenue |
| [`bob-target-revenue.md`](bob-target-revenue.md) | BOB — and the two-concepts-one-acronym problem |
| [`penetration-target-lodging.md`](penetration-target-lodging.md) | Penetration — Target and Non-Target, both segments |
| [`goals.md`](goals.md) | All three goal rows |
| [`_CAPTURE.md`](_CAPTURE.md) | **How Crystal exports reach us** — the attachment surface, the 10 schedules, the gates, and the two dated obligations (2026-10-01 drops window · 2030-12-31 schedule expiry) |
| [`_OUTPUT.md`](_OUTPUT.md) | **Cache → mapper → writer → workbook** — the long-form row shape, upsert vs replace, the three naming rules that silently break lookups, and why this layer hides bugs from numeric gates |
| [`derived-percentages.md`](derived-percentages.md) | The L1/L2/L3 derived layer — percentages, YTD, status flags. No source of their own, and where display bugs hide from numeric gates |

## Audiences

| Doc | For | Contains |
|---|---|---|
| [`_EXTERNAL.md`](_EXTERNAL.md) | us | Every external defect with field names, entities and effect markers |
| *the stakeholder question list (archive repo)* | **the membership administrator** | The same questions in plain terms — no SData, no entities, no code. Only what she can check in SLX or a report she runs, each with a named member |

The two must be kept in step: when an external entry is answered, close it in
both.

## Source-reading status

`_SHARED.md` carries a **"Sources read in full so far"** line. That is the
bookmark — it says which documents have been genuinely read (not grepped) and
distributed into these files.

**Read in full:** `REFERENCE.md` · `DECISIONS.md` (all 533 lines) ·
`RECONCILIATION.md` · `STATE.md` · `PROBLEMS.md` · `THE-PLAN.md` (all 7 parts) ·
`ROADMAP-TO-DONE.md` · `ARCHITECTURE-MAP.md` · `SOP.md` · `ISSUELOG.md` ·
code: `target.py`, `billables.py`, `revenue.py`, `retention.py`, `drops.py`,
`slx/client.py`, `engine.py`

**Not yet:** `ARCHITECTURE.md` · `BACKLOG.md` · ~27 of the `docs/handoff/` files
(the metric-relevant ones are done: penetration evidence, drops edge cases,
retention gap, stakeholder questions) · the memory files.

### Corrections this exercise has produced so far

| Was recorded as | Actually |
|---|---|
| Target hotels = 40+ rooms **(41+ is superseded — the administrator 7/21, ruled 7/29)**; the CRM's 40 is their defect | **40+**, ratified 7/21 — **our docs were stale, not their report** |
| Rejoins: open question for the membership administrator | Ruled twice, in opposite directions — now **unresolved**, and the pivot's basis for it is gone |
| Drops: never validated | **Validated 7/27 and failed** — 155 vs 204, −24%, dollars at 67% |
| BOB: revenue for Black-Owned Business members | The rows compute the **"BOB 2-Year" billing promo** — *"same acronym, unrelated concept"* |
| Corporate/Grocery classification: open | **Closed 7/13** as orthogonal-and-both-correct |
| New members on enrollment basis (the pivot) | **Paid basis** — THE-PLAN superseded the pivot the same day |
| Seller credit: ratified but unimplemented | **Shipped 7/16** via `AccountExtension.Originator`, verified 3/3 |
| Billables — Allied: ratified, sourced from Crystal | **SData**, and **not** ratified — SData 162 · Crystal 145 · the administrator 164 |

### Precedence discovered while reading — important

`THE-PLAN.md` (2026-07-27, written **after** the Crystal pivot failed) declares
itself the winner over *"every earlier plan, pivot doc and reconciliation
strategy."* Several catalog rows had been built on the **pivot**, which
THE-PLAN supersedes. When two sources conflict, the order is:

1. **`THE-PLAN.md`** — the approach
2. **`DECISIONS.md`** — the ruling, later entry wins
3. **the code** — what actually executes
4. everything else

`REFERENCE`, `STATE` and `PROBLEMS` have each been caught carrying a stale rule.

**Grepping is not reading.** Four of the corrections found so far — the 40-room
rule, the rejoins ruling, the drops verification result, and the two BOBs — were
invisible to keyword search and only surfaced by reading a document end to end.
