# Drops — Target (#)

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


**Family:** Drops · **Engine field:** `drops_target` · **Status:** 🟢 rebuilt to the 7/30 rulings + 7/31 event axis
**Last updated:** 2026-07-31 · **Sources read:** REFERENCE · DECISIONS (full) · RECONCILIATION · STATE

Count of Target-band members whose membership was lost, **filed in the month
the loss actually happened**.

## ✅ RULED 2026-07-31 (Jiho) — drops file by FLIP DATE, the team's own axis

The month column answers *"when did we lose them?"* — the month the status
actually changed. This is the administrator's own convention: her SOP runs the dropped-member
report *"1st through last day of the month"*, a date range on the flip.

**Why the bill-month axis died:** it carried no year. September-class members
who failed their **September 2025** bill (flipped Oct/Nov 2025) were filed
under the column labeled Sep — which in this grid is September **2026** — then
hidden by the writer's month emission: **23 real drops computed but published
nowhere**, surfaced by the FY-total cross-check (156 published vs 179
computed). Jiho's boundary insight generalized it: every year-less axis gets
worse approaching FY end.

**Mechanics:** flip dates come from SData's drops detail via the same
name-bridge banding uses (`drop_dates_from_detail`; `member_id` would be
cleaner but is empty across the detail — audit item). A date is trusted only
inside the FY window and not in the future — the 41-stale-dates class
(2012–2024 dates on FY25/26-billed members, found 7/27) is treated as
dateless. **Dateless fallback (conditional):** class window already closed →
file at the close (non-payer shape); window still open → the loss was learned
now, file in the current month. Every fallback filing is flagged by name
(`drop_date_fallback`; 33 on the live July data).

**Consequences:** future columns are empty *by construction* (a July pull can
only contain flips that already happened) · FY totals conserve (179 = 179) ·
**per-month parity with the administrator's legacy monthlies is NOT expected** — hers are
also event-dated but captured on her run schedule; totals reconcile, months
may differ (side-by-side note) · retention keeps its own close-month axis
(genuinely the administrator's: "the June column holds BM5") — the two families answer
different questions by the team's own convention.

---

> ## ⛔ THE 82-MEMBER RESCUE IS DEAD (2026-07-30, recorded call)
>
> Everything below about *counting* RRO exits — the universal billed-last-cycle
> gate rescuing **82 members / $112,521**, the "+82 vs official history"
> disclosure, the territory-recovery work — was overturned by the administrator in the
> meeting: *"RRO statuses I would not include in dropped member reports…
> They're not a dropped."* Those rows are **FYI only** and now reach the flag
> list. The gate survives, demoted to **hygiene** (stale strays inside the
> real Inactive/Closed block). Kept below per rule 8; do not implement it.

## Definition as ratified

> **"A drop in month M is a member who is no longer billed in cycle M."**
> — DECISIONS 2026-07-27, Jiho

Attributed by **BILL MONTH**, not by the date someone quit. The metric is about
*which billing cycle lost members*.

**Why bill month:** the hospitality drops export carries **no per-row date** —
only Bill Month. The alternatives were bill-month attribution, daily diffing of
successive exports, or moving the schedule's date parameter monthly. Jiho ruled
bill month and supplied the definition that makes it *correct* rather than a
fallback.

**Coherence win:** the whole membership block now shares one axis. Retention says
"up for renewal in BM x" and "retained in BM x"; drops says "lost from BM x".
Directly comparable, explainable in one sentence.

**Supersedes** the previous drop-date basis (the Active→Inactive status-history
transition), which retired with the SData composition layer.

**Source:** Crystal `Dropped Members - Hospitality`. Banded Target/Non-Target via
SData's own `is_target` from `drops_detail` (2026-07-28) — the export carries no
size, so the band comes from the same target logic every other family uses.
Measured coverage: **263 of 264 rows band (99.6%)**; the single miss is
`[a member]`, the ownerless account no territory-keyed query can reach.

---

## ⚠️ It is not unverified — it was verified and it FAILED

`RECONCILIATION.md`, corrected 2026-07-27:

| | Ours | Theirs | |
|---|---|---|---|
| Drop **counts** | **155** | **204** | **−49 (−24%), lower in EVERY territory** |
| Drop **dollars** | **$115,164** | **$171,176** | **67% of theirs — ~$56k missing** |

Comparable universe = CRM Hospitality-minus-Retro (157) **+ Allied (47) = 204**,
since our drops include Allied.

> **RECONCILIATION's own verdict: "NOT ready to wire into the engine."**

**An earlier "within 9" claim was wrong** — it compared our hospitality+allied
total against their hospitality-ONLY report (ByType 163). Apples to oranges.

**Prime suspects named:** the billable gate excluded 344 records that run; plus
the unmanaged-account class (`AccountManager` empty).

**On the dollars:** the valuation cascade is **sound** — the gap is **CAPTURE,
not valuation**.

---

## The earlier account-level breakdown (2026-07-22)

Span confirmed comparable (CRM export Oct 1–Jul 1; ours Oct–Jun), so the gap is
real, not a window artifact. Against CRM's clean 162 hospitality drops ($145,842):

- **Matched: 103** · **CRM-only (we lack): 59** · **Ours-only: 470**

**We over-counted (470):** Copied Record (90), Retro Final Distribution (54),
Duplicate Record (34), Never a Member (30), plus Individual (55) and Allied (42)
types. **304 of the 470 were $0-billed** — inflating count, not dollars. Our drop
universe was too broad.

**We under-counted (59):** 34 were **date-attribution** (present in our data but
our drop_date landed outside Oct–Jun — Yum! Brands 2017, Duo's Catering 2020;
CRM uses status/effective date). **25 were TRULY ABSENT** — real hospitality
drops with real dues ($1,070, $2,095, $1,415…): `[a member]`,
`Greenwood American Bistro`, `Cask & Schooner`.

**We under-valued matched members by ~23%** — CRM $96,158 vs ours $74,387, the
"last WRA dues invoice" method versus the CRM's dues figure.

---

## Rules layered on over time

### Closed reason vocabulary (2026-07-22)

> *Jiho's principle: fix OUR logic where it is wrong; never bend it to match
> another report's data quality.*

Record-hygiene reasons **cannot "drop"** a member: `Never a Member`, `Not a valid
WRA Lead`, `L I Account Change`, `New Record from Import`, `2024 List Clean Up`,
`Member Under New Name`, `Confirmed Open` + cleanup strings → **Admin**, excluded
from counts, kept in detail. The vocabulary is **CLOSED**: every known string is
explicitly classified; a never-seen string **WARNS loudly and counts Voluntary**
(the unclassified-charge-code pattern — announce, never silently absorb).
FYTD counted drops 354 → 301.

### Billable gate + closure union (2026-07-23, Jiho GO; membership leadership: *"billable makes more sense"*)

A drop counts **only where the dues live**. No own dues anywhere (Dues Level /
positive WRA invoice / ledger) = never a dues-carrying member = **detail-only**.

- Dissolves the **family-child $0 class** — Taco Time ×4, Chick-fil-A ×2 beside
  their $5,495 parent.
- Dissolves the **retro-only class** — 3 Dairy Queens, [a member] (absent from
  Crystal's own exports).
- **Member-closures missing their status flip** (`[a member]`)
  materialise as drops from native closure fields, provenance-flagged. Canonical
  flip records win dedup; best-date-wins on later correction (a member may move
  month once, visibly).

*(Note: this is SData-composition machinery. The Crystal pivot rules that
"drops are their export rows/dates/dues", so this layer largely retires — but
the billable-gate principle is what membership leadership endorsed.)*

### Valuation cascade

Dues Level primary (Crystal's own field) · positive-only invoices · **$100
remnant floor** (the Zone/Olympia $15.50 class) · **credits never value a drop**
(59'er −$340) · $0-dues drops count as members lost and contribute $0 revenue.

---

## 🔑 The official Dropped Member Report SOP (~2019, preserved in `source-documents/`)

Old, but it documents a **mechanism** nothing else records.

### The drop reasons are CURATED BY HAND, and the report is run TWICE

1. After final reports for the previous month, the **MA runs the ITD Utility** to
   inactivate everyone who did not pay by the end of the **third billing cycle**.
2. The drops report is run.
3. **A Membership Specialist then reviews and RE-CLASSIFIES:**
   > *"Focus on the members with the status reason **'Non-Payment'**. Review
   > **AC Third Notice notes** in SLX to determine the reason the member dropped."*
   They pick the correct reason from a dropdown, member by member.
4. **"Once all statuses have been updated, RERUN the report."**

> **This changes how a drops export must be read.** `Non-Payment` is the **ITD
> default** — what a member gets for not paying. The real reason is written in
> afterwards by a human reading collection notes. **An export pulled before
> curation is mostly "Non-Payment"; the same export pulled after is the real
> distribution.**
>
> That is a **timing hazard we did not know about**, and a strong candidate
> explanation for reason-mix differences between runs.
>
> *"When in doubt of reason, please ask. Reach out to Territory Managers if you
> cannot decipher the reason."* — the reasons are **judgement**, not data.

### The official reason definitions

| Reason | What it means, verbatim |
|---|---|
| **Non-Payment** | *"Member said they were paying and did not"* |
| **No Answer** | *"Unable to reach member and actually speak to them"* |
| **No Benefit** | *"Just as it reads"* |
| **Budget** | *"Member cannot afford it"* |

*(These are the four "most common" — Crystal now emits 19.)*

### Deadline and ordering

- **Monthly processing completed by the 7th** — the same deadline REFERENCE
  records for ITD.
- **Drops run AFTER ITD** (like billables; unlike retention).

### ⚠️ Two things that differ from what we built

**1. Their report is date-ranged; ours is bill-month.**
The SOP runs *"the 1st day of the desired month as Start of Range… the last day…
End of Range"*, times 00:00:00 and 23:59:59. That attributes a drop by **when the
status changed**.

Our export (`Dropped Members - Hospitality`) carries **no per-row date** — only
bill month — which is exactly why bill-month attribution was ratified 2026-07-27.
**These are different reports answering the same question two ways.** Not a
contradiction to resolve, but it explains why date-attribution accounted for
**34 of the 59** members the CRM had and we lacked.

**2. Their report is "No Allieds" by design.**
The official report is **`Dropped Member No Allieds Revised`**. Ours includes
Allied — correctly, under the T/NT lock, where Allied is Non-Target.

**So when comparing to any CRM drops export, add its Allied report back** — which
is what RECONCILIATION does (Hospitality-minus-Retro 157 + Allied 47 = 204).

---

## What the membership administrator counts as a drop (her call, [J 21:16–21:43])

Between two billing-state snapshots:

| Movement | Means |
|---|---|
| **Decrease** | **A drop** — closed, sold |
| **Increase** | **A dues adjustment** — *"their dues level is set wrong, and they adjusted it during billing"* |

**Ideally such changes happen 60 days before billing**; late ones *"cause a
problem in Accounting."*

> This is a useful cross-check on our bill-month definition: she reads drops as
> **the decrease in a billing-state snapshot between two runs**, which is the
> same idea as *"no longer billed in cycle M"* — arrived at from the other
> direction. It also warns that **not every movement is a drop**: an upward
> movement is a dues-level correction, and a naive diff would read the pair as
> churn.

**The snapshots themselves** are typed from a *"retention / billables report
covering multiple bill months"*, run at set times — e.g. for the September bill
month, the **first week of August, before billing goes out**. the membership administrator:
**"Yes, this could be auto-populated."** [J 19:07–20:19]

---

## ✅ RRO RESOLVED 2026-07-29 — by Jiho's rule, confirmed by a field we never parsed

### The rule (Jiho)

> *"When they become inactive some go to RRO for insurance and return purposes.
> But they are no longer members — they are not part of the 1–12. **The RRO can't
> be dropped because they are already not a member.** The only way you can be RRO
> is if you aren't a member."*

**RRO is a destination, not an event.** A member leaves bill months 1–12 — *that*
is the loss. Becoming RRO afterwards is only where they went. So an RRO row is the
**receipt for a drop**, never the drop itself.

This dissolves the old A/B-vs-C contradiction rather than picking a side.
A and B (*"Retro drops are count-excluded"*) were right about **the RRO state**.
C (*"the move into RRO IS a drop"*) was right about **the exit from 1–12**. Two
halves of one transition; nobody had separated them.

**⚠️ Corollary WITHDRAWN.** I read *"and return purposes"* as *returning to
membership* and wrote that RRO is the rejoin pool. **Jiho, same day: *"new
member, yeah… wouldn't come from RRO, that's right."*** "Return" means the **L&I
retro premium return** — the money coming back — not the member coming back.
**New Members must not treat RRO as a rejoin source.**

**Bounded by Jiho:** *"idk if all drops go to bm14 (RRO), but I know all RRO is
no longer a member."* The claim is **RRO ⟹ not a member**. The converse is not
claimed, and the data agrees — most drops never become RRO.

### The export already classifies this itself

`Dropped Members - Hospitality` has a **top-level status group** above the
`Status Reason:` sub-headers. We never read it, in any parse:

| Group | Rows | Dues |
|---|---|---|
| `Inactive` | 100 | |
| `Closed` | 63 | |
| **real drops** | **163** | **$147,686** |
| `RRO` | 94 | |
| `RRO LNI Active` | 7 | |
| **RRO** | **101** | **$121,591** |
| | **264** | **$269,277** |

**Measured 2026-07-29:**

- **Zero member-ID overlap** between the RRO block and the Inactive/Closed block.
- **Zero group changes across 12 days** — comparing the 07-14 and 07-26 runs, all
  261 members present in both kept the same group. The group is assigned at the
  drop; it does not flip between runs.
- ~~Widening the window doubled real drops but moved RRO only +11%, so RRO is a
  standing roster.~~ **WRONG — retracted 2026-07-29.** That assumed one window
  strictly contained the other, which was never checked. `AccountExtension.StatusDate`
  settles it: **the RRO rows are event-filtered, not a roster** (below).
- Reason mix fits: RRO is **70 Sold + 26 Out of Business** (96 of 101). `No Answer`,
  `No Benefit` and `Non-Payment` appear **only** in the real block.

**So RRO is now excluded by the right field, for the right reason** — instead of by
bill month 14, which was a parsing accident wearing a definition's clothes.

### ⛔ Both of our current exclusion filters delete REAL drops

**1. Filtering by `Retro Coordinator` TERRITORY deletes 6 real `Closed` drops
($4,810.50):**

Grand Avenue Partners · Kevin Pereira · Pig Iron Bar-B-Q *(Out of Business)* ·
Do So Pizza · John Gauthier · Mayflower Park Hotel *(Sold)*

**This is exactly RECONCILIATION's "Hospitality-minus-Retro (157)"** — 264 − 107
territory rows. The export's own field says **163**. Six real losses were thrown
out with the retro bathwater, and the published gap inherited the error.

**2. The BM14/15 gate deletes 10 real drops ($5,895.50)** — the six above, plus
`[a member]` (blank BM), `Taco Time - Kennewick` (BM14, Southwest), and
`Brinker International` + `Dave & Buster's` (BM15, NRA Paid Member).

**Bill month is not an RRO marker.** 9 real drops carry BM14/15 and 1 carries none.

### The corrected comparable

The Allied export (`Dropped Allied Report`, 47 rows) has **no RRO block at all** —
46 `Inactive` + 1 `Closed` — and, unlike the hospitality report, **carries a
`Status Date` on every row** (range 2025-10-28 → 2026-06-30). Date attribution is
available for Allied and not for hospitality.

```
comparable universe  =  163 hospitality (real)  +  47 Allied  =  210
```

**not** the 204 RECONCILIATION used. Our 155 is measured against 210.

### ✅ MEASURED against live SLX 2026-07-29 — it is a MIX, and 38 are ours to reclaim

Jiho: *"I wouldn't assume they are all from last year. Doesn't make sense but
check."* Correct — it is neither.

| | |
|---|---:|
| RRO accounts in the retro book (`AccountManager.Id eq 'U6UJ9A00008G'`) | **307** |
| …`StatusDate` inside Oct '25 – Jun '26 | **131** *(so the export is event-filtered, not a roster)* |
| …outside | 176 *(2024: 80 · 2025: 85 · 2023: 3 · Jul 2026: 8)* |
| **…of the 131, billed WRA dues in BM 1–12 this FY** | **38 — $32,908.23** |

> **THE RULE — generalized by Jiho 2026-07-29 PM.** My first cut ("an RRO row
> counts if billed in BM 1–12 this FY") was RRO-scoped, and Jiho rejected the
> shape: *"the filter shouldn't be 'which retro members were moved to BM14
> within this year' — it should be something that ALL drops have."*
>
> **Universal gate: a row counts as a drop in cycle M iff the account was
> billed WRA dues at the PREVIOUS occurrence of cycle M.**
> *Billed last time, not billed this time* — which is the ratified definition
> ("no longer billed in cycle M") made mechanically testable, applied to every
> export row identically. No RRO-specific logic; the 38 fall out as ordinary
> drops, the ~93 fall out as non-members, and any FUTURE mis-grouped row is
> handled without a new rule.
>
> **Attribution follows from the same evidence:** the cycle of the last WRA
> dues invoice (via `CustomerNo` — see below), sidestepping the wiped
> `Duesbillmonth`.
>
> **THEY COUNT (Jiho, 2026-07-29 PM, unambiguous).** The counted RRO exits go
> into the drop COUNTS, not detail-only. And no old-report archaeology: *"the
> logic isn't about what the old report did."* The the membership administrator question is dead —
> the rule stands on the definition, not on precedent.
>
> **✅ NRA edge — SETTLED BY MEASUREMENT 2026-07-29 PM.** Jiho asked whether any
> per-member NRA dollar exists ("is it all zero?"). Measured: **0 of 70 active
> Majors/NRA-book accounts carry a membership product** — no Dues Level exists
> for any NRA member, and the book's FY invoices are the association-level
> quarterly (~$24k) and service fees, not member dues. **So the treatment is
> forced, not chosen: NRA members outside the billing system are gated by
> status alone and count as members lost at $0** — exactly the old MPR's
> Majors/NRA convention (revenue $0; NRA money is a Finance figure).

**Bound:** 38 spans the whole retro book (all types); the hospitality export's
101 RRO rows are a subset, so hospitality recovery is **≤ 38**.

**⚠️ `Duesbillmonth` is overwritten on the flip** — 126 of the 131 read `14`.
The prior cycle is **not retained**, so a reclaimed RRO drop cannot be attributed
via `cMemberGens`. The invoice `Comment` is the only surviving bill-month
evidence, and it is **blank on 23 of the 38** (the void-and-rebill class).
`CRetroFlippedAccount` (26/307) and `CRetroOldWRAID` (22/307) were checked as
markers and are **too sparse to use**.

**Full working:** `docs/handoff/2026-07-29-rro-drops-evidence.md` *(archive repo)* *(archive repo)*

---

## Rulings locked 2026-07-29 PM (Jiho, drops walkthrough)

- **The 19 Crystal reasons wire straight through to the report.** Our 5 template
  buckets are *"semantic reduction with no benefit"* — retired.
- **The Closed Businesses sheet goes.** (Distinct from Benefit Reviews, deleted
  7/20.) Bundle its removal with the 19-reasons template work — one workbook
  surgery, not two.
- **Drops does NOT need special freezing.** Reasons updating live is a feature —
  the specialist's curation (done by the 7th, per the official SOP) heals the
  report as she works. The one mutation risk is a REJOIN: the export shows
  current status only, so a member who rejoins vanishes from it and silently
  erases their old drop. The existing month-close photograph already covers
  this. **J3 withdrawn from the the membership administrator list.**
- **Negative drop revenue: not a question.** Our own ratified rule ("credits
  never value a drop", the 59'er −$340 case) already decides it; the negative
  cells come from the pre-rule detail path, which retires. **J4 withdrawn.**
- **Terminology:** "reclaimed RRO" → **counted RRO exit** — an RRO row counted
  as a drop because the account was billed WRA dues in BM 1–12 this FY.
- **J6 stays a courtesy note, not a comparison.** Her "No Allieds" report can
  never reconcile with our Non-Target column: ours = small hospitality + Allied;
  hers = all-size hospitality − Allied. Different cuts of the pile.
- **S1 has one actionable ask:** Crystal holds the SLX account ID — the reports
  just don't print it. Adding that column to both exports would create the
  missing join key. Ask the Crystal report owner.

---

## The 2026-07-29 stress-test ("is drops REALLY understood?") — findings

Jiho asked for a deliberate gap-hunt before moving on. Result: the conclusion
holds, with these seams found and bounded.

**1. ✅ The special bill months are now MEASURED, and the gate handles them
uniformly.** Live probe:

| BM | Population | Products | Billed this FY |
|---|---|---|---|
| **13** | 24 rows — **CVBs/tourism bureaus** (Bellingham Whatcom Tourism, Seattle-King County CVB, Visit Spokane…). The old "BM13 = Apple WA" note was incomplete | 3 | **4 of 19 checked** |
| **15** | **109 rows — national chains** (Darden, Red Robin, Sizzling Platter, Elmer's…) — the NRA/corporate book | 38 | **0 of 20** |
| **16** | 2 rows (Harman Management, P.F. Chang's) | 2 | **0 of 2** |

**The carve generalizes:** BM 1–12 → universal gate. BM 13–16 → if a real dues
invoice exists, the gate applies normally (some BM13 CVBs ARE billed); if not,
the member is outside the billing system → **status-gated, counts at $0** (the
NRA rule). Invoice evidence is checked FIRST, so an RRO account wiped to 14 is
rescued by its invoices before any carve applies.

**2. ✅ RULED (Jiho, 2026-07-29 PM): counted RRO exits carry their DUES — side B.**

> *"'Why is there a dropped member but no $ lost?' — the situation where a
> dropped member exists but no $ dropped is unacceptable, cuz that logically
> doesn't make sense."*

**The principle, scoped:** within the billing system, a counted drop MUST carry
dollars — a $0 drop row is a logical error on the report face. The scope
matters because two ratified cases sit outside it, deliberately:

- **NRA / special books:** member-level dollars are *unknowable* (0/70 carry a
  product), and the whole Majors/NRA revenue column is $0-by-design (Finance
  owns NRA money). A $0 NRA drop is coherent **because its whole column is**.
- **The genuine $0-dues class** inside billing is already handled by the
  **$100 remnant floor** (the Zone/Olympia $15.50 class) — which exists for
  exactly Jiho's reason. A billed member never drops at $0.

So: billed member drops → Dues Level (incl. the 38, ~$33k). Special-book
drops → $0, disclosed as outside billing. Nothing in between.

**3. ⚠️ Attribution fuzz, bounded:** 23 of the 38 counted RRO exits have
blank-comment invoices, so their bill month must be inferred from invoice date
(1st notice ≈ M−1). A late rebill can shift the inference ±1 month. Design:
attribution hierarchy (comment → `Duesbillmonth` if 1–12 → date inference),
with date-inferred rows **flagged loudly**, never silent.

**4. Implementation constraints inherited from ratified rules:** "billed at the
previous occurrence" means a **net-positive ask** (the net-ask rule — a fully
rescinded invoice is not billing); the month-close photograph must happen **no
earlier than the 7th of M+1** so the specialist's reason curation is captured.

**5. ✅ The "25 truly-absent" investigation is REFRAMED.** Those 25 were absent
from our *SData composition* — but THE-PLAN makes the export the count source,
and **the 25 are IN the export**. The residual is only: can every export row
band and key? `CustomerNo` keying (2026-07-29) likely closes what the name
bridge missed. The ownerless-account class stays on BROKEN-RECORDS for the
CRM owners regardless.

---

## 🔑 `Dropped Report For Leadership` — a 2017-frozen corroboration, NOT the operational source

Jiho spotted the name and exported it, then challenged the claim it's "what's
used" — correctly. **Investigated 2026-07-29 PM:**

- **Run history: 7 runs EVER** (2018 · 2019 · 2021 · 2022 · 2× Oct 2025 —
  KristinaP then victoriam, at FY start · Jiho today). The operational cadence
  belongs to `DroppedMembersHospitalityBM<N>` + `DroppedMemberAllieds`
  (**48+ runs, the member-services admin 32**, monthly).
- **Definition created 2017-08-28 and last modified THE SAME DAY** — untouched
  for nine years. (Hospitality: created 2024, modified Aug 2025 — maintained.)

**So: FOG LIFTER, not game changer.** It is *"Dropped Member Report,
Association"* — **209 records**, territory-first with dollar subtotals — and
its value is that a 2017 report author **independently encoded every rule we
ratified this month**: association-wide (hospitality+Allied), status-based
(keeps the retro-territory Closed drops), RRO excluded. The institution had
the answer in 2017; the current process stopped consulting it.

**The reconciliation target remains the monthly runs the team actually uses.**

| Fact | Measured |
|---|---|
| Statuses | **Inactive 145 + Closed 64 — ZERO RRO rows.** The report already implements the RRO rule |
| vs our hospitality real block | **161 of 163 overlap** (missing: `Yeh Yeh's Inc.`, `Hotel Hotel Hostel` — unexplained residual) |
| vs our RRO block | **0 of 101** |
| Allied | **included inline** (48 rows — Mautone, CBRE, LAZ Parking…) vs the Allied export's 47 (+1 unexplained) |
| Retro Coordinator territory | **6 rows — exactly our six real Closed drops.** Their own leadership source classifies by STATUS, not territory — our old territory filter is disproven by their own report |
| NRA Paid Member | 4 rows included |
| Columns | has **Enroll Date**; no City |

**Roles:** `Hospitality` (+ Allied) = capture source (carries the RRO blocks
the gate needs) · the **monthly BM runs** = the reconciliation target (what
the team publishes from) · `Leadership` = a corroborating cross-check
(209 / $175,471), pulled ad-hoc — its 3 diffs vs our universe (Yeh Yeh's,
Hotel Hotel Hostel, +1 Allied) go to the proving run. No 11th schedule needed.

---

## ✅ THE ADMINISTRATOR QUESTION — ANSWERED EMPIRICALLY, 2026-07-29 PM (Jiho's idea)

Jiho: *"can't we check? by checking who is in retro, and then looking at
dropped member reports for the past bill months…"* — yes, and the archive made
it possible: **the member-services admin/the previous analyst's official monthly runs** (`…BM<N>`, date-ranged
per calendar month, run the 3rd–7th) are archived as SLX attachments going
back two years. Pulled all 8 of this FY's runs and section-parsed them.

> **Of the 101 current-RRO members, 70 appear in this FY's official monthly
> runs — ALL 70 in the RRO / RRO LNI Active sections. ZERO ever appeared as
> Inactive or Closed. The flip beats every report run, every month.**

**So the official process has NEVER counted a retro-bound member's exit — in
any month, of any year.** Combined with Leadership's zero-RRO structure: the
~38 billed members (~$33k) who left this FY and went retro have never been in
any leadership number. **The question to the membership administrator is DEAD** — replaced by a
one-line disclosure: our drops read up to +38 / ~$33k above the official
history, because the official reports route retro-bound members out of sight
before any run can count them.

---

## ~~🟡 THE ONE ADMINISTRATOR QUESTION FOR DROPS (added 2026-07-29 PM)~~ *(answered above — kept for the reasoning)*

Jiho's framing of why the old process ignoring retro rows is *coherent*, not a
defect: *"the only way to be a retro is by being dropped — so it doesn't make
sense to look at a retro and go 'OH! that's a drop!'"* Correct, and it is our
rule too. **But it leaves one factual unknown about HER process:**

When a member leaves and then flips into retro, there is a race between the
flip and her report run. If she runs the report while they still read
`Inactive`, she counted them; if the flip won, they went straight to the RRO
block and **were never counted in any month of any year**.

> **For the administrator, in her terms:** *"When a member drops and moves into the retro
> program, do they show up on your dropped-member report first — or does going
> retro skip the report entirely?"*

**Why it matters:** it does NOT change our logic (the universal gate counts
their exit regardless). It only calibrates comparisons: if the flip usually
wins, our FY numbers will read up to ~38 members / ~$33k HIGHER than her
history, for a reason we can name in one sentence.

---

## ✅ PROVING RUN EXECUTED 2026-07-29 PM — `scripts/drops_proving_run.py` *(archive repo)*

Output preserved at
`handoff/2026-07-29-drops-proving-run-output.txt` *(archive repo)*.

```
export rows 264 | COUNTED 222 ($243,160) | excluded 42
conservation: OK — every row is counted or named beside the rule that excluded it
```

| | members | dollars |
|---|---:|---:|
| **Counted** | **222** | **$243,160** |
| …of which RRO exits (discarded before today) | **82** | **$112,521** |
| …of which ordinary Inactive/Closed | 140 | $130,640 |
| Excluded — last dues invoice predates the previous cycle | 21 | *(Columbia Tower Club, [a member]…)* |
| Excluded — special book, no WRA billing, $0 | 12 | |
| Excluded — no WRA dues invoice EVER | 9 | *(Olympia Hotel at Capitol Lake, Cask & Schooner…)* |

**Banding: Target 123 / Non-Target 94 / Unknown 5.** Attribution provenance:
133 export bill month · 58 invoice comment · **29 date-inferred (flagged)** · 2 status-only.

### ✅ Date-inference VALIDATED — 93% exact, and it can never drop a row

Jiho's concern: *"what if this is silently dropping the proper drops?"* Tested
against the **147 rows where ground truth exists** (a real export bill month AND
invoices) by asking what inference *would* have said:

| inferred − true | rows |
|---|---:|
| **0 (exact)** | **136 — 93%** |
| ±1 month | 6 → **97% within ±1** |
| +2 / +4 | 5 |

**And inference cannot drop anything.** It only chooses a month for a row the
gate has already counted; the worst case is a member landing in an adjacent
month's cell. The gate's own window carries **90 days of grace**, far wider than
the ±1-month error, so a mis-inference cannot flip counted → excluded either.
**Bounded, measured, and flagged in the output.**

### ✅ The 9 "no invoice EVER" — verified two ways, correctly excluded

Jiho: *"they signed up but prob cancelled before ever paying?"* — **right for the
clearest case.** `[a member]`: opened **2026-04-15**, inactive **2026-04-29**.
Fourteen days, never billed.

Re-checked by an independent route (`Account.Id` instead of `CustomerNo`):
**zero invoices of any kind, any company code, ever** — so the keying was not
hiding them. Two of the nine are $0-dues NRA/corporate rows (`Yum! Brands`,
`Fogo De Chao`).

⚠️ **But three carry a Dues Level with no invoice in ~20 years** — `Kate's Pub`
(opened 2006), `Big Wally's` (2004), `Rainier Restaurant & BBQ` (2008). The
invoice table reaches back to at least 2006, so this is a genuine record anomaly,
not a horizon effect. `Big Wally's` and `Olympia Hotel at Capitol Lake` each have
**two account records**. → BROKEN-RECORDS.

### ⚠️ CORRECTED — the window's real filter field is UNKNOWN (not MODIFYDATE)

I reported that the reports filter on `MODIFYDATE`. That is the SLX metadata
(`dateField: MODIFYDATE`), **but it cannot be the effective filter**: a bulk
`ADMIN` job touched **305 of 308** retro accounts and **57 of 57** sampled
ordinary drop accounts inside eight days, so a real MODIFYDATE filter would
return an almost totally different set each run. Behaviour matches a
**status-date** filter (240/241 in window). The Crystal selection formula is not
exposed. **Treat the window's semantics as unverified** — and never build logic
on the assumption that it means "dropped in this period".

### ✅ Stale records DO slip through — and the gate catches all of them

My earlier "240 of 241 in-window" check silently skipped the 23 rows with no
invoices. Completing it: **3 of those 23 are stale** — `[a member] Pizzeria`
(StatusDate **2003-11-04**), `Evergreen Restaurant Group` (2020-03-10),
`Olympia Hotel at Capitol Lake` (2022-05-26) — plus `Hotel Hotel Hostel`
(2026-07-23, two days past the window's end).

**Total: 4 of 264 rows (1.5%) are admitted by MODIFYDATE alone — and the
billed-last-cycle gate excludes every one of them.** The gate is doing exactly
the work that makes the export safe to use.

### 🔴 CORRECTION — the RRO exit population is 82 / ~$112k, NOT 38 / ~$33k

The **38** figure quoted all day (and written into `_EXTERNAL`, memory and
`BROKEN-RECORDS`) was a *narrower measurement*: RRO accounts with a dues invoice
**inside FY25-26 only**. The ratified gate is *"billed at the **previous
occurrence** of the cycle"*, which for a June drop means **June 2025** — the
prior FY. Applying the actual rule: **82 of the 101 RRO rows counted.**

Both numbers were measured correctly; they answered different questions. **82 is
the one the ratified gate produces**, so it is the one that governs. All
documents corrected 2026-07-29.

### The gate had a real bug, and the proving run is what caught it

First implementation used a **flat FY-boundary cutoff** (`invoice >= 2024-10-01`).
Wrong *in shape*: "the previous occurrence of cycle 11" is Nov 2024 while "of
cycle 6" is June 2025 — a single date cannot express both, and the flat version
admitted members who had been gone a year before their own cycle. Now computed
**per row** from that row's cycle (`notice_date()` − 12 months − 90 days grace).
**This is exactly why the proving run exists.**

## 🔑 THE AUDIT LOG SOLVES THE ATTRIBUTION FUZZ — and dissolves the territory problem

Jiho's screenshots of `Hilton Hotel Employer LLC` pointed at the Notes/History
tab. It turns out `history` carries **`atDatabaseChange` records that store the
OLD VALUE of every changed field**:

```
Description: 'Change to Duesbillmonth'
Notes:       'Duesbillmonth: 14\r\n  Old Value: 6'
```

### ✅ Pre-flip bill month recovered for 88 of 95 retro rows (93%)

**This replaces date-inference with hard evidence** for the rows that needed it
most. Hilton is the proof: the audit log says its real cycle was **6**; the
proving run's date-inference had guessed **8**. Recovered months spread sensibly
across all twelve cycles (6:12 · 5:12 · 9:11 · 8:11 · 10:9 · 12:9 · …).

**Wire this into the attribution hierarchy above the date-inference tier:**
`export bill month → invoice comment → AUDIT-LOG Old Value → date inference`.
Expected effect: **29 date-inferred rows → ~5**.

### ❌ RETRACTED — "they were always on the retro book" was WRONG

I inferred from the audit log that the flip never moved these accounts. **Jiho
challenged the inference** — *"what if they just never logged it, or is this
genuinely true because a log would have been logged systemically?"* — and also
noted it **contradicted what membership leadership said about how members get added to retro.**
He was right on both counts.

**The log cannot support the claim.** Logged `AccountManager` changes on these
accounts run 2018 → **2025-06-11 and then stop**, while logged `Duesbillmonth`
changes continue with **52 in 2026**. So "zero manager changes in 2026" is
indistinguishable from "manager changes stopped being logged in 2026."

**A log-independent test settles it.** Archived `Adjusted Retention` exports
carry **MID + Territory**, so exact zero-padded ID matching needs no inference:

> **38 of 107 retro rows (36%) appear in an archived retention export under a
> REAL territory.** SpokaneNE 11 · Snohomish 8 · NorthKing 5 · NorthCentral 3 ·
> Pierce 3 · Southwest 2 · TKP 2 · SouthKing 2 · EastKing 1 · Southeast 1.

**`Hilton Hotel Employer LLC` was on SpokaneNE's book, seen 2026-06-02 — nine
days before its 2026-06-11 flip.** So the move demonstrably happened, and the
audit trail simply does not record it.

**Corrected conclusions:**
1. **The retro flip DOES move accounts off a TM's book, and does NOT log it.**
   That is a real defect, and a worse one than a lost field — the account's own
   history denies that anything happened. → BROKEN-RECORDS.
2. **Territory IS recoverable — 36% today** (was 1/107 before; my first attempt
   read the wrong column). The limit is *archive density*: recovery works when an
   archived export exists shortly before the flip. Combining with the archived
   billables route (29/103 by name) should raise it further — union not yet computed.
3. **Jiho's "check daily" instinct was right after all.** Going forward, capture
   photographs the owner before the flip; the gap is only historical.
4. Hilton's profile still shows the dual nature that made the wrong story
   plausible — L&I 231,303-29, Retro Program Year 2026, Corp. Name *"NFA29 RRO
   Hilton Motif Seattle"* **and** Dues Level $4,944.50 at bill month 6, 319
   rooms, Sales Code *"WHA Lodging Dues (51+)"*. Dual-purpose, **but it had a
   territory.**

### 🆕 Two more things the audit log gave us

1. **An undocumented status: `Pending Sold`.** Hilton's real sequence was
   Active → Inactive (2026-04-09) → **Pending Sold** → RRO LNI Active
   (2026-06-11). Nothing in any doc or export mentions this intermediate state.
2. **`history` is a general-purpose field-level audit log with old values** — we
   did not know this existed. It is directly relevant to three open defects:
   D4 (which field is the true leave date), B3 (`ReinstatedDate` overwritten),
   and B2 (backdated cleanup) — **all three may be answerable from the log
   rather than by asking anyone.** Worth a dedicated pass.

### ~~🔴 THE REMAINING PROBLEM — 88 of 222 drops (40%) have no usable territory~~ *(superseded above; kept for the reasoning)*

The retro flip overwrites `AccountManager` to Retro Coordinator, so a counted
RRO exit cannot be attributed to the TM who lost it. **Three recovery routes
tried, all failed:**

| Route | Result |
|---|---|
| `AccountExtension.Originator` | Present on 72/95, but resolves to **24 long-departed staff ids, none of them current TMs** — it is the original seller, not the territory |
| Archived retention snapshots (monthly, back to Sep 2025, carry MID + Territory) | **1 of 107 recovered.** Retro members are already absent — the export is currently-active-only (C3). ⚠️ column indices verified only on the 7/26 layout, so **one more pass is warranted** before calling it dead |
| The account record itself | Nothing preserves the prior owner; `CRetroOldWRAID` is set on 22 of 307 |

**A fourth route PARTLY works — archived billables snapshots.**
`BillablesbyTerritorynoAllied` archives (2024-08 → 2026-07) list members **under
their territory heading**, so a pre-flip snapshot still shows the real owner.
**Recovered 29 of 103 (28%)**, mostly from the 2024-08 snapshot.

⚠️ **Ceiling unknown.** Those archives come in **two layouts** — grouped
(territory as a header row, .xls) and flat (territory repeated per row, .csv,
13 cols). The flat files yielded **zero**, which is either a parser gap or
genuine absence; not resolved. So 28% is a floor, not a limit.

### The durable answer is forward-looking, and it is Jiho's own

> *"We will just have to accept drops' territory will have to be checked on a
> daily basis… but I don't think the administrator was doing daily pulls."*

Exactly right, and it explains the whole history: **the membership administrator never needed the
pre-flip territory, because the official process never counted these members at
all** (proven — 70 of 101 appear in official monthly runs, every one in an RRO
section). The territory was only ever lost for a number nobody was computing.

**So:**
- **FY26-27 onward — SOLVED by capture.** Our daily/monthly snapshots photograph
  `AccountManager` before the flip can wipe it. No ask required.
- **FY25-26 history — 28% archive-recoverable**, the rest needs a presentation
  ruling: (a) an honest `Retro Coordinator` row, (b) statewide-only for RRO
  exits, (c) leave them out of the territory split but in the statewide total.
- **The ask (nice-to-have, not blocking):** can the flip preserve the prior
  owner? `CRetroOldWRAID` exists and is filled on 22 of 307.

**Only (a)/(b)/(c) needs a Jiho decision. Nothing here blocks the build.**

---

## The original sealing checklist (all steps now implemented)

Per Jiho: *"let's not rush, cuz once we get to building and it doesn't check
out that's annoying."* Drops is NOT sealed until a standalone script (no engine
changes) does this end-to-end on the real export and survives eyeballing:

1. Parse all 264 rows with the status group (`scripts/parse_drops_export.py`)
2. Key every row to SLX via `CustomerNo` — **conservation: every row keys or is
   named in a failure list** (target: better than the name bridge's 263/264)
3. Apply the universal gate row by row — billed at the previous occurrence of
   its cycle (net-positive ask), special-book carve where applicable
4. Attribute each counted drop to its month via the evidence hierarchy
   (comment → BM 1–12 field → date inference, flagged)
5. Band T/NT, attach territory (incl. the RRO-territory recovery attempt)
6. Emit the per-territory / per-month counts + dollars **with every excluded
   row listed next to the rule that excluded it**

Only when that output makes sense line by line does the logic move into the
engine. *(This is GATE-C conservation thinking applied before the build
instead of after.)*

---

## Open items

| # | Item | Status |
|---|---|---|
| 1 | **The 24% undercount** — ours 155 vs their **210** (corrected comparable) | The blocking issue. Partly our own subtraction error (157 vs 163) |
| 2 | **25 CRM-listed drops absent from our data entirely** | Capture-gap investigation; inherited by `reports/dues_analysis` |
| 3 | **Unmanaged accounts** (`[a member]`, `AccountManager` empty) | Invisible to all user-keyed sweeps; needs a manager-less status sweep. **Prime suspect for #2** |
| 4 | **Drop keying Account-ID → Member-ID** | Member-ID confirmed correct by the truth PDF; needs a re-pull |
| 5 | **RRO / bill month 14** | Contradiction above |
| 6 | **19 reasons into the report face** | **LOCKED 2026-07-29: direct wire.** Mapper + template work |
| 8 | **Closed Businesses sheet — KEEP (Jiho, 2026-07-29 PM).** It is a **subset of drops** — the export's own `Closed` status group — so keeping is nearly free: same parse, same FY window as the export, and it mirrors `accounts.Status` **by construction**, satisfying *"if the administrator sees somebody closed and checks SLX, she better find it closed."* Remove later only if it becomes a problem — *"drops come first"* | ✅ |
| 9 | **Territory of a counted RRO exit** — the flip also overwrites `AccountManager` to RetroCoordinator, so WHICH TM lost the member is erased along with the bill month. Recovery candidates: `AccountExtension.Originator`, invoice-era evidence. Ours to investigate; if unrecoverable → statewide-only attribution + broken-record list | us |
| 7 | Drop-$ valuation (~23% low on matched) | Superseded properly by the dues-ledger build |

**Truth-source note:** the drops truth is a **single-month window**, not
FY-to-date (STATE, "still-useful confirmations"). Comparisons must respect that.

---

## The SData-era definitions (`logic/drops.py`) — kept because the detail sheets still use them

*Ratified 2026-07-14. The Crystal pivot moved the COUNTS to the export, but the
`Data - Drops` and `Data - Closed Businesses` detail sheets still come from here.*

- **Drop** = the account went **Inactive**. **ALL** `Statusreason` values are
  counted and categorised (Closed / Sold / Non-Payment / Voluntary); the
  **ADMIN_REASONS** (Admin / Retro-program) are **EXCLUDED from the counts**.
  *(Supersedes the old 2-reason whitelist — 'Non-Payment'/'Sold' only — which
  undercounted **206 vs 450**.)*
- **Closed Business** = the physical business no longer exists. Reported on its
  own sheet.

### Data sources (confirmed live 2026-05-08)

| Entity | Supplies |
|---|---|
| `accounts` | name, type, territory (via `AccountManager.Id`) |
| `AccountExtension` | `Statusreason`, `Dateclosed` — **`Dateclosed` is mostly unpopulated, do not rely on it** |
| `history` | `'Change to Status'` records give the **actual** drop date (39,323 records confirmed) |
| `cRestProfiles` | `Avgrangefteperloc` (93% coverage) for the employee band and restaurant Target classification |
| `cMemberGens` | `Rooms` (reliable) for hotel Target classification; `Duesbillmonth` for the renewal month |

### Drop date — a two-tier source with a known weakness

**Primary:** the `history` entity's `'Change to Status'` records — the most recent
Active → Inactive transition, using its `CreateDate`.
**Fallback:** `AccountExtension.StatusDate` — populated on virtually all records,
represents when the `Statusreason` was recorded. **May lag the actual drop by
days or weeks if entered retroactively**, but is consistently available.

> This two-tier design is exactly why the `[a member]` class exists:
> the history log goes stale when a reactivation is never logged, so its "most
> recent" transition can predate a live invoice by years. Measured live
> 2026-07-28: only **5 of 14** inactivated BM5 members had a history record at
> all. See `_SHARED.md`.

**Employee count:** `Avgrangefteperloc` → midpoint via `target._RANGE_MIDPOINTS`
— **the single source of truth, imported from `target.py`. Do not re-declare it
here or it will drift.** `Totalemployees` is 97% null — do not use.

---

## ✅ The exports DO share a key — `CustomerNo` (corrected same day)

My "different namespaces" finding was wrong; ISSUELOG's *solved-once* table had
it: **the export Member ID = "WRA Member #" = `CustomerNo` on invoice headers.**
Verified live: `CustomerNo eq '0050811'` → the RRO Evergreen's 32 retro
invoices; `'0010748'` → the *other*, active Evergreen's 438 member invoices.
Two same-named businesses. The zero ID overlap between the drops and retention
exports is **C3** (retention export is currently-active-only), not a key
mismatch.

**So every export row keys to its SLX invoices directly — the universal gate
above is implementable with no name-matching**, and the S6 name bridge
(263/264) can likely be retired for banding too.

---

## Available truth sources

**Parse with `scripts/parse_drops_export.py` *(archive repo)*** —
it reads the `Status` group. Snapshots land in `data/truth/` (gitignored).

| Source | Status group | Per-row date |
|---|---|---|
| `Dropped Members - Hospitality` | ✅ | ❌ bill month only |
| `Dropped Allied Report` | ✅ (**no RRO block**: 46 Inactive + 1 Closed) | ✅ `Status Date` 2025-10-28 → 2026-06-30 |
| `Dropped Members By Type` | ❌ | ❌ |
| `Dropped Members By Ac` | ❌ | ✅ — only 20 rows, incl. `[a member]` (2026-06-18) |

- Crystal `Dropped Members - Hospitality` (264 rows, $269,277, 19 reasons)
- Crystal `Dropped Members By Type`
- Crystal `Dropped Allied Report`
- **the previous analyst's June PDF** — `DroppedMembersHospitality_HannahCB_2026_06_03_1240.pdf`
- Prior CRM exports 2026-07-22 and 2026-07-26 in `~/Downloads`
