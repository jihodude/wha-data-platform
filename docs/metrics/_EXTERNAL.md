# External systems — SLX and Crystal defects, tagged to the metrics they hit

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


Everything that is **not our logic**: platform behaviour, data-quality defects,
and CRM report semantics. Each entry says what it is, the proof, **which metrics
it affects**, and **the open question with an owner**.

Companion to [`_SHARED.md`](_SHARED.md) (our own rules) and the per-metric files.

**Legend:** ⛔ blocks a number · ⚠️ distorts a number · 🔧 forces a workaround ·
✅ resolved

---

# PART 1 — SLX platform (API / query behaviour)

| # | Defect | Effect | Affects | State |
|---|---|---|---|---|
| S1 | **`payAllocationViews` collapses multi-line payments.** Its `$key` is the payment **DOCUMENT** id; a payment covering N invoices emits N rows whose content collapses onto one arbitrary line, query-plan dependent | A genuinely-paid invoice can carry **no** allocation row | Retention (numerator), New sales revenue | 🔧 guarded — an **undatable payment is never demoted** |
| S2 | **`payAllocationViews` cannot be filtered by account** — account filters silently return **incomplete** rows (proof: Pond's $1,070, visible by `Invoice_number`, invisible by `AccountId`) | Every payment question needs a date-range pull filtered locally | Retention, New sales revenue | 🔧 |
| S3 | **No cash-receipt date on invoices** — `Due_Date` == `Invoice_Date`. Full field dump verified; **no payments entity is exposed** (9 names probed, all 404; 291 entities enumerated) | "When did they pay" requires S1/S2 | New sales revenue (basis), Retention | 🔧 `payAllocationViews.AllocationDate` is the answer, found 2026-07-21 |
| S4 | **`Invoice_total` is always null** — `Net_invoice` carries the amount | A field named for the total contains nothing, on every row, forever | Retention revenue, New sales revenue | 🔧 confirmed 2026-05-08 |
| S5 | **Sage sync duplicates invoices** — same invoice twice, once `Balance=0.0`, once `Balance=None` | Every query must dedup or double-count | Retention (both halves) | 🔧 dedup by AccountId |
| S6 | **`cMemberGens.Membernum` is EMPTY database-wide** | No joinable member id between CRM exports and the database — rows are matched by **name** | Drops (banding), any Crystal↔SData join | 🔧 name bridge; 263/264 rows resolve |
| S7 | **`AccountExtension` breaks with `select=`** — it drops the nested `Account.$key` | Must fetch every field on every row | Retention (status dates), Drops | 🔧 |
| S8 | **`select=` returns HTTP 500 on `users`** | Same | Territory discovery | 🔧 |
| S9 | **`accounts` cannot paginate reliably** — cursor unsupported; the legacy `$next` fallback is documented as *approximate* on large results | Counts over accounts cannot be fully trusted at scale | Billables, Penetration, BOB | ⚠️ open |
| S10 | **NULL trap** — `field ne 'x'` silently drops rows where the field is null | Every exclusion filter must be written twice | New members (`Salescode`), all filtered queries | 🔧 `(x ne 'v' or x eq null)` |
| S11 | **Territory is not a field** — path is `account.AccountManager.Id` → `territory_map.yaml` | A rep change silently rewrites history; a missing mapping drops a whole book (the NRA chains fell out entirely until 7/13) | Every territory-split metric | 🔧 |
| S12 | **Per-territory bulk joins UNDER-FETCH** on large sets (`Account.AccountManager.Id` on `cMemberGens`/`cRestProfiles`) — −37..−97 actives/territory, **scaling with size**, so small territories looked exact | Silent undercount that hid itself | Billables, Penetration, Retention, Revenue | ✅ fixed 2026-07-14 — Id-batch backfill |
| S13 | **Silent-partial pagination** — the client's old policy returned PARTIAL data with only a Python warning when SData 500'd | **Every bulk metric silently undercounted**, varying run-to-run with retry luck | All | ✅ fixed 2026-07-14 — compares `$totalResults`, cursor-walks the remainder, fails loud |
| S14 | Single quotes must **not** be percent-encoded; `@` in date filters stays literal; ~500 records/page | Query construction | All | 🔧 |
| S15b | **The old SLX password is recoverable from git history** and **cannot be rotated from our end** | Credential exposure, indefinite | All | 🔧 **Decided mitigation:** erase remaining *plaintext* traces (working tree, memory, docs — done) and **let the credential die with the vendor's CRM migration**. Git history is deliberately left. **⚠️ This means the exposure persists until the migration lands** — if that slips, the mitigation slips with it |
| S15 | **The SLX host is being migrated by the vendor** — `crm.wrahome.com` will change | Integration needs re-pointing | All | ⚠️ isolate host/auth so it is one config change |

**⚠️ S1's audit is stale.** PROBLEMS marks the `$key`-collapse **CLOSED, no live
MPR exposure** (2026-07-24) — but that audit predates retention's 2026-07-28 use
of `payAllocationViews` for payment dates. **The exposure should be re-audited,
not assumed closed.**

---

# PART 2 — SLX data quality (records, not code)

| # | Defect | Named proof | Affects | Question → Owner |
|---|---|---|---|---|
| D1 | **A member on the billing roster was never invoiced** | `Four Points By Sheraton Bellingham` `[account-id]` — Active, BM5, **38 historical invoices, 0 in FY2026**; both children (`B-Town Kitchen`, `Chinuk`) also 0. the membership administrator bills **$2,046**; the CRM retention export lists them at BM5 | ⛔ Retention (NorthCentral denominator can never match) | Where does $2,046 come from, and who issues the missing invoice? → **Billing** *(Jiho 7/28: ruled THEIR gap, not ours)* |
| D2 | **Duplicate account records for one business** | `Four Points by Sheraton Bellingham` `[account-id]`, Type Prospect, 0 invoices | ⚠️ any count over accounts; name-matching can resolve to the wrong record | Which is the real record? → **CRM owners** |
| D3 | **Accounts with no `AccountManager` are unreachable by any query** | `[a member]` — Closed, **$1,070 of dues in the CRM's own drops export**, manager empty | ⛔ Drops (prime suspect for the 25 truly-absent), Billables, Retention | Can every account be required to have an owner? → **CRM owners** |
| D4 | **Two SLX fields give the same event dates 3 years apart** | `[a member]` `[account-id]` — history log says Active→Inactive **2023-12-21**; `AccountExtension.StatusDate` says **2026-06-30**; **invoiced in 2026** | ⛔ Retention (who was a member on date X), Drops (41 members carried 2012–2024 dates) | Which field is authoritative for a leave date? Is a rejoin logged anywhere? → **CRM owners** |
| D5 | **Status history is incomplete** | Only **5 of 14** inactivated BM5 members had a `Change to Status` record | ⚠️ Retention, Drops | — |
| D6 | **A closure recorded with the membership left open** | `[a member]` — closed 2025-10-15, flagged member at closure, **no drop record, status never flipped**. Sheet read Closed 1 / Drops 0 | ⚠️ Drops (undercount) | What should happen on closure, and who does it? → **CRM owners** |
| D7 | **The monthly cleanup is entered late and backdated** | Nine BM5 accounts: `StatusDate = 2026-06-30`, records **modified 2026-07-21** | ⛔ Retention — **this single mechanism is the 146-vs-136 dispute** that cost multiple days | Can it be entered on the day it happens? Can a closed month be frozen? → **membership leadership** |
| D8 | **Adjustments carry the original invoice's date, not their own** | `[a member] La Spiga` #0148242 — AD row `Invoice_Date 2026-04-01`, `CreateDate 2026-06-23`. **10 of 10** BM5 adjustments | ⚠️ Retention revenue, any month-end figure | Is there a field recording when the write-off happened? Can reports use `CreateDate`? → **CRM owners** |
| D9 | **Membership product is never cleared on exit** | **2,986** inactive/closed accounts carry one. Oldest: `Clarion Hotel Seatac`, Closed **1999-11-09**, still a membership product. Lapse spread: 401 under 12mo · 1,084 at 2–5yr · **796 over 10yr** | ⚠️ "Billable" is not directly computable | Answered by Jiho 7/28 — billable is **bill-month scoped, fixed at month end**. Remaining: **which day fixes it?** → **membership leadership** |
| D10 | **The BOB flag is effectively unused** | `CDiverseOwnership` populated on **11 of 9,546** sampled accounts (0.1%) | ⚠️ BOB (unautomatable; hand-flagged monthly) | Can it be filled in? And where is *Black-Owned* specifically recorded — the field is general diverse-ownership (Latino chapter, AAHOA) → **Admin** |
| D11 | **A 12th login holds a whole business line** | `RetroCoordinator` `U6UJ9A00008G` — **1,605 accounts** (1,145 Closed · 292 RRO · 150 Active · 14 RRO LNI Active · 4 Inactive) | ⚠️ Billables (**143** of the 170-report gap), Drops (**107 of 264 rows**, 104 at BM14, $122,892) | Should retro/L&I appear in membership reports? → **membership leadership** *(Jiho 7/28 answered what RRO IS; the count rule is still contested — see the drops file)* |
| D11b | **`ReinstatedDate` is OVERWRITTEN on a later reinstate** | the membership administrator [J 26:43–27:33]: *"if a member reinstates again later, SLX overwrites the reinstate date, so an old year re-run returns different numbers. Within the current year it's fine"* | ⛔ **New members** — the cohort filter is `ReinstatedDate eq null`, so a member who reinstates again **retroactively changes a closed month's count**. This is a *history-rewriting* field, the same class as the status filter removed on 7/15 | Can a reinstate history be preserved rather than overwritten? → **CRM owners** |
| D12 | **Self-reported / lagging fields** — FTE, statuses, duplicates | — | All | **Accepted limit:** *"we can be perfectly faithful to a flawed database — data-entry quality is WHA's operational domain. Mitigation: anomaly flags and loud warnings, never silent correction"* |

---

# PART 3 — Crystal / CRM report semantics

| # | Behaviour | Proof | Affects | Question → Owner |
|---|---|---|---|---|
| C1 | **Two billables reports disagree by 170** | `Active Billables By Ac And Fte` = **2,143** · `Billables By Territory Summary By Bm` = **2,313**. Decomposed: 143 Retro + 9 EF School − 1 ARM + **19 unexplained** | ⛔ Billables (and everything using it as a base) | Which is authoritative? → **the membership administrator** |
| C2 | **Two lodging reports disagree ~2×** | **784** vs **1,548** properties, same state, same week | ⚠️ Penetration | Which is right? → **CRM owners** |
| C3 | **`Adjusted Retention` is currently-active only** | A closed month returns a different answer every run: May = **136** today, the membership administrator's same-cycle file = **146** | ⛔ Retention — the CRM cannot reproduce its own history, so it can never be a stable check | Can it stop filtering to active? → **CRM owners** |
| C4 | **The lodging market universe is a hidden report filter** | Drops `RV Park or Campground`, `Vacation Rental`, `Military Housing`, `Bed & Breakfast`. Our market 833, theirs 782. **The rule exists only inside the report definition** | ⚠️ Penetration — cost ~3 months of unexplained mismatch | ✅ adopted 2026-07-19 (subtype in-list, derived from all 782 rows) |
| C5 | **Room threshold** | The report's cutoff is ≥ 40; 23 hotels sit at exactly 40 | Penetration | ✅ **RESOLVED — the report was right.** the membership administrator confirmed 40+ on 7/21; *our docs* were stale at 41+ |
| C6b | **All three drops reports filter their date window on `MODIFYDATE`** — the account record's last-touched timestamp, NOT a status or drop date (report definitions read live 2026-07-29). **Latent fragility:** any edit to an old dropped record re-admits it to a current window. **Measured today: NOT currently distorting** — 240 of 241 export rows have a `StatusDate` inside the stated window, because for a dropped account the status change *is* the last edit | ⚠️ latent | Drops | Should the window use a status/effective date? → **CRM owners** |
| C6 | **The drops export carries no per-row date** — only Bill Month. ⚠️ **Partially corrected 2026-07-29: the REPORT carries its window in the footer** (*"Report is run for this date range: 10/1/2025 and 7/21/2026"*), so the window is machine-readable even though rows are not dated | — | ⛔ Drops (forces bill-month attribution; and the **Oct 1 2026** FY-rollover problem) | Move the window annually, or one schedule per FY? → **Jiho** (see `_SHARED.md`) |
| C7 | **The same report parses differently run-to-run** | June 8's export has a different layout than July 26's; the parser gate **refused** it | ⚠️ every Crystal-sourced family | 🔧 gates catch it; layout-agnostic parsing where possible |
| C8 | **The `New Member Sales` report has a known gap** | `[a member]` — a real June NorthKing member who paid **$2,435**, absent from the report. the membership administrator's edition follows the report, so her June NorthKing is missing him | ⚠️ New members, New sales revenue | ✅ he counts (2026-07-22); the report is demoted to secondary |
| C9 | **The `New Member Sales` report counts rejoins as new** | Our counts matched it exactly while we excluded rejoins by the administrator's rule — so the report shares the rejoins-as-new behaviour | New members | ⚠️ two ratified rulings disagree — see the new-members file |
| C10 | **Reports contradict each other, violate agreed definitions, and staff cannot always explain them** | the administrator tracks manually because the sales report *"misses things"* | All | **Doctrine (7/14):** CRM reports are **rank 3** — convention documentation and reconciliation targets, **never truth** |
| C10b | **NRA is not billed at all — they pay quarterly** | the membership administrator [J 35:01, 35:36, 36:00]: *"We don't bill the NRA. They just pay us quarterly"* — $24k per quarter. **Verify annually** with whoever owns the NRA relationship that the agreement is unchanged | Majors/NRA revenue reads $0 in the MPR, correctly | Annual check → **Finance** |
| C10c | **Bill months 13–16 are named special groups, not a category** | ✅ **MEASURED 2026-07-29:** **BM13 = CVBs/tourism bureaus** (24 rows; Seattle-King County CVB, Visit Spokane… — the "Apple WA" note [J 35:16] was incomplete; 4/19 checked ARE dues-billed) · **BM14 = RRO** · **BM15 = national chains/NRA book** (109 rows — Darden, Red Robin…; 0/20 billed) · **BM16 = 2 chains** (Harman, P.F. Chang's; unbilled). Drops handles all via invoice-evidence-first + status-gate carve | Retention, Drops, Billables | ✅ residual: confirm Apple WA's placement with **Victoria** (WorkSafe) whenever convenient |
| C11 | **Scheduled triggers self-expire** | SLX deletes a trigger after firing when the run-to date is not far-future — it killed two dues test schedules and Jiho's first four attempts | ⛔ the whole capture pipeline | 🔧 all 10 schedules set to **2030-12-31** — renew before then; the signature of missing it is every report reporting STALE on the same day |
| C12 | **Every schedule for one report produces the same filename prefix** | The archive holds `DroppedMembersHospitalityBM8_suzannes_…`, a name the report does not have — suggesting the **Description** field drives the filename, but that was an interactive export | ⚠️ blocks the one-schedule-per-FY option (C6) | **Free test:** give one live schedule a distinctive Description and read tomorrow's filename |

---

# PART 3b — Solved once, do not re-derive (`ISSUELOG.md`)

*Every one of these cost a full investigation. They are recorded so no future
session pays twice.*

| Date | Symptom | Root cause | Affects |
|---|---|---|---|
| 07-14 | Every bulk metric undercounted, **differently each run** | SData `$next` returns a **different random row subset per pass** on large results (server-side unstable ordering). Their own Crystal reports go straight to SQL and never see it | All. EastKing read **400 vs 529 rows minutes apart** |
| 07-14 | Drops captured **15%** of the CRM's dropped-member list | The fetch demanded `Status eq 'Inactive'`, but closed businesses are **97% `Status='Closed'`** (Sold → Closed/RRO); plus no membership filter, so prospect noise | Drops. Gate went 15% → 38% → **100%** (328/328) |
| 07-14 | Retention **October column empty** | FY edge: Oct = **BM9 of the PRIOR fiscal year**; the engine computed the *future* September | Retention |
| 07-14 | Billables split leaned hospitality (2,149/145 vs 2,132/161) | 11 vendor partners under the **unmapped** AlliedRelationsManager house user. **NOT** a missing-type bug — 0 blank types statewide, and the product-name fallback was *double-dead* because `MembershipProduct` is a **nav object with no name in the payload** | Billables |
| 07-15 | *"SLX is office-network-only"* — a **belief**, not a fact | Split-horizon DNS + the web ROOT path 403ing externally + a flawed hairpin test. The SData API **is** internet-reachable with a valid DigiCert cert | Everything — it unblocked working from anywhere |
| 07-15 | Mar/Apr revenue ~$9k under, counts 3–4 short | Cohort queries filtered `Status eq 'Active'` **TODAY**, so enrollees who later dropped were **retroactively erased from history** | New members, Revenue |
| 07-16 | Cross-territory sales in the wrong TM's column | The seller lives in **`AccountExtension.Originator`** (UI *"Acct. Originator"*). `CreateUser` is the **data-entry clerk**, not the seller | New sales revenue — **this is the field the unimplemented seller-credit rule needs** |
| 07-16 | **473 dropped members showed $0 lost revenue** | Chain child locations **bill on the PARENT** account (Papa Murphy's #105 has 0 own invoices) — invoice archaeology cannot see it | Drops $. Fix: drop amount = **Dues Level** = the product's `products.Price`, which is their export's own `dues` convention |
| 07-16 | **4 of March's 22 members missing**, and June's Palouse | `EnrolledDate` stores **midnight PACIFIC** (07:00Z), so `le @last-day@` compares against midnight and **every last-day-of-month joiner was silently dropped, all year** | New members, Revenue |
| 07-16 | Majors/NRA combined penetration blank | A **missing segment VETOED** the combined ratio | Penetration — a missing segment now contributes zero |
| 07-16 | **The entire TM-Snohomish sheet showed East King's numbers** | Template clone bug — the sheet was duplicated from TM - E KING and its **376 formula cells kept `"East King"`** as the territory criterion. **Invisible to every NUMERIC gate**: the data layer was correct, the display wiring lied | All (display). Caught by **Jiho's eyeball on a stale file** — now guarded by `scripts/wiring_check.py` across 8,610 formulas |
| 07-17 | Console served a **fresh-looking MARCH file** | Three faults at once: period defaulted to `2026-03` for any env-less process; each session re-downloaded and rewrote the local cache, giving the March file **today's mtime**; and the freshness badge read **file mtime, not `_meta.saved_at`** | All. Caught by **Jiho downloading from the console** |

**Pre-campaign, summarised:** duplicate Sage-sync rows wiped Rooms/FTE
(prefer-non-null + Id-batch backfill) · **`cMemberGens` `select=` silently drops
fields — never use `select` on it** · `Salescode` is the dues category, **not**
the seller · **`Membernum` ≠ the report MID** — the report's MID is *"WRA
Member #"* on AccountProfile, and `CustomerNo` on invoice headers.

> **Two of the worst bugs were caught by a person looking, not by a gate** — the
> Snohomish sheet and the stale March file. Both were invisible to numeric
> checks because the data was right and the *wiring* lied.

---

# PART 3c — The five stakeholder questions (2026-06/07) — all now answered

*`docs/handoff/stakeholder-questions-report-1.md` *(archive repo)* framed five human-answer
questions as blocking final correctness. Every one has since been settled — but
the doc still reads as open, so it is resolved here rather than re-asked.*

| # | Question | Answer | Where |
|---|---|---|---|
| 1 | **Retention % — members or dollars?** | **BOTH**, matching the revenue-goal display | membership leadership, 2026-06-17; re-confirmed 06-28 |
| 2 | **Goals — Hospitality/Allied or Target/Non-Target?** | **Target/Non-Target**, *"so reps focus on harder Target accounts"* — supersedes the goals workbook's H/A default | department leadership, 2026-06-17 |
| 3 | **Penetration — validate beyond Pierce** | Superseded by a better check: account-ID-level reconciliation against the raw Crystal exports, **all 11 territories, actives exact** | 2026-07-19 |
| 4 | **Benefit Reviews — are they in SLX?** | **No.** Three independent primary sources confirm they live only in the specialists' private tracking. *"The verbal 'it's in SLX' claim is not backed by any artifact."* Then **retired entirely** 7/20 | 2026-06-28, 2026-07-20 |
| 5 | **Where do the non-payment "reason" notes live?** | **`AccountExtension.Statusreason`** — used by `drops.py` for the whole reason vocabulary. The retention detail additionally carries a **"Last Note"** from SLX History (`AC…Notice` activity), shown only for members with a positive balance | in code |

**Note the framing that turned out to be right:** *"the June demo blew up mostly
because numbers were computed against ASSUMED definitions instead of confirmed
ones."* That is the same diagnosis THE-PLAN reached a month later, and it is
AGENTS.md hard rule 6.

**⚠️ Question 3's premise is stale:** it describes the food-service whitelist as
*Restaurant / Catering / Recreational / Concession*. The code narrows penetration
restaurants to **`Type = 'Restaurant'` only**, which STATE's ratified-rules line
confirms.

---

# PART 4 — The open questions, consolidated

> 📄 **THE MASTER QUESTION LIST (2026-07-30):**
> *the stakeholder question list (archive repo)* — every
> surviving question, by owner (the membership administrator · membership leadership · CRM owners · Admin ·
> Finance), plain-worded with named members. **This Part 4 below is the
> graveyard + changelog**; the clean list lives there. The defect evidence
> lives in `../BROKEN-RECORDS.md` *(archive repo)* *(archive repo)*.

*Everything above that still needs an answer, by owner.*

## the membership administrator

0. ~~CMP communication debt~~ — ✅ DEAD 2026-07-29: **the administrator is the SOURCE of the
   correction** ("CMP is an acronym for a program"), so there is nothing to tell her.
1. ~~Which billables report is authoritative~~ — ✅ CLOSED 2026-07-29: they answer
   different questions (snapshot vs billing schedule). See the billables file.
2. ~~Recognition basis~~ — ✅ **the administrator already answered**: count = sale month;
   revenue = added each time they pay. Logged in the new-sales file.
3. ~~Rejoins~~ — ✅ RULED 2026-07-29 (Jiho): **not new if not their first time
   paying.** Residual → **membership leadership**: her sales report counts them as new (32/194 measured).
4. ~~All-MSC members~~ — ✅ reframed: MSC ≠ payment plan; **no SLX code exists**
   for payment plans (the administrator). Detection = payment-date patterns. Ours.
5. ~~Write-offs reduce the ask?~~ — ✅ neither: billed = Dues Level (2026-07-29).
5d. ~~add-on locations~~ — ✅ **RULED 2026-07-30 (Jiho): count children, like
    her own report does** (measured: `Puget Sound Pizza - LakeBay`/`- Port
    Orchard`, children of `Cannell Investments`, are member rows in the CRM
    export). `ParentId` exclusion comes out of the count → code batch.

5c. ✅ **RULED 2026-08-03 (Jiho, post-leadership-meeting): NO — retro-book
    losses do NOT show on the report.** The meeting framed retro as its own
    department, no longer "membership" (new forfeiture rule, "doesn't screw
    up retro or Accounting"); the report is the membership team's. The 82
    members / $112,521 stay a disclosure, not a report row. Original
    question kept below for history.
    ~~**⭐ THE ONE DROPS QUESTION — narrowed 2026-07-29 PM to something only she can answer.**~~
    *"Accounts like `Hilton Motif Seattle` are retro-program accounts — L&I
    number, retro program year — but they also pay membership dues ($4,944.50 at
    bill month 6). They sit on the Retro Coordinator's book, not a territory
    manager's, and always have. When one of them stops being a member, should
    that loss show on the report — and where? It was never in any TM's numbers."*
    **Worth 82 members / $112,521 this FY.** Options: an honest Retro Coordinator
    row · statewide total only · out of drops entirely. **This is the last open
    item in the drops family.**

5b. ~~the retro race question~~ — ✅ **ANSWERED EMPIRICALLY 2026-07-29 PM**
    (Jiho's check): section-parsed all 8 of this FY's official monthly runs
    from the SLX archive — 70 of the 101 RRO members appear, **all in RRO
    sections, zero ever as Inactive/Closed**. The flip always wins; the
    official process has never counted a retro-bound exit. Now a DISCLOSURE —
    **+82 members / ~$112,521** vs official history (corrected from 38/$33k by
    the proving run; see the drops file) — not a question.
    **the membership administrator's drops question count: zero.**

## membership leadership

6. ~~Which day fixes the billable base~~ — ✅ RULED 2026-07-29 (Jiho): **pay-window
   close, end of M+1** — one clock with retention.
7. ~~Retro/L&I in membership reports?~~ — ✅ RESOLVED by the RRO rule (drops file):
   billed-last-cycle exits count; the rest is detail-only. **NEW for membership leadership:** the
   `New Member Sales` report counts rejoins as new AND misses real members — both
   directions, one report.
8. **Can the monthly cleanup be entered on the day it happens**, and can a closed
   month be frozen? (D7)

## CRM owners / IT

9. **Can every account be required to have an Account Manager?** (D3)
10. **Which field is authoritative for a leave date**, and is a rejoin logged? (D4)
11. **Is there a field recording when a write-off happened** — can reports use
    `CreateDate`? (D8)
12. **Can `Adjusted Retention` stop filtering to currently-active?** (C3)
13. **Which of the two lodging reports is right?** (C2)
14. **What excludes `[a member] Cafe & Patisserie`** from the retention export —
    Active, real BM5 invoice, absent from the export *and* the membership administrator's file?
15. **What should happen to a membership when a business closes, and who does it?** (D6)
16. **Which `Four Points` record is real, and who issues the missing invoice?** (D1, D2)

## Admin

17. **Can `CDiverseOwnership` be filled in**, and **where is Black-Owned Business
    specifically recorded**? (D10)
18. The **monthly BOB list** — the only machine-unreadable input in the report.

## department leadership

19. ~~Allied in retention %~~ — ✅ RULED (Jiho, T/NT lock 2026-07-29): included, Non-Target.
20. ~~Negative drop revenue~~ — ✅ dead: credits never value a drop; nothing negative reaches the face.
21. ~~Drop reasons on the face~~ — ✅ LOCKED 2026-07-29: all 19, direct wire.

## Membership team

- **Negative drop revenue** — see question 20 above.

## Jiho / us

**🔒 One standing security item.** The old SLX password is recoverable from git
history and **cannot be rotated from our end**. The ratified mitigation is to
scrub plaintext traces (done) and let it **expire with the vendor's CRM
migration** — so the exposure is bounded by a date **we do not control**. If the
migration slips, revisit; it is not a fire, but it is not closed either.

**⏰ Two dated obligations — both fail silently if missed. Detail in
[`_CAPTURE.md`](_CAPTURE.md).**

- **2026-10-01** — the drops FY window starts spanning two years. Guarded (the
  run blocks rather than lying), but the decision between an annual window move
  and one-schedule-per-FY is unmade, and the latter is blocked on a free test.
- **2030-12-31** — all 10 CRM schedules expire together. The signature of missing
  it is every report reporting STALE on the same day.

**🔖 QUEUED — THE AUDIT-LOG PASS (Jiho, 2026-07-29: "add audit for later, don't
forget").** SLX's `history` entity holds field-level change records with OLD
VALUES (`Description` = "Change to <Field>", `Notes` = `"Field: new\r\n  Old
Value: old"`; query `history where AccountId eq '<id>'`, batch 12 with OR).
Discovered 2026-07-29 while recovering retro bill months (88/95). **It plausibly
answers three questions currently assigned to CRM owners — without asking:**
- **D4** which field is authoritative for a leave date → the log records the
  actual `Change to Status` transitions with old values (`Status: Inactive, Old
  Value: Active`), so the true sequence is reconstructible.
- **B3 / D11b** `ReinstatedDate` overwritten → check whether reinstates appear as
  logged changes, which would preserve the history the field destroys.
- **D7** backdated cleanup → the log's `CreateDate` vs the stamped `StatusDate`
  measures the lag directly, per account.
**Caveat learned the hard way:** the log is **NOT complete for every field** —
retro `AccountManager` moves are provably absent (see the drops file). So any
finding must be corroborated by a log-independent route before it is trusted.

0. **⚠️ The SOP ships Aug 14 with at least two superseded rules** (41+ rooms as a
   deliberate divergence; CMP dues counted in new sales). Re-check it line by
   line against THE-PLAN and DECISIONS before delivery.

21. **Oct 1 2026** — annual window move, or one schedule per FY? Blocked on C12's
    free test.
22. **Re-audit the `payAllocationViews` exposure** now that retention reads it.
23. ~~RRO transitions~~ — ✅ RESOLVED 2026-07-29: the universal billed-last-cycle
    gate. See the drops file + `handoff/2026-07-29-rro-drops-evidence.md`.

## Finance

24. **NRA revenue** — a Dues Summary workbook figure, not derivable from SLX.
