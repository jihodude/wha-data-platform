"""metric_registry.py — every face metric's source + computation card.

Ruled by Jiho 8/6: "make sure every metric being made traces back to its
sources and computation logic and that gets directly reflected into the
trace-a-number page." This file IS that guarantee's substrate: one entry
per mapper metric — where the number comes from, how it is computed in
plain words, which receipts family holds its member lists, and which
ratified rules explain its eyebrow-raisers.

A suite test enforces: every METRIC_FIELD_MAP key has an entry here.
Adding a metric without a trace path fails the build.

Sources:
  slx-live        computed from the live SLX pull (member-level receipts)
  crystal-export  overlaid from an archived scheduled Crystal export
  admin           entered by staff in Admin Inputs on SharePoint
  derived         arithmetic over other metrics (trace the operands)
  photo           point-in-time roster snapshot (its month's own pull)
"""

RULES = {
    "two-photo-close": (
        "A month closes with two snapshots: retention keeps the picture "
        "from the night before ITD (so non-payers still show as billed), "
        "while billables, drops and penetration are captured AFTER ITD (the "
        "cleaned-up roster)."
    ),
    "comp": (
        "A comped member counts towards retained member count but "
        "contributes $0 to both revenue sides. The face value is shown on "
        "the comp line."
    ),
    "comp-vs-void": (
        "A credit issued the SAME DAY as the bill is a data-entry void "
        "(excluded); a credit issued later is a comp. Validated against the "
        "GS Dues Discounts ledger."
    ),
    "bob": (
        "BOB renewals are comped but count on both revenue sides. The TM "
        "gets the credit. Opposite of ordinary comps by design."
    ),
    "first-cycle": (
        "A new member's first bill is a SALE, not a renewal. They are "
        "excluded from retention until their first renewal a year later."
    ),
    "fees-out": (
        "County fees that are included in the dues invoice are excluded "
        "from the calculation. Dues only everywhere."
    ),
    "dues-level-ask": (
        "The ASK is the Dues Level, not the invoice amount. Accounting "
        "deletes and recreates invoices on adjustments, so the invoice is "
        "not a stable record. Per-room priced lodging = price × rooms."
    ),
    "single-bill": (
        "A multi-invoice cycle (county-fee members get fee + dues + "
        "combined invoices the same day) is valued by its SINGLE combined "
        "bill — and the county-fee portion inside it is then excluded, so "
        "the numbers stay dues-only."
    ),
    "event-axis": (
        "A member drop gets filed in the month of the status-flip date, not "
        "its bill month. The bill month is the fallback when no flip date "
        "exists."
    ),
    "allied-drops": (
        "Drops INCLUDE allied members. Allied are never part of hospitality "
        "retention, so an allied drop never moves the retention %."
    ),
    "stale-hygiene": (
        "A drop with a years-old last invoice left long ago, not this "
        "year. If Usable drop date exists within this year: counted in "
        "that month. If no usable date: not counted — listed on the "
        "Flags Tab."
    ),
    "rro": (
        "RRO / retro-program rows are never counted in drops."
    ),
    "posting-lag": (
        "A payment that lands after the month's pay window closes doesn't "
        "count in the frozen month — the member shows on this page under "
        "\"Considered but excluded\" as paid after close."
    ),
    "partial-pay": (
        "A member who paid part of their renewal counts as Retained. The "
        "dollars show what was actually paid."
    ),
    "target-def": (
        "Target = SIZE: restaurants 10+ FTE, lodging 40+ rooms. Excludes "
        "Allieds."
    ),
    "goal-colors": (
        "Green = at/above the admin goal, yellow = within 5 points below "
        "it, red = further below. Goals live in Admin Inputs; change them "
        "there and the colors follow on the next build."
    ),
    "photo-ytd": (
        "Roster counts (billables, locations) are snapshots. Quarter and "
        "YTD cells show the LATEST snapshot. Months never captured show "
        "'-'."
    ),
    "frozen": (
        "Closed months are locked."
    ),
}

_RET_RULES = ["two-photo-close", "comp", "comp-vs-void", "bob",
              "first-cycle", "fees-out", "dues-level-ask", "single-bill",
              "partial-pay", "posting-lag", "frozen"]
_DROP_RULES = ["event-axis", "allied-drops", "stale-hygiene", "rro",
               "dues-level-ask", "two-photo-close"]
_BILL_RULES = ["two-photo-close", "photo-ytd", "target-def"]
_SALES_RULES = ["first-cycle", "fees-out", "bob", "comp"]


def _e(source, card, family=None, rules=()):
    return {"source": source, "card": card, "family": family,
            "rules": list(rules)}


REGISTRY = {
    # ---- goals (admin) ----
    "Goal - New Sales Revenue ($)": _e("admin", "Entered by staff in Admin Inputs (monthly revenue goal per territory)."),
    "Goal - New Members (#)": _e("admin", "Entered by staff in Admin Inputs (monthly new-member goal)."),
    "Goal - Retention %": _e("admin", "Entered by staff in Admin Inputs (retention goal; drives the status colors).", rules=["goal-colors"]),
    "Goal - Penetration %": _e("admin", "Entered by staff in Admin Inputs (penetration goal; drives the status colors).", rules=["goal-colors"]),
    # ---- new sales ----
    "New Sales Revenue - Target ($)": _e("slx-live", "Dues dollars actually paid by new members whose first payment landed this month. Fees excluded.", "New Members / New Sales", _SALES_RULES),
    "New Sales Revenue - Non-Target ($)": _e("slx-live", "Same as Target new sales, but for the Non-Target members (includes unclassifiable).", "New Members / New Sales", _SALES_RULES),
    "New Sales Revenue - BOB/Promo ($)": _e("slx-live", "New-member revenue credited under the BOB initiative (comped dues; rep gets credit).", "New Members / New Sales", ["bob"]),
    "BOB - Target ($)": _e("slx-live", "BOB share of target-band new-sales revenue.", "New Members / New Sales", ["bob"]),
    "BOB - Non-Target ($)": _e("slx-live", "BOB share of non-target-band new-sales revenue.", "New Members / New Sales", ["bob"]),
    "New Sales - Comped ($)": _e("slx-live", "Face dollars of NEW memberships comped outside BOB.", "New Members / New Sales", ["comp", "bob"]),
    "New Members - Target (#)": _e("slx-live", "Count of paying new members.", "New Members / New Sales", _SALES_RULES),
    "New Members - Non-Target (#)": _e("slx-live", "Same as New Members - Target, but for non-target band.", "New Members / New Sales", _SALES_RULES),
    "New Members - BOB (#)": _e("slx-live", "New BOB joins counted (Anthony 8/12: the count, not just the revenue). Subset of the new-member count; identified by the diversity checkbox at face value.", "New Members / New Sales", _SALES_RULES + ["bob"]),
    # ---- comp lines (retention) ----
    "Retention - Comped (#)": _e("slx-live", "Members whose renewal was comped this cycle. Counted retained, $0 both sides.", "Retention", ["comp", "comp-vs-void"]),
    "Retention - Comped ($)": _e("slx-live", "Face dollars of those comped renewals.", "Retention", ["comp"]),
    "Retention - Comped Target (#)": _e("slx-live", "Comped renewals, target band.", "Retention", ["comp"]),
    "Retention - Comped Non-Target (#)": _e("slx-live", "Comped renewals, non-target band (unclassifiable folds here).", "Retention", ["comp"]),
    "Retention - Comped Target ($)": _e("slx-live", "Comped face dollars, target band.", "Retention", ["comp"]),
    "Retention - Comped Non-Target ($)": _e("slx-live", "Comped face dollars, non-target band.", "Retention", ["comp"]),
    "Retention - BOB (#)": _e("slx-live", "BOB renewals. Counted in retention (unlike comps).", "Retention", ["bob"]),
    "Retention - BOB ($)": _e("slx-live", "Face dollars of BOB renewals, counted in retained revenue.", "Retention", ["bob"]),
    # ---- billables ----
    "Billables - Hospitality Target (#)": _e("photo", "Roster photo: active dues-carrying hospitality members, target band, enrolled by month-end.", "Billables", _BILL_RULES),
    "Billables - Hospitality Non-Target (#)": _e("photo", "Same photo, non-target band.", "Billables", _BILL_RULES),
    "Billables - Allied (#)": _e("photo", "Active allied members.", "Billables", ["target-def", "photo-ytd"]),
    # ---- retention counts/dollars ----
    "Members Up for Renewal - Target (#)": _e("slx-live", "Members billed for renewal this cycle, target band.", "Retention", _RET_RULES),
    "Members Retained - Target (#)": _e("slx-live", "Of those, who paid (anything) by the cycle close.", "Retention", _RET_RULES),
    "Members Up for Renewal - Non-Target (#)": _e("slx-live", "Billed for renewal, non-target band.", "Retention", _RET_RULES),
    "Members Retained - Non-Target (#)": _e("slx-live", "Paid by close, non-target band.", "Retention", _RET_RULES),
    "Revenue Up for Renewal - Target ($)": _e("slx-live", "Dues asked of the target-band cohort (at Dues Level).", "Retention", _RET_RULES),
    "Revenue Retained - Target ($)": _e("slx-live", "Dues actually collected by close, target band.", "Retention", _RET_RULES),
    "Revenue Up for Renewal - Non-Target ($)": _e("slx-live", "Dues asked, non-target band.", "Retention", _RET_RULES),
    "Revenue Retained - Non-Target ($)": _e("slx-live", "Dues collected by close, non-target band.", "Retention", _RET_RULES),
    # ---- drops ----
    "Drops - Target (#)": _e("crystal-export", "Members lost, filed at the month the membership ended; target band. From the scheduled Crystal drops exports.", "Drops", _DROP_RULES),
    "Drops - Non-Target (#)": _e("crystal-export", "Members lost incl. allied, non-target band.", "Drops", _DROP_RULES),
    "Dropped Revenue - Target ($)": _e("crystal-export", "Dues value of target-band drops (at Dues Level).", "Drops", _DROP_RULES),
    "Dropped Revenue - Non-Target ($)": _e("crystal-export", "Dues value of non-target drops.", "Drops", _DROP_RULES),
    # ---- penetration ----
    "Total Target Locations - Restaurant (#)": _e("photo", "Market size: target restaurants in the territory (active + inactive).", "Penetration", ["target-def"]),
    "Total Target Locations - Lodging (#)": _e("photo", "Market size: target lodging.", "Penetration", ["target-def"]),
    "Target Members - Restaurant (#)": _e("photo", "Active target restaurant members (snapshot).", "Penetration", ["target-def", "two-photo-close"]),
    "Target Members - Lodging (#)": _e("photo", "Active target lodging members (snapshot).", "Penetration", ["target-def", "two-photo-close"]),
    "Penetration - Restaurant %": _e("derived", "Active ÷ (active + inactive) of target restaurants.", "Penetration", ["target-def", "goal-colors"]),
    "Penetration - Lodging %": _e("derived", "Active ÷ (active + inactive) of target lodging.", "Penetration", ["target-def", "goal-colors"]),
    "Penetration - Combined %": _e("photo", "Both segments combined.", "Penetration", ["target-def", "goal-colors"]),
    "Non-Target Locations - Restaurant (#)": _e("photo", "Market size below the target threshold, restaurants.", "Penetration", ["target-def"]),
    "Non-Target Locations - Lodging (#)": _e("photo", "Market size below threshold, lodging.", "Penetration", ["target-def"]),
    "Non-Target Members - Restaurant (#)": _e("photo", "Active non-target restaurant members.", "Penetration", ["target-def"]),
    "Non-Target Members - Lodging (#)": _e("photo", "Active non-target lodging members.", "Penetration", ["target-def"]),
    "Penetration - Restaurant Non-Target %": _e("derived", "Active ÷ market, non-target restaurants.", "Penetration", ["goal-colors"]),
    "Penetration - Lodging Non-Target %": _e("derived", "Active ÷ market, non-target lodging.", "Penetration", ["goal-colors"]),
    "Penetration - Combined Non-Target %": _e("derived", "Both non-target segments combined.", "Penetration", ["goal-colors"]),
    # ---- locations ----
    "Member Locations - Target (#)": _e("photo", "Active target member locations (restaurant + lodging) — compare with billables to spot consolidations.", "Penetration", ["target-def", "photo-ytd"]),
    "Member Locations - Non-Target (#)": _e("photo", "Active non-target member locations.", "Penetration", ["target-def", "photo-ytd"]),
}
