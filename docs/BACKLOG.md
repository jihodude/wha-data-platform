# Backlog — open items, verified against the code 2026-08-17

Everything in the first section was **checked against the current tree on the
date above** — the claim, the code path, and what a maintainer would actually
do. The short second section is inherited from older trackers and is honestly
labelled *unverified*. There is no third section: if an item isn't here, it was
checked and found already fixed, superseded, or never real.

---

## 1 · ⏰ The drops fiscal-year window — **deadline 2026-10-01**

The one item with a date on it.

**The problem.** A drops export row carries a bill month but no year. The only
thing that scopes an export to a fiscal year is the StatusDate window on the
three drops report schedules inside the CRM. Those windows currently start
**2025-10-01**, so from **Oct 1 2026** a single export spans two fiscal years —
rows carrying a real flip date are safe (the program bounds them to the
reported FY on both edges), but **dateless rows fall back to a bill month that
carries no year and cannot be told apart across years**.

**What the program does about it — and deliberately does not.** On every live
pull it reads the schedule windows and, if they don't begin on the reported
FY's Oct 1, writes a red section to the run's flags naming each mis-scoped
schedule and the remedy (`crystal.check_drops_window`). It does **not** refuse
to build — that was ruled out (2026-08-11) because a hard stop would break
every build after Oct 1 with a fix only a CRM admin can apply. A hard-gate
variant exists in the same file, intentionally unwired, if a future maintainer
prefers refusal.

**What to actually do, once a year, every October:** in the CRM's report
scheduler, set the StatusDate range on the three drops schedules to begin
Oct 1 of the new fiscal year. Needs CRM admin access. The flags tab will
confirm when it's right.

## 2 · SharePoint credentials — verified, and one trap

SharePoint access (cache publish, workbook delivery, receipts, boot hydration)
authenticates with an Azure app-registration client secret. Those secrets carry
a hard expiry, and an expired one fails every SharePoint operation at once.

**Verified 2026-08-17: the live secret expires 2028-05-17.** No action is due
before then. Renewal, when it comes, means creating a new secret in
Azure Portal → App registrations → the app → Certificates & secrets, and
updating the Cloud Run service environment with `--update-env-vars` (see
DEPLOY.md — `--set-env-vars` would replace the whole environment).

**The trap:** the environment carries two credential sets, `SHAREPOINT_*` and
`AZURE_*`. The client reads `SHAREPOINT_*` first and falls back to `AZURE_*`
(`src/sharepoint/client.py`). As of 2026-08-17 the `AZURE_*` values are stale
and fail authentication — only `SHAREPOINT_*` works. The client's own docstring
names `AZURE_*` as the canonical set, which is misleading: removing or
overwriting `SHAREPOINT_*` on the assumption that `AZURE_*` is the real one
would break all SharePoint access.

## 3 · Retention still computes its splits in three places

The drops family was collapsed to a single loop (2026-08-14) after parallel
copies of the same rules drifted twice in one week. Retention has the same
shape and hasn't had the treatment: the combined count, the Target/Non-Target
split, and the Trace-page renderer each walk the same per-account data and
each re-apply the comp/void/close-date branches
(`logic/retention.py` — `_retention_counts`, `_retention_target_split`;
`logic/receipts_render.py` — `render_retention`).

They agree today, and the conservation gate catches divergence after the fact.
The exposure is the next rule change: it has to be made in all three places.
The drops family solved the same problem with one classifier and projections
for count, split and render.
The related deeper fix, recorded as a design note: seal the member *list* at
month close and derive the number from it, rather than sealing the number and
keeping the list in step by hand.

## 4 · One ruling shipped on inference — confirm with membership leadership

Allied's exclusion from the **drop counts** (# Dropped / $ Lost) was applied
as the consistent consequence of the leadership's retention ruling
(2026-08-14) — it was not asked of leadership directly. If leadership wants allied back in
the drop counts, it is a single, isolated change (`crystal_feed.classify_drop`,
the allied branch) — retention is unaffected either way.

## 5 · Statewide penetration is an unweighted average — definition question

The dashboard's statewide penetration averages the 11 territory percentages;
revenue- and account-retention on the same row pool numerators and
denominators. Which one statewide penetration *should* be is a business
definition question, not a bug. Fixing it to a pooled rate also needs a small
data-layer change (the data sheet publishes only the combined %, not its
active/market components — the mapper would need to export those).

## 6 · Small security hygiene

- No dependency-CVE scan has ever run (`pip-audit`); `requirements.txt` is
  pinned but unaudited.
- TLS verification is relaxed for the CRM host (`verify=False` in the SLX
  client) — an accepted risk for an internal system, worth revisiting if the
  host changes.

## 7 · CRM host migration readiness — already cheap, just know it

The CRM vendor is expected to replace the SLX host at some point. The base URL
is a single constant (`src/slx/client.py`, also injectable via the client
constructor). When it happens: change the constant (or env), re-run the suite,
run one live pull, compare against the prior cache.

---
