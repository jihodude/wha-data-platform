# New Members — Target (#) / Non-Target (#)

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


**Family:** New Sales · **Engine fields:** `new_members_target`, `new_members_non_target`
**Status:** 🟡 partial — verified broadly, but the counting basis flipped three times
**Last updated:** 2026-07-29 · **Sources read:** REFERENCE · DECISIONS (full) · RECONCILIATION · STATE · `logic/target.py` · `logic/revenue.py`

---

## The cohort filter (one source of truth: `target.new_member_cohort_where`)

```
Account.AccountManager.Id eq '<user>'
and EnrolledDate ge @<start>@
and EnrolledDate lt  @<end + 1 day>@
and (Salescode ne '510' or Salescode eq null)
and ReinstatedDate eq null
```

Three hard-won details, each with its own incident:

| Rule | Why | Cost of getting it wrong |
|---|---|---|
| **NO current-status filter** (2026-07-15) | A March sale is a sale **even if the member later dropped**. `Status eq Active` retroactively *erased* since-dropped enrollees | CRM report showed March = **22**, we showed **18**. the administrator's workbook counted them because they were active when she wrote it. History must not rewrite itself |
| **EXCLUSIVE next-day end** (2026-07-16) | `EnrolledDate` carries midnight **Pacific** (07:00Z), so `le @last-day@` drops last-day-of-month joiners | **4 missing 3/31 members** |
| **NULL-safe reinstatement exclusion** | `Salescode ne '510'` **alone silently drops the NULL-salescode majority** — the SData NULL trap | Would have excluded most of the cohort |

**~~Also excluded:~~ REVERSED 2026-07-30 (Jiho): add-on child locations COUNT
as new members** — matching the CRM report the administrator publishes from (measured:
`Puget Sound Pizza - LakeBay`/`- Port Orchard`, children of `Cannell
Investments LLC`, appear as member rows in the export). The `ParentId eq null`
exclusion comes out of the member count. → code batch.
**⚠️ CHALLENGED (Jiho, 2026-07-30):** this creates revenue-without-member cells
— the mirror of the drops must-carry-dollars principle. **And the tiebreaker is
measured: the CRM report the administrator publishes from COUNTS children** — today's export
carries `Puget Sound Pizza - LakeBay` + `- Port Orchard` (both ParentId →
`Cannell Investments LLC`) as member rows. Our exclusion is the divergence.
Awaiting Jiho's rule: match her source, or keep + disclose.

**Reinstatements** = `Salescode='510'` or `ReinstatedDate` set → new **REVENUE**
(credit) but **not** a new **MEMBER**.

### ⚠️ REINSTATE ≠ REJOIN — two populations, verified against the transcript 2026-07-30

Jiho caught the conflation risk and ordered a transcript re-read. **A reinstate
is a LATE RENEWAL** (this cycle's member paying after the window — months
timescale, same account, old EnrolledDate, membership continuity). **A rejoin
is a RETURNING FORMER MEMBER** (years-gap, fresh enrollment record). The
`ReinstatedDate eq null` cohort filter only addresses the first and cannot
catch the second — which is how 32/194 rejoins entered the cohort despite it.
The rejoin gate must be **ever-paid-before via invoice history** (the administrator's rule A),
with a same-cycle guard for the `Siren Song` stamping-noise class.

### What a reinstate actually is (the membership administrator, [J 28:01–28:36, 31:55, 33:20])

> A payment posted **after the billing cycle** by a member who had gone inactive;
> the membership is reactivated and **typically keeps the same bill month**. If
> they are not in retro, they can move their BM if reinstated within so many
> months.

Identified in SLX by the **reinstate date field** — *"something you could
statically pull"* — **but** the membership administrator's own caveat:

> ⚠️ *"if staff don't update the date, **garbage data**."*

**Two compounding problems with that field:**

1. **It is only as good as data entry** (above).
2. **It is OVERWRITTEN on a later reinstate** [J 26:43–27:33] — *"an old year
   re-run returns different numbers. Within the current year it's fine."*

Our cohort filter is `ReinstatedDate eq null`, so both problems land directly on
the new-member count: a missed entry **over**-counts, and a second reinstate
**retroactively changes a closed month**.

### Payment plans have no field at all

> *"No SLX field distinguishes a payment plan."* On the report both a reinstate
> and a plan payment look like **out-of-cycle revenue**. the membership administrator **clicks into
> each entry** and decides manually. Volume: **fewer than ~10 per month
> combined** — small, but time-consuming. [J 31:11–31:44, 32:08–32:37, 33:42]

The only machine signature we have is structural: **2+ payments in a 12-month
cycle** (46 of 194 FY cohort members are plan-shaped).

**Out-of-cycle attribution, in her words:** a plan payment received in **March**
for a **January** BM **counts in March's revenue** — the month received.
[J 32:56–33:00]

**Band:** Target/Non-Target by size — see `_SHARED.md`. Allied **counts** as a new
member and is always Non-Target (verified already true in code, 2026-07-21).

---

## ⚠️ The counting basis changed three times

| Date | Basis | Fate |
|---|---|---|
| original | **Enrollment cohort** — counted in the sign-up month | |
| **2026-07-22 (late)** | **PAID members only** — *"Do not count members as new unless they have paid."* Counts derive inside the revenue pass from the **same paid amounts** as the dollars (`revenue._countable_ids`): net paid > 0 counts; **BOB (comped) counts with $0 by design**; refund-only and never-paid enrollees do not count | **Superseded** |
| 2026-07-27 (pivot) | **Enrollment basis** again — *"counts enrollment-basis"*, *"the count⟺$ invariant retires"* | **superseded same day** |
| **2026-07-27 (THE-PLAN)** | **PAID basis** — *"members whose dues were paid, counted in their first-payment month"*, source `revenue.revenue_and_counts_by_first_pay()`. THE-PLAN was written **after** the pivot failed and supersedes it | **CURRENT** |

**✅ RE-RATIFIED 2026-07-30 (Jiho): the PAID basis stands — count lands in the
first-payment month, together with the dollars.** *"the administrator said sales = paid, so
they should indeed land together."* The sale-month alternative (the administrator's described
practice, option B in the 7/30 decision packet) was considered and not chosen;
one confirm-sentence with the administrator at the meeting closes the difference (a member
sold in March who first pays in May sits in May's column).

**Why paid-only was adopted (7/22):** the count-without-revenue class existed in
**every era** — 17 band-cells on 7/13, 7 on 7/21, 21 post-reversion — because
counts and dollars came from **two different passes with two different bases**.
One pass, one rulebook made the mismatch structurally impossible.

**Why it looked dropped (7/27 pivot):** the pivot retired the count⟺$ invariant
along with the paid-only basis — **but only for as long as Crystal was the
source.** THE-PLAN, written later the same day after the pivot failed its first
honest test, puts new members back on the **SData ledger with the paid basis**.

> **So paid-only stands.** Its reasoning was never refuted, and the source change
> that briefly displaced it was itself reversed within the day.

---

## ✅ Rejoins — RULED 2026-07-29 (Jiho): a rejoin is NOT a new member

> *"Rejoins can't be a new member if it's not their first time paying — like
> logically, how does that make sense?"*

**the administrator's rule A governs. B is retired** — its only basis was the Crystal reports'
own listing, and THE-PLAN had already moved new members off those reports.

**And the CRM report defect is CONFIRMED, for membership leadership:** the `New Member Sales`
report counts returning members as brand-new. Measured while A governed:
**32 of 194** FY-cohort "new members" had paid invoices predating their
enrollment (2005–2025). Named multi-year cases: `Green Suites` (paid 2020–22,
"enrolled" 2026) · `Amelia's Hangar` (paid 2023–24, "enrolled" Dec 2025) ·
`Jalapenos Family Mexican` (enrolled 7/2026, 14 paid invoices back to 2017) ·
`Fischer Services` (enrolled 5/2026, 10 back to 2017). The same report also
**misses** real members (`[a member]`, $2,435). Both directions, one
report.

*(The superseded contradiction, kept per rule 8:)*

## ~~⚠️ Rejoins — two rulings, opposite answers~~

| # | Ruling | Source |
|---|---|---|
| A | ~~"Never paid before = new; ever paid before = renewal, regardless of how long ago."~~ **DEAD — superseded 2026-07-30 by the administrator herself** on the recorded call: a return after ~6 months IS a new member (*"That exact same member"*). The 32-of-194 measurement stands as a *count of returning members*, not as a count of errors | the administrator 7/21, superseded 7/30 |
| B | **"Rejoins count as new"** — per the reports' own listing | Crystal pivot, 2026-07-27 |

**Both are recorded because both were ratified.** ⚠️ **B's standing is now
doubtful:** its only basis was *"per the reports' own listing"*, and THE-PLAN
moved new members **off** those reports and back onto the ledger. With the source
reversed, the reason for B goes with it — but THE-PLAN does not restate the
rejoin rule explicitly, so this is **unresolved**, not settled back to A. Note the pivot's own reasoning: our counts *matched* the CRM
"New Member Sales" report, **so that report shares the rejoins-as-new
behaviour** — under A it was a documented divergence, under B it becomes
agreement.

**Named examples of the class** (from RECONCILIATION's divergence list, written
while A governed): `Green Suites` (paid 2020–22, "enrolled" 2026),
`Amelia's Hangar` (paid annually 2023–24, "enrolled" Dec 2025), `Classic Eats`,
`Robert Stocker`, `Southern Kitchen`.

**⚠️ Unverified figure:** a 2026-07-29 probe suggested 73 of 212 FY enrollees
(34%) had prior paid invoices, but the measurement did not separate *genuine
rejoins* (paid years earlier) from *same-cycle payments* (paid days before their
enrollment date was stamped — e.g. `Siren Song Wines` enrolled 3/17, paid 3/16).
**Do not quote 34%.** The defensible cases are the multi-year ones:
`Jalapenos Family Mexican` (enrolled 7/2026, 14 paid invoices back to 2017),
`Fischer Services` (enrolled 5/2026, 10 back to 2017).

---

## Verification

**9 months × 11 territories** against the membership administrator's published workbook — fixture
`tests/fixtures/mpr_published_2025-26.json` — every difference account-named.
Last verified **2026-07-21**.

**June:** 9 of 11 territories count-exact.

**Known divergence at the time:** her editions count unmarked rejoins (CRM report
behaviour); we excluded them by the then-ratified ever-paid rule, each excluded
account documented. *(The Crystal pivot inverts this — see above.)*

**Named case:** `[a member]` (NorthKing, June) — **HE COUNTS**, decided
2026-07-22 after the administrator delegated. He is in the June cohort and paid **$2,435**.
The only thing excluding him is the CRM New Member Sales report's **known gap**;
that report is demoted to secondary here.

---

## Open items

| # | Item | Owner |
|---|---|---|
| 1 | ~~Rejoins~~ — **RULED 2026-07-29: not new.** Residual: tell membership leadership the report counts them as new | → membership leadership brief |
| 2 | Re-measure the rejoin population **separating multi-year rejoins from same-cycle payments** | — |
| 3 | If the pivot is ever reversed, the count⟺$ mismatch returns — the paid-only reasoning is unrefuted | — |
| 4 | ~~Seller-vs-territory credit unimplemented~~ — **done 2026-07-16**: the seller is `AccountExtension.Originator` (UI *"Acct. Originator"*), wired in `new_members.py` ×2 and verified 3/3. `Salescode` (dues category) and `CreateUser` (data-entry clerk) were both disproven | ✅ |
