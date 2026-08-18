# CONTRIBUTING — how to add a new report

The platform is built so each report is an isolated folder that a fresh session
can open and understand. ~9 reports reuse the same SLX cache ("the cache is the
contract"). Follow this to add one.

## 1. Scaffold it
```bash
PYTHONPATH=$PWD python3 scripts/new_report.py <report_name>
```
Creates `reports/<report_name>/` with `AGENTS.md`, `SPEC.md`, `PRD.md`,
`ROADMAP.md`, `memory.md`, an `engine.py` stub, and `tests/`.

## 2. Fill the SPEC first (definitions before code)
Open `reports/<report_name>/SPEC.md` and pin, from a **primary source / stakeholder**:
- what each number means, where its SLX data comes from, the exact calculation,
- the output layout, and **how you verify it** (the ground-truth gate).

This is the step skipped before the June demo. A number is only "done" when its
gate passes on a fresh run — not when tests pass.

## 3. Build (TDD)
- Implement `engine.py` against the contract in `src/base/report.py` (`name()`, `run(hub, params)`).
- Get data via `hub.load_data(period)` (read-only — see `DATA_ACCESS.md`). Never touch `src/`.
- Write the failing test first, then code. Run `PYTHONPATH=$PWD python3 -m pytest`.

## 4. Hard rules (also in AGENTS.md)
- FY = Oct→Sep; period is an input (`src.config.period`), never hardcoded.
- Don't commit `.env`, `data/cache|output|hub`, decrypted spreadsheets. Stage explicit paths.
- Update the report's docs in the same commit. Log decisions in `docs/DECISIONS.md`.
- The SLX pull is WHA-network-only; reports only read the SP cache.

## 5. Sequencing
Reports building in parallel must touch different folders. Anything shared lives
in `src/` and changes only via a main-session decision.
