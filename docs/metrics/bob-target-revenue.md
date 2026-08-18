# BOB — Target ($) / Non-Target ($) / New Sales Revenue — BOB-Promo ($)

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


**Family:** New Sales · **Engine fields:** `revenue_bob_target`, `revenue_bob_non_target`, `revenue_bob`
**Status:** 🔴 the three rows do not all mean the same thing
**Last updated:** 2026-07-29 · **Sources read:** REFERENCE · DECISIONS (full) · RECONCILIATION · STATE · `logic/revenue.py` · `src/slx/client.py` · memory `reference_bob_black_owned`

---

## ⚠️ "BOB" means TWO UNRELATED THINGS

The codebase says so explicitly:

> *"DISTINCT from the 'BOB 2-Year' / 'Best of Both' billing promo in revenue.py
> (`BOB_PROMO_PO_LABEL`) — **same acronym, unrelated concept**."*
> — `src/slx/client.py`, `get_bob_new_accounts`

| | **BOB¹ — Black-Owned Business** | **BOB² — the billing promo** |
|---|---|---|
| What | A **comped membership** for a diverse-owned business | A **billing promotion** ("BOB 2-Year" / "Best of Both") |
| Where recorded | `accounts.CDiverseOwnership` + `accounts.CDiverseEnrollDate` | The invoice's **`Po_number`** contains `"bob"` |
| Code | `SLXClient.get_bob_new_accounts()` | `revenue._sum_bob_face_value()`, `BOB_PROMO_PO_LABEL = "bob"` |
| Purpose | The monthly **alert** so admin flags them for manual revenue credit | A **face-value line** in the revenue split |
| Feeds | *(no metric row — it is an alert)* | **The catalog's three BOB rows** |

**The catalog was wrong.** It described the BOB rows as *"revenue credit for
comped Black-Owned Business members"* sourced from `Po_number ~ "bob"`. That
source is **BOB² (the promo)**. Black-Owned Business is BOB¹ and lives in
different fields entirely.

This confusion was already flagged in memory (`reference_bob_black_owned`:
*"rename vs BOB-2yr promo"*) and never actioned.

---

## BOB¹ — Black-Owned Business (the comped membership)

**Definition** (primary source: the Dues/MPR training PDF, the member-services admin Clark training
the membership administrator; corroborated in `REFERENCE.md`):

A diverse-owned business given a **comped membership** through the **"diverse
dues" / DIV** discount code — **$0 is collected**, and it shows in the invoice
data as **negative lines** (dues issued, then credited to $0). The rep still
earns **revenue credit toward goal** (a nominal dues amount, e.g. $510/$730) and
**new-member credit**.

**The workflow is manual and monthly:** admin (a team lead/the previous analyst) flags "all the Bobs
for the month" and hands them to AR (Zooie) so the credit is applied. **Some reps
use the WRONG code**, which is why the manual step exists.

**The query** (`get_bob_new_accounts`) fetches accounts enrolled in the month
window where `CDiverseOwnership ne null` and `CDiverseEnrollDate` falls in the
window. Ownership lives on the **account**, not the member gen.

### ⚠️ Two live risks on BOB¹

1. **`CDiverseOwnership` is a general diverse-ownership flag, not BOB-specific.**
   Jiho, 2026-07-28: it would also cover the **Latino chapter, AAHOA** and
   similar. So the field identifies *diverse-owned*, not *Black-owned* — using it
   as the BOB source would over-select. **Open: where is Black-Owned Business
   specifically recorded, if anywhere?**

2. **Measured coverage is 0.1%.** `CDiverseOwnership` is populated on **11 of
   9,546** sampled accounts, all `True` (measured 2026-07-28). And the code
   carries its own warning:

   > *NOTE (2026-07-17, finding #4): the window scoping was ADDED — the query
   > previously ignored its dates and returned every diverse-owned account every
   > month. **Confirm `CDiverseEnrollDate` is populated on the next LIVE pull (a
   > null date would under-report BOBs vs the old catch-all).***

   That confirmation has **not** been done. If `CDiverseEnrollDate` is as sparse
   as `CDiverseOwnership`, the alert silently under-reports.

---

## BOB² — the billing promo (what the metric rows actually compute)

**What it actually is (the membership administrator's call 2026-07-22 [J 40:30–42:20], [S 40:39–40:57]):**

A rep *"sells"* a membership — e.g. **$1,070** — that is actually **FREE FOR TWO
YEARS**. So it **overstates new sales**, and the adjustment **backs it out**.

**Programme timeline:** sales last year + this year (one more year of selling);
each membership runs **2 years from its sale**; the adjustment line **ends two
years after the final sale date**.

the membership administrator: *"you should be able to run a report for that."*

> This is why the rows compute a **face value that gets subtracted** — the rep
> earns the credit, no cash arrives, and a reader needs both numbers to see
> actual collections.

`_sum_bob_face_value()` — the per-account **face-value** portion of counted
revenue that is BOB/promo credit (Jiho, 2026-07-20):

> the positive BOB-labeled dues lines that count as sales while the comp credits
> them back — **so readers can subtract it to see cash**.

It mirrors the main revenue sum's filters exactly: dues comp codes, `IN`/`AD`
rows, paid basis (`Net_invoice − Balance`), positive amounts only, and
`"bob" in Po_number.lower()`.

**Interaction with the new-member count** (ratified 2026-07-22 late): *"BOB
(comped) counts with $0 by design — face value in the BOB row."* So a comped
member **does** count as a new member while contributing $0 cash, and the face
value is surfaced separately here rather than hidden.

---

## Verification

**Spot check only — one member.** `RECONCILIATION.md`: the membership administrator's MPR,
NorthCentral February = **$730 = Cafe Blue at face value** (2026-07-21).

Coverage is a single cell. This is the **least-verified family in the report**.

---

## Under the Crystal pivot

**BOB and goals stay admin inputs** (DECISIONS 2026-07-27). BOB is not sourced
from a Crystal report, so it does not inherit the pivot's "carry the report's
printed number" rule.

---

## ✅ CONFIRMED BY THE FIELD OWNER — a team lead, 2026-07-30 12:45 (via membership leadership)

> *"We have a group called 'Black Owned Businesses', and it is based on having
> the field Diverse Ownership and a date checked."*

**The flag + `CDiverseEnrollDate` IS the official BOB mechanism** — an SLX
group exists by that name, and a team lead sent the member list (36 active, local
file `~/Downloads/group-Black Owned Business Mem 3.XLSX`; carries per-member
Dues Bill Month, dues level, FTE, territory, owner contact). Matches our
2026-07-30 measurement (39 flagged-True; hers is the active-only view; every
spot-checked name present). the administrator's confirm-with-a team lead homework: closed.
The AAHOA worry is settled by ownership: the program owner defines the group
AS the flag.

**⏰ And it sharpens the pre-billing alert:** the group's earliest
`DiverseEnrollDate` is **2025-10-08** — the two-year comp's first renewals hit
billing from **October 2026**, and the list's BM10–12 members are first in
line. The alert (deferred build item) now has its exact source: this group,
bill month within the comp window.

## ✅ RULED 2026-07-30 (Jiho): BOB is a TRAIT, not an enrollment type

New/rejoin logic applies to BOBs like everyone; the BOB row only ANNOTATES
whatever landed in the displayed metrics. The comp substitutes for the payment
requirement ("deemed fulfilled at $0"), never for the novelty requirement — so
a returning BOB (`Southern Kitchen`, paid 2019–24, BOB-enrolled 2025-10) is a
rejoin and enters nothing. Identification = `CDiverseOwnership`+enroll date
(measured: 41 flagged, 39/41 dated); quantification = positive `"BOB Two Year
Membership"` `Po_number` lines. Convergence measured ≈100%; one stray credit
memo (`Silverbeard's Marina`, −575, never counted by the positive-only row).

## Open items

| # | Item | Owner |
|---|---|---|
| 1 | **The three catalog rows are named for BOB¹ but compute BOB².** Rename, or re-source them | Jiho |
| 2 | Where is **Black-Owned Business** specifically recorded? `CDiverseOwnership` is broader (Latino chapter, AAHOA) | Admin |
| 3 | **Confirm `CDiverseEnrollDate` is populated** on a live pull — a null date under-reports BOBs, and the check has never run | — |
| 4 | Verify beyond one spot-checked cell | the membership administrator |
| 5 | Reps using the wrong billing code is the reason the manual flag exists — fixable at source | Admin |
