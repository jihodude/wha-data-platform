# WHA Membership Performance Report — the system

The program runs unattended: it pulls membership data from the CRM nightly,
computes the monthly membership metrics, and publishes the report workbook to
SharePoint. This document is the map of that system — what it is, how it's
built, the rules it enforces, and where to look when something goes wrong.

The system's behaviour is defined by its code and its test suite (820 tests
pass on a fresh clone; a further 13 skip until live data exists). This document
points at the specific files and tests behind each description, and was
verified against them on 2026-08-17.

The repository is deliberately small: it describes what the system is, not how
it came to be. The development history — decision reversals, session logs,
reconciliation records — lives in a separate private archive repository.
`docs/DECISIONS.md` states the business rules currently in force;
`docs/BACKLOG.md` lists what is open.

---

## 1. What this is, in one paragraph

A Python program that pulls membership data from the WHA CRM (Infor SLX, via
its SData HTTP API — the host is internet-reachable, no VPN needed) and a set
of Crystal Reports exports, computes the monthly membership metrics
(retention, drops, billables, new sales, penetration), and writes them into an
Excel workbook — one dashboard plus one tab per territory manager. It runs
itself every night, publishes to SharePoint, and is driven by a web console.
The whole thing is deployed as a single container on Google Cloud Run.

## 2. The one idea to understand first: **the cache is the contract**

Everything hangs off one artifact. The engine scrapes and computes; it writes a
JSON file (`data/cache/scoreboard_<YYYY-MM>.json`, a serialized
`ScoreboardData` in `logic/model.py`). Every downstream step — the workbook,
the transparency layer, future reports — *reads that cache*. Nothing downstream
re-scrapes the CRM. Get this and the rest of the architecture falls out of it.

```
   SLX CRM  ─┐
             ├─▶  ENGINE  ─▶  scoreboard_<period>.json  ─▶  WORKBOOK  ─▶  SharePoint
 Crystal xls ─┘   (scrape +       (THE CACHE —              (mapper +
                   compute)        the contract)            writer + template)
```

## 3. Where the program actually is — the entry points

Five doors. Everything else is called from one of these.

| # | File | What it is |
|---|------|-----------|
| 1 | `reports/membership_performance_tracker/runner.py` (`main()`) | The whole pipeline. Scrape → compute → cache → build workbook → publish. Run directly or spawned by the console/scheduler. |
| 2 | `console/app.py` | The Streamlit web console — data freshness, trigger a run, set the schedule, "Trace a Number", "Adjust a Number". Login-gated. |
| 3 | `console/scheduler_boot.py` | The nightly daemon. Boots with the container, hydrates inputs from SharePoint, then ticks the scheduler loop. Process-level — independent of any browser session. |
| 4 | `src/scheduler.py` | The scheduling logic the daemon runs. `due_now()` decides whether tonight's pull should fire; `_scheduler_loop()` is the tick. |
| 5 | `scripts/build_receipts.py` | Builds the transparency layer ("receipts") the console's Trace page reads. Runs at the end of a live pull. **Refuses to publish if the receipts don't reconcile to the published numbers** — see §7. |

Supporting infrastructure (shared, report-agnostic): `src/slx/client.py` (the
CRM HTTP client), `src/hub/datahub.py` (the SharePoint access facade).

## 4. Repo layout (current — paths verified 2026-08-17)

```
wha-data-platform/
├── src/                          ← platform, shared, report-agnostic
│   ├── slx/client.py                 SLX SData client (auth, retry, pagination)
│   ├── hub/datahub.py                SharePoint facade — the access contract
│   ├── sharepoint/client.py          Microsoft Graph file ops
│   ├── config/period.py              MPR_PERIOD → fiscal year / months
│   ├── base/                         BaseReport protocol + registry (multi-report)
│   └── scheduler.py                  nightly-refresh decision + loop
├── reports/membership_performance_tracker/
│   ├── runner.py                     ① the pipeline entry point
│   ├── mapper.py                     ScoreboardData → long-form rows
│   ├── writer.py                     rows → template.xlsx
│   ├── template.xlsx                 the workbook template (formulas read the data sheets)
│   ├── logic/                        ← ALL the report's computation lives here
│   │   ├── engine.py                     orchestrates the scrape + L1/L2/L3 compute
│   │   ├── model.py                      ScoreboardData — the typed cache contract
│   │   ├── cache.py                      JSON save/load
│   │   ├── retention.py  drops.py  billables.py  revenue.py  new_members.py
│   │   ├── target.py                     Target / Non-Target classification
│   │   ├── crystal_*.py                  the Crystal-export path (drops live here)
│   │   ├── month_close.py                the two-phase close (seal / apply_frozen)
│   │   ├── adjustments.py                hand corrections to a closed month
│   │   └── receipts_*.py  trace.py       the transparency layer
│   └── tests/                        ← the report's own test suite
├── console/app.py  console/scheduler_boot.py
├── scripts/                          build_receipts.py + operational tools
├── tests/                            ← platform tests (SLX, hub, scheduler, console)
├── data/                             ← runtime, GITIGNORED: cache/, output/, receipts/, closes/
├── docs/                             AGENTS.md-adjacent; see the trust order in the intro
├── Dockerfile  requirements.txt  .env.example
└── AGENTS.md                         ← read this next; it's short and current
```

> **Note on `src/` vs `reports/.../logic/`:** the report's computation (engine,
> model, retention, drops…) lives under `reports/membership_performance_tracker/
> logic/`, **not** `src/logic/`. It was moved there 2026-06-28. Older docs that
> say `src/logic/engine.py` are stale — the file is `logic/engine.py` inside the
> report.

## 5. How a report gets built — the data flow

A full live run (`runner.py`, ~3 hours end to end — the order below matches
the sequence in `runner.main()`):

1. **Hydrate** inputs from SharePoint (close docs, prior snapshots, the Crystal
   archive, receipts) so a fresh container has what it needs —
   `runner._hydrate_sp_inputs`, called first in `main()`.
2. **Scrape SLX and compute** — billables, retention (per bill-month,
   Target/Non-Target), new members, revenue, penetration, per-account detail,
   then the derived layers (combined totals, %s, YTD, statewide, status flags).
   All in `logic/engine.py`. Hundreds of CRM calls; this is the slow part.
3. **Save the cache** (`cache.save_scoreboard`) — deliberately *before* the
   Crystal overlay, so SLX's own numbers survive underneath as a cross-check.
4. **Overlay Crystal drops** — the drops family is owned by the Crystal export,
   not SLX (`runner._apply_crystal_overlay` → `crystal_feed.overlay`).
5. **Stamp the closed months** — sealed months overwrite the fresh compute with
   their frozen values (`month_close.apply_frozen`, called before the mapper). See §6.
6. **Build the workbook** — `mapper.py` → long-form rows → `writer.py` fills
   `Data - Monthly Metrics` (and the other data sheets) in `template.xlsx`; the
   Summary Dashboard and TM tabs are Excel formulas reading those sheets.
7. **Build the receipts** and gate them (`scripts/build_receipts.py`) — §7.
8. **Publish** the workbook + cache snapshot to SharePoint.

`--from-cache` skips steps 1–5 and rebuilds the workbook from the last cache —
seconds, no CRM hit. **Cache-mode shows stale numbers after a code change**
until a live run repopulates the cache.

## 6. The concepts that aren't obvious from reading one file

**Fiscal year = Oct 1 → Sep 30.** Month M's retention column reports bill month
M−1 (July's column is bill month 6). Any Sep-first logic (`>= 9` cutoffs,
`MONTHS` starting "Sep") is a bug — `AGENTS.md` hard rule 2. Enforced across the
suite; grep the tests for `test_admin_inputs_month_axis` and the FY-boundary
tests.

**Target vs Non-Target (T/NT).** Every performance metric is split into Target
(members above a size threshold — 10 FTE for restaurants, 40 rooms for lodging)
and Non-Target. The classifier is `logic/target.py`. Size-unknown members count
Non-Target so territory totals stay whole.

**The two-phase month close** (`logic/month_close.py`). A month closes with one
human action: pick the date the CRM's ITD job ran, press Close. Retention
*freezes* from the last nightly snapshot taken **before** ITD (ITD inactivates
unpaid accounts, which would shrink the retention denominator and inflate the
rate); billables/drops/penetration re-capture **after** ITD. `seal()` writes the frozen record; `apply_frozen()` stamps it back over
every later build, so a closed month never moves. This is why July's column
reads the same in the August report and every report after.

**Allied members are tracked separately, not part of hospitality performance.**
They are excluded from hospitality retention and from the drop counts, but stay
*visible* (listed, uncounted). They remain in billables as their own line. This
is a business rule, sourced from the membership leadership team, ruled
2026-08-14. See §8 for the tests that enforce it.

**The transparency layer ("receipts" / "Trace a Number").** Every published
number can be traced to the member rows behind it. The receipts are rendered
from the same data the pipeline computed and are **gated**: the member rows
must sum to the published cell or the artifact refuses to publish. This is what
makes a challenged number answerable — "here are the members, and they add up."

**Adjustments — hand corrections to a closed month** (`logic/adjustments.py`).
The team can correct a number the program got wrong; the correction persists as
first-class data and is applied on every rebuild, with the members behind it
still shown. This exists because month-close froze conclusions that later
needed amending.

## 7. The publish gate — why a run can "succeed" but not publish receipts

`build_receipts.py` runs every gate (`gate_retention`, `gate_drops`,
`gate_new_members`, `gate_billables`, `gate_penetration` in
`logic/receipts_render.py`) and **refuses to write if any single cell's member
rows do not equal the published number.** It is all-or-nothing across the
artifact. So a workbook can publish correctly while the receipts step
prints `⛔ CONSERVATION GATE FAILED — N cell(s)` and does not update SharePoint.

The message names the exact failing cell — territory, month, family, and the
receipts value against the published one — which localises the disagreement to
one family's render and gate in `receipts_render.py`. The design intent is that
a broken Trace is caught before it misleads anyone. The numbers themselves are
unaffected: the workbook is valid, and only the explanation layer is held
back.

## 8. The rules that matter — and the test guarding each

These are the business rules that are not obvious from any single file. Each is
guarded by a test, named here so the relationship between rule, implementation
and guard is visible.

| Rule | Lives in | Guarded by |
|------|----------|-----------|
| Allied is OUT of hospitality retention | `retention.py` | `test_allied_members_are_OUT_of_hospitality_retention` |
| Allied is out of the drop counts too, but stays listed | `crystal_feed.classify_drop` | `test_allied_drops_are_listed_but_never_counted` |
| An excluded member moves no total — count *and* dollars | `receipts_render.gate_new_members` | `test_an_excluded_row_moves_no_total_not_even_the_dollars` |
| A drop count and the member list behind it are one loop | `crystal_feed.drop_ledger` | `test_the_count_and_the_member_list_are_the_same_objects` |
| A new-sales cell is the sum of its member rows | `revenue.aggregate_new_sales` | `test_new_sales_single_path.py` |
| A sealed month never recomputes | `month_close.apply_frozen` | `test_month_close.py`, `test_trace.py` |
| The whole grid conserves (members reproduce every cell) | the gates in `receipts_render.py` | `test_full_grid_conserves_across_all_traceable_families` |
| Fiscal year is Oct-first everywhere | throughout | `test_admin_inputs_month_axis` + FY-boundary tests |
| The nightly survives a container swap | `scheduler.due_now` | `test_scheduler_daily_window.py` |

`docs/DECISIONS.md` holds the reasoning behind each of these. Several
deliberately reversed earlier decisions, and the entry records why.

## 9. Running and deploying

From the repo root, always. On macOS, if a Homebrew Python shadows the system
one, use `/usr/bin/python3` (the Homebrew install lacks the deps).

```bash
# fresh clone only: the suite needs an .env to exist (placeholders fine)
cp .env.example .env

# the test suite
PYTHONPATH=$PWD python3 -m pytest -q

# the console, locally
PYTHONPATH=$PWD python3 -m streamlit run console/app.py

# rebuild the workbook from cache (no CRM hit)
PYTHONPATH=$PWD python3 reports/membership_performance_tracker/runner.py --from-cache

# a full live pull for a month
MPR_PERIOD=2026-08 PYTHONPATH=$PWD python3 reports/membership_performance_tracker/runner.py
```

**Deployment** is to Google Cloud Run — project `wha-report-automation-project`,
region `us-west1`, service `wha-console`. `docs/DEPLOY.md` carries the exact
command and the reason for each flag. Three properties of the deployment are
load-bearing:

- `--min-instances 1 --max-instances 1 --no-cpu-throttling` — one always-on
  instance hosts the nightly daemon. Two instances would run two schedulers,
  and therefore two simultaneous CRM pulls, which the CRM cannot serve (one
  session at a time).
- `--set-env-vars` *replaces* the entire environment, dropping the credentials;
  `--update-env-vars KEY=VAL` changes a single variable.
- A deploy wipes container disk and restarts the service, which terminates a
  pull in flight. The nightly window is 01:50–06:00.

## 10. Operational characteristics

- **The CRM allows one SLX session at a time.** A manual pull started while the
  scheduled one is running fails on arrival.
- **The nightly runs at 02:00 (container-local, `TZ=America/Los_Angeles`).** As
  of 2026-08-16 the scheduler asks "has today's pull run yet, and are we still
  before 06:00?" rather than "is it exactly 02:00 now?" — so a container that
  Google replaces mid-window still catches up. It logs its decision each tick
  (`[scheduler-daemon] …`); that log is the first place to look if a night is
  missed.
- **Data freshness is visible on the console** (Data & Schedule page). There is
  no push alerting; an SLX cache age of more than a day indicates a nightly
  did not complete.
- **`.env` holds the secrets and is gitignored.** `.env.example` lists every
  required key. The console login is `APP_PASSWORD` (no default — an unset value
  locks the console rather than falling back to anything).

## 11. Known-open

Open items are listed in **`docs/BACKLOG.md`**, verified against the code, with
the one dated item first: the drops fiscal-year window, due **2026-10-01**.

---

*Verified against the code 2026-08-17.*
