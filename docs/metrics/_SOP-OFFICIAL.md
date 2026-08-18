# The official SOPs — WHA's own process documents

**Primary sources**, preserved at `../source-documents/` *(archive repo)*:
`SOP - Monthly Membership Performance Report.docx` · `SOP - Dues Analysis.docx`

These are **the team's own instructions**, not our reconstruction. Where they
conflict with a later conversation, both are recorded — an authored SOP and a
verbal confirmation are different kinds of evidence.

---

# The MPR SOP — the whole manual process

## Cadence and audience

- The review meeting is the **3rd Friday of the month**.
- Complete it **at least a week ahead** so the **Director and Senior TM** can
  review results with the team beforehand.
- Method: **duplicate the previous month's tab**, update to the current month.
- Template lives in the **Membership Admin folder → "Performance - TM"**.
- **Distribution: department leadership, membership leadership, membership leadership — CC Kristina and membership leadership.**

## The four reports it is built from

| # | Report | What is taken from it |
|---|---|---|
| 1 | **New Member Sales** | monthly **sales goal** · **actual sales revenue** · **billable count** *(the workbook is password-protected; the password is held by the membership team)* |
| 2 | **Retention Report** | **revenue retained percentage** · **number of retained members versus billed members** — for **the 3rd notice just completed** |
| 3 | **Penetration Report** | % for **Restaurants 10+ FTE** · % for **Lodging over 41 Rooms** · **Combined** % · **total number of active accounts** |
| 4 | **Billables by Territory Summary** | number of **Allied and Hospitality** in the respective territory box |

Plus: **Benefit Review count**, requested by email from the Membership Specialist
team at the start of each month.

---

## What this SETTLES

### ✅ The retention denominator is "BILLED members" — and leadership's formula is a DIFFERENT REPORT

**Clarified by Jiho 2026-07-29: leadership's *(billed − closed) ÷ total billable* is
the DUES ANALYSIS logic, not the MPR's.** That fully dissolves the
billed-vs-billable contradiction — the two formulas were never competing for the
same cell; they belong to two different reports.

> *"the number of **retained members versus billed members**"*

Not *billable*. The SOP's own wording matches the **invoice-anchored**
denominator we built — and it is the phrasing of the process owner, not an
inference from numbers.

*(This addresses the billed-vs-billable question directly. leadership's
"(billed − closed) ÷ total billable" is a different formula from the one the SOP
describes.)*

### ✅ The M−1 display offset, stated explicitly

> *"this is done for the **3rd notice just completed** for the month i.e. if
> this is for **December month-end, you would provide the report data for BM 11**"*

December = month 12 → **BM 11**. Exactly the M−1 rule, in the SOP's own example.

### ✅ Retention is reported on BOTH bases

> *"you will provide the **revenue retained percentage** & **number of retained
> members versus billed members**"*

Dollar basis and member basis, both — confirming leadership's 2026-06-17 ruling from
the process side.

### ✅ Penetration reports an active-account count too

> *"...Combined percentage, and **total number of active accounts**"*

### ✅ Restaurants are "10+ FTE"

Matches the built rule exactly.

---

## ⚠️ What this RE-OPENS

### The lodging room threshold — the SOP says **41**

> *"percentage for **Lodging over 41 Rooms**"*

| Source | Says | Kind of evidence |
|---|---|---|
| **This SOP** | *"Lodging over 41 Rooms"* | **Authored process document** |
| DECISIONS 2026-07-13 | **41+** — *"a Target hotel is 41 rooms or more"* | Ratified decision |
| DECISIONS 2026-07-21 | **40+** — *"the membership administrator confirmed directly: 40 or more rooms = Target"* | Verbal confirmation, **supersedes 7/19** |
| The CRM report | cutoff **≥ 40** (23 hotels sit at exactly 40) | Report behaviour |
| **The code** | `TARGET_ROOMS_MIN = 40` | Implementation |

**This is now genuinely unresolved.** On 2026-07-29 I recorded 41+ as *stale* and
withdrew an evidence-sheet item that had called the CRM's 40 a defect. **That
withdrawal may itself have been wrong** — the official SOP says 41.

**Complication worth noting:** the SOP was authored by the process owner
(the member-services admin, now on leave); the 40+ confirmation came from the membership administrator, who is
covering. Both are legitimate; they are not the same authority.

**Also note the wording is ambiguous:** *"over 41 Rooms"* literally means 42+.
Read loosely it means "41 and over". Neither reading is 40.

> **✅ RULED 2026-07-29 (Jiho): 40 or higher.** The code is already correct.
> **The official SOP is wrong on this line** and should be corrected on their
> side — it is a team document, not ours to edit silently.

### Billables are reported as **Hospitality and Allied**

> *"provide the number of **Allied and Hospitality** in the respective territory box"*

The SOP describes the **H/A** split. department leadership ruled **Target/Non-Target** on
2026-06-17 for goals, and T/NT was consolidated as "the system". This is the
**H/A remnant** already flagged for department leadership — the SOP is the old system, and the
MPR still splits billables H/A while everything else is T/NT.

---

# The Dues Analysis SOP — what it confirms for the MPR

*Different report, but it uses the same retention export and states rules that
bind us.*

### ✅ ITD ordering, stated as a rule

> *"These reports are run at the beginning of each month **BEFORE ITD is run**."*

### ✅ Four live bill months, with a worked example

> *"Adjusted Retention... for 4 months — **3rd notice, 2nd notice, 1st notice,
> pre-billing** (i.e. for Dec month end, run **BM 11, 12, 1 & 2**)"*

### ⚠️ Retention reports may be MANUALLY ADJUSTED

> *"The retention reports **may or may not require manual adjustments**."*

**This matters for every reconciliation we have run.** It means the published
retention figures can contain hand adjustments that exist in no report and no
ledger — so a cell that will not reproduce may never have been reproducible.

**Open: what adjustments, and on what basis?** This is a strong candidate
explanation for residuals we have been treating as our own errors.

### ✅ "Balanced" is defined

> *"Due to rounding, the report is considered balanced at either **$0 or $1**."*

### ✅ Variance threshold

Variances to budget of **$1,000 or more** must be explained.

### Item-code hygiene is a known, expected problem

> *"look for **item code anomalies** — ask Database Admin to remove any that do
> not belong to you"*

The team already treats bad item codes as routine cleanup — which corroborates
the unknown-charge-code handling in our own parsers.
