# Revenue Up for Renewal ($) / Revenue Retained ($) — Target & Non-Target

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


**Family:** Retention · **Engine fields:** `rev_up_target`, `rev_retained_target`, `rev_up_non_target`, `rev_retained_non_target`
**Status:** 🟢 internally verified (invariants + per-member probes, 7/30–31); external anchor still one bill month (HCB BM5, to the cent) — the July side-by-side is the acceptance test
**Last updated:** 2026-07-31 · **Sources read:** REFERENCE · DECISIONS (full) · RECONCILIATION · STATE · PROBLEMS · `logic/retention.py`

The dollar half of retention. Same cohort as the member counts — see
[`retention-members-up-for-renewal-target.md`](retention-members-up-for-renewal-target.md)
for who is in it.

---

## Why both a count and a dollar basis exist

> **2026-06-17 · membership leadership (team):** show **BOTH** member-based and dollar-based
> retention, consistent with how the Revenue Goal % is presented.

Confirmed again 2026-06-28: the %-metrics are shown on **both** bases. The old
the previous analyst BM file being dollar-only per-territory reflects the **OLD** system, not a
constraint.

---

## Definition as built

**Revenue Up for Renewal** = the cohort's **ask** — the invoice amount after
adjustments. A fully rescinded invoice is not an ask (see the net-ask rule).

**Revenue Retained** = what was actually **collected** by the cycle close:

```
collected = ask + adjustments − outstanding      (never negative)
```

**Netting, not all-or-nothing** — ratified 2026-07-13, `_netted_retained`:
a partial payer contributes **their paid portion**, not $0.

> Live: a member billed $730 with $532.03 outstanding contributes **$197.97**,
> not zero.

**Unknown balance** (every row null) → **$0 retained**. Don't invent.

**Dedup-safe:** the Sage artifact of `Balance = 0.0` **and** `Balance = None` for
one invoice nets to full rather than double-counting.

**Fields:** `Invoice_total` is **always null**; `Net_invoice` carries the amount
(confirmed 2026-05-08).

---

## The write-off fix (2026-07-28)

An invoice can be zeroed by an **adjustment**, not a payment — so
`Balance == 0.0` was reading **forgiveness as payment**.

| Live case | Invoice | Shape |
|---|---|---|
| `[a member] LLC` | #0148248 | IN 510 + **AD −510**, Balance 0.0 → **$0 collected** |
| `[a member] La Spiga` | #0148242 | IN 1,170 + **AD −1,070**, Balance 0.0 → **$100 collected** |

Neither had any payment allocation; the membership administrator's file shows both at paid = 0.

**Now:** `AD` rows are fetched alongside `IN` and joined per invoice, so
`collected` subtracts the adjustment. A write-off contributes nothing; a partial
write-off contributes the genuine residual.

**Void-and-rebill** was found in the same pass: `Contreras Group` had #0148253
voided (1,755 + AD −1,755) and **rebilled as #0148917 at 1,135 with a BLANK
comment** — invisible to any bill-month filter. The old code got such members
"right" by reading the voided invoice's zero balance as payment. Both wrongs are
now replaced by one primitive: **retained = money actually collected**.

---

## The T/NT split, and where Unknown goes

`_retention_target_split` splits paid/billed and both dollar figures by band.

**The Unknown bucket — accounts missing FTE/rooms size data, ~35% of billed
accounts in practice — is folded into Non-Target.** This matches the v4
reporting convention (`model.py`) and the billables engine path, and it
guarantees:

```
Combined = Target + Non-Target = the true total, with no leaked revenue
```

*(Note the figure: **~35% of billed accounts** lack size data in the retention
path, against ~7% of restaurant records overall. Worth reconciling — the two
numbers describe different populations.)*

---

## Verification

| Date | Against | Result |
|---|---|---|
| 2026-07-21 | HCB per-member file, bill month 5 | **Matches to the cent.** Her "Rev Retention %" = paid ÷ billed dollars from the same file — the same ratio we compute |

**Coverage: one bill month.** This is the only external check the dollar side has
ever had.

**One of the five P1 ground-truth gates is "Retention $ vs the HCB file"** — it
has not been re-run since the strict close and write-off fix landed.

---

## Timing

Dollars inherit the retention cohort's timing exactly:

- **Cycle close = end of M+1**; money arriving later is a reinstate, not a renewal
- **Live until the cycle closes, then frozen** — `as_of = min(today, cycle_close)`
- The report's month column shows **bill month M−1**
- **Run BEFORE ITD**

**⚠️ Paid dollars age out.** The 2026-07-27 June validation found **every Oct–Feb
member showing $0 paid today — 0 of 40 cells**. This is the single strongest
piece of evidence for CAPTURE AND FREEZE: a dollar figure computed from today's
ledger cannot answer a closed month, because the ledger no longer holds the
state it had then.

---

## ✅ SETTLED 2026-07-29 — what "billed" and "paid" actually mean

Resolved by reading the CRM's own export and the payment ledger, not by choosing
between our options.

### Billed = **Dues Level** (the membership product's `Price`)

Proven 3/3 against the `Adjusted Retention` export:

| Member | Product | Price | Export `billed` |
|---|---|---|---|
| [a member] La Spiga | 1 million to 2 million Dues | 1,070 | **1,070** |
| Contreras Group | 1 million to 2 million Dues | 1,070 | **1,070** |
| Otter Bar & Burger | Up to 500,000 Dues | 510 | **510** |

**Not the invoice** — not gross, not net. [a member]'s invoice was 1,170 with a
1,070 write-off; Otter's rebill was 610. The export ignores both and reports the
member's annual dues level.

**the membership administrator copies the export** — her file matched it exactly for [a member].

> **We already ratified this convention for DROPS on 2026-07-23** — *"Dues Level
> primary (Crystal's own field)… their export's `dues` column convention."*
> Same convention, discovered twice, applied once.

### Paid = **sum of POSITIVE payment allocations**, never inferred from balance

**The bug:** `collected = ask + adjustments − outstanding` inferred $100 for
[a member] from a zero balance. But **`Balance = 0` means the invoice is CLOSED**,
and an invoice closed by *credit* is indistinguishable from one closed by *cash*.

**Proof:** [a member]'s only allocation is **−1,070 on 2026-06-10** — the write-off
passing through the ledger. **No cash ever arrived.** The control, Contreras, has
**+197.97** on 6/28 and the export reports paid 197.97 exactly.

**This also explains the membership administrator's note.** She wrote *"Selling (Paid 6/10)"* — 6/10
is that negative allocation's date. She read a **credit as a payment**. Her
*columns* (Paid 0) are right; the note is wrong. We trusted the note.

### Measured exposure (bill month 5)

| BM5 WRA invoices | 167 |
|---|---|
| With a real positive allocation | **139** |
| **Balance 0, no cash — our rule called these PAID** | **10** |

The 10 are exactly the write-off set: [a member] #0148248 · [a member] #0148212 ·
Contreras' voided original #0148253 · Otter's voided original #0148304 · [a member]
#0148242 · and five more.

### Consequence

**EastKing 8 → 7 = the membership administrator exactly.** That takes retention to **9 of 10
territories matching**, leaving only Southeast's [a member] — a strict-close
ruling, not a defect.

**⛔ CODE CHANGES QUEUED** (batched, not yet applied):
1. `Revenue Up for Renewal` = Dues Level, not invoice sum.
2. `paid` = positive allocations only; stop inferring from `Balance`.
3. Remove the D2 Allied exclusion from `_retention_counts` (Allied is Non-Target
   and included — ruled 2026-07-29).

---

## 🔴 DEFECT FOUND AND HALF-FIXED 2026-07-30 — retention printed >100%

**Caught by Jiho's eyeball on the live workbook** (the same way the Snohomish
sheet and the stale March file were caught — not by a gate): Snohomish Oct
Target read **Revenue Retention 100.9%**, retained $30,521 against an ask of
$30,241.

**Mechanism, proven:** `_netted_retained` computed the ask from the IN row
alone while computing collected as IN + adjustments − outstanding. An **upward**
adjustment therefore inflated the numerator and never the denominator.
Live proof: `Anacortes Brewing Company` invoice 1,040 + AD **+330**, balance 0 →
collected 1,370 against an ask of 1,040 = **131.7%**. Snohomish Oct Target
netted +330 (Anacortes) −50 (Tulalip Resort) = **exactly the +$280 seen**.

**Blast radius measured:** **13 of 188** revenue-retention cells were over 100%
(7%), worst **120.6%** (Spokane/NE Feb NT). Member-count cells: **0 affected** —
this is a dollars-only defect.

**Fixed (the unambiguous half):** an upward adjustment now raises the ask too.

### ⚠️ PARTIAL *(then closed — see RESOLVED below)* — 5 of the 13 cells survived,
### and my "cannot exceed 100% by construction" claim was WRONG

Verified on the 2026-07-30 live pull: **13 → 5** cells over 100%. Snohomish Oct,
the cell Jiho caught, is fixed (100.9% → **99.8%**). But five remain with
**values identical to before**, so the fix never touched them:

| territory | month | band | ask | retained | |
|---|---|---|---:|---:|---|
| Spokane/NE | Feb | NT | 1,895 | 2,285 | **120.6%** |
| Pierce | Apr | NT | 4,740 | 5,250 | 110.8% |
| TKP | Mar | T | 10,175 | 11,012 | 108.2% |
| Spokane/NE | Mar | T | 56,150 | 57,414 | 102.3% |
| TKP | Jul | T | 37,760 | 38,320 | 101.5% |

### ✅ RESOLVED 2026-07-30 — a **negative ask**, which is why the arithmetic
### said it was impossible

The stated next step (dump `by_account` for TKP Mar Target) was run and it
found the account immediately: **[account-id]**, billed **+1,891** on 01-02
(invoice 0147151) and **credited −1,891** on 02-24 (invoice 0147795).

`_netted_retained` chooses the **latest-dated** invoice as the cycle's ask, so
the **credit note won** and the ask came back as **−1,891**.

That is why the per-account reasoning above was wrong without being wrong: no
member's retained ever exceeded their own ask. A negative ask **shrinks the
territory denominator**, and the ratio climbs from below. The check that would
have caught it is `ask >= 0`, which nobody was asserting.

**Rule adopted:** when a cycle's invoice rows net to **≤ 0 with a negative row
present**, the bill was rescinded — **no ask, no retention, out of both sides**.
This is the void-and-rebill pattern `_group_invoice_rows` already documents.

**This does NOT touch the write-off question below.** That contradiction is
about downward **AD adjustment** rows; this is a negative **IN** row. A credit
invoice is not an adjustment. The open item stays open.

Verified against live SLX, all five:

| territory | month | band | was | now |
|---|---|---|---:|---:|
| Spokane/NE | Feb | NT | 120.6% | **77.1%** |
| Pierce | Apr | NT | 110.8% | **100.0%** |
| TKP | Mar | T | 108.2% | **91.3%** |
| Spokane/NE | Mar | T | 102.3% | **100.0%** |
| TKP | Jul | T | 101.5% | **98.7%** |

A guard test pins the legitimate **$0 bill** so the void rule cannot swallow it
(`any(t < 0)` is required, not just a ≤ 0 net).

### ⚠️ STILL OPEN — should a WRITE-OFF also reduce the ask?

Three of our own records disagree, so it is left unresolved rather than
silently picked:

| Source | Says the ask for [a member] (1,170 invoice, −1,070 write-off) is |
|---|---|
| This file's **net-ask rule** — *"a fully rescinded invoice is not an ask"* | **100** |
| The **2026-07-28 tests** (`test_full_write_off_is_not_retained`) | **1,170** — "they WERE billed, stays in the cohort" |
| The **Dues-Level ruling** (ratified 7/29, never implemented) | **1,070** |

Current behaviour is the middle one (ask stays gross; the write-off is a
retention loss). Note the first option has a trap: a net ask of 0 makes a
fully-written-off member trip the zero-billed edge in `_member_retained` and
count as **RETAINED**. **Owner: Jiho.**

---

## Open items

| # | Item | Owner |
|---|---|---|
| 1 | ~~Should write-offs reduce the ask?~~ **ANSWERED by evidence** — neither. Billed is **Dues Level**, independent of invoicing and write-offs | ✅ |
| 2 | Verify beyond one bill month | — |
| 3 | Re-run the HCB gate after the strict-close and write-off changes | — |
| 4 | Reconcile the two "missing size" figures — ~35% of billed accounts here vs ~7% of restaurant records in `target.py` | — |
| 5 | Allied in or out (inherited — see the members file, contradiction C1) | department leadership / Jiho |

### ✅ RATIFIED 2026-07-31 (Jiho) — dollars follow the SAME close as the count

Found by Jiho's own squint at the workbook: **Snohomish May read 11 of 12
members but 100% revenue retention.** The date test lived only on the count
branch — a late payer was demoted from Members Retained while their cash
still counted in Revenue Retained. Two questions sharing one row: the count
asked "did you renew on time?", the dollars asked "how much did we eventually
collect?".

Ruling, verbatim: *"those members and dollars act regarding the same
retention insight. So they must abide by the same semantic rules."*

Implementation: `retained_dollars_as_of` — ONE function both accumulation
loops call (combined and T/NT split), so they can never drift. The ask never
moves (they were billed); the retained dollars go with the count. Demotion is
narrowing-only: only a payment date that exists and is provably late demotes,
and the undatable-payment carve ($key-collapse) applies to dollars exactly as
to the count. Live anchors: Duke Atlas / JMLM / Porthole (mid-July cash
against a 6/30 close).

History: this was an OMISSION, not a decision — the dollar lines were built
on balance-netting before the strict close was ratified (7/28) and were never
revisited when the close was bolted onto the count branch.


### 🆕 RULED 2026-08-03 — fees are not retention dollars

From the the administrator reconciliation call: county/local/alliance fees (King County
$65/location, Spokane fees, hotel-alliance/AHLA codes) are **not dues** and
leave BOTH sides of revenue retention. This AMENDS the 7/31 combined-invoice
ruling: the combined invoice is still *the bill* (payments allocate to it),
but the reported ask/retained is the DUES component only. Fee lines ride
INSIDE dues invoices (BGP 0149139: /KINGCOFEE $260 inside $2,695) and the
ledger's $key-collapse shows different lines per query shape — fee detection
requires the union-fetch primitive (see ledger_revenue.cohort_screen, fixed
8/3). Implementation for retention: task #2 — until it lands, published
retention dollars still include fees (TKP bm6 43,131 vs the administrator's ~42,610).

---

## 2026-08-06 ruling — fee money is never retention (Jiho, dress rehearsal)

Encoded in `retention.py`; tests `test_fee_aware_count.py`,
`test_fee_only_invoice_bill.py`; sealed July corrected via amendments #3
(+$11,240/9 members) and #4 (+$2,400/3 members, −2 counted).

1. **Fee-only supplemental invoice is never the bill.** Accounting bills
   county/alliance fees as their own later invoice; the latest-positive
   rule used to pick it, and fees-out then valued a fully-paid cycle at
   $0 (Thai Ginger class, nine members).
2. **A fee attribution that swallows the whole dues bill**
   (`fee == gross == dues level`) is a payAllocationViews $key-collapse
   artifact — the fee is ignored and the dues dollars count (Wapato
   Point / Kemper / Slumber; SLX-confirmed single WRA dues invoice each).
3. **A genuine fee-only payment counts nobody as retained** — not in
   dollars, not in the member count (Smokin' Pete's: one paid $20
   county-fee invoice, no dues bill in the cycle). "They did not pay
   their actual dues, so it's not retained."
4. **Cent tolerance everywhere**: `710 − 473.33 − 236.67` leaves
   2.84e-14 and `> 0` once counted a written-off cycle as paid (Notable
   Restaurant Group). Below half a cent is zero — count and dollars,
   one story.

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
