"""receipts_sheet.py — render the receipts into the workbook + artifact.

Sheet: `Data - MPR Members` (Excel's 31-char limit). SP: the receipts JSON
goes to Reports/Membership Performance Report/Data/, sibling of Output
(ruled 2026-08-03); the sheet itself travels inside the report workbook.
Layout ruled 2026-07-31: Block 1 = definitions (Metric | What it is — every
sentence verified against the implemented code before shipping); Block 2 =
member rows in the MPR's own metric order, one bold reconciliation row per
published cell. Simple and basic — no prose generation, closed vocabulary.
"""
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

MONTH_ORDER = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep"]
# MPR row order (the TM sheet's metric sequence)
METRIC_ORDER = ["New Members / New Sales", "Billables", "Retention", "Drops"]

HEADERS = ["Metric", "Year", "Month", "Territory", "Band", "Member",
           "WRA # / ID", "Invoice #", "Key date", "Asked $", "Amount $",
           "Counted?", "Qualifies as"]

# Every statement verified against the implemented code (file:behavior) before
# shipping — Jiho's hard requirement. See test_receipts_render for the pinned
# dispositions these sentences describe.
DEFINITIONS = [
    ("New Members / New Sales",
     "A new member counts in the month their first payment arrived, and the "
     "dollars are the money received that month (installments land as they "
     "come). Rejoins after ~6 months are new members. Leaves out: reinstates "
     "within the window, CMP fees, and corporate-bill increases for new child "
     "locations (dues adjustments, not sales). BOB members count as new "
     "members; their comped face value shows in the BOB figure."),
    ("Billables",
     "Members who are Active and carry a membership (dues) product on the day "
     "the report ran — a photograph, not a month total. Hospitality vs Allied "
     "by the product's name. Target vs Non-Target by size (restaurants 10+ "
     "employees, lodging 40+ rooms); no size on file counts as Non-Target. "
     "Child locations with their own product count separately."),
    ("Retention",
     "Of the members billed for a cycle, those who paid any amount before the "
     "cycle's window closed (end of the month after their bill month) — the "
     "month column shows the cycle that closed that month. Partial payments "
     "count; a payment after the close counts in neither members nor dollars "
     "(a reinstate, not a renewal). The combined invoice is the bill for "
     "payment matching, but dollars report DUES ONLY — county/local fees and "
     "pass-through dues collected for other associations (Seattle Hotel "
     "Association, AHLA) are excluded (ruled 8/3). Leaves out entirely: "
     "retro-program flips, "
     "first-cycle members, mid-cycle exits (those are drops), and rescinded "
     "bills of members no longer active. Comped members (bill credited off "
     "weeks later, member still Active) count as retained members with $0 on "
     "both revenue sides — their face value shows on the Comped line (ruled "
     "8/4). A same-day bill-and-credit pair is a data-entry void, not a comp "
     "— excluded entirely and flagged. BOB members' comped renewals count at "
     "FULL face value on both sides (ruled 8/4) and show on the BOB Renewals "
     "line."),
    ("Drops",
     "Members whose status changed to Inactive or Closed, counted in the "
     "month the status actually changed, valued at their last actual dues "
     "bill. Retro-program flips are never drops (listed here for reference "
     "only). Reasons are the CRM's own vocabulary. A row with no usable flip "
     "date is filed at its cycle's close and marked 'date estimated'."),
    ("Penetration",
     "Active hospitality members divided by the county market count, "
     "photographed on the run day. Member-level rows are the Billables "
     "roster; this sheet reconciles the counts."),
]


def _recon_key(r):
    return (r["metric"], r["territory"], r["month"], r.get("band") or "")


def build_sheet(wb, period: str, all_rows: List[dict]) -> None:
    """Append (replacing if present) the Data - MPR Members sheet."""
    name = "Data - MPR Members"
    if name in wb.sheetnames:
        del wb[name]
    ws = wb.create_sheet(name)
    from openpyxl.styles import Font
    bold = Font(bold=True)

    ws.append([f"Members behind the numbers — {period}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append(["Every number on this report can name its members. Rows below "
               "list, for each metric, every member counted — and every member "
               "deliberately left out, with the reason."])
    ws.append([])
    ws.append(["Definitions"])
    ws[f"A{ws.max_row}"].font = bold
    for metric, text in DEFINITIONS:
        ws.append([metric, text])
        ws[f"A{ws.max_row}"].font = bold
    ws.append([])

    ws.append(HEADERS)
    for c in ws[ws.max_row]:
        c.font = bold

    year_of = {m: (int(period[:4]) if m in ("Oct", "Nov", "Dec") else
                   int(period[:4]))
               for m in MONTH_ORDER}
    # FY: Oct-Dec belong to fy_start; Jan-Sep to fy_start+1
    fy_start = int(period[:4]) if int(period[5:7]) >= 10 else int(period[:4]) - 1
    year_of = {m: (fy_start if m in ("Oct", "Nov", "Dec") else fy_start + 1)
               for m in MONTH_ORDER}

    def sort_key(r):
        return (METRIC_ORDER.index(r["metric"]) if r["metric"] in METRIC_ORDER else 99,
                r["territory"] or "",
                MONTH_ORDER.index(r["month"]) if r["month"] in MONTH_ORDER else 99,
                r.get("band") or "", r.get("member") or "")

    groups = defaultdict(list)
    for r in all_rows:
        groups[_recon_key(r)].append(r)

    for key in sorted(groups, key=lambda k: sort_key(groups[k][0])):
        rows = sorted(groups[key], key=lambda r: (not r["counted"], r["member"] or ""))
        for r in rows:
            ws.append([
                r["metric"], year_of.get(r["month"], ""), r["month"],
                r["territory"], r.get("band") or "", r.get("member") or "",
                r.get("member_id") or "", r.get("invoice") or "",
                r.get("key_date") or "",
                r.get("ask", ""), r.get("retained", r.get("amount", "")),
                "Yes" if r["counted"] else "No", r["qualifies"],
            ])
        counted = [r for r in rows if r["counted"]]
        metric, terr, month, band = key
        total = sum((r.get("retained", r.get("amount")) or 0) for r in counted)
        ws.append([metric, year_of.get(month, ""), month, terr, band,
                   f"Σ {len(counted)} member(s), ${total:,.0f} — matches the report",
                   "", "", "", "", "", "", ""])
        for c in ws[ws.max_row]:
            c.font = bold

    for col, width in (("A", 24), ("B", 6), ("C", 6), ("D", 13), ("E", 11),
                       ("F", 38), ("G", 14), ("H", 16), ("I", 11), ("J", 10),
                       ("K", 10), ("L", 9), ("M", 30)):
        ws.column_dimensions[col].width = width


def save_receipts_json(period: str, all_rows: List[dict], receipts_dir: Path) -> Path:
    out = receipts_dir / f"receipts_{period}.json"
    # generated_at lets the trace page tell "receipts are an older run than
    # the face" (calm, self-healing) apart from a genuine same-build
    # mismatch (red alarm). 8/12: every cell red-alarmed for two days
    # because 8/10 receipts were compared against an 8/11 face.
    import datetime as _dt
    out.write_text(json.dumps({"period": period,
                               "generated_at": _dt.datetime.now(
                                   _dt.timezone.utc).isoformat(),
                               "rows": all_rows},
                              indent=0, default=str))
    return out


# The flags tab, human layout (Jiho 8/10): one consistent 6-column table
# per section, plain names, severity colors. Severity: "red" = should never
# happen, investigate; "amber" = data quality, fix the record; "gray" = FYI
# by design. Order below is display order (most urgent first).
_CAL_ABB = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
            7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}


def _mon(v):
    return _CAL_ABB.get(v, str(v) if v not in (None, "") else "")


FLAG_SECTIONS = {
    "active_without_payment": (
        "Active members with no payment", "red",
        "Enrolled and active, but no dues payment on record for their "
        "cycle. Policy says this should never happen — investigate each."),
    "comped_new_sales": (
        "Comped new memberships", "red",
        "A NEW membership was comped. Policy says this never happens "
        "outside BOB — investigate."),
    "uncovered_billed_accounts": (
        "Billed accounts the report cannot explain", "red",
        "Billed this FY but in no metric's receipts, no flag, and no known "
        "exclusion rule. Should always be empty — investigate each."),
    "billed_excluded_by_rule": (
        "Billed but excluded by rule (audit trail)", "gray",
        "Billed this FY and deliberately outside every metric: retro/NRA "
        "book, internal accounts, allied house accounts, individual "
        "memberships, unassigned books. Listed so nothing is silent."),
    "drop_date_fallback": (
        "Drops filed without a usable end date", "amber",
        "These drops ARE counted. The end date on record was missing or "
        "unusable when captured, so each was filed at the class close — "
        "the month staff normally date the flips to."),
    "hygiene_counted": (
        "Counted drops with stale billing records", "amber",
        "Real end date this year, so the drop counts in that month — but "
        "billing shows no recent dues invoice. Fix the record."),
    "hygiene": (
        "Old departures — excluded", "amber",
        "Last real dues invoice is years old: they left in an earlier "
        "year, and the record only got cleaned up now. Not counted this "
        "year. Fix the record."),
    "no_cycle": (
        "No valid billing cycle", "amber",
        "Bill month is outside the 12 real cycles (13-16 are retro "
        "program artifacts) — excluded by rule."),
    "voided_bills": (
        "Voided bills", "amber",
        "A bill and its cancellation were entered the SAME DAY — treated "
        "as a data-entry correction, not a comp. The cycle is excluded."),
    "duplicate_records": (
        "Same name, multiple records", "amber",
        "Several CRM records share one name — usually chain locations, "
        "sometimes true duplicates. Listed so per-member lookups don't "
        "mix them up."),
    "record_cleanup": (
        "Record cleanup (duplicates & transfers)", "gray",
        "Billing residue of fixing duplicate records — the bill was fully "
        "credited on the closed twin and the real sale is counted once on "
        "the surviving record. Never a comp, never counted here."),
    "ungrouped_export_rows": (
        "Export rows outside every group (not counted)", "gray",
        "The source export printed these outside every territory/status "
        "group — usually house accounts. They cannot be attributed to a "
        "territory, so they are listed here and never counted."),
    "rro_fyi": (
        "Retro program rows (FYI only)", "gray",
        "Never counted anywhere, by rule. Shown so nothing disappears "
        "silently."),
    "admin_reason_excluded": (
        "Record housekeeping — not counted as drops", "gray",
        "The CRM closed these records for an administrative reason (a new "
        "lead that never joined, a record cleanup, a duplicate, a record "
        "replaced by a newer one) rather than because a member left. By rule "
        "they are not member losses, so they are outside the drop counts and "
        "listed here so nothing disappears silently."),
    "missing_goals": (
        "No goals set for this fiscal year", "red",
        "Goals are entered by hand once a year and none exist for the fiscal "
        "year being reported, so every goal, attainment and goal-vs-actual "
        "cell on the report is blank. Nothing else is affected — the actuals "
        "are still correct. Fix: enter this year's goals in config/goals.yaml "
        "(and the penetration/retention defaults in config/admin_inputs.yaml). "
        "This is an annual step every October."),
    "drops_schedule_window": (
        "Drops exports are not scoped to this fiscal year", "red",
        "The drops reports in the CRM are scheduled with a StatusDate range "
        "that does not begin on Oct 1 of the year being reported, so one "
        "export can hold more than one year of departures. Drops carrying a "
        "real end date are still filed by that date and are safe; drops "
        "WITHOUT one fall back to their bill month, which has no year on it, "
        "and those can land in the wrong column. Fix: open each named report "
        "in the CRM scheduler and set its StatusDate range to start Oct 1 of "
        "the current fiscal year. This is an annual step every October."),
}

# kept for backward compatibility with older callers/tests
FLAG_FAMILY_NOTES = {k: v[2] for k, v in FLAG_SECTIONS.items()}
FLAG_FAMILY_NOTES.update({
    "comp_review": "The comp credit landed less than 7 days after the bill — "
                   "counted as a comp, but check it against the accounting "
                   "discount ledger.",
    "status_unknown_excluded": "SLX has no Status for this account, so the "
                               "credited bill was excluded the safe way. If "
                               "they are actually Active, it is a comp.",
    "billable_without_invoice": "Carries a dues product but was never "
                                "invoiced this year — review with billing.",
})

_SEV_FILL = {"red": "C00000", "amber": "C55A11", "gray": "44546A"}


def _flag_cells(family: str, r: dict, names: dict) -> list:
    """Map one flag row into the consistent 6 columns:
    Member | WRA # | Territory | Month | Amount ($) | What happened."""
    def nm(raw, aid):
        # the row's name can BE the account id (members with no payments
        # never enter the payment-derived name map, 8/10) — resolve it
        if raw and raw != aid:
            return raw
        return (names or {}).get(aid) or raw or aid or ""
    if family == "active_without_payment":
        aid = r.get("account_id", "")
        extra = "" if r.get("mid") else f" · account {aid}"
        return [nm(r.get("name"), aid), r.get("mid", ""),
                r.get("territory", ""), _mon(r.get("month")), "",
                (r.get("why", "") or "") + extra]
    if family == "comped_new_sales":
        return [r.get("accounts", ""), "", r.get("territory", ""),
                _mon(r.get("month")), r.get("face_dollars", ""),
                r.get("defect", "")]
    if family == "drop_date_fallback":
        why = r.get("reason", "")
        if r.get("bill_month"):
            why += f" (billed {_mon(r.get('bill_month'))})"
        return [r.get("name", ""), r.get("mid", ""), r.get("territory", ""),
                _mon(r.get("filed")), "", why]
    if family == "hygiene_counted":
        note = r.get("defect", "")
        if r.get("billing_note"):
            note += f" — {r['billing_note']}"
        return [r.get("name", ""), r.get("mid", ""), r.get("territory", ""),
                _mon(r.get("filed")), r.get("dues", ""), note]
    if family == "hygiene":
        return [r.get("name", ""), r.get("mid", ""), r.get("territory", ""),
                "", r.get("dues", ""), r.get("reason", "")]
    if family == "no_cycle":
        return [r.get("name", ""), r.get("mid", ""), r.get("territory", ""),
                "", r.get("dues", ""),
                f"bill month {r.get('bill_month')} — not a real cycle; "
                f"status {r.get('status', '?')}"]
    if family == "voided_bills":
        aid = r.get("account", "")
        return [nm(None, aid), r.get("mid", ""), "",
                _mon(r.get("bill_month")), "", r.get("defect", "")]
    if family == "duplicate_records":
        accts = r.get("accounts") or []
        resolved = ", ".join((names or {}).get(a, a) for a in accts)
        return [r.get("name", ""), "", "", "", "",
                f"{len(accts)} records share this name — usually chain "
                f"locations. Records: {resolved}"]
    if family == "rro_fyi":
        return [r.get("name", ""), r.get("mid", ""), r.get("territory", ""),
                "", r.get("dues", ""), r.get("reason", "")]
    if family == "record_cleanup":
        aid = r.get("account_id", "")
        extra = "" if r.get("mid") else f" · account {aid}"
        return [nm(r.get("name"), aid), r.get("mid", ""),
                r.get("territory", ""), _mon(r.get("month")),
                r.get("face_dollars", ""), (r.get("why", "") or "") + extra]
    if family in ("uncovered_billed_accounts", "billed_excluded_by_rule"):
        aid = r.get("account", "")
        why = str(r.get("class", ""))
        if r.get("status"):
            why += f" · status {r['status']}"
        return [nm(r.get("member"), aid), r.get("mid", ""), "", "", "",
                why + f" · account {aid}"]
    # unknown family — show everything rather than hide it
    return [r.get("name", r.get("account", "")), r.get("mid", ""),
            r.get("territory", ""), _mon(r.get("month")), r.get("dues", ""),
            "; ".join(f"{k}={v}" for k, v in r.items()
                      if k not in ("name", "mid", "territory", "month",
                                   "dues", "account"))]


def build_flags_sheet(wb, period: str, flags: dict, names: dict = None) -> None:
    """Append (replacing if present) the Data - MPR Flags sheet.

    One colored section per flag family, every section the same 6 columns.
    Data-defect flags are the things the pipeline could NOT settle from the
    data — a human list, deliberately off the report face (ruled 8/4).
    `names` (account id -> AccountName) resolves ids the flag rows carry.
    """
    sheet = "Data - MPR Flags"
    if sheet in wb.sheetnames:
        del wb[sheet]
    ws = wb.create_sheet(sheet)
    from openpyxl.styles import Alignment, Font, PatternFill
    wrap = Alignment(wrap_text=True, vertical="top")

    ws.append([f"Data Flags — {period}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Records the program could not settle from the data alone. "
               "Nothing here is in the report's numbers the wrong way — "
               "each row says what was unclear and what the program did. "
               "Fix the source data and the row disappears on the next "
               "run. Red = investigate. Orange = fix the record. "
               "Gray = FYI only."])
    ws["A2"].alignment = wrap
    carried = flags.get("_carried_from_previous_run") if flags else None
    if carried:
        ws.append([f"Carried from the previous run (no fresh scan this "
                   f"run): {', '.join(map(str, carried))}"])
        ws[f"A{ws.max_row}"].font = Font(italic=True, color="595959")
    ws.append([])

    known = [k for k in FLAG_SECTIONS if flags and flags.get(k)]
    extra = sorted(k for k in (flags or {})
                   if not k.startswith("_") and k not in FLAG_SECTIONS
                   and flags.get(k))
    for family in known + extra:
        rows = flags[family]
        title, sev, desc = FLAG_SECTIONS.get(
            family, (family.replace("_", " ").capitalize(), "amber",
                     FLAG_FAMILY_NOTES.get(family, "")))
        fill = PatternFill("solid", start_color=_SEV_FILL[sev])
        ws.append([f"{title}  ({len(rows)})"])
        hr = ws.max_row
        for col in "ABCDEF":
            ws[f"{col}{hr}"].fill = fill
        ws[f"A{hr}"].font = Font(bold=True, color="FFFFFF", size=11)
        ws.append([desc])
        ws[f"A{ws.max_row}"].font = Font(italic=True, color="595959")
        ws[f"A{ws.max_row}"].alignment = wrap
        ws.append(["Member", "WRA #", "Territory", "Month", "Amount ($)",
                   "What happened"])
        hdr = ws.max_row
        for col in "ABCDEF":
            c = ws[f"{col}{hdr}"]
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", start_color="D9D9D9")
        for r in rows:
            if isinstance(r, dict):
                cells = [", ".join(map(str, v))
                         if isinstance(v, (list, tuple, set)) else v
                         for v in _flag_cells(family, r, names or {})]
                ws.append(cells)
            else:
                ws.append(["", "", "", "", "", str(r)])
            ws[f"F{ws.max_row}"].alignment = wrap
        ws.append([])

    for col, width in (("A", 42), ("B", 10), ("C", 13), ("D", 7),
                       ("E", 11), ("F", 95)):
        ws.column_dimensions[col].width = width


def build_metric_reference(wb) -> None:
    """Rewrite 'Ref - Metrics' from the enforced metric registry (8/6:
    the template's static master list had gone stale — missing every
    metric added since July). Generated per build = can never drift from
    the code again. Plain words, Suzanne-first."""
    from reports.membership_performance_tracker.metric_registry import REGISTRY
    SRC = {"slx-live": "computed from the CRM pull",
           "crystal-export": "from the archived Crystal exports",
           "admin": "entered in Admin Inputs on SharePoint",
           "derived": "calculated from other lines",
           "photo": "a point-in-time roster photo"}
    name = "Ref - Metrics"
    if name in wb.sheetnames:
        del wb[name]
    ws = wb.create_sheet(name)
    ws.append(["Metric", "Where it comes from", "What it means"])
    for c in ws[1]:
        c.font = c.font.copy(bold=True)
    for metric, e in sorted(REGISTRY.items()):
        ws.append([metric, SRC.get(e["source"], e["source"]), e["card"]])
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 34
    ws.column_dimensions["C"].width = 110
