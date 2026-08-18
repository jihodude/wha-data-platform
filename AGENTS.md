# AGENTS.md — WHA Membership Data Platform

Python/Streamlit app that pulls SLX (Infor CRM) data and generates monthly
membership reports. The Membership Performance Report (MPR) is report #1; the
architecture supports more reports reusing the same cache ("the cache is the
contract"). **Read this first, then `docs/HANDOFF.md`.**

## Commands (run from the repo root, always)

```bash
# Tests — keep green. PYTHONPATH must be the repo root.
PYTHONPATH=$PWD python3 -m pytest -q

# Run the console UI locally
PYTHONPATH=$PWD python3 -m streamlit run console/app.py

# Generate a report from cache (no SLX hit)
PYTHONPATH=$PWD python3 reports/membership_performance_tracker/runner.py --from-cache

# Live pull for a specific month (the SLX host is internet-reachable)
MPR_PERIOD=2026-06 PYTHONPATH=$PWD python3 reports/membership_performance_tracker/runner.py
```

Set `MPR_PERIOD=YYYY-MM` to report any month (`src/config/period.py` derives
FY/months/current-month from it).

⚠️ **Cache mode shows STALE numbers after code changes** — `--from-cache` skips
SLX, so a logic fix won't show until a live run repopulates the cache.

## Doc map

| Doc | Job |
|---|---|
| **`docs/HANDOFF.md`** | **START HERE — what the system is, how it's built, where everything lives** |
| **`docs/METRIC-CATALOG.md`** + `docs/metrics/` | what every number MEANS — definition, source, status, one file per metric. The source of truth for meaning |
| `docs/DECISIONS.md` | the business rules in force, and why |
| `docs/BACKLOG.md` | open items, verified — the Oct 1 deadline is item 1 |
| `docs/DEPLOY.md` | Cloud Run deploy, exactly as the service runs |
| `docs/DATA_ACCESS.md` | the DataHub read contract for reports |
| `docs/CONTRIBUTING.md` | how to add a new report |
| `reports/<name>/SPEC.md` | what that report computes |

## Hard rules

1. **`src/` is the shared platform — report-agnostic.** Reports import from
   `src/`; report logic never moves into it.
2. **FY = Oct 1 → Sep 30.** Any Sep-first logic (`>= 9` month cutoffs,
   `MONTHS` starting "Sep") is a bug.
3. **"Tests pass" ≠ "numbers right."** A number is only correct when it
   reconciles at member level — that is what the receipts/Trace layer and its
   conservation gates exist for. Don't close a numbers issue until its gate
   passes on a fresh run.
4. **Never commit `.env`, `data/cache/`, `data/output/`, `data/hub/`, or any
   member-data spreadsheet.** Stage explicit paths; never `git add -A`.
5. **One SLX session at a time** (credential collision). Never run two pulls
   at once; don't restart the console while an SLX subprocess runs.
6. **Definitions are sourced, not guessed.** Most historical failures were
   wrong *definitions*, not wrong code. Pin a metric's meaning with the
   business stakeholders before implementing — and log it in
   `docs/DECISIONS.md`.
7. **Docs are maintained in the same change that makes them stale.** A stale
   doc poisons every future reader.
8. **A metric's meaning lives in `docs/metrics/`, one file per catalog row.**
   When a definition changes: update that file, log the decision, then change
   the code — in that order.

## Layout

- `src/` — platform only: `slx/` (SData client), `hub/` (DataHub cache + SP
  sync), `config/`, `base/` (BaseReport contract), `scheduler.py`.
- `reports/membership_performance_tracker/` — the MPR: `logic/` (engine,
  model, retention, drops, billables, revenue, crystal_*, month_close,
  receipts_*…), `runner.py` / `mapper.py` / `writer.py` / `template.xlsx` /
  `tests/`.
- `console/` — the Streamlit console (`app.py`) + the nightly daemon boot
  (`scheduler_boot.py`).
- `scripts/` — operational tools (receipts build, verification sweeps,
  durable-input push).
- `tests/` — platform tests. Report-specific tests live inside each report.

## Common tasks

- **Fix a bug:** write a failing test first, then fix, then re-run the suite.
- **Change a number's definition:** update its `docs/metrics/` file + log it
  in `docs/DECISIONS.md` first, then change the code.
- **Deploy:** `docs/DEPLOY.md`, and never while a pull is in flight.

## Environment gotchas

- On macOS, if a Homebrew install shadows `python3`, use `/usr/bin/python3`
  (the Homebrew one lacks the deps). Any machine: `.env.example` lists every
  required key.
- LibreOffice macros for template surgery live at
  `scripts/libreoffice/Module1.xba` (copy into LibreOffice's
  `Standard/Module1`; LibreOffice saves strip the quarter-column `collapsed`
  flags, so every macro pass re-applies them via openpyxl).
