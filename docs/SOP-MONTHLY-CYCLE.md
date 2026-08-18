# SOP — The Monthly Cycle (DRAFT, gate 4)

> Status: skeleton drafted 2026-08-05; finalize at gate 4 with screenshots.
> leadership's ask: build the training walkthrough with **Scribe** alongside
> this document (Jiho records it during the gate-2 supervised August run).

Who this is for: the person running the Membership Performance Report after
the handoff (the administrator / the member-services admin / a contractor). No coding involved — everything
happens in the web console.

## Every night (automatic — you do nothing)

The system pulls the CRM around 2 AM, rebuilds the current month's report,
publishes it to SharePoint, and files an immutable photo of every number.
If the report looks stale, check the console's status bar first.

## First week of the month (the one human ritual)

1. **Wait for accounting's green light** (payments posted, ~5th business
   day) and confirm with the CRM owner that **ITD has been run** — get the
   date AND the rough time ("ITD ran Tuesday around 6 am").
2. Open the console → **Month Close** panel. It offers the right month by
   itself (oldest month that ended without a close — months close in
   order; you can't skip one).
3. Enter the ITD date and time. The panel shows WHICH nightly photo the
   retention numbers will keep (always the last one before ITD). Read the
   line, then press **Close**.
4. **Read any warning out loud before trusting the month.** A warning
   means the chosen photo may already contain ITD's write-offs — usually a
   wrong date. Warnings are saved on the month's record either way.
5. The close triggers one fresh pull automatically (~2.5 h). When it
   lands, the month is fully locked: every number frozen, and re-running
   the month can change how the report *looks*, never what it *says*.

## What "locked" means

- Retention keeps the picture from the night BEFORE ITD (non-payers still
  show as billed — ITD's write-offs never flatter the percentage).
- Billables / penetration / drops keep the picture from AFTER ITD (the
  cleaned-up roster).
- Both photos live in the month's close record (locally and on SharePoint
  under Reports › Membership Performance Report › Closes).

## If a month was closed with the wrong date

There is deliberately no button for this. Every night's numbers — before
and after ITD — are archived as immutable snapshots, so a wrong-date
close is always repairable later, carefully, from the correct archived
photo. Contact the developer/maintainer, who re-freezes from the archive
with the change logged on the month's record (the same amendment
discipline every locked-month change uses).

## Reading the flags

Every generated report carries a **Data - MPR Flags** tab: things the
program noticed but refuses to silently fix (voided bills, comped
memberships, records missing fields, duplicates…). These are DATA issues
for the CRM owners, not report errors. The flag names the member or the
account id; the Members tab has the full roster detail.

### The one flag that is a calendar chore, not a data issue

**"Drops exports are not scoped to this fiscal year"** — expect this the
first time the report runs in **October**, and only then. The dropped-member
reports in the CRM are scheduled with a date range that has to be moved
forward every October; until someone moves it, one export can hold more than
one year of departures. Departures that carry a real end date are still filed
correctly. Departures with no end date fall back to their billing month, which
has no year on it, and those can land in the wrong column.

**What to do:** open each schedule the flag names in the CRM scheduler and set
its StatusDate range to start **October 1 of the fiscal year now being
reported**. The flag disappears on the next nightly run. This is the only
once-a-year manual step in the whole cycle, and it is why the report tells you
about it instead of relying on anyone remembering.

## When something looks wrong

1. Check the flags tab first — the answer is usually named there.
2. Check `docs/RULED-DIFFS.md` *(archive repo)* — if you're comparing against a CRM report,
   the gap is almost always a named, ruled difference.
3. A gap that fits NO ruled class is a finding — write it down and
   investigate before trusting either number.

## Checking a number (the Trace page)

Console → Membership Performance Report → **Trace a Number**. Pick the
report month, the number family, the territory and the month. You get:
the member list behind the number (and everyone considered-but-excluded,
each with a reason), a green check that the members add up to the
published value exactly, where the data came from, and the rules that
shape the number in plain words. If the check is ever red, that cell
needs investigating — the page will not pretend.

## Two kinds of numbers (worth understanding once)

**Photo numbers** — billables, member locations, penetration. The CRM only
knows who is a member *right now*, so these can only be photographed. Every
month's photo is archived automatically, and the month close locks it from
the after-ITD capture. Past months on the report show their own photos.

**Story numbers** — retention, new sales, drops. The CRM keeps dated
records (invoices, payments, status changes), so every rebuild re-tells the
whole year from them. They lock only when their month closes — and
retention is the one number locked from BEFORE ITD (so members who never
paid still show as billed), while everything else locks after.

## Where everything lives on SharePoint (and what you must never hand-edit)

```
Membership Data Hub/
├── Documents/            ← guides like this one — read freely
├── Inputs/      ← admin_inputs.xlsx — THE file you edit (goals)
├── Audit & History Log/  ← 🚫 machine-only: every night's photos
└── Reports/Membership Performance Report/
    ├── Data/             ← 🚫 machine-only: receipts, flags, close records
    │                        (Data/closes = the month locks), durable inputs
    └── Output/
        └── <month>/
            ├── Runs/     ← every generated copy, one folder per run day
            │   └── YYYY-MM-DD/   (timestamped files inside — read freely)
            └── FINAL/    ← the ONE locked report for a closed month —
                             this is the file to share or archive
```

**The rule in one line:** you *edit* only `admin_inputs.xlsx`; you *read*
anything in `Documents/` and `Output/`; everything marked 🚫 is written by
the system and repaired only through the amendment procedure. Hand-editing
a 🚫 file can silently corrupt closed months.

**Finding a locked month's report:** Output → the month → FINAL. One file,
always current (amendments refresh it automatically). No searching.
