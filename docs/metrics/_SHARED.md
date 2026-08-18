# Shared — knowledge that belongs to no single metric

> # ⛔ 2026-07-30 MEETING SUPERSESSIONS APPLY
> The recorded 7/30 call (the administrator + membership leadership) outranks this file where they
> conflict. See **`handoff/2026-07-30-MEETING-RULINGS.md` *(archive repo)***.
> Headlines affecting this file: RRO conversions are NEVER drops (the 82/$112k
> rescue is dead; RRO flips also leave the retention cohort entirely) · new
> member = 6-MONTH-GAP rule (ever-paid-before is dead; EnrolledDate cohort is
> right; the "report counts rejoins" defect is retracted) · corporate-bill baby
> = dues adjustment (not new member/revenue); separately-billed baby counts ·
> unpaid-active = FLAG for the administrator, never a silent rule · strict retention close
> confirmed; exceptions = manual-adjustments tab · month-close runs wait for
> accounting green light + ITD (1st-of-month is wrong) · size-unknown → NT
> confirmed · BOBs face real billing at renewal (alert wanted).


Cross-cutting facts referenced by many rows of [`../METRIC-CATALOG.md`](../METRIC-CATALOG.md).
Where two statements conflict, **both are kept** and marked.

**Sources read in full so far:** `docs/REFERENCE.md` *(archive repo)* · `docs/DECISIONS.md` (all 533 lines) · `docs/RECONCILIATION.md` *(archive repo)* · `docs/STATE.md` *(archive repo)* · `docs/PROBLEMS.md` *(archive repo)* · `docs/THE-PLAN.md` *(archive repo)* · `docs/ARCHITECTURE-MAP.md` *(archive repo)* · `docs/SOP.md` *(archive repo)* · agent memory · a recorded stakeholder call *(archive repo)* · code: `logic/target.py`, `logic/billables.py`, `logic/revenue.py`, `logic/retention.py`

---

## Fiscal calendar

**FY = Oct 1 → Sep 30.** Sep-first logic (`>= 9` month cutoffs, `MONTHS` starting
"Sep") is a bug.

---

## The billing cycle — three notices (SOURCED, do not re-derive)

From the membership administrator's call 2026-07-22 [J 1:40–2:15], recorded in
the recorded stakeholder call of 2026-07-22, §1 *(archive repo)*.

| Notice | Calendar month |
|---|---|
| 1st | **M − 1** (month before the bill month) |
| 2nd | **M** (the bill month) |
| 3rd | **M + 1** (month after) |

- **The pay window closes at the end of M+1** (~90 days).
- The MA runs the **ITD utility early in M+2** (SOP: by the 7th) to inactivate
  non-payers. That is **cleanup, NOT an extension of the window**.
- A payment after M+1 is **late/reinstate, not a cycle renewal**.
- Retention for BM M **finalises at the end of M+1** — the freeze point for the
  MATURING semantic.
- **The report's month column is BM+1** because that is when the cohort stops
  collecting: the June column holds BM5.
- **In any calendar month four bill months are live.** Worked example from the
  call: pulled in **January** → **December = 3rd billing · January = 2nd ·
  February = 1st · March = pre-billing.** *"One report gives all four numbers."*
  [J 22:12–22:46]
- **"Notice" is the in-house term**; the workbook's "billing" columns mean the
  same thing — *"they're synonymous."* [J 2:36, 3:40]
- **"Members technically have 90 days to pay"** — and the membership administrator added *"I don't
  know if we're going to continue that way."* [J 1:40–2:15] The window is a
  **current practice, not a law**; if it changes, the cycle-close rule changes
  with it.
- **September appears twice** in the billing view because the **prior FY's
  September cohort is still collecting** — its 3rd notice lands in October, so
  for that row only 3rd billing is projected. [J 3:00–3:40] *(This is the same
  edge the engine handles by evaluating BM9 against `fiscal_year_start − 1`.)*

## ITD ordering (CRITICAL)

ITD = Inactivate Members Utility; moves unpaid Active → Inactive; run by IO once
payments post.

| Run **BEFORE** ITD | Run **AFTER** ITD |
|---|---|
| Retention | Billables, Penetration |

**Why they differ — confirmed structurally 2026-07-29.** ITD is the moment the
member population changes, and the two metrics need opposite sides of it:

- **Retention** asks *"of the members billed in cycle M, how many paid?"* — it
  needs the population **while it was still collecting**. Run it after ITD and
  the non-payers have been inactivated out of the denominator, so retention
  drifts toward 100%. **This is not hypothetical — it is the 146-vs-136 problem.**
- **Billables** asks *"who do we bill next?"* — it needs the population **after
  cleanup**, or it counts members already gone.

> **membership leadership states the same distinction from the reporting side:** *"retention
> goes by month, and billables right now."* The CRM's two billables reports are
> built on exactly that split — `Active Billables By Ac And Fte` is the snapshot,
> `Billables By Territory Summary By Bm` is 12 blocks, one per bill month.

**Retention timing, precise, from SOP:** use the **3rd notice of the month just
completed**. A report run April 1 is for March, using February's 3rd notice.
"December month-end → use BM 11 data." Make all corrections to the 3rd notice.

---

## Target vs Non-Target

**Bill month = the month the member joined** [J 1:21] — it is a property of the
member, stable year to year, not an assignment made each cycle.

**Target vs Non-Target = SIZE**, not member type:

- Restaurants **≥ 10 FTE**
- Hotels **≥ 40 rooms**

### ⚠️ Rooms threshold — the chain, because stale copies are still in circulation

| Date | Ruling |
|---|---|
| 2026-07-13 | Target lodging = **41+** rooms. "Intentional divergence from the CRM reports" — they count the 23 hotels at exactly 40 |
| 2026-07-19 | 41+ **kept** during the subtype investigation; `final_verdict` nets the 23 out of CRM references |
| **2026-07-21 (day 2)** | **REVERTED to 40+. "the membership administrator confirmed directly: 40 or more rooms = Target, 39 or fewer = Non-Target." Supersedes 7/19.** The 23 forty-room hotels enter the universe; the netting was removed; our penetration should match the CRM reports **directly** |

**Live state:** the code is **correct** — `target.TARGET_ROOMS_MIN = 40`.
**Stale copies still saying 41+:** `REFERENCE.md` (lines 52, 56) and five code
comments (`target.py:113,212`, `billables.py:143`, `drops.py:543`, and
`target.py`'s module docstring). The behaviour is right; the comments lie.

**Allied = TYPE** (supplier), not size — **always Non-Target**.

### The full classification table (`logic/target.py`)

| Account `Type` | Classified by |
|---|---|
| `Hotel`, `Lodging` | **`Rooms`** from `cMemberGens` — Target if **≥ 40** (*"the membership administrator confirmed 2026-07-21: 40+ = Target, 39 and under = Non-Target"*, in the code's own docstring) |
| `Allied` | **always Non-Target** |
| `Corporate` | **always Target** — it is the billing entity for a multi-location chain and the system aggregates FTE across all child locations, so corporate-level FTE is ≥ 10 **by definition**. *(Confirmed from a team lead Jackson's notes, 2026-05-08.)* In practice it falls through to the `Avgrangefteperloc` check; **if the corporate parent has no `cRestProfiles` record → Unknown**. **TODO in code:** confirm whether SLX stores aggregate FTE on the corporate parent or whether child records must be summed |
| all others | treated as restaurant — `Avgrangefteperloc` ≥ `'10 to 19'` |

**Three buckets, not two:** Target · Non-Target · **Unknown** (a hospitality
account whose size data is missing — ~7% of restaurants, rare for hotels).
Consumers fold Unknown into Non-Target so totals stay whole.

**Field coverage:** `Avgrangefteperloc` is populated on ~93% of restaurant
records. **`Totalemployees` is 99% null — do NOT use** (confirmed 2026-05-08).

**Why territory-wide, not per-account:** classifying 200+ accounts one at a time
would need 200+ API calls. `build_target_map()` fetches **3** territory-wide
lookups (`accounts`, `cMemberGens`, `cRestProfiles`) and classifies in memory —
3 calls per territory regardless of account count.

**⚠️ Open:** how **Corporate / Grocery** are classified in the retention / revenue
/ new-member T/NT splits. Penetration excludes them; `target.py:_classify_one`
(which feeds retention, revenue, new members and drops) still lumps them in. The
two classifiers need reconciling.

### ⚠️ Contradiction — Allied and the retention %

### 🔒 LOCKED 2026-07-29 — Target/Non-Target is the system, everywhere

> **Jiho:** *"I said T/NT. Lock. The old SOP is old SOP. We are
> upgrading/automating."*

Every member metric splits **Target / Non-Target**, including **billables**. The
official MPR SOP's instruction to record *"the number of Allied and Hospitality
in the respective territory box"* documents the **old manual process** — it is
not a specification for the automated report.

**No H/A remnant.** The 2026-07-13 flag for department leadership is closed.

### ✅ SETTLED 2026-07-29 — Allied is Non-Target and IS included

> **Jiho:** *"Allied is non-target, include it. They are a nice to have but not
> targeted."*

Allied appears in every member metric, in the **Non-Target** band. No carve-out,
no side table. This reaffirms the 2026-07-13 ruling made under department leadership's T/NT
consolidation.

**Superseded:** REFERENCE.md line 56 (*"excluded from retention %"*) and the
2026-07-28 D2-applied-to-retention exclusion. **D2 still governs billables**,
where Hospitality and Allied are reported as separate counts.

**When reconciling to the membership administrator's file, subtract Allied** — her retention file is
hospitality-only. Publishing and reconciling are different operations.

*(The three prior statements, for the record:)*

| # | Statement | Source |
|---|---|---|
| A | "Allied = TYPE (supplier) — **excluded from retention %**" | REFERENCE.md line 56 — **superseded** |
| B | "Allied gets NO special-casing — **Non-Target across ALL member metrics including the retention %**" | DECISIONS 2026-07-13 — **GOVERNS** |
| C | "D2 applied to retention. Allied… belongs to billables, not hospitality retention" | DECISIONS 2026-07-28 — **superseded for retention** |

Detail and the reconciliation consequence in
[`retention-members-up-for-renewal-target.md`](retention-members-up-for-renewal-target.md) § C1.

---

## Majors / NRA

- ~**893** national-chain accounts managed by the Majors/NRA **house user**.
- **$0 dues in SLX** — they pay national WRA.
- They surface **inside the Majors/NRA column** via the house-user mapping.
- **NOT** a separate `Duesbillmonth > 12` bucket. The bm>12 NRA marker was
  **DISPROVEN 2026-07-14**; BMs 13–16 are unrelated special groups.
- **NRA revenue is a finance figure** (Dues Summary workbook), not a clean SLX
  pull — see the detail below.
- **Majors/NRA is excluded from retention and penetration.**

### Where NRA revenue actually lives (memory `project_nra_and_dues_revenue`, 2026-06-04)

**There is NO confirmed SLX field equal to finance's "Dues from NRA."**

The finance workbook **`FY 26-27 Dues Summary.xlsx`** tracks it explicitly — the
`Accounting` sheet has a **"Dues from NRA"** line, and `Irregular Revenue` has an
NRA column with real per-bill-month dollars (BM10 = **$24,115**; BM1 = $24,115
plus Retro BM13 **$61,669**). **This is the "GL report" the team means** —
compiled by **Christina / finance**.

**SLX probe:** NRA accounts do carry invoices, under comp codes `RET` ($118k in
an 8-account sample), `WRA` ($46k), `MSC`, `WLA`. **`RET` is most likely
Retro/retention, NOT NRA** — the Accounting sheet lists *"Dues from Retro"*
(Retro BM13) and a RETENTION block **separately** from *"Dues from NRA"*. The
earlier guess that `RET = NRA` is **probably wrong**.

> **Do not auto-wire NRA $ from `RET` without confirming its meaning with
> Christina / finance.**

`revenue.py` sums `Comp_code = 'WRA'` only, which is exactly why NRA reads $0.

**Why this matters for the MPR:** the team asserts *"everything is in SLX."* For
NRA dues that is only loosely true — the dollars exist under non-WRA codes, but
**the figure finance actually reports comes from a workbook**, not a clean SLX
query. The MPR's Majors/NRA revenue cells are $0 for this reason, which matches
the SOP.

> **Scope note:** the same workbook holds `Territories Budget - MASTER` and
> `Territories Actuals - MASTER`. Those feed **Dues Analysis, not the MPR** —
> the MPR has *Goals* (admin input), not budget-vs-actual. Recorded here only so
> nobody mistakes them for an MPR source.

---

**Two users, not a discrepancy (resolved by DECISIONS 2026-07-13):** the NRA
house user `U6UJ9A000083` was *added* to the territory map alongside
`U6UJ9A0000A5`; both map to Majors/NRA. Before that it was missing entirely and
"the chains fell out of our report". **Multi-user territories SUM per territory**
in billables and penetration (previously the last user overwrote).

---

## Territory map (SLX User ID → territory → rep)

*Rep names drift — verify against the current goals workbook before trusting.*

| User ID | Territory | Rep (verify) |
|---|---|---|
| U6UJ9A00009U | NorthCentral | Tiffany |
| U6UJ9A00009V | Snohomish | Amy |
| U6UJ9A00009W | NorthKing | Michele |
| U6UJ9A00009X | EastKing | (open) |
| U6UJ9A00009Y | SouthKing | Bailey |
| U6UJ9A00009Z | Pierce | the selling rep |
| U6UJ9A0000A0 | TKP | Robin B |
| U6UJ9A0000A1 | Southwest | a sales rep |
| U6UJ9A0000A2 | Southeast | (open) |
| U6UJ9A0000A3 | Spokane/NE | membership leadership |
| U6UJ9A0000A5 | Majors/NRA | — |
| U6UJ9A0000A6 | null | GeneralOpen — skip |

**Territory is not a field on an account.** The path is
`account.AccountManager.Id` → `territory_map.yaml` → canonical name.

*(Observed 2026-07-28, not in REFERENCE: a 12th login `RetroCoordinator`
`U6UJ9A00008G` owns 1,605 accounts and appears in membership reports. See the
drops files.)*

---

## SLX connection and SData query gotchas

- **Base URL:** `https://crm.wrahome.com/sdata/slx/dynamic/-/`
  *(the vendor is migrating the CRM — this host will change)*
- **Auth:** Basic auth; self-signed cert (`verify=False`). Credentials in `.env`
  (`SLX_USERNAME` / `SLX_PASSWORD`), gitignored. Same env vars on Railway.

**Gotchas (timeless — these bite):**

1. **Single quotes must NOT be percent-encoded.** Build the URL manually with
   `quote(where, safe="'@(),. /")`.
2. **`@` in date filters stays literal:** `EnrolledDate ge @2026-03-01@` — never `%40`.
3. **NULL trap:** `Salescode ne '510'` silently drops NULLs. Use
   `(Salescode ne '510' or Salescode eq null)`.
4. **Pagination:** ~500 records/page max — always follow `$next`; never
   client-side filter large sets.
5. **Territory is not a field on accounts** (see above).
6. **`AccountExtension` queries must NOT use `select=`** — it drops the nested
   `Account.$key`. Fetch all fields.

### Confirmed entities

| Entity | Feeds |
|---|---|
| `accounts` | billables, penetration, BOB |
| `cMemberGens` | new members, reinstatements, dues codes, `Duesbillmonth` |
| `dlInvoiceHistoryHeader` | retention paid/billed |
| `users` | territory discovery |

---

## Consolidated accounts

N accounts merge into 1 → the billable count legitimately drops by **N−1**.
`consolidation_events` is an **empty placeholder** — the query was never built.
**Needs the accountant.**

---

## Benefit Reviews (MSS)

**⚠️ Contradiction — is this live?**

| Statement | Source |
|---|---|
| Full definition below, treated as a live MPR section (rows 26–37) | REFERENCE.md lines 74–84 (still present) |
| **RETIRED 2026-07-20** — Jiho deleted the sheet and ALL plumbing; it had been off the report since 7/13 and the collection fed nothing | agent memory `reference_benefit_reviews` |

Definition retained for history:

- **What:** three Membership Specialists (the previous analyst, a member-success specialist, a member-success specialist — "MSS reps";
  field name on the MPR = "MSS Benefit Reviews") do monthly calls walking a member
  through their WHA perks. Member-success work, not sales.
- **Source = MANUAL.** No SLX entity, no SharePoint report, no shared spreadsheet.
  The only source is what the three specialists track privately. *(A team member
  verbally claimed it is in SLX — primary sources say otherwise, three independent
  ways.)*
- **Collection:** the report builder emails the three at the start of each month;
  each replies with one number. The intended automation is a monthly submission
  form — the `admin_inputs.xlsx` "Benefit Reviews" sheet.
- **On the MPR:** rows 26–37, one row per fiscal month (Oct=26 … Sep=37), three
  columns. Raw integer counts, no math.
- **Rule: `"n/a"` is written as-is, NEVER treated as 0.** (a member-success specialist's column is
  "n/a" from Dec onward — a live case.)
- **BR goals are separate** (6-month targets in another doc) and **intentionally
  NOT on the MPR** — only actuals. So "MSS goals missing" is by design.
- ✅ Fixed 2026-06-28: an off-by-one month. Root cause was the **generator**
  (`utility/generate_admin_inputs_xlsx.py` emitted Sep-first headers — missed in
  the FY migration), **not** the parser. Live xlsx migrated in place, values
  preserved, round-trip regression test added.
- **The writer's `BENEFIT_MONTH_ORDER` (Jan–Dec, calendar) is intentional and
  name-keyed — do NOT "fix" it to Oct-first; that would misplace every value.**

---

## Reinstatements

`Salescode = '510'` **or** `ReinstatedDate` set.
→ New **REVENUE** (credit) but **NOT** a new **MEMBER**.

---

## Zero-goal territories

**NorthKing / Pierce / Spokane-NE have null goals intentionally** — high
penetration, commissioned on total revenue. `_attainment()` returns None → the %
cell renders blank. That is correct, not a gap.


---

## The truth hierarchy — CRM reports are NOT objective truth

*DECISIONS 2026-07-14, Jiho — doctrine.* Established after proving CRM reports
contradict each other (784 vs 1,548 lodging), violate agreed definitions, use
inconsistent categorisations, and that the team often cannot explain their
behaviour (the administrator tracks manually because the sales report "misses things").

1. **Database records** (account-level facts) — the closest thing to objective
   truth; both systems derive from it.
2. **Ratified definitions** (the decisions log) — the team's stated intent.
3. **CRM reports** — convention documentation and reconciliation targets,
   **never truth**. A discrepancy resolves by tracing BOTH sides to account level
   and applying the definition — whoever deviates is wrong (sometimes them,
   sometimes us).
4. **Handmade MPR** — archive of what was presented; historical reference only.

**"100% accuracy" means:** every number derives from database records through
ratified definitions with account-level traceability; it matches a CRM report
ONLY where that report follows the same definition, with divergences documented
in plain words.

**Known residual limit:** we can be perfectly faithful to a flawed database.
Data-entry quality (self-reported FTE, lagging statuses, duplicate rows) is WHA's
operational domain. Mitigation is anomaly flags and loud warnings, **not silent
correction**.

### ⚠️ In tension with the Crystal pivot

*DECISIONS 2026-07-27* moved the MPR's numbers **to the Crystal reports'
printed figures** — "the past report's numbers CAME from these Crystal reports…
cells carry the reports' printed numbers". That makes reports the source for
most families, which reads against hierarchy rank 3. Both entries stand; the
pivot is later and governs which SOURCE feeds a cell, while the hierarchy still
governs how a DISPUTE is settled.

---

## Precedence rules for this documentation

- **Where an old artifact conflicts with a logged decision, `DECISIONS.md` wins**
  (2026-07-28 process note). Primary sources can be STALE relative to consolidated
  decisions — the 06-28 sweep wrongly flagged T/NT, dual-basis % and the
  penetration denominator as "wrong assumptions" by trusting pre-consolidation
  artifacts over the team's decision.
- **Definitions are sourced, not guessed** (AGENTS.md hard rule 6). Most past
  failures were wrong *definitions*, not wrong code.

---

## ⚠️ THE-PLAN SUPERSEDES THE PIVOT — read this before the table below

`THE-PLAN.md` was written **2026-07-27, AFTER the Crystal pivot failed its first
honest test**, and states: *"This supersedes every earlier plan, pivot doc and
reconciliation strategy. If a doc conflicts with this one, this one wins."*

**So the pivot's consequences below are themselves superseded.** The pivot said
"cells carry the reports' printed numbers"; THE-PLAN says **right source per
family**, and puts most families back on the SData ledger.

| The pivot said (7/27) | THE-PLAN says (7/27, later) |
|---|---|
| Retention lives on their Adjusted BM axis | **SData** — Crystal's cohort shifts between runs and scored **0/10** |
| Counts are enrollment-basis | **Paid basis** — *"members whose dues were paid, counted in their first-payment month"* |
| Rejoins count as new (their listing) | *(not restated — the pivot's basis for it is retired with the source)* |
| Drops are their export rows/dates/dues | **Split** — Crystal for the reason vocabulary and the list; the counts question is still open |
| BOB + goals stay admin inputs | **BOB is NOT an admin input** — ⚠️ *"the earlier draft was wrong"*; it is SLX invoices where `Po_number` contains `"bob"` |
| The count⟺$ invariant retires | *(follows the paid basis — the invariant is the reason paid-basis existed)* |

**The two families Crystal keeps** are the two it *earned* by being better:
**Billables — Hospitality T/NT** (its 2,143 is the membership administrator's figure exactly; ours
was 2,137, and its native FTE bands remove our size inference) and **Drops**
(the list, the dues, and 19 real reasons, with no history parsing and nothing
invented — the family where SData cost the most and delivered least).

**SData stays the engine.** Crystal takes exactly those two jobs plus its
permanent role as cross-check everywhere else.

### Why each family landed where it did

| Family | Source | Deciding evidence |
|---|---|---|
| New members # · Revenue $ · BOB | **SData** | Ledger answers any month; Crystal returns **$0 for five of them** |
| Up for renewal · Retained | **SData** | Member-level exact 7/21; Crystal scored **0/10** |
| Penetration (both bands) | **SData** | Already exact vs the CRM report; Crystal agrees within **0.2%** and stays the cross-check |
| Billables — Hospitality T/NT | **Crystal** | **2,143 = the membership administrator exactly** vs our 2,137 |
| Drops — # · $ · reasons | **Crystal** | FY-windowed, dues per row, 19 real reasons |
| Goals | Admin input | No source exists |
| **Allied billables** | **SData** | SData **162** vs the administrator **164** — a 2-count gap explained by past consolidation work (Jiho 7/27). *"Not important, not blocking"* |

---

## The Crystal pivot (2026-07-27) — what it changed for every metric

The MPR's numbers come from **scheduled Crystal report exports**. Ratified
divergences are ABANDONED. Supersedes the SData-composition basis and its
divergence registry.

**Why:** after three audit→reconstruction rounds (84 solved / 137 escalated), the
residual never closed, because the report layer's hidden semantics (stale-paid
window, Adjusted BM re-anchoring, enrollment-listing gaps) cannot be
reverse-engineered to zero. The contract is "do what the past report did
automatically with 100% accuracy" — and the past report's numbers came from these
reports.

**Consequences, per metric:**

| Consequence | Affects |
|---|---|
| **Rejoins count as new** (their listing) | New members |
| Counts are **enrollment-basis** | New members |
| Retention lives on **their Adjusted BM axis** | Retention |
| Drops are **their export rows / dates / dues** | Drops |
| The count ⟺ $ invariant **retires** | New members, new revenue |
| The paid-only / first-pay-anchoring basis (7/23) **retires** as a source of MPR numbers | New members, new revenue |
| SData remains **only where no report exists** (non-target penetration; pending GAP rulings) and must reconcile exactly with Crystal where they overlap | Penetration Non-Target |
| **BOB and goals stay admin inputs** | BOB, Goals |
| The ledger/receipts machinery is **archived, not wired** — it answers challenges, it does not feed cells | New revenue |

Baseline tagged `pre-crystal-pivot`; map and gaps in
`docs/superpowers/specs/2026-07-27-crystal-pivot-map.md` *(archive repo)*.


---

## CAPTURE AND FREEZE — the current approach (2026-07-27)

The Crystal pivot was tried and **failed its first honest test**. June was
validated end to end for the first time: **16 of 66 cells matched.** New members
and revenue were close (7/10 counts, 5/10 dollars); **every billing metric was
0/10.**

Three findings explain it — and also explain three months of "ratified
divergences" before it:

1. **Retention cohorts shift.** the membership administrator's June retention matches NO bill month
   in the July export; BM6 today is a different set of members than BM6 was in June.
2. **The same report parses differently run-to-run.** June 8's export has a
   different layout than July 26's; the parser gate refused it.
3. **Paid dollars age out.** Every Oct–Feb member shows $0 paid today — 0/40 cells.

**Root cause:** we were reconciling a COMPUTATION against a PHOTOGRAPH of a
moving system. That can never close retroactively. The fix is to replicate the
team's *practice* (observe on schedule, archive, freeze) rather than their
*arithmetic*.

**In force:**

| Period | Treatment |
|---|---|
| **FY2025-26 (Oct–Jul)** | **History** — frozen from the existing computed cache. **Not** rebuilt from Crystal; proven impossible |
| **FY2026-27 (Aug onward)** | **Captured** from the daily Crystal schedules already running (10 schedules, 00:00–00:50, verified live 7/27) |

**No new "ratified divergences." Ever.**

**Kept from the pivot:** `logic/crystal.py` (fetch/archive/staleness/FY-window
gates) · `logic/crystal_parsers.py` (10 parsers, each gated on its report's own
printed totals) · the daily archive · the FTE-billables discovery (statewide
2,143 = the membership administrator's exact figure, with a native T/NT split) · Crystal's own 19
drop reasons.

---

## Ratified rules, as summarised in STATE

- Billables = **MembershipProduct carriers**
- Penetration restaurants = **Type 'Restaurant' only**
- Retention column M = **bill-month M−1** + first-cycle guard
- Drops = all reasons categorized, **Admin + Retro detail-only**
  *(⚠️ see the RRO contradiction in [`drops-target-count.md`](drops-target-count.md))*
- New Revenue Sold = **WRA + MSC "CMP Fee" lines only, paid basis** — SW June
  $5,723.50 matches the administrator EXACTLY (the 7/14 draft's $6,805.21 was WRONG: Perch's
  $1,081.71 is a Retro programme fee, not a sale)
  *(⚠️ superseded 7/21: CMP = Claims Management Programme service fees, NOT dues —
  excluded from new member sales. Both recorded.)*
- Allied house partners **out** + provenance note
- **BOB alert month-scoped via `CDiverseEnrollDate`** ← a second BOB field, distinct
  from `CDiverseOwnership`

---

## Known-but-unfixed (completeness audit)

- Empty **3-year trend sections** — the backfill never ran (~80 min/yr to populate)
- **Streamlit background-thread state propagation broken**
- **~25 unverified candidate gaps** from the completeness audit
- Drops keying **Account-ID → Member-ID** (Member-ID confirmed correct by the
  truth PDF; needs a re-pull)

## ⚠️ Stale in STATE.md

STATE lists **Corporate/Grocery classification** as an open "definition
question". **DECISIONS 2026-07-13 closed it:** penetration is a *location* metric
(correctly excludes Corporate/Grocery); the member splits are a *dues-payer*
metric (Corporate IS a member with aggregate FTE — excluding would undercount).
Orthogonal, both correct, no `target.py` change. `PROBLEMS.md` repeats the stale
version too.


---

## ⏰ DEADLINE 2026-10-01 — the FY-rollover drops scoping

**The problem.** A drops row carries a bill month and **no date**, so the only
thing saying which fiscal year it belongs to is the schedule's StatusDate window.
On 2026-10-01 the current window (10/1/2025 → 12/31/2030) starts spanning **two
fiscal years**, and the rows cannot be told apart — nothing in the file can split
them.

**Already in place:** `crystal.assert_drops_window_matches_fy` reads the live
schedule over the API and **refuses** to compile a drops grid whose window does
not begin on the reported fiscal year. So the failure mode is a blocked run with
a clear message, never a wrong number. Verified live 2026-07-27.

**The decision still to make (Jiho, deferred):**

- **(a)** move the window each October on the three drops schedules — one date
  change, now machine-verified; or
- **(b)** *Jiho's idea:* **one schedule per fiscal year** (10/1/25→9/30/26,
  10/1/26→9/30/27 …), so each file is permanently one year and there is no annual
  step at all. Strictly safer, and it keeps past years **re-pullable** rather than
  surviving only in our archive.

**(b) depends on one unknown:** every schedule for the same report currently
produces the same filename prefix, so five FY schedules would be
indistinguishable and the fetcher would take whichever is newest. The archive
holds `DroppedMembersHospitalityBM8_suzannes_…` — a name the report itself does
not have — which suggests the **Description field drives the filename**, but that
was an interactive export, not a scheduled one.

**Free test:** give one live schedule a distinctive Description and read
tomorrow's filename.

---

## payAllocationViews — the $key-collapse audit (2026-07-24)

The view's `$key` is the payment **DOCUMENT** id: multi-line payment documents
emit N rows whose content collapses onto one arbitrary line, and which line
survives is query-plan dependent (orderby / select / batching reshuffle it).

**PROBLEMS.md marks this CLOSED with no live MPR exposure**, on this audit:
published dollars are invoice-based; `filter_renewals` is a wrapper over
`cohort_screen`'s INVOICE-TABLE renewal test; `cohort_screen`'s fee sums use
max-per-code so duplicated rows cannot inflate; its first-pay anchor has an
invoice-date fallback (bounded month-attribution risk only).

Dormant, callerless helpers (`fetch_month_allocations`, `summarize_month`,
`fetch_first_dues_payment`, `cohort_dues_and_renewals`) are hazard-noted in code
— **do NOT revive them against this view.**

**⚠️ The audit predates a new use.** On 2026-07-28 retention began reading
`payAllocationViews` for **payment dates** (`_first_payment_dates`, date-range
query, one per bill month). That path did not exist when the audit was written,
so "no live exposure" no longer covers the whole system. The mitigation built in
is that an **undatable payment is never demoted** — a missing allocation row
cannot cost a member their renewal — which is the right shape for this hazard,
but the exposure should be re-audited rather than assumed closed.

---

## Open problems by priority (PROBLEMS.md spine)

```
P0 Period engine ─▶ P1 Fresh run + 5 gates ─▶ P2 Calc fixes ─▶ P3 Display ─▶ P4 Scope ─▶ Re-demo
P5 Ops/robustness — runs in PARALLEL
```

**P1 — the master blocker: a fresh live run + five ground-truth gates.**
Run post-ITD for a real month, then check: **Penetration** (vs the previous analyst ±1pp) ·
**Drops** (vs the drops PDF) · **Retention $** (vs the HCB file) · **Goals** (vs
workbook) · **FY structure** (Oct-first everywhere). *No issue closes until its
gate passes.*

**P2 items still listed open:**
- Retention finish — dual basis, netted dollars, "exclude Allied + new members
  from the %" *(⚠️ the Allied half is contested — see the contradiction above)*
- Two Target classifiers reconciliation *(⚠️ **stale** — DECISIONS closed this
  2026-07-13 as orthogonal-and-both-correct)*
- Goals fill-in into the T/NT structure; fix the null territories

**P4:** drops FY/date filter + Account-ID→Member-ID keying · 3-year trend
backfill (T6/T7/N5/N6 empty, ~80 min/yr) · verify the ~25 candidate gaps
(statewide-penetration aggregation, negative-drop credits, combined-% summing).

**P5:** loud failures · progress visibility (the 80-min blind spinner) ·
concurrency PID lock · atomic `save_scoreboard` · **SLX host migration
readiness** (the vendor is replacing the CRM; isolate host/auth so re-pointing is
one config change) · cybersecurity sweep (backlog, track only).

**Rules in force:** sequential chips on overlapping files · invariant-grep exit
gate per migration chip · **"tests pass ≠ numbers right"** (gate before close) ·
**do not touch the writer's `BENEFIT_MONTH_ORDER`.**


---

## THE-PLAN Part 7 — hard rules for every session

*These govern how a metric may be changed, so they belong with the metric docs.*

1. **Every month must regenerate correctly, any day.** The report is **LIVE**,
   like the membership administrator's. **If a month cannot be regenerated, the source is wrong for
   that family — fix the pairing, do not freeze the number.**
2. **Never add a "ratified divergence."** A gap means the logic is wrong, the
   source is wrong, or the report is wrong. Find out which. No registry, no
   permanent excuses, **no bending a definition to close a gap.**
3. **Validate one month end-to-end before building the next layer.** The pivot
   built four layers on an unvalidated premise and all four had to stop.
4. **"Parses correctly" is not "is correct."** Reconciling to a file's own
   printed total proves the parser works, nothing more. **Say which one you
   mean.**
5. **A green pipeline is not a working product.** Open the workbook. If a month
   shows members joining and $0 revenue, the run failed regardless of exit code.
6. **Stage explicit paths in git.** Never `git add -A` — a parallel dues session
   shares this repo.

### ⚠️ Rule 1 vs CAPTURE AND FREEZE

`STATE.md` records **FY2025-26 as frozen from the computed cache, "not rebuilt
from Crystal — proven impossible."** THE-PLAN Part 4 says the opposite shape:
*"There is no frozen-history seam,"* because each family is answered by a source
covering every month, and Rule 1 explicitly forbids freezing a number in place
of fixing the source pairing.

They are reconcilable — the freeze applies to **snapshot** families (billables,
penetration) whose past cannot be re-observed, while the **ledger** families
(revenue, retention, drops, new members) genuinely do regenerate. But the two
documents state it in opposite terms and neither says which scope it means.
**Unresolved.**

---

## The build order (THE-PLAN Phase 2) — cheapest signal first

1. **Billables** — Crystal FTE report, native T/NT, statewide already exact
2. **Penetration** — Crystal Target + SData Non-Target, gated disjoint + complete
3. **New members # and revenue $** — SData ledger, **paid basis**
4. **Retention** — SData ledger, per bill month, partial payers count
5. **Drops # / $ / reasons** — bill-month axis, Crystal's 19 reasons
6. **Goals / BOB** — admin inputs, unchanged
   *(⚠️ contradicts Part 3, which states BOB is NOT an admin input — see the
   pivot-supersession table above)*

**A family is DONE only when its definition, source and logic are settled AND a
month validates end to end. No family starts before the previous one is done.**

**Where a definition is genuinely ambiguous, ask the membership administrator once — do not infer
from numbers.**

---

## GATES vs VALIDATION (THE-PLAN Phase 4)

**A deployed run must be right BY CONSTRUCTION, not because someone checked it
— nobody is there to interpret a flag.**

| In the product — **GATES** | Dev only — **VALIDATION** |
|---|---|
| Objective, machine-settled, **STOP the run** with a message naming what to fix | Needs judgement about what the business meant |
| Parser totals · export presence · FY window · bands summing · zero formula errors | SData vs Crystal · ours vs the membership administrator's |

Cross-source comparison is a **dev tool used to decide a family's source**. Once
decided, the product just uses it, and `_meta.sources` records file / run-date /
hash so any number is traceable **without being re-derived**.


---

## Where a metric's value is actually produced (ARCHITECTURE-MAP, verified 2026-07-29)

**The cache is the contract.** Everything below `scoreboard_YYYY-MM.json` —
mapper, trend_sheet, history, writer, template, SharePoint, console — is
untouched by any source change, because the overlay writes **the same field
names the engine already writes**.

```
SLX (SData)                        SLX attachments (Crystal exports)
     │                                          │
engine.run()  PULL + FEED           crystal.fetch_period() → parsers → feed
     │                                          │
     │ new members · revenue · BOB               │ billables T/NT
     │ retention · penetration                   │ drops # · $ · 19 reasons
     └────────────────┬─────────────────────────┘
                      ▼
        OVERLAY — Crystal wins its 2 families
                      ▼
        _compute_layer1/2/3()   derived %, ratios, YTD
                      ▼
        scoreboard_YYYY-MM.json   ← ONE cache, THE CONTRACT
```

**Why there is no engine refactor:** SData computes **all eight families**; for
billables and drops its values are simply *replaced* before the derived layers
run. That keeps SData's version alive as a **free cross-check**.

| Family | Produced at |
|---|---|
| Billables (incl. an `unknown` bucket merged into non-target) | `billables.compute_billables_by_target()` → `engine.py:255-266` |
| Retention (paid/billed + T/NT + revenue) | `retention` pass → `engine.py:325-340` |
| New members # and revenue $ | `revenue.revenue_and_counts_by_first_pay()` → `engine.py:405-422` |
| BOB | `revenue.py:134 _sum_bob_face_value`, split T/NT at `engine.py:415-417` |
| Penetration (both bands) | `compute_penetration_by_segment()` → `engine.py:658-670` |
| Drops | `engine.aggregate_drops_buckets()` → `engine.py:469-490`, from `drops_detail` |
| Goals | admin inputs → `engine.py:627-630`, `712-717` |

### Build list — status checked against the code, not the doc

| Item | Planned | **Actual state 2026-07-29** |
|---|---|---|
| **B1** `crystal_feed.py` | ~120 lines | ✅ **built** |
| **B2** Overlay step | ~20 lines in `runner.py` | ✅ **built** — and corrected 7/28, it ran only on the cache path so every LIVE pull shipped SData's billables and drops |
| **B3** Cross-check gate | ~60 lines | ⛔ **moved OUT of the product** (Jiho 7/27) — a per-run "SData says 162, Crystal says 145, please review" needs a human with judgement, and in production there is none. It became a **dev tool** |
| **B4** Drop-reason rows | mapper + template | ❌ **not done** — Crystal's 19 reasons reach the data; the template still shows our 5 invented buckets *(retired 2026-07-29 — all 19 Crystal reasons wire straight through)* |
| **B5** Template pass | template surgery | ❌ **not done** — Closed Businesses sheet and its dashboard cells still present. ⚠️ **29 charts and cross-sheet formulas: one careful revision, not two** |
| **B6** Delete dead code | −1,086 lines | ✅ **done** — `reconstruct.py` and `snapshots.py` are gone from `logic/`; no CRYSTAL cache file remains |
| **B7** Trim banding | −60 lines | 🔶 **partial** — `band_from_detail` added 7/28; the name-bridge path remains as fallback |

### Mess still standing (M-list)

- **M7 — Closed Businesses still populated.** The mapper stopped emitting it, but
  the **engine still fills the fields** and the **template still has the sheet**
  (396 cells per metric). Needs the B5 template pass.
- **M8 — Drop reasons are ours, not Crystal's.** `drops.py` classifies into 5
  invented buckets. Needs B4.
- **M1 — pull and populate are fused in `engine.run()`.** Ruled **leave it**: it
  works, and the overlay makes a refactor unnecessary.

*(M2, M3, M6 are resolved — the dead modules and the chimera cache are gone.)*


---

## ⚠️ The SOP is a contract deliverable and it is STALE

`docs/SOP.md` *(archive repo)* (draft v1, 2026-07-16) — *"written so a person who did NOT build
the system can run it. **Contract deliverable (due Aug 14).**"*

That makes its errors expensive: it teaches the wrong rule to whoever inherits
the report. **Two of its reconciliation one-liners are superseded:**

| SOP says | Actually |
|---|---|
| *"Lodging targets: the MPR enforces the team's **40+ rooms **(41+ is superseded — the administrator 7/21, ruled 7/29)**** rule; CRM reports include 40-room hotels. **Ours reads slightly lower ON PURPOSE**"* | **Reverted to 40+ on 2026-07-21** — the membership administrator confirmed. The code uses 40. There is **no** deliberate divergence and ours does **not** read lower |
| *"New sales revenue: MPR = CRM's New Member Sales report **plus payment-plan ('CMP Fee') dues** the CRM report ignores"* | **CMP is excluded** (2026-07-21) — it is a Claims Management Programme service fee, not dues. The proof is [a member]'s relabelled retro fee |

Both were true when written and were overturned five days later. **The SOP must
be re-checked line by line against `THE-PLAN` and `DECISIONS` before it ships.**

### What the SOP gets right and is worth keeping

**The monthly ritual** (~3 hours, mostly waiting): pick the **last business day**
of the month (penetration and revenue are snapshots — the capture date matters) ·
pull the same-day truth exports into `data/truth/` · run
`scripts/capture_snapshot.py YYYY-MM` (refuses if another pull is running,
checks reachability, runs the 1–2.5h pull, then every gate, printing one
PASS/FAIL) · read the gate output · publish.

**Rule: ANYTHING unexpected → stop, write it down, investigate. Do NOT hand-edit
the xlsx.**

**Stated limitations worth preserving:**

- **Southeast history** — the seat changed reps mid-year, and account
  reassignment **rewrites the past**, so pre-change months cannot match
  then-archives exactly.
- **Point-in-time metrics (penetration, billables) cannot be reconstructed for
  the past** — history exists only where humans recorded it. *(This is the
  cleanest statement of the snapshot/ledger split, and it is the scope that
  reconciles Rule 1 with CAPTURE AND FREEZE.)*
- **NRA chains** produce $0 in new sales; their numbers live in the Majors/NRA
  column and the finance Dues Summary.
- The CRM vendor migration will require re-pointing plus one revalidation pull.

**Troubleshooting worth knowing:** `[SLX] NOTE: legacy $next pagination` in a log
means **that pull's numbers are suspect** — re-run; if persistent, the entity
needs the cursor fix. And: **never run two pulls.**

**Its own open items:** BOB footnote wiring + the administrator confirmations · seller-credit
verification pull · scheduler wiring for the month-end alarm · formula-recalc
scan · **July 31 parallel-month sign-off.**


---

## Who owns which input and answer

*From agent memory `wha_people`. Names recur in the source notes, the training
transcript and the backlog blockers — this is who to route a question to.*

| Person | Owns |
|---|---|
| **the member-services admin Clark** | The month-performance process — **trained the workflow being automated** (the training PDF covers both the MPR and Dues Analysis). On maternity leave |
| **the membership administrator** | Covering for the member-services admin; was the **trainee** in that training session. The published editions we reconcile against are hers |
| **the previous analyst** | Pulls SLX reports and saves them to the SharePoint report folders; also a benefit-reviews owner. **Her market size is the external penetration reference** |
| **the accountant / a team lead** | SLX activation, dues codes, SLX **group ownership** — the source for CSV group exports **not exposed via SData**. *(Pen-Active automation was blocked waiting on her; `consolidation_events` still is)* |
| **Christina** | **GL / NRA.** The NRA figure comes from her — see the Dues Summary section above |
| **department leadership / membership leadership** | Leadership; **consumers** of the reports. department leadership set the Target/Non-Target structure |

> **Worth noting:** the person who *designed* the process (the member-services admin) is on leave,
> and the person we reconcile against (the membership administrator) was her **trainee**. Several
> conventions we have been reverse-engineering are inherited rather than authored
> — which is consistent with how often "why is it this way" has no answer.

---

## The original architectural decision, and what it means now

*From memory `project_scope_shift` — the founding premise.*

> **"Eliminate intermediate Excel files entirely. Compute all Scoreboard data
> directly from SLX."**
>
> the previous analyst's xlsx/csv files are **NOT independent data sources** — they are SLX
> exports saved manually to xlsx. The automation target bypasses them.

```
CURRENT:  SLX → the previous analyst exports xlsx → manual fill-in → report
TARGET:   SLX SData API → compute directly → report
```

**⚠️ The Crystal pivot partially reversed this.** Billables and drops are now
sourced **from CRM report exports** rather than computed from the ledger —
deliberately, because those reports are *"the numbers they would have used."*

The two positions are reconcilable and worth stating together: **the founding
rule rejects hand-copied intermediates**, while the pivot accepts
**machine-fetched, gated, archived exports**. Nothing is hand-copied either way —
what changed is whether a report may be a *source* rather than only a
*cross-check*, and `THE-PLAN` limits that to the two families Crystal
demonstrably answers better.


---

## The 75-percenter rule — one policy behind several numbers

*the membership administrator's call, [J 4:23–8:44], [S 7:52–8:10].*

Territories **at or above 75% penetration** are treated differently in three
places, and it is the same underlying policy each time:

| Where | Effect |
|---|---|
| **New-member goals** | 75%+ territories get **no goal** — just replace losses. Under 75% = **4 new members/month** |
| **Revenue goals (MPR)** | The same three territories carry **null goals** — commissioned on total revenue instead |
| **Budget adjustment** *(dues-side, for context)* | Their expected billing is **reduced** — NorthKing −1%, Spokane −4% |

**⚠️ the membership administrator does not agree with the budget half of it:** *"I've got a gazillion
questions about it"*, and she doubted it would be done again. **Methodology owners
to explain: department leadership and membership leadership.**

For the MPR the consequence is narrow but useful: the zero-goal territories are
**derivable from penetration**, not an arbitrary list — so if a territory crosses
75%, its goal treatment should change, and today nothing makes that happen.


---

## Where the files live (memory `wha_reference_locations`)

**SharePoint "Membership Data Hub"** — the central cache and publish target:
`Documents / Internal Dept Files / Membership Data Hub`.
**The engine reads and writes here via `DataHub` (`src/hub/datahub.py`) — never
via the SharePoint client directly.**

**the previous analyst's monthly SLX report exports:**
`Internal Dept Files / reports and trackers / monthly SLX reports / hospitality /
[FY] / [month]`

> ⚠️ **The "Commission report" folder is MISLABELLED** — it actually holds the
> **final (end-of-3rd-billing) retention figures.** That is a genuinely useful
> source hiding behind a wrong name, and it is exactly the *end-of-cycle* figure
> the strict-close rule targets.

**Primary-source notes outside the repo:** `a team lead 1st meeting Notes.pdf`
(membership domain, dues structure, NRA) and the Dues/MPR training PDF (the member-services admin
training the membership administrator) — the source for the BOB definition.

**⚠️ Path drift:** that memory refers to `mpr-automation/docs/` and files
(`HANDOFF_v1.6.md`, `HANDOFF.md`) that no longer exist — the repo is
`wha-data-platform/` and those HANDOFFs were archived into `REFERENCE.md`.
The **SharePoint** paths are still current; the repo paths are not.

---

## What the cache does NOT carry (memory `dues_cache_gap`)

`ScoreboardData` was built for the MPR. It carries ~31 metrics × Target/Non-Target
× 11 territories × months, plus the audit detail lists.

**It does not expose** — and any report needing these must source them
separately:

- dues paid by bill month **split into 1st / 2nd / 3rd notice cycle**
- **reinstatement dollars** separated out
- **payment-plan** classification *(no SLX field distinguishes one — see the
  new-members file)*
- **dues adjustments / bill-month-shift** dollar reconciliation
- **BOB / DIV comp** dollar handling as an irregular line
- a **GL grand total** to balance against

**For the MPR this is not a gap** — none of these are MPR metrics. It is recorded
because the same cache is the contract for ~9 planned reports, and the first one
that needs an irregular-item breakdown will hit this boundary.

---

## Benefit Reviews — the definition survives, the feature does not

**RETIRED 2026-07-20.** Off the report since 7/13, so collecting the counts fed
nothing. The admin-workbook sheet **and all code plumbing** — parser, model
field, engine ingest, writer, template sheet — were deleted. Git history holds
the full implementation.

The definition is kept in this file as **true history from primary sources**, and
because it is the cleanest recorded example of a verbal claim being wrong:

> *"A team member's verbal 'it's in SLX' claim is **wrong** — three primary
> sources say otherwise."*

`REFERENCE.md` still presents it as a live MPR section (rows 26–37). See
[`_STALE.md`](_STALE.md) item 6.
