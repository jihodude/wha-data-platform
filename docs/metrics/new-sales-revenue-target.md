# New Sales Revenue — Target ($)

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


**Family:** New Sales · **Engine field:** `revenue_target` · **Status:** 🔴 basis under rebuild
**Last updated:** 2026-07-29 · **Sources read:** REFERENCE · DECISIONS (full) · RECONCILIATION · STATE · PROBLEMS · `logic/revenue.py`

First-year dues from members who joined in the month, Target band.
---

## ✅ RULED 2026-07-29 (the administrator's answers, relayed by Jiho — stop re-asking these)

**Recognition basis:** *"If somebody pays in partial, the new-sales MEMBER COUNT
goes up in the sale month, but the new-sales REVENUE gets added every time they
are paid."* Count = sale month, once. Dollars = as payments arrive, in the month
they arrive. The count⟺dollars "mismatch" is not a defect — it is the design.

**Payment plans have NO code in SLX.** *"CMP isn't what payments are — CMP is an
acronym for a program."* **MSC is not it either.** A payment plan is detected only
by its **payment behaviour** — several dated part-payments against one member —
so identifying installment members is OUR implementation work (payment dates via
`payAllocationViews`), not a code lookup and not a question for anyone.

---

## Definition as ratified

Dollar amounts live on `dlInvoiceHistoryHeader.Net_invoice`. We want only
invoices sent to **NEW** members (their first-year dues), not renewals.

**Method (per territory, per window):**
1. Find members enrolled in the window via `cMemberGens`, excluding
   reinstatements (`Salescode = '510'` OR `ReinstatedDate` set).
2. Pull dues invoices across a window from just before enrollment through the
   member's first ~10 billing months — **payment-plan installments lag
   enrollment by months**.
3. Sum **signed** `Net_invoice` for invoices whose `Accountid` is in the
   new-member set, restricted to dues comp codes.

**Basis:** **PAID**, not billed — `Net_invoice − Balance`.
> the administrator, 2026-07-14: *"sales = paid; TMs could bill without collecting."*
> [a member] counts **535 of its 1,070 bill**.
> **Locked by Jiho 2026-07-22.**

**IN and AD rows are both summed**, relying on the sign of `Net_invoice`, so a
reversed-and-rebilled installment nets to the right number.

**Credit goes to the SELLER, not the account's territory** (ratified 2026-07-15):
when a sales rep sells a business living in TKP's territory, the sale shows in
**a sales rep's** column — matching the membership administrator's workbook, the CRM report's "AC/Sale"
column, and the administrator's own words.

**✅ IMPLEMENTED 2026-07-16.** The seller lives in
**`AccountExtension.Originator`** (UI: *"Acct. Originator"*). Two earlier
candidates were disproven: `Salescode` is the **dues category**, not the seller
(7/14), and `CreateUser` is the **data-entry clerk**. Wired into all four sales
functions via `attribution.originator_territory_map` — live call sites in
`revenue.py` (×2), `new_members.py` (×2) and `ledger_revenue.py`. Verified 3/3
on `Perch`, `El Sombrero`, `My's Cove`. When `Originator` is missing or is not a
TM, the sale falls back to the account's own territory **with a loud warning**.

---

## Comp codes — FINAL RULE (2026-07-21, the administrator primary source)

- **Dues = WRA ONLY. No MSC line is ever a sale.**
- **CMP = Claims Management Program** — a service fee, **not** dues and **not**
  payment plans.
- Non-dues codes (PAC, EDF…) stay excluded.

### How CMP was got wrong twice, and the proof that settled it

| Date | Belief | Fate |
|---|---|---|
| 2026-07-14 PM | Count all payment-plan (MSC) money — the administrator hand-adds it, so the CRM report scoring those members $0 is its gap | Too blunt |
| 2026-07-15 | Narrowed: MSC counts only where `Po_number` contains "CMP Fee" — those ARE pro-rated dues | **Wrong** |
| **2026-07-21** | **CMP is a Claims Management Program service fee. Excluded entirely.** | **CURRENT** |

**The proof:** `[a member]`'s full history — Apr 1 "Retro Fee Q2"
$766.76 billed, **same-day reversed**, May 1 **rebilled at the identical
$766.76** as "CMP Fee BM 4-12". A relabeled retro fee, not dues. Their dues level
is $0.00 (dues bill at the parent group, if at all).

**Measured contamination of the wrong rule:** $1,094.19 across 2 accounts, both
Snohomish. The same error invalidated the 7/20 drops-$ CMP fallback (11 accounts
/ $2,249 of claims fees shown as lost dues).

**Live MSC taxonomy** (all 929 FY MSC invoices): ~655 Retro Fee rows ($612k) ·
66 blank-label batch postings ($3.7M) · vendor ACH/commission rows · ~67
"CMP Fee BM x-y" rows ($181k).

**Consequence:** Southwest June = **$5,723.50** — the membership administrator's number was exactly
right, and the shipped 7/14 file ($6,805.21) overstated revenue.

---

## ⚠️ Recognition basis — the module and the ratified rule disagree

| | Basis |
|---|---|
| **What `revenue.py` does now** | Attributes by **ENROLLMENT month** — first-year dues summed into the month the member signed up |
| **the administrator's pinned rule (7/21)** | **PAYMENT month** — each payment counts in the month it was PAID, including split/plan payments landing across months. The member COUNT stays once, in the sign-up month |

**Until the ledger rebuild ships, monthly revenue splits are approximate
wherever billing month ≠ payment month.** Measured: **$112,939 of $278,403** FY
cohort dues (**41%**) are invoiced in a different month than enrollment.

**But the administrator's own practice is not purely payment-month either** — her Southwest
June figure includes a May-invoiced line (account `[account-id]`, enrolled June,
billed May). Likely actual rule: initial payment → sale month, installments →
pay month. **Confirm before touching `revenue.py`.**

**Payment dates are available:** `payAllocationViews.AllocationDate`, found and
validated 2026-07-21 — the SW June member's May-invoiced $1,658.50 shows
`AllocationDate 2026-06-24`, the exact reason the administrator counted it in June. Her basis
= payment month, proven.

**⚠️ Superseded twice in one day.** The Crystal pivot (7/27) retired the
paid-only / first-pay-anchoring basis — then `THE-PLAN.md`, written later the
same day after the pivot failed, put revenue back on the **SData ledger, paid
basis**: *"PAID dues, first-payment month, ledger-identified fees excluded."*
**THE-PLAN governs.** The ledger/receipts machinery being *"archived, not
wired"* was a pivot-era statement and should be re-checked against Part 3.

---

## Verification

**9 months × 11 territories** against the membership administrator's published workbook
(fixture `tests/fixtures/mpr_published_2025-26.json`), every difference
account-named. Last verified **2026-07-22**.

| Month | Statewide gap |
|---|---|
| January | within **$208** |
| February | **$346** |
| May | **$1,068** |
| June | **8/11 territories $-exact**, 9/11 #-exact |

### The splice finding (2026-07-22, VERIFIED) — why Oct–Mar cannot reconcile

**Her published year changes data source mid-stream.**

- **Oct–Mar editions** were copied from her **personal tracker**, which records
  members at **SALE value** when they sign. December/January/February match that
  tracker to the dollar.
- **Apr–Jun editions** came from the **CRM New Member Sales report** (paid basis)
  after she stopped maintaining the tracker — its Apr–Jun sections are empty.

Our report uses **one consistent basis (paid) all year**. So Oct–Mar gaps are a
**SOURCE-BASIS difference, not errors on either side**, reconciled at class level
(billed-vs-paid + rejoins + tracker drift — her Oct/Nov editions differ from her
own tracker by ~$3,200 each). Apr–Jun, where her basis matches ours, aligns
tightly.

---

## Named cases, resolved

| Account | Resolution |
|---|---|
| **[a member]** (NorthKing, June) | **HE COUNTS** — decided 2026-07-22, the administrator delegated the call. Paid **$2,435** in dues (one invoice, confirmed via the invoice-number ledger query). Ratified rule is paid = counts. The only thing excluding him is the CRM New Member Sales report's **known gap**. Net NK divergence: +2,435 [a member] − 505 Restaurant365 rejoin = **+1,930** |
| **[a member] Worlds** (Snohomish, June) | **CLOSED 2026-07-22.** Her edition implied $895; the CRM report, payment ledger and invoices all say **$535** — exactly half the $1,070 bill, a split payment whose second half never arrived. the administrator does not know the source of the $895. **Her figure is unsupported by any record; ours stands** |
| **[a member]** | Its extra $1,081.71 is a **Retro Fee Q3**, not dues — the case that broke the 7/15 CMP rule |

---

## NRA exception

NRA chains have **no WRA/MSC sign-up invoice** — dues are paid to NRA directly
and prorated back via the accounting GL. They produce **$0** here, which matches
the SOP. **For NRA revenue see the finance Dues Summary workbook** — it is not a
clean SLX pull.

---

## Open items

| # | Item | Owner |
|---|---|---|
| 1 | **Recognition basis** — enrollment month (built) vs payment month (ratified) vs her actual practice (initial→sale month, installments→pay month) | the membership administrator |
| 2 | ~~Seller attribution unimplemented~~ — **done 2026-07-16** via `AccountExtension.Originator`, verified 3/3 | ✅ |
| 3 | **All-MSC payment-plan members** score $0 under WRA-only — how does the administrator want them shown? | the membership administrator |
| 4 | October's 3 dollar-adjustments (Amy / Bailey / Michele) | pending the invoice-label probe |
| 5 | Whether the Crystal pivot supersedes this module entirely | — |
