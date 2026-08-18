# MPR Metric Catalog

Every metric the report produces: what it means, where it comes from, whether it
is verified, and what is still unanswered. **Rewritten 2026-07-31 against the
recorded 7/30 call.**

> ⛳ **PRIMARY EVIDENCE lives in `source-documents/` *(archive repo)*** —
> the 7/30 MPR meeting transcript, the 7/22 dues call, leadership's
> standardization summary, and the team's own SOPs. **They outrank this
> catalog.** Where a transcript and a doc disagree, the transcript wins and the
> doc is marked superseded, never silently edited to agree.

**Status key** — 🟢 verified against an external source · 🟡 partially verified ·
🔴 unverified or known wrong · ⚪ pass-through (no computation to verify)

**This catalog is the source of truth.** Each row owns one file in
[`docs/metrics/`](metrics/), linked from its Notes cell (📄). That file holds
everything known about the metric, gathered from every doc, decision log and
handoff — contradictions kept side by side rather than resolved silently.
Cross-cutting knowledge that belongs to no single row lives in
[`metrics/_SHARED.md`](metrics/_SHARED.md) (our rules) and
[`metrics/_EXTERNAL.md`](metrics/_EXTERNAL.md) (SLX/Crystal defects and the
consolidated open-question register). Superseded rules still written down
elsewhere are tracked in [`metrics/_STALE.md`](metrics/_STALE.md).

**Sibling rows share a file.** Target and Non-Target variants of one metric are
the same definition with a band filter, so they point at the same document
rather than duplicating it — two copies of one fact carry no more meaning than
one, and would drift apart on the first edit.

---

## Retention

| Metric Name | Definition | Source | Status | Explanation | Open Question | Owner | Notes |
|---|---|---|---|---|---|---|---|
| **Members Up for Renewal — Target (#)** | Target members holding a dues invoice for bill month M | SData `dlInvoiceHistoryHeader` | 🟢 | The denominator. Invoiced for that cycle and not exited before it closed. **A member who flips to RRO leaves the cycle entirely — both sides of the ratio** (the administrator 7/30: *"they removed the six month, put it in bill month 14 — completely removed out of June's retention"*). | — *(base day ANSWERED 7/29: pay-window close, end of M+1)* | ratified | 📄 [`metrics/retention-members-up-for-renewal-target.md`](metrics/retention-members-up-for-renewal-target.md) — Allied is INCLUDED (Non-Target) per the T/NT lock |
| **Members Retained — Target (#)** | Of those, the count who paid **any** amount by the cycle close | SData `dlInvoiceHistoryHeader` + `payAllocationViews` | 🟢 | Partial payers count — and this matches the utility, which *"will keep a member as Active for one full year if ANY payment was made"* (leadership's summary). **No grace period** — the administrator 7/30: *"If I was queen for the day I would not allow that… It's when they pay. Facts are the facts."* Late-payment exceptions are leadership's manual approvals and belong in an adjustments tab, never in logic. | — | ratified | Close = end of M+1. **Verified one bill month only** (HCB file) · 📄 [`metrics/retention-members-up-for-renewal-target.md`](metrics/retention-members-up-for-renewal-target.md) |
| **Members Up for Renewal — Non-Target (#)** | Same, Non-Target band | same | 🟢 | | | | Members with no size on file count Non-Target (the Unknown bucket, ~35% of billed accounts) · 📄 [`metrics/retention-members-up-for-renewal-target.md`](metrics/retention-members-up-for-renewal-target.md) |
| **Members Retained — Non-Target (#)** | Same, Non-Target band | same | 🟢 | | | | · 📄 [`metrics/retention-members-up-for-renewal-target.md`](metrics/retention-members-up-for-renewal-target.md) |
| **Revenue Up for Renewal — Target ($)** | Dollars asked of the Target cohort | SData `Net_invoice` | 🟡 | **Upward adjustments raise the ask** (fixed 7/30 — they previously raised only the collected side, so retention printed **100.9%** in Snohomish Oct; 13 of 188 cells were over 100%). | **Should a WRITE-OFF also reduce the ask?** Three of our own records disagree — the net-ask rule says yes, the 7/28 tests say no, the Dues-Level ruling says neither. One option silently makes a written-off member count as RETAINED | Jiho | 📄 [`metrics/retention-revenue.md`](metrics/retention-revenue.md) — `Invoice_total` is always null; `Net_invoice` carries the amount |
| **Revenue Retained — Target ($)** | Dollars actually collected by the close | SData invoice + adjustments | 🟡 | Collected = ask + adjustments − outstanding; **can never exceed the ask** (7/30 fix). A write-off is not a payment. | — | | 📄 [`metrics/retention-revenue.md`](metrics/retention-revenue.md) — fixed 7/28: write-offs previously counted as paid |
| **Revenue Up / Retained — Non-Target ($)** | Same, Non-Target band | same | 🟡 | The **Unknown** size bucket (~35% of billed accounts) folds in here so Target + Non-Target = the true total | | | 📄 [`metrics/retention-revenue.md`](metrics/retention-revenue.md) — |

---

## Billables

| Metric Name | Definition | Source | Status | Explanation | Open Question | Owner | Notes |
|---|---|---|---|---|---|---|---|
| **Billables — Hospitality Target (#)** | Active hospitality members, 10+ FTE / 40+ rooms | **SData** (Crystal overlay removed 7/30) | 🟡 | *"Any active record with a dues or investment level and a membership product"* (the administrator 7/30). Point-in-time — describes the day it ran. **Members enrolled AFTER the reported month are excluded** so the administrator no longer has to withhold activation. **RRO members are not billable** — *"once that member flips, they're no longer considered a billable"*. Run AFTER ITD. | — *(the two-reports question CLOSED 7/29: they answer different questions — snapshot vs billing schedule)* | ratified | 10/10 territories vs the CRM (2,294 vs 2,293) · 📄 [`metrics/billables-hospitality-target.md`](metrics/billables-hospitality-target.md) |
| **Billables — Hospitality Non-Target (#)** | Active hospitality below the size threshold, **plus** members with no size on file | same | 🟢 | Size-less members ride here — **confirmed in-call 7/30** by both the administrator (*"that's fair"*) and membership leadership (*"if it were truly a target, there would be FTEs in there"*), with the data-hygiene caveat that FTE should be updated at sale. | — | ratified | 📄 [`metrics/billables-hospitality-target.md`](metrics/billables-hospitality-target.md) |
| **Billables — Allied (#)** | Active members whose membership **product** name contains "Allied" | **SData** | 🟡 | Allied is decided by the product, not `Type` — `[a member]` is Type "Corporate" with product "Allied Corporate". Allied is always **Non-Target** (T/NT lock). | Residual: SData 162 · the administrator 164 — small and unexplained; the 11 house-managed vendor partners sit outside every territory column (Jiho 7/30: *"if they don't have a territory they don't belong anywhere"*) | Jiho | 📄 [`metrics/billables-hospitality-target.md`](metrics/billables-hospitality-target.md) |

---

## Drops

| Metric Name | Definition | Source | Status | Explanation | Open Question | Owner | Notes |
|---|---|---|---|---|---|---|---|
| **Drops — Target (#)** | Target members lost in cycle M | **Crystal** `Dropped Members - Hospitality` (+ the Allied export) | 🟡 | **`Inactive` + `Closed` status groups ONLY.** RRO / RRO LNI Active are **never drops** — the administrator 7/30: *"RRO is not a dropped"*; they sit on her report *"just as FYI"* and reach our flag list instead. **Bill month 14 is out regardless of status.** Allied drops are merged in as Non-Target. **🆕 7/31: filed by FLIP DATE (event axis — the administrator's own SOP convention); dateless rows take the conditional class-close fallback, flagged.** Stale strays (last dues invoice predates their own previous cycle) are excluded and named in the flags. | — *(the RRO question is ANSWERED — this row's whole premise changed 7/30)* | ratified | 📄 [`metrics/drops-target-count.md`](metrics/drops-target-count.md) — the old "155 vs 204" gap died with the RRO ruling: their 204 counted RRO rows we correctly exclude |
| **Drops — Non-Target (#)** | Same, Non-Target band | same | 🔴 | | Same | | · 📄 [`metrics/drops-target-count.md`](metrics/drops-target-count.md) |
| **Dropped Revenue — Target ($)** | Dues value of Target members lost | same | 🟡 | Value = the member's **Dues Level**; $100 remnant floor; **credits never value a drop**. A counted drop inside the billing system always carries dollars (Jiho: *"a dropped member with no $ lost is unacceptable"*); special-book members (NRA etc., never billed) drop at $0, disclosed. | — *(RRO revenue question is moot — RRO is not a drop)* | ratified | 📄 [`metrics/drops-target-count.md`](metrics/drops-target-count.md) |
| **Dropped Revenue — Non-Target ($)** | Same, Non-Target band | same | 🔴 | | Same | | · 📄 [`metrics/drops-target-count.md`](metrics/drops-target-count.md) |
| **Drops — \<Reason\> (#)** ×19 | One row per Crystal status reason (`Out of Business`, `Sold`, `Non-Payment`, `No Answer`, `Budget`, …) | same | 🟡 | Replaces the 5 buckets SData invented. **⚠️ Reasons are hand-curated**: ITD stamps everyone `Non-Payment`, then a specialist re-classifies from the Third Notice notes and re-runs — so an export pulled before curation is mostly `Non-Payment` (official SOP; curation due by the 7th). | — *(LOCKED 7/29: all 19 wire straight through — the 5 buckets were "semantic reduction with no benefit")* | ratified | Template still shows the old 5; mapper + template work outstanding · 📄 [`metrics/drops-target-count.md`](metrics/drops-target-count.md) |

---

## New Sales

| Metric Name | Definition | Source | Status | Explanation | Open Question | Owner | Notes |
|---|---|---|---|---|---|---|---|
| **New Members — Target (#)** | First-time payers (and genuine returns), Target band | SData `cMemberGens.EnrolledDate` | 🟡 | Counted in the month their **first payment arrives** — a sale is not a sale until paid. **A rejoin after ~6 months IS a new member** (the administrator 7/30: *"That exact same member"*) — and because the admin **rewrites the enroll date** on such rejoins, the EnrolledDate cohort is already correct. **Separately-billed child locations COUNT**; a location that merely raises the corporate's dues is a **dues adjustment**, not a new member. **A member should never be active without payment — any exception is FLAGGED, not silently dropped.** | Reinstate window is ~6 months but **unconfirmed** — the administrator to confirm 60d/90d/6mo. One constant: `target.REJOIN_NEW_MEMBER_MONTHS` | the membership administrator | 📄 [`metrics/new-members-target.md`](metrics/new-members-target.md) — the prior-payer screen was REMOVED 7/30; it wrongly excluded genuine rejoins like Jalapenos |
| **New Members — Non-Target (#)** | Same, Non-Target band | same | 🟡 | | Same | ratified | 📄 [`metrics/new-members-target.md`](metrics/new-members-target.md) — Allied counts as a new member and is always Non-Target |
| **New Sales Revenue — Target ($)** | First-year dues from new Target members | SData invoices + `payAllocationViews` | 🟡 | **Each payment counts in the month it ARRIVES** — installments land as they come (the administrator 7/30). CMP excluded (claims-programme fee); NRA contributes $0 (never billed — they pay quarterly). Seller credit follows `Acct. Originator`. | — *(ANSWERED 7/30: money in the month received)*. Payment plans have **no SLX field** — detected by payment pattern (10 in the whole FY); Zooie holds an Ebiz list | ratified | 📄 [`metrics/new-sales-revenue-target.md`](metrics/new-sales-revenue-target.md) — verified 9 months × 11 territories (7/22): Jan within $208, Feb $346, May $1,068 statewide; June 8/11 $-exact. **Oct–Mar gaps are the SPLICE class** — her Oct–Mar editions came from her personal tracker (sale value), Apr–Jun from the CRM report (paid). Not errors on either side |
| **New Sales Revenue — Non-Target ($)** | Same, Non-Target band | same | 🔴 | | Same | | · 📄 [`metrics/new-sales-revenue-target.md`](metrics/new-sales-revenue-target.md) |
| **BOB — Target ($)** | The comped share **inside** New Sales Revenue, so a reader can subtract it and see cash | SData invoices (`Po_number` = "BOB Two Year Membership") | 🟡 | **An annotation, not a metric of its own.** BOB is a **trait of a member, not an enrollment type** (Jiho 7/30) — new/rejoin logic applies to BOBs like anyone, and the comp substitutes for the *payment* requirement, never the *novelty* one. **Identity = the flag**: a team lead confirmed 7/30 that the SLX group "Black Owned Businesses" IS `Diverse Ownership` + a date (36 active). | ⏰ The 2-year comp starts renewing **Oct 2026** (first notice ~Sep 1 — M-1, same event). Landing in normal billing IS the intent, not a landmine: a team lead, 8/4 — *"there's something already built into the billing export that on a B[O]B account based off the date they joined… After their second year, they're going to land into our normal billing, which is going to prompt AR."* Year 3 renew = retention, don't renew = counts against (ruled 8/4). Our code needs nothing: `_bob` is set only while a comp is actually applied, so year 3 flows through the ordinary retention path. **Corrected 2026-08-11** — the old note said they would be wrongly invoiced "unless excluded (Zooie has a process in flight)", which inverted it | Admin | 📄 [`metrics/bob-target-revenue.md`](metrics/bob-target-revenue.md) — flag and invoice-label routes agree ~100% (36/36 with invoices) |
| **BOB — Non-Target ($)** | Same, Non-Target band | same | 🔴 | | Same | Jiho | 📄 [`metrics/bob-target-revenue.md`](metrics/bob-target-revenue.md) — |
| **New Sales Revenue — BOB/Promo ($)** | Combined promo face value | same | 🔴 | The only one of the three whose name matches what it computes. | Same | Jiho | 📄 [`metrics/bob-target-revenue.md`](metrics/bob-target-revenue.md) — |

---

## Penetration — Target

| Metric Name | Definition | Source | Status | Explanation | Open Question | Owner | Notes |
|---|---|---|---|---|---|---|---|
| **Total Target Locations — Restaurant (#)** | Market size: all qualifying restaurants, member or not | SData `accounts` | 🟢 | Denominator = Active + Inactive. **Code uses `Type = 'Restaurant'` only** (REFERENCE's wider whitelist — Catering/Recreational/Concession — is stale; STATE agrees with the code). Excludes Corporate / Grocery / Non-Commercial. | — | ratified | · 📄 [`metrics/penetration-target-lodging.md`](metrics/penetration-target-lodging.md) |
| **Total Target Locations — Lodging (#)** | Market size: hotels **40+ rooms** | SData `accounts` | 🟢 | Threshold is **40+**, confirmed by the membership administrator 2026-07-21 (supersedes the 7/19 41+ ruling). Code matches (`TARGET_ROOMS_MIN = 40`). | — *(was 'is it 40 or 41?' — answered; REFERENCE.md and 5 code comments are stale at 41+)* | ratified | 📄 [`metrics/penetration-target-lodging.md`](metrics/penetration-target-lodging.md) — the 23 forty-room hotels are **in** the universe |
| **Target Members — Restaurant (#)** | Active qualifying restaurant members | SData `accounts` | 🟢 | Numerator. | — | | Matches the CRM exactly: TKP 56/56, NorthCentral 52/52 · 📄 [`metrics/penetration-target-lodging.md`](metrics/penetration-target-lodging.md) |
| **Target Members — Lodging (#)** | Active qualifying lodging members | SData `accounts` | 🟢 | | — | | · 📄 [`metrics/penetration-target-lodging.md`](metrics/penetration-target-lodging.md) |
| **Penetration — Restaurant %** | Members ÷ market | derived | 🟢 | | — | | · 📄 [`metrics/penetration-target-lodging.md`](metrics/penetration-target-lodging.md) |
| **Penetration — Lodging %** | Members ÷ market | derived | 🟢 | | — | ratified | 📄 [`metrics/penetration-target-lodging.md`](metrics/penetration-target-lodging.md) — should match the CRM report directly now that 40+ is adopted |
| **Penetration — Combined %** | Both segments combined | derived | 🟢 | | — | ratified | · 📄 [`metrics/penetration-target-lodging.md`](metrics/penetration-target-lodging.md) |

---

## Penetration — Non-Target

| Metric Name | Definition | Source | Status | Explanation | Open Question | Owner | Notes |
|---|---|---|---|---|---|---|---|
| **Non-Target Locations — Restaurant (#)** | Market size below the size threshold | SData `accounts` | 🟡 | Sub-threshold hospitality — smaller restaurants and hotels. | Is there a CRM report to check these against? None exists today | the previous analyst | No external source has ever validated the Non-Target band · 📄 [`metrics/penetration-target-lodging.md`](metrics/penetration-target-lodging.md) |
| **Non-Target Locations — Lodging (#)** | Same, lodging | same | 🟡 | | Same | | · 📄 [`metrics/penetration-target-lodging.md`](metrics/penetration-target-lodging.md) |
| **Non-Target Members — Restaurant (#)** | Active sub-threshold restaurant members | same | 🟡 | | Same | | · 📄 [`metrics/penetration-target-lodging.md`](metrics/penetration-target-lodging.md) |
| **Non-Target Members — Lodging (#)** | Active sub-threshold lodging members | same | 🟡 | | Same | | · 📄 [`metrics/penetration-target-lodging.md`](metrics/penetration-target-lodging.md) |
| **Penetration — Restaurant / Lodging / Combined Non-Target %** | Members ÷ market, same formula as Target | derived | 🟡 | | Same | | · 📄 [`metrics/penetration-target-lodging.md`](metrics/penetration-target-lodging.md) |

---

## Goals

| Metric Name | Definition | Source | Status | Explanation | Open Question | Owner | Notes |
|---|---|---|---|---|---|---|---|
| **Goal — New Sales Revenue ($)** | Monthly revenue target per territory | `admin_inputs.xlsx` (SharePoint) | ⚪ | Typed by admin; the report reads it as-is. | — | Admin | 📄 [`metrics/goals.md`](metrics/goals.md) — NorthKing / Pierce / Spokane-NE are intentionally null (commissioned on total revenue) |
| **Goal — New Members (#)** | Monthly member-count target | same | ⚪ | | — | Admin | 📄 [`metrics/goals.md`](metrics/goals.md) — |
| **Goal — Retention %** | Retention target per territory | same | ⚪ | Constant across months per territory | — | Admin | 📄 [`metrics/goals.md`](metrics/goals.md) — default **92%** (`DEFAULT_RETENTION_GOAL`) |

---

## Cross-cutting definitions

| Term | Meaning | Status | Open Question |
|---|---|---|---|
| **Target vs Non-Target** | **Size.** Restaurants 10+ FTE; hotels **40+ rooms**. Not a member type. | ratified 2026-07-13, rooms revised to 40+ **2026-07-21 (the membership administrator)** | How are Corporate / Grocery classified in the retention and revenue splits? · 📄 [`metrics/_SHARED.md`](metrics/_SHARED.md) |
| **Allied** | **Type**, not size. A supplier. Decided by the membership **product** name. | ratified (D2 product test) + **RULED 2026-08-11 (Jiho): INCLUDED in retention as Non-Target** | Always Non-Target. **In** retention % (a billed allied member counts on both sides; an unbilled one was never in the cohort). Still excluded from penetration · 📄 [`metrics/_SHARED.md`](metrics/_SHARED.md) |
| **Bill month** | The member's fixed annual dues month (`Duesbillmonth`, 1–12). "Mar" column = bill month 3, not calendar March. | ratified | BMs 13–16 are special groups; **14 = RRO** · 📄 [`metrics/_SHARED.md`](metrics/_SHARED.md) |
| **Cycle close** | End of M+1. Notices: 1st M−1, 2nd M, 3rd M+1 — ~90-day pay window. | sourced from the membership administrator's call | — · 📄 [`metrics/_SHARED.md`](metrics/_SHARED.md) |
| **Billable** | Scoped to the **bill month**, fixed at month end — not a rolling status. | answered by Jiho 7/28 | Which day fixes it: end of the bill month, or end of M+1? · 📄 [`metrics/_SHARED.md`](metrics/_SHARED.md) |
| **RRO** | Retro Refund member = bill month 14. Stopped paying dues, still in the L&I insurance programme. | answered by Jiho 7/28 | Do the 105 BM14 rows represent the *transition* (a countable drop) or later RRO activity (out of scope)? · 📄 [`metrics/_SHARED.md`](metrics/_SHARED.md) |
| **Display offset** | Month M's retention column shows bill month **M−1** — the cycle that closed in M. | ratified | — · 📄 [`metrics/_SHARED.md`](metrics/_SHARED.md) |
| **Majors/NRA** | ~893 national chain accounts, $0 dues in SLX (they pay national). Excluded from retention and penetration. | ratified | NRA revenue is a finance figure, not an SLX pull · 📄 [`metrics/_SHARED.md`](metrics/_SHARED.md) |

---

## Where the risk is

| Status | Count | Which |
|---|---|---|
| 🟢 verified | 9 | Retention members, penetration Target |
| 🟡 partial | 17 | Billables, retention revenue, new members, penetration lodging + Non-Target |
| 🔴 unverified | 11 | **All of drops**, new sales revenue, all of BOB |
| ⚪ pass-through | 3 | Goals |

**Correction 2026-07-29:** drops HAS been checked — and it failed. `RECONCILIATION.md`
records ours **155 vs their 204** (−24%, lower in every territory) and dollars at
**67% of theirs**, with the verdict *"NOT ready to wire into the engine."* BOB has
only ever had a **single-member spot check**.

So the risk is sharper than "unverified": drops is **known wrong by a measured
margin**, and BOB is effectively unmeasured.
