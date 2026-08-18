# Penetration — Lodging (Total Target Locations, Target Members, %)

**Family:** Penetration — Target · **Engine fields:** `pen_market_lodging`, `pen_active_lodging`, `pen_lodging_pct`
**Status:** 🟢 verified — actives exact against the CRM report
**Last updated:** 2026-07-29 · **Sources read:** REFERENCE · DECISIONS (full) · RECONCILIATION · STATE · PROBLEMS · `logic/billables.py` · `logic/target.py`

*Covers three catalog rows that share one definition and one investigation.*

---

## Definition as ratified

```
Penetration % = active Target lodging / (active + inactive Target lodging)
```

- **Numerator** = active Target locations
- **Denominator (market)** = **active + inactive** Target locations
- **Target lodging** = `Rooms >= 40` **AND** `SubType ∈ LODGING_MARKET_SUBTYPES`

**The denominator is Active + Inactive members ONLY** — settled 2026-06-04, and
the earlier "market-size vs Active+Inactive fork" was loose old phrasing, not a
real fork. We deliberately do **not** use all statuses: that pulls Closed/RRO
accounts which are not part of the member universe and **inflated the
denominator in every territory**.

**Corporate billing entities are excluded** — they are not physical locations.
*(Note the asymmetry: Corporate is always **Target** in the member splits, but
excluded from penetration. DECISIONS 2026-07-13 ruled this orthogonal and both
correct — penetration is a **location** metric, the member splits are a
**dues-payer** metric. STATE and PROBLEMS still list this as an open question;
they are stale.)*

**Missing-FTE accounts are dropped** — **Policy A**, decided 2026-06-05 by a
live 11-territory probe against the previous analyst's Pierce figure of **78.9%**:

| Policy | Pierce result |
|---|---|
| **A — drop UNKNOWN** | **80.3% ✓ matches the previous analyst** |
| B — UNKNOWN in numerator + denominator | 62.7% — under by 16pp |
| C — UNKNOWN in numerator only | Pierce 100% / NorthKing 127% — broken |

Baked into `_count_target_locations`, with a breadcrumb in its docstring:
**revisit if the previous analyst's numbers become available for more territories, or if the
missing-FTE rate drops below 7%.**

*(The cleaner long-term mechanism is the **research-data inlet** backlog item —
not editing the function.)*

**The other three divergences from the previous analyst's report**, all fixed 2026-06-04/05:
market denominator = Active + Inactive (was pulling Closed/RRO) · Corporate
billing entities excluded from both numerator and denominator · the account-type
whitelist narrowed so Grocery / Non-Commercial / unknown types no longer count.

**Cost:** two target-map builds per territory (`status='Active'` and
`status='Inactive'`), shared through the session cache with billables and
retention if they ran first.

---

## The market universe — SubType, not rooms alone (adopted 2026-07-19)

The lodging denominator was ~50 accounts adrift statewide (TKP/NC-heavy) for
weeks. Two theories were wrong before the answer was found:

| Theory | Fate |
|---|---|
| the previous analyst's manual step introduces it | **Wrong** — the raw export shows the same gap |
| An inactive-status filter | **Wrong (7/17, superseded)** — it only *looked* status-shaped because RV parks are mostly inactive members |

**The answer:** it is the **Crystal report's own universe**. Jiho pulled the raw
exports (`PenetrationLodging*_2026_07_19`, author "Crystal D", zero human touch)
and reconciled at account-ID level. The report counts **only true lodging
subtypes** and drops:

- `RV Park or Campground`
- `Vacation Rental`
- `Military Housing`
- `Bed & Breakfast`

**ADOPTED:** our lodging universe = `SubType ∈ {Full Service Lodging, Limited
Service Lodging, Economy Service Lodging, Extended Stay, Resort, Gaming}` —
derived empirically from all **782** listed accounts, applied to **numerator AND
denominator** via `_count_locations(subtype_map=…)`.

**Unknown or missing subtypes WARN loudly and are excluded** — a new CRM subtype
must never be silently counted or dropped.

**Scope: penetration only.** Billables T/NT stays rooms-based (7/13 rule). A
41+-space RV park is Target-**SIZED** but not the hotel **MARKET**.

**Result:** lodging actives match Crystal **EXACTLY** — verified live
**TKP 56/56, NorthCentral 52/52**. Markets match Crystal (TKP 101, NC 111).

---

## The room threshold — SETTLED

### ✅ RULED 2026-07-29 (Jiho): **40 or higher.**

`Rooms >= 40` = Target. The code is already correct (`TARGET_ROOMS_MIN = 40`).
The SOP's *"over 41 Rooms"* and the 7/13 41+ entry are both **superseded**.

**Consequences:**
- The 23 forty-room hotels are **IN** the universe.
- Our penetration should match the CRM reports **directly** — no netting, no
  footnote, no "we read lower on purpose".
- `REFERENCE.md` (lines 52, 56), `SOP.md`, the 7/19 penetration-evidence script
  and **five code comments** still say 41+ and are genuinely stale.
- The evidence-sheet item calling the CRM's 40-room cutoff a defect stays
  **withdrawn** — the report was right.

---

*Evidence that produced the question, kept for the record:* the official MPR SOP
instructs *"percentage for Lodging over 41 Rooms."*

That is WHA's own authored process document. It does not settle the question in
favour of 41 automatically — the membership administrator confirmed 40+ verbally on 7/21, later — but
it does mean **41 is not merely a stale artifact of ours**, which is what I
concluded on 7/29 before reading it.

**Current state of the evidence:**

| Source | Threshold | Kind |
|---|---|---|
| MPR SOP | **"over 41"** | authored, by the process owner (the member-services admin, on leave) |
| DECISIONS 7/13 | 41+ | ratified decision |
| DECISIONS 7/21 | **40+** | verbal, from the membership administrator (covering) |
| CRM penetration report | ≥ 40 | report behaviour |
| **Our code** | **40** | implementation |

~~One ruling needed~~ — **answered above: 40 or higher.**

**The withdrawal stands.** The evidence-sheet item calling the CRM's 40-room
cutoff a defect was correctly withdrawn — at 40+, there is no divergence at all.

---

## The 40-room boundary — the ruling chain

| Date | Ruling |
|---|---|
| 2026-07-13 | Target lodging = **41+**. Logged as an *"intentional divergence from the CRM reports"* |
| 2026-07-19 | 41+ **kept**; `final_verdict` nets the 23 forty-room hotels out of CRM references to compare apples-to-apples |
| **2026-07-21 (day 2)** | **REVERTED to 40+.** *"the membership administrator confirmed directly: 40 or more rooms = Target, 39 or fewer = Non-Target."* **Supersedes 7/19.** The 23 enter the universe; the netting was removed; our penetration should match the CRM reports **directly** |

**The 23 hotels, named** — printed by the CRM report itself with rooms = 40, and
none below 40, so its cutoff was always ≥ 40. **21 inactive, 2 active.**

| Territory | Status | Hotel |
|---|---|---|
| NorthCentral | Inactive | Evergreen Inn · Great Links Resort Desert Canyon · Motel 6 Burlington · Posthotel · Three Rivers Inn · Tulip Inn · Veranda Beach Resort · West Winds Motel |
| **NorthKing** | **Active** | **[a member]** |
| Pierce | Inactive | Sunshine Motel |
| Snohomish | Inactive | Doe Bay Resort & Retreat · Welcome Everett Inn |
| SouthKing | Inactive | Crystal Chalets · Economy Inn Auburn · GuestHouse Inn · West Wind Motel |
| **Southwest** | **Active** | **[a member] Harbor Lodge** |
| Southwest | Inactive | Timberland Inn & Suites · Toppenish Inn & Suites · Travel Inn |
| TKP | Inactive | Guesthouse Inn & Suites Montesano · Lakeview Inn · Ocean Shores Resort |

**⚠️ The evidence sheet that lists them is itself stale.** Written 2026-07-19, it
scripts a talking point — *"the report includes hotels with exactly 40 rooms; our
ratified rule is 'over 40,' meaning 41 and up… the program is filtering
correctly"* — which the membership administrator **reversed two days later**. The hotel list is still
accurate and useful; **the script must not be used.** Under the 40+ rule these
23 are simply **in** the universe and there is no difference to explain.

Its market figures reflect the old netting: TKP 101 vs the report's 104,
NorthCentral 111 vs 119. Under 40+ those should now agree directly.

**Live state:** the code is **correct** (`TARGET_ROOMS_MIN = 40`, and
`target.py`'s own docstring quotes the membership administrator's confirmation). **Stale at 41+:**
`REFERENCE.md` lines 52 & 56, and five code comments.

> **This mattered.** An outbound evidence sheet listed the CRM report's 40-room
> threshold as a defect on *their* side. It is not — we were stale. Withdrawn
> 2026-07-29.

---

## Restaurant side (same investigation)

**Restaurant universe = `Type` 'Restaurant' only** (`PENETRATION_RESTAURANT_TYPES`).

The food-service whitelist in REFERENCE reads
`{Restaurant, Catering, Recreational, Concession}` — **⚠️ but the code narrows it
to `{"Restaurant"}`**, with a comment that it can be reverted "if the team ever
ratifies the broader view." STATE's ratified-rules line agrees with the code
("penetration restaurants = Type 'Restaurant' only"). **REFERENCE is the stale
copy.**

**Reconciles** ±1–6 per territory. The export lumps Majors under NorthKing.
Crystal accepts variant band formats ('10-19' shown as-is), consistent with our
7/18 normalization.

---

## Verification

| Date | Against | Coverage | Result |
|---|---|---|---|
| 2026-07-19 | Crystal CRM penetration exports | **All 11 territories** | Account-ID-level; **actives exact** |
| earlier | the previous analyst's Pierce report | one territory | ~79–80%, matches |

**the previous analyst's market size is the external reference.**

**Open (owner self-serving):** Jiho to pull the previous analyst's latest penetration report
from SharePoint to validate beyond Pierce.

---

## ⚠️ Which source owns penetration? THE-PLAN says both

| Where | Says |
|---|---|
| Part 3 family table | **SData** computes both bands; Crystal is the **cross-check** |
| Part 3 hybrid table | **SData**, both bands |
| **Phase 2 build order** | **Crystal Target** + SData Non-Target |

The code computes **both bands** in `compute_penetration_by_segment()`, which
matches the two Part 3 statements. Agent memory follows the Phase 2 version.

**Why it matters:** the Crystal penetration report covers the **Target universe
only**. Taking Target from Crystal while computing Non-Target ourselves puts the
two bands on **different universes** — the "gated disjoint + complete" risk that
same line names.

**Currently:** SData computes both, and the reconciliation is against Crystal —
which is the Part 3 reading and the one the verification history supports.

---

## Open items

| # | Item | Owner |
|---|---|---|
| 1 | Validate beyond Pierce against the previous analyst's latest | Jiho |
| 2 | Two CRM lodging reports return **784 vs 1,548** properties for the same state — at most one is right, nothing marks which | CRM owners |
| 3 | `REFERENCE.md` still lists the broader restaurant whitelist and 40+ rooms **(41+ is superseded — the administrator 7/21, ruled 7/29)** — both stale | doc fix |
| 4 | Statewide-penetration aggregation is among the ~25 unverified candidate gaps | — |

---

## Non-Target penetration

Sub-threshold hospitality (smaller restaurants and hotels) uses the **same
formula** — active ÷ (active + inactive) — via `compute_penetration_by_segment`,
with the % divided at map time.

**⚠️ No external source has ever validated the Non-Target band.** The Crystal
pivot notes SData remains the source "only where no report exists (non-target
penetration)" and must **reconcile exactly with Crystal where they overlap** —
Jiho's cross-source gate: *"if we find the numerator for nontarget as 55, then
billable (all active) should be 55 in crystal."*
