# Membership Performance Report — how every number is made

Each metric below: the formula, the data pulled, and the exact conditions,
in order. Size rules are shared, so they come first.

---

## Size rules — used by every Target / Non-Target split

Applied to every account, top to bottom:
- Allied: Non-Target
- hotel with 40 or more rooms: Target
- hotel with 39 or fewer: Non-Target
- hotel with no room count: Unknown
- restaurant with 10 or more employees: Target
- restaurant with fewer than 10: Non-Target
- restaurant with no size: Unknown

Room counts come from each hotel's membership record. Employee sizes come from
each restaurant's profile, and variant spellings like "10-19" are read the same
as "10 to 19". Unknowns print a warning; each metric below says where its
Unknowns go.

---

## Goals — New Sales Revenue $, New Members #, Retention %

Formula: copied straight from the admin workbook. The only hand-entered
numbers on the report.

Conditions:
- months are matched by the column's header name, so a reordered sheet cannot shift months
- a typed zero stays zero; a blank stays blank
- retention and penetration goals: one default, plus per-territory overrides

---

## New Members — Target # / Non-Target #

Formula: count of members enrolled in the month, per territory.

Data pulled: membership records with an enrollment date inside the month,
for each territory's accounts.

Conditions:
- enrolled within the month, first day through last day inclusive
- a member who ever paid dues before is a renewal, not new; this catches
  rejoining members even when the reinstatement fields were left blank
  (checked against the payment ledger, any prior dues payment)
- marked reinstatements do not count as new
- child locations count: both Domino's count
- members who later dropped still count; history does not rewrite
- credit goes to the TM who sold it, even into another TM's territory
- Target / Non-Target by the size rules; Unknowns are counted inside Non-Target

---

## New Sales Revenue — Target $ / Non-Target $

Formula: dues actually collected from that month's new members, per territory.

Data pulled: the invoice ledger for the month's new-member accounts.

Conditions:
- paid basis: amount billed minus remaining balance
- WRA dues invoices only
- MSC invoices never count: CMP is the Claims Management Program, a service
  fee, not dues; retro fees and batch postings are also not sales
- county and local fees and event purchases are subtracted: they ride the
  same invoice as dues but are not membership sales (identified by their
  charge codes in the payment ledger, one per fee type per year)
- members excluded as renewals contribute no revenue here
- rebill reversal pairs cancel out
- BOB two-year promo members count at face value, even though the promo
  credits the dues back; the BOB row shows how much
- credit goes to the selling TM, same as new members
- the month is the member's sign-up month, matching the membership team's
  published report; their first-year dues land in that month's column

---

## Billables — Hospitality Target # / Hospitality Non-Target # / Allied #

Formula: count of active accounts carrying a membership bill, on the day of
the pull, per territory.

Data pulled: active accounts and their membership products.

Conditions:
- the account must be Active and hold a membership product
- Allied versus hospitality is decided by the member's billing product: a
  product named with the word Allied (for example "Allied Corporate Dues")
  makes the member Allied; any other dues product is hospitality. The account
  type does not decide: Harbor Foods is typed Corporate but bills on an
  Allied product, so it counts as Allied, matching the membership team
- hospitality splits Target / Non-Target by the size rules; Unknowns are
  counted inside Non-Target and tracked separately
- about eleven statewide vendor partners are managed by a house login instead
  of a TM; they belong to no territory, so they are left out of every
  territory's Allied count

---

## Retention — Members and Revenue, Up for Renewal and Retained, Target / Non-Target

What retention means here: every member has one bill month a year. When it
arrives they get their renewal bill — that is their yearly choice to stay or
leave. Up for Renewal = the members billed that month. Retained = the ones
who paid. This matches the membership team's own retention file member for
member.

Formula: retained divided by up-for-renewal, members and dollars, per territory.

Data pulled: WRA renewal invoices for the members whose annual renewal is due
in the bill month.

Conditions:
- the report's month column shows the previous bill month: June's column is
  May's renewal cohort
- a member's first-ever bill is not a renewal, so first-year members are out
- a partial payer counts as retained: they stayed, they just could not pay in
  full — the membership team's convention, and ours
- retained dollars: amount billed minus remaining balance, so partial payers
  count what they paid
- rebill reversal pairs cancel out
- territories with two TMs are added together, never overwritten
- the percentage is recomputed from the summed counts
- Target / Non-Target by the size rules

---

## Drops — Target # / Non-Target #, Dropped Revenue $, category rows, Top Drop Reason

Formula: members lost in the month, counted and dollar-valued, per territory.

Data pulled: accounts that left Active status inside the fiscal year, dated by
the actual status-change entry in the account history.

Conditions:
- must hold a membership record; prospects can never be drops
- every drop reason counts and lands in one category: Closed, Sold,
  Non-Payment, or Voluntary
- administrative cleanups and retro-program removals are not lost members;
  they appear only in the detail listing, never in the counts
- dropped revenue is the amount that was billed on the dropped membership
- Target / Non-Target by the size rules
- Top Drop Reason is the largest category for the month

---

## Closed Businesses — Target # / Non-Target #

Formula: businesses that physically ceased to exist, per territory.

Conditions:
- status reason says the business is gone: out of business, or permanently closed
- kept on its own sheet, separate from drops: closed means the business died,
  dropped means the membership ended

---

## Penetration — Restaurant %, Lodging %, Combined %, and the Non-Target versions

Formula: Active divided by Active plus Inactive, per territory, per segment.

Data pulled, per territory:
1. every account under the territory's manager with status Active
2. every account with status Inactive
3. each hotel's room count, from its membership record
4. each restaurant's employee-size range, from its restaurant profile

Counted as restaurant:
- Target size
- and account type is Restaurant

Counted as lodging:
- Target size
- and account type is Hotel
- and subtype is real lodging: full service, limited service, economy,
  extended stay, resort, gaming
- RV parks, campgrounds, vacation rentals, military housing, and bed and
  breakfasts are not counted

Numbers:
- Target Members = the Active count
- Total Target Locations = the Active plus Inactive count
- Penetration % = Target Members divided by Total Target Locations
- the Non-Target rows repeat every step with Non-Target size, so small
  restaurants and small hotels get their own numerator and denominator
- Unknown-size accounts are left out of penetration entirely

---

## Dashboard numbers

- % to Goal: revenue divided by goal, as of the month; blank when no goal is set
- Average Retention: total retained divided by total up-for-renewal across the
  year, so a 100-member month outweighs a 2-member month
- Monthly Trends sheet: October through December read the prior calendar year,
  because the fiscal year starts in October

---

## Console alerts

- BOB accounts: the month's newly enrolled BOB members. Their dues are comped,
  so the membership team hand-credits each one to its TM; this alert is that
  to-do list. Empty list = no BOB sign-ups this month, nothing to credit
- Retention watch: territories below their own retention goal from the admin
  workbook
- No-goal warnings: revenue was booked in a month with no goal entered

---

## How it is all verified

Four automated checks run after every pull: every written cell matched back to
the pulled data, all 8,600-plus formulas checked for the right territory,
metric, month, and year, penetration and billables reconciled against the
CRM's own reports, and the formulas recalculated. The report ships only when
all of them pass.
