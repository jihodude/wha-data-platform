# WHA Membership Data Platform

Automates the Washington Hospitality Association's monthly membership
reporting. The program pulls membership data from the association's CRM
(Infor SLX) and a set of Crystal Reports exports, computes the monthly
membership metrics, and publishes an Excel workbook — a summary dashboard plus
one tab per territory manager — to SharePoint.

It runs unattended: a nightly job refreshes the data and republishes the
report. A web console sits on top for the team to trigger runs, inspect data
freshness, trace any published number back to the members behind it, and apply
hand corrections to a closed month. The whole system is deployed as a single
always-on container on Google Cloud Run.

The Membership Performance Report is the first report on the platform; the
architecture supports additional reports reading the same cached data.

## Where to start

| | |
|---|---|
| **[`docs/HANDOFF.md`](docs/HANDOFF.md)** | **Start here.** What the system is, how it's built, the entry points, the data flow, and the rules it enforces. |
| [`AGENTS.md`](AGENTS.md) | Working conventions and the commands for this repo. |
| [`docs/METRIC-CATALOG.md`](docs/METRIC-CATALOG.md) + [`docs/metrics/`](docs/metrics) | What every number means — one file per metric: definition, source, status. |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | The business rules currently in force, and the reasoning behind each. |
| [`docs/BACKLOG.md`](docs/BACKLOG.md) | Open items, verified against the code. |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | Cloud Run deployment, exactly as the service runs. |

## Running it

```bash
# fresh clone: the runner reads env vars at import, so an .env must exist
cp .env.example .env

# the test suite
PYTHONPATH=$PWD python3 -m pytest -q

# the console, locally
PYTHONPATH=$PWD python3 -m streamlit run console/app.py

# rebuild the workbook from cached data (no CRM access needed)
PYTHONPATH=$PWD python3 reports/membership_performance_tracker/runner.py --from-cache
```

A full live run queries the CRM and takes roughly three hours; `--from-cache`
rebuilds the workbook from the last cached pull in seconds.

## Layout

- `src/` — the shared platform: CRM client, SharePoint access, scheduling,
  period configuration, the report contract.
- `reports/membership_performance_tracker/` — the report engine: its
  computation (`logic/`), the mapper and writer, the workbook template, and
  its test suite.
- `console/` — the Streamlit console and the nightly daemon.
- `scripts/` — operational tooling (receipts build, verification sweeps).
- `tests/` — platform tests.

## Credentials

`.env` holds all secrets and is gitignored; `.env.example` lists every
required key. Nothing in this repository contains a live credential.
