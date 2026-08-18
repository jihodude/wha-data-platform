# DATA_ACCESS — the read-only contract for reports

Every report reads platform data the same way and never reaches into SLX or other
reports directly. This is what keeps reports independent and lets new ones plug in.

## The rule
- Reports **import from `src/`** (`slx`, `hub`, `config`). Nothing in `src/` imports from `reports/`.
- A report **never modifies `src/`** or another report's folder. If shared code needs a change, raise it to a main session.
- Reports get data from the **DataHub** — they do not call SLX themselves.

## Getting data
```python
from src.hub.datahub import DataHub

hub = DataHub()
data = hub.load_data(period)   # period "2026-03"; SP snapshot first, local cache fallback
```
- `load_data(period)` returns the cached `ScoreboardData` for that period (the SLX pull is already done + cached). Read-only.
- The **cache is the contract**: the SLX pull happens once (on a WHA-network machine, post-ITD), is published to SharePoint, and every report reads from it. Reports do not re-scrape SLX.

## Why the pull is separate
The CRM is **on-premise** (`crm.wrahome.com`, self-signed cert) — reachable only on WHA's network. So the *pull* runs there and writes the snapshot to SP; reports (and the cloud app) only **read** the snapshot. See `REFERENCE.md`.

## Period
All reports take a `period` ("YYYY-MM"). Derive FY values with
`from src.config.period import parse_period`. Never hardcode a month.
