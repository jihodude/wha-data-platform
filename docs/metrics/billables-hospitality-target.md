# Billables — Hospitality Target (#)

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


**Family:** Billables · **Engine field:** `hosp_bills_target` · **Status:** 🟡 partial
**Last updated:** 2026-07-29 · **Sources read:** REFERENCE · DECISIONS (full) · RECONCILIATION · STATE · PROBLEMS · `logic/billables.py` · `logic/target.py`

Active hospitality members clearing the Target size threshold.

---

## Definition as ratified

> **A billable is an ACTIVE account that CARRIES A MEMBERSHIP BILL** — a
> `MembershipProduct` on `cMemberGens`. *(ratified 2026-07-14)*

- **Hospitality vs Allied is decided by the membership PRODUCT NAME, not the
  account `Type`.** Allied = product name contains "Allied". Allied is **always
  Non-Target**.
- **Target = SIZE:** restaurants ≥ 10 FTE; hotels ≥ `TARGET_ROOMS_MIN` rooms
  (**40**, confirmed by the membership administrator 2026-07-21 — see `_SHARED.md` for the full
  ruling chain; five code comments still say 41+).
- Members with **no size on file** go to **Non-Target**, never dropped: Target
  means clearing a threshold, and they have not been shown to clear it.
  Including them gives **2,143**; excluding gives 2,036 — below every month
  the membership administrator ever published.
- Territory: `account.AccountManager.Id` → `territory_map.yaml`. Multi-user
  territories **SUM** (fixed 2026-07-13; previously the last user overwrote).

**ITD dependency:** billables counts are only valid **AFTER** ITD has run for
the month. *(Retention is the opposite — see `_SHARED.md`.)*

**Source — RULED 2026-07-30 (Jiho): SData computes billables; the Crystal
overlay comes OFF.** Consistent with the penetration ruling (*"if we believe
both produce the same output, use the more reliable one — reconciling against
Crystal asserts it is more accurate"*). The `Active Billables By Ac And Fte`
export remains captured as reference/validation evidence, not the source.
→ code batch: remove `BILLABLES_FIELDS` from the crystal overlay.
**Side effect:** size-less members stop riding wholesale into Non-Target via
Crystal's `Others` band — hotels like `Element Seattle Hotel` (247 rooms,
currently published NT by the overlay) get the rooms rule. *(The old "Current
source: Crystal" line below this stands superseded.)*

---

## The rule changed three times — the full chain

| Date | Rule | Fate |
|---|---|---|
| pre-7/13 | Active, `Type != 'Allied'`, `ParentId eq null` | Approximation. Undercounted hospitality (~350 bills go to non-top-of-family records) and overcounted Allied (~31 active Allied records carry no bill). Closest known figure: 1,782 |
| 2026-07-13 | "The record that carries the bill" — `Duesbillmonth` 1–12 | **DISPROVEN 2026-07-14.** `Duesbillmonth` is stamped on **every location record**, not just the invoiced one → counted **5,148** vs the CRM's 2,132 |
| 2026-07-13 | NRA = `Duesbillmonth > 12`, shown separately | **DISPROVEN 2026-07-14.** BMs 13–16 are unrelated special groups. `count_nra_billables` removed |
| **2026-07-14** | **`MembershipProduct` carrier** | **CURRENT.** CRM-verified 10/10 territories (statewide 2,294 vs 2,293) |

Also probed and failed: `CBillingAccount` / `CPrimaryAccount` (SData returns
reference *names*; no self-reference pattern found).

> **Jiho's plain words to the membership administrator, 7/14:** *"My first guess at your billables
> rule was wrong — the test this morning proved it before it ever reached a
> report. Tell me the exact filter your report uses and I'll match it the same
> day."*

**Do not reintroduce** the superseded rules — they are removed, not deprecated.

---

## Verification

| Date | Against | Result |
|---|---|---|
| 2026-07-14 | CRM, 10/10 territories | statewide **2,294 vs 2,293** |
| 2026-07-20 | the membership administrator's June MPR | **hers 2,143 / 164 · ours 2,137 / 162** |
| 2026-07-27 | Crystal FTE report | **2,143 statewide = the membership administrator's published figure exactly** |
| 2026-07-28 | Second CRM export, per territory | Every difference decomposed (below) |

### ✅ CLOSED 2026-07-29 — the two reports answer DIFFERENT QUESTIONS

Investigated by reading the exports' structure, not by comparing totals.

| Report | Structure | Answers |
|---|---|---|
| **`Active Billables By Ac And Fte`** | one block, territory → FTE band | **"Who is an active billable RIGHT NOW?"** — a snapshot |
| **`Billables By Territory Summary By Bm`** | **12 blocks, one per bill month**, each territory → category → count + dues $ | **"Who gets billed in each cycle, and for how much?"** — the **billing schedule** |

**Proof:** EastKing appears **12 times** in the ByBM export — once per bill month
— summing to 185 (171 hospitality + 14 Allied). The FTE report shows EastKing
**once**, at 170.

> **leadership's phrasing is the answer, and it is structural:**
> *"retention goes by month, and billables right now."*

**So there is no "which report is authoritative" question.** The MPR's billables
row is a **point-in-time count** → `Active Billables By Ac And Fte`. The ByBM
report is the **billing-schedule / forecasting** view, which is why the **Dues**
SOP uses *"billable by bill month"*.

**This also retires my earlier framings.** The "170 apart" comparison summed a
12-cycle schedule against a snapshot; the "19 apart" correction compared the same
two things more carefully but still treated them as rival answers to one
question. They were never rivals.

**What remains is small and ours to check:** per territory, the snapshot and the
schedule differ by ~1–4 members (EastKing 170 vs 171). Expected — a member can
change bill month, or be added/removed between the schedule being set and the
snapshot being taken. Worth one investigation, needs no ruling.

*(Superseded framing, kept for the record:)*

### ~~The two CRM billables reports disagree by 170~~

| Report | Hospitality |
|---|---|
| `Active Billables By Ac And Fte` | **2,143** ← we use this |
| `Billables By Territory Summary By Bm` | **2,313** |

**Decomposed:** 143 RetroCoordinator + 9 EF School − 1 Allied Relations Manager
+ **19 spread across the ten real territories**.

Per-territory (FTE vs by-BM): EastKing 170/171 · NorthCentral 185/188 ·
NorthKing 259/262 · Pierce 224/225 · Snohomish 218/220 · SouthKing 198/199 ·
Southeast 35/35 ✓ · Southwest 226/230 · Spokane/NE 298/300 · TKP 294/296 ·
Majors/NRA 34/34 ✓.

**⚠️ Open:** which report is authoritative? We chose 2,143 because it matches
the membership administrator — that is matching a *person*, not a *source*. **Owner: the membership administrator.**
The residual 19 are unexplained.

---

## Known exclusions and their reasons

| Excluded | Count | Reason |
|---|---|---|
| **11 house-managed Allied vendor partners** | 11 | Paylocity, US Bank/Elavon, BMI, TipHaus… owned by the `AlliedRelationsManager` house user, not a territory. A by-territory scoreboard has no row for them; no TM's numbers are affected. Decision 2026-07-14 PM: do NOT invent a house row while the administrator has not seen the layout; carry a provenance note. **Revisit with the administrator for placement.** Their CRM statewide Allied line (161) = our territory-summed 145 + these 11 + ~5 timing drift |
| **RetroCoordinator accounts** | 143 | The retro/L&I book. Excluded from the published figure. *(Same family as Retro Program drops: detail-visible, count-excluded)* |
| EF School | 9 | Not a territory |

---

## Consolidations are invisible

When N accounts merge into 1, the billable count legitimately drops by **N−1**.
`consolidation_events` is an **empty placeholder** — the query was never built.
**Needs the accountant.** An unexplained billables drop therefore cannot be distinguished
from a data error.

---

## Data hazards

- **SData join under-fetch** — per-territory bulk joins via
  `Account.AccountManager.Id` on `cMemberGens` / `cRestProfiles` return
  incomplete rows on large sets (−37..−97 actives/territory; the shortfall scales
  with size, so tiny Southeast was exact and looked fine). Fixed 2026-07-14 by
  re-fetching still-missing accounts in `Account.Id` batches inside
  `build_target_map`.
- **Silent-partial pagination** — the SLX client's old policy returned PARTIAL
  data with only a Python warning when SData 500'd on deep pagination. **Every
  bulk metric silently undercounted**, scaling with result size and varying
  run-to-run with retry luck. Fixed 2026-07-14: `_fetch_all` compares against
  `$totalResults` and cursor-walks the remainder, printing loud recovery/failure
  lines. The per-table backfill remains as a second net.

---

## Semantics

**Billables is a SNAPSHOT** — it describes the day the report ran, not a whole
month. Only the snapshot month is written; other cells stay zero rather than
repeating a count across months it never described. A billables figure can
never be borrowed from another month's export.

**⚠️ Related open question (Jiho, 2026-07-28):** billable is scoped to the bill
month and fixed at **month end** — so *which day* fixes the month's base? End of
the bill month, or end of M+1 when the pay window closes?

---

## Open items

| # | Item | Owner |
|---|---|---|
| 1 | ~~Which report is authoritative~~ — **CLOSED**: they answer different questions. Snapshot = FTE report (ours); schedule = ByBM (dues) | ✅ |
| 2 | Per-territory drift of ~1–4 between snapshot and schedule — expected, but unexamined | us |
| 3 | ~~Placement for the 11 house Allied partners~~ — **RULED 2026-07-29 (Jiho): no territory → nowhere.** Not in territory sheets, not in the summary. The current exclusion is final; no house row | ✅ |
| 4 | Consolidation events — the query was never built | the accountant |
| 5 | ~~Which day fixes the month's base~~ — **RULED 2026-07-29 (Jiho): when the pay window closes (end of M+1)** — *"they could still pay within that grace window."* Same day retention freezes; one clock for the whole membership block | ✅ |
| 6 | ~~H/A remnant~~ — **LOCKED 2026-07-29 (Jiho): Target/Non-Target, everywhere.** Allied is Non-Target. The official SOP's Hospitality/Allied boxes describe the **old manual process**; we are automating an upgrade, not reproducing it | ✅ |
