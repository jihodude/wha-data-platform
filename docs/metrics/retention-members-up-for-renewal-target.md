# Members Up for Renewal — Target (#)

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


**Family:** Retention · **Catalog row:** 1 · **Engine field:** `ret_billed_target`
**Status:** 🟢 verified (bill month 5 only) · **Last updated:** 2026-07-28

The **denominator** of member-basis retention. Count of Target-band members who
held a dues invoice for bill month M and had not exited before that cycle closed.

---

## Definition as built

Source: SData `dlInvoiceHistoryHeader`, filtered `Comp_code = 'WRA'`.
Code: `retention._retention_counts` → `_retention_target_split`.

### 🔴 DEFECT FIXED 2026-07-30 — the T/NT split did not apply the strict close

Found by an invariant sweep of the whole live grid, not a spot check:
**Target + Non-Target EXCEEDED the combined total in 24 cells**, always by one
or two members (EastKing Nov `6 + 3 = 9` vs **8**; NorthKing Feb `14 + 7 = 21`
vs **20**).

**One rule, two implementations.** The combined path tested each member with
`retained_as_of` — the strict close, where money arriving after the cycle shut
is a reinstate and not a renewal (ratified 7/28, reconfirmed by the administrator 7/30:
*"It's when they pay. Facts are the facts."*). The split used
`_member_retained`, which only asks whether anything was ever collected, and
**did not even receive `as_of`** — so it could not have applied the rule.

**Every TM sheet reads the split.** Per-territory retention therefore counted
late payers as retained while the statewide number correctly refused them. This
is exactly the failure mode Jiho named — computation scattered per TM sheet
instead of solid in one central place.

`compute_retention_all_months` also computed the close **inline** at the
combined call site, so the two paths had no shared value to drift from. It is
now bound once (`cycle_as_of`, `month_payments`) and passed to both.

⚠️ **Numbers move on the next pull.** Any workbook generated before 2026-07-30
carries the 24 overcounted cells.

### 🔶 EXTENDED 2026-07-30 (late) — rescinded asks: one rule, two vehicles

The ratified NET-ASK exclusion ("an ask fully rescinded and never reissued is
not an ask", 7/28) only examined **adjustment**-bearing accounts. A **credit
invoice** rescinds the same way and slipped past it into the count path, where
credit-zeroed balances read as a fully-paid $0 bill — the member counted
RETAINED while the dollars path excluded them. Now one predicate
(`_cycle_rescinded`) covers both vehicles at the cohort level, so count and
dollars always agree, and the run log names every removed account.

**The nine live cases (probe-verified, all vehicles=credit-invoice):** all
still **Active**, unchanged bill months, not dropped, not RRO, no diverse/comp
flag. Billed at cycle start, credited off weeks later, never re-billed.
`Governor Hotel Olympia` · `Velvet's Big Easy` · `Guesthouse Inn & Suites` ·
`Mt Spokane Ski & Snowboard Park` · `Latah Bistro` · `Silverbeard's Marina` ·
`Skyway Cafe` · `Hama Hama Oyster Saloon` · `Falls Terrace Restaurant`.

**✅ ANSWERED 7/31 — they are COMPS.** All nine accounts' notes were read:
seven explicitly comped/waived (Governor renovation · Latah road-closure,
membership leadership-approved · Skyway fire · Mt Spokane · Silverbeard's via BOB ·
Velvet's hardship · Falls Terrace), zero contrary, two silent (ride the same
rule, blessed). **RULED (Jiho): rescinded + still Active ⇒ comp ⇒ counted
RETAINED at $0/$0** (cash-anchored dollars). Non-active rescissions stay
excluded. Code: `comp_or_rescinded`.

### ✅ RESOLVED 7/31 — the King County three-invoice pattern (was A1b-NEW)

Seven SouthKing members carry three SAME-DAY invoices per cycle: $65 county
fee + dues + combined (dues+fee). The payment ledger answered it: **all seven
visible allocations sit on the COMBINED invoice, zero on the splits** — the
combined invoice is the bill. **RULED (Jiho): combined = the ask** ("its
their invoice so why not count"). Detection is mechanical: a positive invoice
equal to the sum of the other positives wins. The $65-per-member cell dies on
the next pull (~$1,820/member).

A member is in the cohort when **all** of these hold:

| # | Rule | Origin |
|---|---|---|
| 1 | They hold an invoice for this cycle (invoice-anchored, not roster-anchored) | ratified 2026-07-27 (denominator A vs B test) |
| 2 | The cycle is theirs — anchored on `Comment = M`, **or** on their own `Duesbillmonth` when their only bill carries a blank comment **and** they hold a membership product | 2026-07-28 (roster anchor) |
| 3 | The ask was not fully rescinded — an invoice voided and never reissued is not a bill | 2026-07-28 (net ask) |
| 4 | ~~They are not Allied~~ **REVERSED 2026-07-29** — Allied is included, as Non-Target. The D2 exclusion must be removed from `_retention_counts` | 7/13 ruling reaffirmed |
| 5 | It is not their first cycle — a first bill is not a renewal | ratified A2, 2026-07-14 |
| 6 | They had not exited mid-cycle — a member who left before the close is a **drop**, not a retention miss | 2026-07-28 |
| 7 | Territory ≠ Majors/NRA | ratified (`engine.NO_RETENTION_TERRITORY`) |

**Gate:** every invoiced account must end up either counted or claimed by a named
rule. One that vanishes unclaimed raises (`GATE C`, conservation).

---

## Axis and timing

- **Bill month, not calendar month.** The "Mar" column means `Duesbillmonth = 3`.
- **Display offset:** month M's retention column shows bill month **M−1** — the
  cycle that *closed* in M. Ratified 2026-07-14 from the team's archived sheets;
  decisive evidence was the handmade June TKP 12/14 = BM5 (BM6 was 29/35).
  October's column shows BM9 of the **prior** fiscal year.
- **Cycle close = end of M+1.** Notices: 1st = M−1, 2nd = M, 3rd = M+1 — a ~90-day
  pay window. Sourced from the membership administrator's call, transcript [J 1:40–2:15].
- **Live then frozen:** the cohort is computed as of `min(today, cycle_close)`.
  While the cycle is open the number moves; once shut it never moves again.
- **SOP timing (official, verbatim):** *"this is done for the 3rd notice just
  completed for the month i.e. if this is for **December month-end, you would
  provide the report data for BM 11**"* — the M−1 offset in the SOP's own example.
- **SOP timing:** use the 3rd notice of the month just completed. A report run
  April 1 is for March, using February's 3rd notice. "December month-end → use
  BM 11 data." Make all corrections to the 3rd notice.
- **ITD ordering (critical):** run retention **BEFORE** ITD, because ITD
  (Inactivate Members Utility) moves unpaid Active → Inactive.

---

## Known data hazards handled

- **Sage sync duplicates** — the same invoice imported twice, once `Balance = 0.0`
  and once `Balance = None`. Dedup by AccountId.
- **`Invoice_total` is always null.** `Net_invoice` carries the amount (confirmed
  2026-05-08).
- **Blank invoice comments.** The `Comment` field is data entry and has failed
  three ways: void-and-rebill replacements, late original bills, and both blank.
  Live case: `[a member]` #0148881, $795 WRA dues, blank comment, their only
  FY26 bill. Rule 2 exists because of this.
- **SData join under-fetch.** Queries joining via `Account.AccountManager.Id` on
  `cMemberGens` return incomplete rows on large sets. Mitigation: re-fetch missing
  accounts by `Account.Id` batches (`fetch_by_id_batches`). Flagged 2026-07-13 as
  affecting retention/revenue invoice fetches specifically.

---

## ⚠️ Contradictions — both statements preserved

### C1. Is Allied in or out of the retention denominator?

**Statement A — 2026-07-13, Jiho per department leadership's authority (DECISIONS.md:28):**
> "Allied gets NO special-casing — pure Target/Non-Target everywhere. **SUPERSEDES**
> 'Allied excluded from retention % with a side table.'" Allied is TYPE=supplier
> with no hospitality size, so it falls into **Non-Target across ALL member
> metrics including the retention %** — no Allied section, no side table, no
> retention-% carve-out.

**Statement B — 2026-07-28 (DECISIONS.md, cohort rules):**
> "D2 applied to retention. Allied is decided by the membership PRODUCT — Dick's
> Restaurant Supply is Type 'Corporate', product 'Allied Corporate', and belongs
> to billables, not hospitality retention. The engine previously never excluded
> allied from retention at all."

**Statement C — REFERENCE.md:56 (still live):**
> "Allied = TYPE (supplier) — **excluded from retention %**."

**Why this matters:** the membership administrator's file is *Hospitality* Retention — hospitality
only. RECONCILIATION.md:33 records the 7/21 resolution: *"our 20 = her 18 + two
ALLIED members (Scott Kingsbury CPA, Zoom Drain) — her file is hospitality-only,
our row includes Allied; pipeline itself exact."*

That reading says Allied belongs **in** our row and must be subtracted only when
*comparing* to her file. The 7/28 change excludes Allied from the computation
itself, which made SouthKing match her exactly — but if Statement A governs the
report, the published row should still include Allied as Non-Target.

### ✅ RULED 2026-07-29 (Jiho): **Allied is Non-Target — INCLUDE it.**

> *"Allied is non-target, include it. They are a nice to have but not targeted."*

Statement A governs. Allied members appear in the retention row, in the
**Non-Target** band. Statement C (the 7/28 D2 exclusion) is superseded for
retention; D2 still governs **billables**, where Hospitality and Allied are
counted separately.

**⚠️ CODE CHANGE REQUIRED — the current build is wrong for the published row.**
`_retention_counts` excludes Allied by membership product (added 2026-07-28).
That must come out, so Allied lands in Non-Target like any other sub-threshold
member.

**Consequence, and it is expected, not a regression:** SouthKing returns to
**10/10 vs her 9**. Her file is *Hospitality* Retention — hospitality-only by
construction — so the difference is `[a member]`, an Allied member
she never had. **Subtract Allied when reconciling to her file; publish with it
included.** Those are two different operations and were being conflated.

### C2. Is the axis "billed" or "billable"?

**Statement A — as built:** the denominator is *invoice-anchored* — members who
were actually invoiced. Test 2026-07-27: option A (invoice exists) = 150 for BM5;
option B (`Duesbillmonth`, active hospitality) = 355, **2.3× too big and dead**.

**Statement B — membership leadership, 2026-07-28 (relayed):** retention is
`(billed − closed) ÷ total billable`, and members who were dropped are still
billable.

**Statement C — Jiho, 2026-07-28:** billable is scoped to the **bill month**,
fixed at month end — not a rolling status.

These are three different denominators. A is what the code does and it reproduces
the membership administrator's published numbers; B and C have never been computed.

**✅ RESOLVED by the official MPR SOP (2026-07-29):** it instructs the preparer to
provide *"the number of **retained members versus billed members**."*

**Billed**, not billable. That is the process owner's own wording and it matches
statement A — the invoice-anchored denominator we built. leadership's
"(billed − closed) ÷ total billable" describes a different formula from the one
the SOP documents.

*(The remaining sub-question stands: which day fixes the month's base.)*

### ⚠️ And a warning from the Dues SOP that affects every reconciliation

> *"The retention reports **may or may not require manual adjustments**."*

The published retention figures can contain **hand adjustments that exist in no
report and no ledger.** A cell that will not reproduce may never have been
reproducible — which is a live candidate explanation for residuals we have been
attributing to our own logic.

**Open: what adjustments, and on what basis?**

---

## Validation history

| Date | Against | Result |
|---|---|---|
| 2026-07-14 | `AdjustedRetention` export (administrator), 1,969 members | Ground truth acquired. Zero June-2026 enrollee MIDs present → their "Adjusted" **excludes first-cycle members**, confirming rule 5 matches their convention |
| 2026-07-21 | HCB per-member file, BM5 (snapshot 7/2) | Resolved at member-ID level: our 20 = her 18 + 2 Allied. Pipeline itself exact |
| 2026-07-27 | the membership administrator's `Hospitality Retention BM 5 ALL.xlsx` | 7 of 10 territories exact on billed; +5 traced to a 10-account shortlist |
| 2026-07-28 | Same file, after strict close + cohort rules | **8 of 10 territories exact.** Both differences are documented rulings |

**Current live figures (BM5, as of 2026-07-28):**

| Territory | Ours (paid/billed) | Hers (paid) | |
|---|---|---|---|
| NorthCentral | 12/13 | 12 | ✓ |
| Snohomish | 9/11 | 9 | ✓ |
| NorthKing | 17/20 | 17 | ✓ |
| Pierce | 17/18 | 17 | ✓ |
| TKP | 12/14 | 12 | ✓ |
| Southwest | 17/18 | 17 | ✓ |
| SouthKing | 9/10 | 9 | ✓ |
| Spokane/NE | 29/31 | 29 | ✓ |
| EastKing | 8/9 | 7 | +1 [a member] (real $100 collected pre-close) |
| Southeast | 1/2 | 2 | −1 [a member] (paid 7/01, strict ruling) |

---

## The as-of curve (denominator reconciliation, 2026-07-28)

`view(D)` = invoiced cohort minus members inactivated before D. Reproduces both
published editions exactly:

| D | view(D) | matches |
|---|---|---|
| any June date | **146** | the membership administrator's file |
| ≥ 2026-07-15 | **136** | the CRM export |

**Mechanism:** nine BM5 accounts carry `StatusDate = 2026-06-30` but were modified
**2026-07-21** — a backdated batch cleanup. the membership administrator captured 7/20, the day
before; the export ran after. Same cohort, two capture dates, neither wrong.

The CRM's backdating target (6/30) equals end of M+1 — the same close the payment
dates independently produced.

---

## the membership administrator's own sanity check

> *"This month had 88% retention… **100% retention? I'd question that — I've
> never seen 100% retention**."* — [J 44:58–45:30]

A territory-month reading **100%** should be treated as suspect rather than
celebrated. Useful as a review heuristic, and a candidate for an anomaly flag.

**Related, from the same call:** *"bill month = the month the member joined"*
[J 1:21] — the plainest statement of the axis, and the reason a member's bill
month is stable rather than assigned per cycle.

---

## Open questions

| # | Question | Owner |
|---|---|---|
| 1 | Which day fixes the month's base — end of the bill month, or end of M+1? | membership leadership |
| 2 | Is Allied in or out (contradiction C1)? | department leadership / Jiho |
| 3 | How are **Corporate / Grocery** classified in the retention T/NT split? Penetration excludes them; `target._classify_one` (which feeds retention) still lumps them in | open since 2026-07-13 |
| 4 | `Four Points By Sheraton Bellingham` — the membership administrator bills $2,046, the CRM retention export lists them at BM5, SLX has **zero FY26 invoices** on them or either child. We drop them, so NorthCentral's denominator can never match hers | Billing |
| 5 | `[a member] Cafe & Patisserie` — Active, real BM5 invoice (#0148212, $575, fully rescinded), absent from the CRM retention export *and* the membership administrator's file. Rule 3 removes it, but nothing explains *their* exclusion | CRM owners |

---

## Sources mined for this file

`docs/DECISIONS.md` (2026-06-17, 06-28, 07-13, 07-14, 07-15, 07-22, 07-27, 07-28 ×3) ·
`docs/REFERENCE.md` *(archive repo)* (business rules, billing cycle, ITD timing) ·
`docs/RECONCILIATION.md` *(archive repo)* row "Retention counts" ·
`docs/STATE.md` *(archive repo)* · `docs/PROBLEMS.md` *(archive repo)* ·
`docs/handoff/2026-07-27-retention-gap-named.md` *(archive repo)* ·
`docs/EVIDENCE-SHEET.md` *(archive repo)* items 1, 3, 7 ·
code: `logic/retention.py`, `logic/engine.py:_query_retention`

---

## 2026-08-06 addendum — count-side consequences of the fee ruling

See `retention-revenue.md` §2026-08-06: a member whose collected money is
entirely fees is NOT counted retained (rule 3), and sub-cent float residue
is not a payment (rule 4). The denominator (billed cohort) is untouched by
both.

---

## ⛳ RULED 2026-08-14 (membership leadership · membership leadership Fruit · the membership administrator) — ALLIED IS OUT

**Allied members are excluded from hospitality retention — count and revenue,
Target, Non-Target and the combined line.** They are tracked separately.

This SUPERSEDES the 2026-08-11 ruling ("Allied = Non-Target, INCLUDED") and the
2026-07-29 line it restored. Both are kept below for history; neither is the
rule any more. The earlier D2 exclusion (2026-07-28) was, in outcome, right.

**How it surfaced.** membership leadership read Spokane revenue retention as 93.2%; her own
report says 95% (the administrator: 24 of 27 paid, bill month 6). The report showed 31 up for
renewal instead of 27 — four allied members inside Non-Target. Allied retain
poorly by design, so they drag the percentage down.

**Why they are out** (their words):
- No TM carries a goal on allied — *"they don't have goals on allied"* (the administrator).
- They are not pursued: *"if they leave, we leave"* (membership leadership).
- *"We don't have any consideration for allied … that's not what we need to
  retain. We don't measure those."* (membership leadership)
- The line is paid on: *"it's down to the percentage point that somebody could
  get a commission or not"* (membership leadership).

**Scope boundary — allied is NOT removed everywhere.** It stays in **new sales**
(the administrator: *"I wouldn't include allied in any of this other than new sales"*), and
stays visible and identifiable in **drops**. It is out of retention, out of the
overall **billables** total, and out of **penetration**.

**The combined line is `Target + Non-Target`**, and the TM sheets now say so —
the rows are labelled `Account Retention % — T + NT` and `Revenue Retention % —
T + NT` rather than "Combined", because "Combined" never said what it combined
and that ambiguity is what hid this for three weeks.

Open question 5 in this file ("Allied in or out — department leadership / Jiho") is CLOSED.
It was never department leadership's to answer; see `DECISIONS.md` 2026-08-14 on provenance.
