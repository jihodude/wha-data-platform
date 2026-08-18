# Deploy — Cloud Run, exactly as the service runs today

Platform: **Google Cloud Run** · project **`wha-report-automation-project`** ·
region **`us-west1`** · service **`wha-console`**. One container serves the
console *and* hosts the nightly scheduler daemon.

## The deploy command (and why every flag exists)

```bash
gcloud run deploy wha-console --source . --project wha-report-automation-project \
  --region us-west1 \
  --min-instances 1 --max-instances 1 \
  --no-cpu-throttling \
  --memory 4Gi --cpu 2 --timeout 3600 --session-affinity \
  --quiet
```

- `--min-instances 1` + `--no-cpu-throttling`: the nightly daemon lives in the
  container and must be running (with CPU) at 2 AM with no request active.
- `--max-instances 1`: **critical — two instances = two schedulers = two
  simultaneous CRM pulls**, and the CRM allows one session at a time. Never
  drop this flag.
- `--timeout 3600`: the websocket cap (Cloud Run max). Console sessions
  hard-reset after 60 min — cosmetic.
- **No env flags on a redeploy.** Cloud Run carries the existing environment
  forward. To change one variable use `--update-env-vars KEY=VAL`. **Never
  `--set-env-vars`** — it *replaces* the entire set and silently drops the
  credentials.

## Environment (set on the service; template in `.env.example`)

| Key | Purpose |
|---|---|
| `SLX_USERNAME` / `SLX_PASSWORD` | CRM SData login |
| `SHAREPOINT_*` / `AZURE_*` | Graph app credentials. The client reads `SHAREPOINT_*` first, `AZURE_*` as fallback; as of 2026-08-17 only `SHAREPOINT_*` authenticates and its secret expires 2028-05-17 (BACKLOG §2) |
| `APP_PASSWORD` | console login. **No code fallback** — unset means the console locks and says so |
| `WHA_SCHEDULE_DEFAULT_ENABLED=1` | a wiped disk boots with the nightly ON at 02:00 (deploys wipe `data/schedule.json`) |
| `WHA_SCHEDULER_DAEMON=1` | the process-level daemon owns the clock; the console's in-session ticker stays off |
| `TZ=America/Los_Angeles` | 2 AM means Pacific |
| `WHA_DEV_AUTOLOGIN` | **test revisions only — the final revision MUST NOT carry it** (verified below) |

Secrets are plaintext env vars today (readable by project admins). Migrating
them to Secret Manager (`--set-secrets`) is a known improvement, not done.

**Recovering a working `.env` from scratch:** every live value sits on the
Cloud Run service itself. With project IAM access:

```bash
gcloud run services describe wha-console --region us-west1   --project wha-report-automation-project --format=yaml
```

The `env:` block of the output contains every credential the system uses —
copy the needed keys into a local `.env`. Nothing beyond this repo plus that
command is required to reconstruct a working environment.

## Why a fresh instance still computes correct numbers

Container disk is **ephemeral** — every deploy or instance recycle wipes it.
Everything the build needs is SharePoint-durable and re-hydrated at boot and at
the start of every run (`runner._hydrate_sp_inputs`): close docs, prior-month
snapshots, receipts, and the durable mirror of the Crystal export archive
(pushed by `scripts/push_durable_inputs.py`). **A new disk-based input belongs in both
the push script and the hydration** — otherwise the first instance recycle
computes without it, silently.

The nightly itself is recycle-proof by design: the scheduler asks "has today's
pull already run, and is it still before 06:00?" rather than "is it exactly
02:00?" — so a container replaced mid-window catches up. It logs its decision
every time it acts (`[scheduler-daemon] …`).

## What a correct deployment looks like

1. The logs carry `[scheduler-daemon] ticker started` at boot, and the
   console's Data & Schedule page shows the next run at 2:00 AM.
2. The service URL presents the password page, and `WHA_DEV_AUTOLOGIN` is
   absent from `gcloud run services describe wha-console` (its presence
   bypasses that gate and belongs only to test revisions).
3. A from-cache build triggered from the Control Panel publishes to the
   SharePoint dated Output folder.
4. The first live pull's log shows hydration lines at the start,
   `✓ receipts rebuilt` near the end rather than `⛔ CONSERVATION GATE
   FAILED`, and closed-month cells unchanged.

## Operational rules

- **A deploy during a pull kills the run** — it won't publish partial data,
  but the night is lost. The nightly occupies 01:50–06:00 Pacific.
- Exactly one machine owns the nightly: the cloud service. A second enabled
  scheduler anywhere would produce a colliding second pull.
- There is no push alerting for a failed nightly. The tripwire is the
  console's data-freshness card: **if "SLX cache refreshed" is more than a day
  old, a nightly failed** — start with the scheduler-daemon log lines.
- Public access is organization-blocked (Domain Restricted Sharing); access
  runs through authenticated users / `gcloud run services proxy` unless an
  org-level exemption is granted.
- Cost: roughly $60–90/month (always-on instance). A documented cheapening
  path exists (Cloud Run Jobs + Cloud Scheduler, scale-to-zero console) if
  that ever matters.

## Rollback

Every deploy creates a revision. Instant rollback:

```bash
gcloud run services update-traffic wha-console --region us-west1 \
  --to-revisions=<previous-revision-name>=100
```

`gcloud run revisions list --service wha-console --region us-west1` shows the
history.
