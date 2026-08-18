# Decisions — the rules in force

Every rule below is **currently live in the code**. This is the curated,
present-tense version of a much longer working log: reversals, dead ends and
superseded rules are omitted on purpose — what's here is what the program does
*now*, with the date each rule was ratified and one line of why.

Definitions were sourced from the WHA membership team (leadership and the CRM
administrator), never guessed — that is this project's hard rule 6, and most
historical defects were wrong *definitions*, not wrong code. When a number is
challenged, the answer starts here and ends in the Trace page's member list.

The **truth hierarchy** (2026-07-14) that governs every dispute:
1. **Database records** (account-level CRM facts) — closest to objective truth
2. **Ratified definitions** (this file) — the team's stated intent
3. **CRM reports** — conventions and reconciliation targets, never truth
   (they contradict each other and violate agreed definitions in places)
4. **The old handmade report** — historical reference only

A discrepancy resolves by tracing both sides to account level and applying the
definition — whichever side deviates is wrong, and it is sometimes the CRM
report.

---

## Structure

- **Fiscal year = Oct 1 → Sep 30** (2026-06). Month M's retention column
  reports bill month M−1. Any Sep-first logic anywhere is a bug.
- **The cache is the contract** — the engine writes
  `scoreboard_<period>.json`; everything downstream reads it, nothing
  downstream re-queries the CRM.
- **Target / Non-Target is the reporting structure** (2026-06-17, membership
  leadership): restaurants ≥ 10 FTE and lodging ≥ 40 rooms (40 confirmed
  2026-07-21) are Target. Size-unknown members count Non-Target so totals
  stay whole — no member is ever dropped from a count for lacking a size.
- **Sources per family** (settled 2026-07/08 after both alternatives were
  tried): **drops** come from the CRM's own Crystal report exports (the
  export *is* the answer — dues and real status reasons on every row);
  **everything else** is computed from CRM database records, because only
  the ledger can answer a past month.

## The month close (2026-08-03)

- A month closes with **one human action**: pick the date the CRM's ITD job
  ran (the utility that inactivates unpaid accounts), press Close.
- **Retention freezes from the last nightly snapshot BEFORE ITD** — ITD
  write-offs shrink the billed denominator, so post-ITD retention overstates.
  Billables, drops and penetration re-capture fresh AFTER ITD.
- A sealed month **never recomputes**. Its frozen values are stamped over
  every later build. The only way a closed number moves is a deliberate,
  recorded amendment ("Adjust a Number" in the console) — and an amendment
  moves the number *and* the member list behind it together (2026-08-15:
  an excluded member carries no money; excluding a member means excluding
  them from the count and the dollars everywhere, or it means nothing).

## Retention

- **Cohort** = members whose record carries the bill month *and* a
  membership (dues) product. A record with no dues product has nothing to
  renew; its fee invoices are pass-throughs (2026-07-28).
- **Live until the cycle closes, then frozen** (2026-07-28): computed as of
  `min(today, cycle_close)` where the cycle closes at the **end of month
  M+1** — the end of the third billing notice's month, confirmed against
  payment-ledger dates. Strict close, no grace: money arriving after the
  close is a reinstate, not a renewal.
- **Partial payers count as retained** (2026-07-21, the administrator's own
  convention), and the dollars are netted: paid = billed − balance.
- **First-cycle members are excluded** — a brand-new member is not "up for
  renewal" (matches the CRM's own "Adjusted" retention convention).
- **A member who exited mid-cycle is a drop, not a retention miss** —
  counting them here would charge the territory twice for one loss.
- **Fee money is never retention** (2026-08-06): county fees, claims-program
  (CMP) fees and retro-program fees are not dues; a fee-only payment counts
  nobody as retained.
- **An ask fully rescinded and never reissued is not an ask**; a bill and
  its reversal entered the same day on the same invoice is a data-entry
  correction, not money (2026-08-11).
- **Comped (BOB) members count as retained at $0/$0**, with their comped
  face value on the program's own line (2026-08-04). BOB = the diverse-
  ownership comped-membership program; the rep keeps revenue credit.
- **The invoice's original bill month wins** (2026-08-12) — the CRM
  retro-edits bill months; filing by the current value would rewrite closed
  history.
- **Allied members are OUT of hospitality retention** (2026-08-14, ruled
  directly by membership leadership — reversing an earlier inherited rule).
  Allied carries no TM goal and is not pursued, so it must not move a line
  that decides commission. Allied members stay *visible* in the Trace,
  listed and uncounted. Majors/NRA is likewise excluded from retention.

## Drops

- **Source**: the CRM's Crystal drops exports (hospitality + allied),
  fiscal-year-windowed.
- **A drop in month M means the member is no longer billed in cycle M**
  (2026-07-27) — the same bill-month axis retention uses.
- **Filed by the status-flip date** when a plausible in-FY date exists
  (2026-07-31), bounded on *both* edges of the fiscal year; dateless rows
  file at the cycle close and are flagged, never guessed into a month.
- **Excluded from the counts, always visible with a reason**: retro-program
  rows (never drops — on the export as FYI), administrative/housekeeping
  closure reasons (a record replaced is not a member lost), rows with no
  usable billing cycle, unknown status groups (surfaced, never silently
  absorbed), and **allied** (2026-08-14, same reasoning as retention: a
  member never counted as retained cannot count against a TM on the way
  out).
- **Stale billing does not hide a real closure** (2026-08-04): a genuine
  status flip with a plausible date counts in its flip month even when the
  billing record is out of date — and the record gets flagged for fixing.
- **Banding joins on the WRA member number first**, names only as fallback
  (2026-08-12) — duplicate member names in one territory made name-matching
  publish dollars into the wrong month.
- **One loop** (2026-08-14): a single classifier produces one ledger entry
  per exported row; the published grids and the Trace page's member list are
  two projections of the same objects, so they cannot disagree.

## New sales — structural

- **The published new-sales cells are summed from the captured member rows**
  (2026-08-18) — the same one-pass structure as drops. Adopted after a live
  divergence: a nightly published a cell $1,754.50 below the sum of its own
  member rows, and the CRM's own New Member Sales export agreed with the
  member rows to the penny. A paid-basis revenue cell that decreases against
  the prior run is flagged (`revenue_decreased_since_last_run`) — legitimate
  but rare, and always worth eyes.

## Billables

- **Billables = the records that actually carry the dues bill**, verified
  against the CRM's own billables export. Allied billables are their own
  line; a combined "incl. Allied" total exists and is labelled as such.
- Corporate accounts are members (aggregate FTE) and stay in the member
  splits; they are excluded from *penetration*, which is a location metric —
  the two rules are orthogonal and both correct (2026-07-13).

## Penetration

- **A location metric**: Active ÷ (Active + Inactive), restaurants and
  lodging only, per territory.
- **The lodging universe is the CRM report's own subtype set** (2026-07-19):
  true lodging subtypes only — RV parks, campgrounds, vacation rentals,
  B&Bs are out. Target lodging = 40+ rooms (2026-07-21).
- Allied is never in penetration. Corporate/grocery are excluded.
- The dashboard's statewide penetration cell is an **unweighted average of
  the 11 territories** and is labelled as such — see the backlog for the
  open definition question.

## New sales

- **Revenue = WRA dues only, on a PAID basis** (payment month, net of
  balance). Claims-program and retro fees are not dues (2026-07-21, the
  administrator's definitions, proven at invoice level).
- **A new member counts once, in the month of first payment** — no payment,
  no count (2026-07-22). Ever paid before = renewal, regardless of gap.
- **Allied counts in new sales** — the one performance metric that keeps
  allied, by the administrator's explicit rule ("allied in nothing but new
  sales").
- **A sale is credited to the SELLER, not to the account's territory**
  (2026-07-15). When a rep sells a business that sits in another territory,
  the sale appears in the selling rep's column. The seller is read from
  `AccountExtension.Originator` and mapped through `seller_user_to_territory`
  in `config/territory_map.yaml` (`logic/attribution.py`, applied in
  `revenue.py` and `new_members.py`). The account's data-entry user is not the
  seller and is never used for attribution.

  **This applies to new sales and new-sales revenue only.** Every other metric
  — retention, drops, billables, penetration — is computed on the account's own
  territory. Goals and %-to-goal key on the sales columns, so attributing those
  by territory would credit reps for other reps' work.
- Goals are graded against Target/Non-Target; the statewide goal is the
  average of the territories that have one (2026-08-11).

## Display

- **The dashboard leads with revenue retention** (2026-08-14, membership
  leadership: "we don't look at count, we look at revenue — that's how we
  get judged"). Retention percentages are shown both member-based and
  dollar-based, labelled "T + NT".
- No analyst jargon in user-visible strings; every closed month announces
  itself plainly ("Jul is closed — these are the numbers it was closed
  with").
