# The capture layer — how Crystal exports reach us

**Sources read:** `logic/crystal.py` · `handoff/2026-07-27-crystal-schedule-sheet.md` · `logic/crystal_feed.py` · DECISIONS · THE-PLAN

Two families are sourced from CRM report exports rather than the ledger
(**billables** and **drops** — see [`_SHARED.md`](_SHARED.md)). This is the
plumbing that delivers them, and the dated obligations that keep it alive.

---

## How an export reaches us

**Every Crystal report run in the CRM is archived as an SLX attachment**,
readable over the same basic-auth surface as everything else:

```
GET /sdata/slx/system/-/attachments?where=fileName like 'Prefix%'
GET /sdata/slx/system/-/attachments('<key>')/file      → the bytes
```

**Proven 2026-07-27:** a `DroppedMembersByType` export fetched by API came back
**byte-identical** to the copy downloaded by hand.

### What is NOT automated — and why

**Firing the reports.** Programmatic execution
(`/sdata/$app/scheduling/-/` + `CrystalReportsJob`) *accepts* jobs, but every run
dies at **"Initialization"** — the Job Service host lacks working Crystal
components. **That is an IT/vendor fix, not ours.**

**Schedules created in the CRM's own wizard DO run server-side.** So a human sets
the schedules once, and the code picks up whatever they produce.

---

## The schedules

**10 live schedules**, staggered 5 minutes apart from **12:00 AM**, all **Excel**
format. Verified firing unattended 2026-07-27 (00:05–00:50).

| Time | Report | Cadence | For |
|---|---|---|---|
| 12:00 | Dues Analysis Report Detail V2 | daily | dues |
| 12:05 | **New Member Sales Report** | daily | **BOTH — schedule once only** |
| 12:10 | Billables By Territory Summary By Bm | 1st | MPR |
| 12:15 | Adjusted Retention SW Multiple Bill Months Exportable | 1st | MPR |
| 12:20 | Dropped Members - Hospitality | 1st | MPR |
| 12:25 | Dropped Members By Type | 1st | MPR |
| 12:30 | Dropped Allied Report | 1st | MPR |
| 12:35 | Penetration Restaurant Count By Location - Detail | 1st | MPR |
| … | Penetration Lodging County By Location - Detail · Penetration Lodging Count of Rooms · Active Billables By Ac And Fte | 1st | MPR |

**Why the stagger:** Crystal jobs contend with **each other** on the Job Service.
They do **not** contend with our fetches — different mechanisms. Our own runs
contend on the **single SLX credential**, so they stay sequential (repo hard
rule: one session at a time).

**The pull is no longer the slow part.** A live test fetched and archived all
nine exports in **3.8 seconds** (2.64 MB), replacing an ~80-minute SData pull for
these families.

---

## ⏰ Dated obligations — both will break the report silently if missed

### 2030-12-31 — every schedule expires at once

SLX **deletes a trigger after it fires** if the run-to date is not far-future.
This already killed two dues test schedules and Jiho's first four attempts, so
all 10 are set to **2030-12-31**.

**The signature of missing it:** every report reporting **STALE on the same day**.

### 2026-10-01 — the drops fiscal-year window

A drops row carries a bill month and **no date**, so the only thing assigning it
to a fiscal year is the schedule's **StatusDate window**. On 2026-10-01 the
current window (10/1/2025 → 12/31/2030) begins spanning **two fiscal years**, and
**nothing in the file can tell the rows apart.**

**Already guarded:** `crystal.assert_drops_window_matches_fy` reads the live
schedule over the API and **refuses** to compile a drops grid whose window does
not begin on the reported fiscal year. The failure mode is a **blocked run with a
clear message**, never a wrong number. Verified live 2026-07-27.

**The decision still to make (Jiho):**

- **(a)** move the window each October on the three drops schedules — one date
  change, machine-verified; or
- **(b)** **one schedule per fiscal year** — each file is permanently one year,
  no annual step at all, and past years stay **re-pullable** rather than
  surviving only in our archive.

**(b) is blocked on one unknown:** every schedule for the same report currently
produces the same filename prefix, so five FY schedules would be
indistinguishable and the fetcher would take whichever is newest. The archive
holds `DroppedMembersHospitalityBM8_suzannes_…` — a name the report itself does
not have — suggesting the **Description field drives the filename**, but that was
an *interactive* export, not a scheduled one.

> **Free test:** give one live schedule a distinctive Description and read
> tomorrow's filename.

---

## The gates on this layer

| Gate | What it refuses |
|---|---|
| **Parser total** | Each of the 10 parsers must reproduce **its own report's printed total** (e.g. *"264 Records representing $269,277.00 in dues income"*) or it raises |
| **Export presence + freshness** | A missing or stale export raises, naming **the CRM schedule to fix** |
| **FY window** | The drops obligation above |
| **Exact report-token match** | Filenames are matched on the **exact** report token, never a prefix — a loose match once handed `DroppedMembersHospitalityBM8` (a single-bill-month export) to the full-report parser, and silently resolved `pen_restaurant` to a different, non-Detail variant |
| **Same-FY fallback only** | A drops export from **another fiscal year** is never borrowed; billables are never borrowed from another month at all (a snapshot describes one day) |

**Filename stamps differ by origin:** interactive exports read
`<Report>_<user>_2026_07_26_0921.xls`; scheduled ones read
`<Report>_<user>_202607_28_1205.xls` — **no separator after the year.** The
parser handles both.

---

## Deliberate duplication

This module is **deliberately independent** of
`reports/dues_analysis/logic/slx_reports.py`, which solves the same problem for
that report.

**Jiho's direction:** develop the two independently, merge into the shared
platform once both are validated. **Do not cross-import.** When they merge, both
files collapse into one `src/slx` module.
