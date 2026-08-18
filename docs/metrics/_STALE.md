# Stale content register — what to fix, and where

> ## 🔴 2026-07-30 — the recorded call superseded MORE than any prior day
>
> Primary evidence: `../source-documents/2026-07-30-MPR-meeting-transcript.docx` *(archive repo)* *(archive repo)*.
> Every item here is now **dead**, and anywhere it still appears is stale:
>
> | Dead rule | Replaced by | Where it lingered |
> |---|---|---|
> | RRO conversions count as drops (the 82-member / $112,521 "rescue") | **RRO is never a drop** — *"RRO is not a dropped"*; FYI rows → flag list | `drops-target-count.md` (marked), `_EXTERNAL` 5c, BROKEN-RECORDS B1b |
> | RRO members stay in retention | **They leave the cycle entirely, both sides** | `retention-*.md` (stamped) |
> | "Ever paid before = renewal, never new" | **~6-month gap ⇒ NEW member**; the admin rewrites the enroll date | `new-members-target.md` (marked) |
> | "Rejoins count as new, per the reports' listing" (Crystal pivot) | same 6-month rule — *both* prior rules died | `_STALE` #13, DECISIONS 7/27 |
> | The CRM sales report "counts rejoins as new" = a defect | **Retracted** — the report was right; our screen was wrong | membership leadership brief, `_EXTERNAL` |
> | Crystal overlay supplies billables | **SData computes**; the FTE export is reference | `billables-*.md`, `METRIC-CATALOG` |
> | Drops = 5 invented buckets | **All 19 Crystal reasons, direct** | `_SHARED`, `_OUTPUT` |
> | 41+ rooms | **40+** | six code comments (fixed), four metric files (fixed) |
> | Retention exceptions belong in logic | **No grace** — *"it's when they pay"*; exceptions → adjustments tab | `retention-*.md` |
> | Drops "155 vs 204, we undercount 24%" | **Void** — their 204 counted RRO rows we correctly exclude | RECONCILIATION (frozen), `METRIC-CATALOG` (fixed) |
>
> **Also superseded: my own claims.** The "retention is washed to 100%" alarm is
> withdrawn (see `handoff/2026-07-30-LIVE-STATE-SWEEP.md`), and BROKEN-RECORDS
> failed its first spot-audit — 2 of 3 items checked were wrong.

Every place a superseded rule is still written down, found by reading the
sources end to end. **This is the doc-cleanup worklist.**

Sorted by blast radius: a stale rule in a *deliverable* or a *primary reference*
teaches the wrong thing to whoever reads it next.

**Rule for fixing:** correct the doc **and** note what superseded it, so the next
reader can tell a correction from a contradiction.

---

## 🔴 CRITICAL — a deliverable, or a doc people are told to trust

### 1. The 41+ rooms rule — stale in **five** places (SETTLED 2026-07-29)

**RULED (Jiho, 2026-07-29): 40 or higher.** `Rooms >= 40` = Target. The code is
correct. The official SOP's *"over 41 Rooms"* and the 7/13 entry are superseded.

**So these are genuinely stale and should be corrected:**

| Where | What it says |
|---|---|
| `docs/REFERENCE.md` *(archive repo)* lines 52, 56 | *"hotels by `Rooms >= 41`"*, *"≥41 rooms"* |
| **`docs/SOP.md` *(archive repo)*** (ours) ⚠️ **contract deliverable, due Aug 14** | *"the MPR enforces the team's 41+ rooms rule; CRM reports include 40-room hotels. **Ours reads slightly lower ON PURPOSE**"* — there is no such divergence |
| **the official MPR SOP** (`source-documents/`) — *"Lodging over 41 Rooms"*. **Theirs, not ours** — flag it to the team rather than editing |
| `docs/handoff/2026-07-19-penetration-evidence.md` *(archive repo)* | Scripts a talking point built on 41+. The **hotel list is still good**; the script is not |
| `target.py:113` (comment), `target.py:212`, `billables.py:143`, `drops.py:543`, `target.py` module docstring | *"41+ (2026-07-13)"* — the behaviour is correct, the comments lie |

**Cost already incurred:** an outbound evidence sheet told membership leadership the CRM
report's 40-room threshold was a defect on *their* side. Withdrawn 2026-07-29.

### 2. CMP dues counted in new sales — in the SOP

**Correct:** CMP is a **Claims Management Programme service fee**, excluded
entirely (2026-07-21). Proof: `[a member]`'s relabelled retro fee.

`docs/SOP.md` *(archive repo)* tells the reader: *"MPR = CRM's New Member Sales report **plus
payment-plan ('CMP Fee') dues** the CRM report ignores."* That was true for six
days, in July.

### 3. `docs/SOP.md` *(archive repo)* as a whole must be re-checked line by line

It is written *"so a person who did NOT build the system can run it"* and is due
**Aug 14**. Two of its five reconciliation one-liners are wrong. The rest should
be verified against `THE-PLAN` and `DECISIONS` before it ships.

---

## 🟠 HIGH — a primary reference contradicting a ratified decision

### 4. `REFERENCE.md`: *"Allied — excluded from retention %"* (line 56) — ✅ RESOLVED 2026-08-11

**RULED (Jiho, 2026-08-11): Allied = Non-Target, INCLUDED in retention.** The
line above is now simply stale and should be read as superseded.

This settles the three-way contradiction: DECISIONS 2026-07-13 (*"Allied gets
NO special-casing… Non-Target across ALL member metrics **including the
retention %**"*) was right, the 2026-07-28 application of D2 to retention was
the outlier, and the code followed the outlier until 8/11.

Shipped: allied accounts stay in the cohort and are locked to Non-Target
regardless of size. The dues-invoice requirement is unchanged and gatekeeps on
its own — 59 of 202 allied rows carry no bill for their cycle and remain out.

**Known consequence:** the membership administrator's own retention reports EXCLUDE allied
(evidenced 2026-07-21, *"our 20 = her 18 + 2 Allied"*), so we now diverge from
her by design — measured at roughly 2 points statewide. See DECISIONS
2026-08-11.

### 5. `REFERENCE.md`: the four-type food-service whitelist (line 52)

Says `{Restaurant, Catering, Recreational, Concession}`. The code uses
**`Type = 'Restaurant'` only**, and STATE's ratified-rules line agrees with the
code. Also repeated in `handoff/stakeholder-questions-report-1.md`.

### 6. `REFERENCE.md`: Benefit Reviews written as a live MPR section (lines 74–84)

**Retired entirely 2026-07-20** — sheet, parser, model field, engine ingest,
writer plumbing and migration utility all removed. The definition is worth
keeping as history; it should say so.

### 7. `STATE.md` and `PROBLEMS.md`: Corporate/Grocery listed as an open question

**Closed 2026-07-13:** penetration is a *location* metric (correctly excludes
them); the member splits are a *dues-payer* metric (Corporate **is** a member
with aggregate FTE — excluding would undercount). *"Orthogonal, both correct. No
`target.py` change."*

### 8. `PROBLEMS.md`: *"fix the null territories"* (P2, issue 11)

NorthKing / Pierce / Spokane-NE have null goals **intentionally** — they are
commissioned on total revenue. The phrasing implies a bug where there is a
decision.

---

## 🟠 HIGH — a brief sent to the membership administrator, now wrong on its headline item

### 8b. `handoff/2026-07-18-jen-confirmation-brief.md`

Sent to the membership administrator as *"a courtesy confirmation, not an open question"*, with the
promise that *"each has a one-line revert if you want it changed."* Its **first
and most prominent rule was reversed three days later**:

| The brief told her | Actually |
|---|---|
| **"Payment-plan money counts as sold revenue (the thing you hand-add)"** — MSC lines count when labelled "CMP Fee" | **Reversed 2026-07-21.** CMP is a **Claims Management Programme service fee**, not dues. Excluded entirely. WRA only |

It even uses [a member] as *proof of calibration* — the same account that
later **broke** the rule when its line turned out to be a Retro Q3 fee.

**Why this one matters more than a stale doc:** she was asked to confirm it. If
she did, she confirmed something we no longer do. **She should be told the rule
changed** — this is a live communication debt, not just a documentation fix.

**Still accurate in that brief:** BOB promo members count at face value (her
convention); house Allied vendors are out of territory counts; the BOB alert is
month-scoped, so an empty alert means *"no credits owed this month"*, not a
broken list.

---

## 🟡 MEDIUM — superseded but lower-traffic

### 9. Two roadmaps, nothing marking which is dead

`docs/ROADMAP.md` *(archive repo)* (last touched 2026-07-14) vs `docs/ROADMAP-TO-DONE.md` *(archive repo)*
(2026-07-27). Nothing in the older one says it is superseded.

### 10. `handoff/stakeholder-questions-report-1.md` reads as open

**All five questions are answered** (see `_EXTERNAL.md` Part 3c). The
reason-note question in particular was answered *by our own code* —
`AccountExtension.Statusreason`, which `drops.py` has always used.

### 11. `ARCHITECTURE-MAP.md` mess items M2, M3, M6 are resolved

`reconstruct.py` and `snapshots.py` are already deleted; no chimera cache
remains. The doc still lists them as work to do.

### 12. DECISIONS 2026-07-15: seller credit *"Rides Q3/Q4"*

**Implemented the next day** (7/16) via `AccountExtension.Originator`, verified
3/3. DECISIONS is append-only so the entry stays — but two metric files
inherited "unimplemented" from it and were wrong until 2026-07-29.

---

## ⚪ STRUCTURAL — not stale, but actively misleading if read alone

### 13. The Crystal pivot entry (DECISIONS 2026-07-27)

Its consequence list — *rejoins count as new · counts enrollment-basis · BOB
stays an admin input · drops are their export rows* — was **superseded the same
day** by `THE-PLAN.md`, written after the pivot failed its first test. Anyone
reading DECISIONS alone will implement the wrong thing.

**`THE-PLAN` says so itself:** *"This supersedes every earlier plan, pivot doc
and reconciliation strategy. If a doc conflicts with this one, this one wins."*

### 14. `PROBLEMS.md`: the `payAllocationViews` audit marked **CLOSED, no live exposure**

True when written (2026-07-24). Retention began reading that view for **payment
dates** on 2026-07-28, which the audit never covered. Not wrong — **out of
date**, and the difference matters.

### 14b. `THE-PLAN` internal disagreement — **penetration's source**

Three statements in the same document, and they do not agree:

| Where | Says |
|---|---|
| **Part 3, family table** (line 118) | *"**SData** computes both and agrees with Crystal within 0.2%; **Crystal is the cross-check**"* |
| **Part 3, hybrid table** (line 152) | *"Penetration (both bands) — **SData**"* |
| **Phase 2, build order** (line 208) | *"Penetration — **Crystal Target** + SData Non-Target, gated disjoint + complete"* |

Agent memory (`project_accuracy_war_2026_07`) follows the **Phase 2** version:
*"Crystal snapshots answer current-state questions — billables…, **penetration
Target**, and drops."*

**Two out of three say SData for both bands**, and the code computes both bands
via `compute_penetration_by_segment()`. But the build order — the part someone
would actually follow when implementing — says Crystal Target.

**Consequence if the wrong one is followed:** the Crystal penetration report
covers **only the Target universe**, so sourcing Target from it while computing
Non-Target ourselves means the two bands come from different universes. That is
exactly the *"gated disjoint + complete"* problem the same line names, and it is
why the cross-source gate exists (Jiho: *"if we find the numerator for nontarget
as 55, then billable (all active) should be 55 in crystal"*).

**✅ RESOLVED 2026-07-30 (Jiho): SData computes BOTH bands.** No standing
Crystal cross-check either — reconciling against Crystal would imply it is more
accurate than the computation (his reasoning, verbatim in the 7/30 decision
packet). The build-order line is dead; the 2026-07-27 nontarget-55 gate quote
is superseded.

### 15. `THE-PLAN` internal disagreement — BOB

Part 3 states BOB is **NOT** an admin input (*"the earlier draft was wrong"*);
Phase 2 lists *"Goals / BOB — admin inputs, unchanged."* Same document.

### 16. `STATE.md` CAPTURE AND FREEZE vs `THE-PLAN` rule 1

STATE: FY25-26 is frozen, *"not rebuilt from Crystal — proven impossible."*
THE-PLAN Part 4: *"There is no frozen-history seam."*

**Reconciled by the SOP**, which states the missing scope: *"point-in-time
metrics (penetration, billables) cannot be reconstructed for the past — history
exists only where humans recorded it."* The freeze applies to **snapshot**
families; **ledger** families genuinely regenerate. Neither document says this;
both should.

---

## Pattern

**Every stale item above was true when written.** Nothing here is careless — it
is the cost of decisions moving faster than the documents recording them, in a
project where the same rule lives in four places.

The metric files exist so that a rule has **one home**. When one changes, this
register is where the copies get hunted down.
