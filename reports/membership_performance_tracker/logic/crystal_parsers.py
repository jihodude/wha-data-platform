"""crystal_parsers.py — turn archived Crystal exports into typed rows.

Under the pivot these parsers TRANSCRIBE; they do not compute. Each one:

  1. reads the export's own printed total out of its header
     ("264 Records representing $269,277.00 in dues income."),
  2. parses the detail rows,
  3. RAISES if the two disagree.

That gate is the whole quality story. Crystal layouts drift when someone edits
a report — a column moves, a group is added — and a parser that silently reads
the wrong column produces a plausible, wrong number. Reconciling to the
report's own arithmetic makes drift impossible to miss.

FISCAL-YEAR SCOPING — read before touching anything here. Every scheduled
report's parameter range runs to 12/31/2030, so exports ACCUMULATE. From
2026-10-01 the same daily file carries FY25-26 and FY26-27 rows together.
Reports fall into two groups:

  * ROW-DATED (New Member Sales via enroll date, Dropped Allied via status
    date): scope with `scope_to_fy()` — the row says which year it belongs to.
  * NOT ROW-DATED (Dropped Members - Hospitality, Dropped Members By Type):
    the file carries no date per row, so the ONLY scope is the report's
    StatusDate parameter. Two consequences, both live in the SOP:
      - within a fiscal year this is fine (the parameter starts at the FY
        boundary, so the newest export contains only this FY);
      - at rollover the parameter must be moved to the new FY start, and the
        outgoing year's final export is what freezes that year's drops.

Parsing keeps the gate and the scoping separate on purpose: the gate checks
the WHOLE file against the whole printed total, and scoping happens after.
Filtering first would make the gate unfalsifiable.
"""
import re
import warnings
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Sequence

import xlrd

# Crystal territory label → our canonical name. Crystal is inconsistent about
# the Spokane label (with and without the slash), so both spellings map.
TERRITORY = {
    "EastKing Territory": "EastKing", "SouthKing Territory": "SouthKing",
    "NorthKing Territory": "NorthKing", "Pierce Territory": "Pierce",
    "Snohomish Territory": "Snohomish", "Spokane/NE Territory": "Spokane/NE",
    "SpokaneNE Territory": "Spokane/NE",
    "Southwest Territory": "Southwest", "TKP Territory": "TKP",
    "Southeast Territory": "Southeast", "NorthCentral Territory": "NorthCentral",
    "EKing Open Territory": "EastKing",
    # Non-territory buckets Crystal reports alongside the real ones. Named
    # explicitly so they cannot be mistaken for unknowns.
    "Retro Coordinator": "Retro Coordinator",
    "Essential Membership": "Essential Membership",
    # Crystal's label for the report's Majors/NRA territory column.
    "NRA Paid Member": "Majors/NRA",
}


def canonical_territory(label: str) -> str:
    """Map a Crystal territory label, warning loudly on anything unknown.

    A silently unmapped label becomes its own pseudo-territory, quietly
    splitting a real territory's numbers in two — the same class of failure as
    an unclassified drop reason. Closed vocabulary, loud unknowns.
    """
    text = _text(label)
    if not text:
        return ""
    if text not in TERRITORY:
        warnings.warn(
            f"[crystal] UNRECOGNIZED territory label {text!r} — passed through unmapped. "
            f"Add it to crystal_parsers.TERRITORY.")
        return text
    return TERRITORY[text]

# Excel's serial-date epoch. 1899-12-30 (not 12-31) absorbs the deliberate
# 1900-leap-year bug Excel inherited from Lotus.
_EPOCH = date(1899, 12, 30)

# "264 Records representing $269,277.00 in dues income." — the report's own
# arithmetic, and therefore the gate.
_TOTAL_RE = re.compile(
    r"([\d,]+)\s+Records?\s+representing\s+\$?\s*([\d,]+(?:\.\d+)?)", re.I)
# "197 members joined from ..." — New Member Sales states a count only.
_JOINED_RE = re.compile(r"([\d,]+)\s+members?\s+joined", re.I)

_STATUS_REASON_RE = re.compile(r"Status Reason:\s*(.*)", re.I)


class ReportMismatch(ValueError):
    """The parsed rows do not reconcile to the report's own printed total."""


@dataclass(frozen=True)
class MemberSale:
    mid: str
    name: str
    territory: str
    rep: str
    billed: float
    paid: float
    enroll_date: Optional[date]
    bill_month: Optional[int]
    reinstate_date: Optional[date]


@dataclass(frozen=True)
class DropRow:
    mid: str
    name: str
    territory: str
    dues: float
    bill_month: Optional[int]
    status_reason: str
    business_type: str = ""
    status_date: Optional[date] = None
    # accounts.Status — the group level ABOVE the reason. Decides whether the
    # row is a membership loss at all (Jen 2026-07-30: "RRO is not a dropped").
    status: str = ""


def serial_to_date(value) -> Optional[date]:
    """Excel serial → date. Accepts the float Crystal writes, or a real date."""
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return _EPOCH + timedelta(days=int(float(value)))
    except (TypeError, ValueError):
        return None


def _num(value) -> float:
    """Crystal writes numbers as floats OR as comma-formatted strings."""
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except ValueError:
        return 0.0


def _int_or_none(value) -> Optional[int]:
    n = _num(value)
    return int(n) if n else None


def _text(value) -> str:
    return str(value).strip() if value not in (None, "") else ""


def sheet_from_bytes(data: bytes):
    """First worksheet of an archived export."""
    return xlrd.open_workbook(file_contents=data).sheet_by_index(0)


def printed_totals(sheet, max_rows: int = 8):
    """(record_count, dollar_total) as the report itself prints them.

    Returns (None, None) when the header states neither — the caller decides
    whether that is acceptable for its report.
    """
    for i in range(min(sheet.nrows, max_rows)):
        for cell in sheet.row_values(i):
            text = _text(cell)
            if not text:
                continue
            m = _TOTAL_RE.search(text)
            if m:
                return int(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
            m = _JOINED_RE.search(text)
            if m:
                return int(m.group(1).replace(",", "")), None
    return None, None


def _check(parsed_count: int, parsed_dollars: float, sheet, label: str,
           check_dollars: bool = True) -> None:
    want_count, want_dollars = printed_totals(sheet)
    if want_count is None:
        raise ReportMismatch(
            f"{label}: the export states no record total in its header. Either the "
            f"layout changed or this is not the expected report — refusing to parse "
            f"a file we cannot check.")
    if parsed_count != want_count:
        raise ReportMismatch(
            f"{label}: parsed {parsed_count} rows but the report prints {want_count}. "
            f"The layout has drifted (a column or grouping moved) — fix the parser "
            f"rather than trusting these numbers.")
    if check_dollars and want_dollars is not None and abs(parsed_dollars - want_dollars) > 0.5:
        raise ReportMismatch(
            f"{label}: parsed ${parsed_dollars:,.2f} but the report prints "
            f"${want_dollars:,.2f}. Wrong dollar column, or rows are being "
            f"double-counted.")


# ---------------------------------------------------------------------------
# New Member Sales — ROW-DATED (enroll date)
# ---------------------------------------------------------------------------
# Column map, verified against the 2026-07-26 export. Crystal's header labels
# sit one column left of their data in places, so these are the DATA columns.
NMS = dict(name=0, billed=7, paid=11, enroll=12, bm=14, reinstate=16,
           territory=19, rep=21, mid=25)


def parse_new_member_sales(data: bytes) -> List[MemberSale]:
    sheet = sheet_from_bytes(data)
    rows: List[MemberSale] = []
    for i in range(sheet.nrows):
        row = sheet.row_values(i)
        if len(row) <= NMS["mid"]:
            continue
        mid = _text(row[NMS["mid"]])
        if not re.fullmatch(r"0\d{6}", mid):
            continue                      # not a member detail row
        rows.append(MemberSale(
            mid=mid,
            name=_text(row[NMS["name"]]),
            territory=canonical_territory(row[NMS["territory"]]),
            rep=_text(row[NMS["rep"]]),
            billed=_num(row[NMS["billed"]]),
            paid=_num(row[NMS["paid"]]),
            enroll_date=serial_to_date(row[NMS["enroll"]]),
            bill_month=_int_or_none(row[NMS["bm"]]),
            reinstate_date=serial_to_date(row[NMS["reinstate"]]),
        ))
    _check(len(rows), sum(r.paid for r in rows), sheet, "New Member Sales",
           check_dollars=False)          # header states a count only
    return rows


# ---------------------------------------------------------------------------
# Dropped Members - Hospitality — NOT row-dated; grouped by Status Reason
# ---------------------------------------------------------------------------
HOSP = dict(name=1, mid=4, city=7, business_type=9, territory=12, dues=14, bm=17)


# The account statuses the export groups by, ABOVE the Status Reason level.
# These are accounts.Status values, verified live 2026-07-29; the label sits in
# the name column with a "N Records representing…" note beside it.
DROP_STATUS_GROUPS = ("Inactive", "Closed", "RRO LNI Active", "RRO")


def parse_drops_hospitality(data: bytes) -> List[DropRow]:
    """Detail rows carrying the Status group AND Status Reason they sit under.

    Two header levels, both arriving as rows rather than columns:
      · the STATUS group (Inactive / Closed / RRO / RRO LNI Active) — this is
        accounts.Status, and it decides whether the row is a membership loss
        at all (Jen 2026-07-30: "RRO is not a dropped");
      · the Status Reason — the report's own 19-value drop vocabulary.
    """
    sheet = sheet_from_bytes(data)
    rows: List[DropRow] = []
    reason = ""
    status = ""
    for i in range(sheet.nrows):
        row = sheet.row_values(i)
        name_cell = _text(row[HOSP["name"]]) if len(row) > HOSP["name"] else ""
        if name_cell in DROP_STATUS_GROUPS:
            status = name_cell
            reason = ""          # a new group resets the reason context
            continue
        for cell in row:
            m = _STATUS_REASON_RE.match(_text(cell))
            if m:
                reason = m.group(1).strip()
                break
        if len(row) <= HOSP["bm"]:
            continue
        mid = _text(row[HOSP["mid"]])
        if not re.fullmatch(r"0\d{6}", mid):
            continue
        rows.append(DropRow(
            mid=mid,
            name=_text(row[HOSP["name"]]),
            territory=canonical_territory(row[HOSP["territory"]]),
            dues=_num(row[HOSP["dues"]]),
            bill_month=_int_or_none(row[HOSP["bm"]]),
            status_reason=reason,
            business_type=_text(row[HOSP["business_type"]]),
            status=status,
        ))
    _check(len(rows), sum(r.dues for r in rows), sheet, "Dropped Members - Hospitality")
    return rows


# ---------------------------------------------------------------------------
# Fiscal-year scoping (WHA FY = Oct 1 → Sep 30)
# ---------------------------------------------------------------------------
def fy_bounds(fy_start_year: int):
    return date(fy_start_year, 10, 1), date(fy_start_year + 1, 9, 30)


def scope_to_fy(rows: Sequence, fy_start_year: int, attr: str) -> List:
    """Rows whose date field falls inside the fiscal year.

    Only for ROW-DATED reports. Rows with no date are dropped: an undated row
    cannot be proven to belong to this year, and silently keeping it is how
    two fiscal years get summed into one report at rollover.
    """
    start, end = fy_bounds(fy_start_year)
    out = []
    for r in rows:
        d = getattr(r, attr, None)
        if d and start <= d <= end:
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Adjusted Retention — SNAPSHOT (live billing state; freeze per period)
# ---------------------------------------------------------------------------
RET = dict(mid=2, name=5, territory=11, billed=16, paid=22, balance=26, bm=29, subtype=32)


@dataclass(frozen=True)
class RetentionRow:
    mid: str
    name: str
    territory: str
    billed: float
    paid: float
    balance: float
    bill_month: Optional[int]
    subtype: str


def parse_retention(data: bytes) -> List[RetentionRow]:
    """Member-level billing state per bill month.

    This report prints NO header total, so the gate is the per-row identity it
    does print: billed = paid + balance. Reading a shifted column breaks that
    arithmetic on the very first row, which is exactly the drift we need to
    catch. Retained = paid > 0 (Jennifer's convention, ratified: a partial
    payer stayed, they just could not pay in full).
    """
    sheet = sheet_from_bytes(data)
    rows: List[RetentionRow] = []
    broken = 0
    for i in range(sheet.nrows):
        row = sheet.row_values(i)
        if len(row) <= RET["subtype"]:
            continue
        mid = _text(row[RET["mid"]])
        if not re.fullmatch(r"0\d{6}", mid):
            continue
        billed, paid, balance = (_num(row[RET["billed"]]), _num(row[RET["paid"]]),
                                 _num(row[RET["balance"]]))
        if abs(billed - (paid + balance)) > 0.5:
            broken += 1
        rows.append(RetentionRow(
            mid=mid, name=_text(row[RET["name"]]),
            territory=canonical_territory(row[RET["territory"]]),
            billed=billed, paid=paid, balance=balance,
            bill_month=_int_or_none(row[RET["bm"]]),
            subtype=_text(row[RET["subtype"]]),
        ))
    if not rows:
        raise ReportMismatch("Adjusted Retention: no member rows found — layout changed.")
    if broken:
        raise ReportMismatch(
            f"Adjusted Retention: {broken} of {len(rows)} rows fail the report's own "
            f"billed = paid + balance identity. The dollar columns have moved.")
    return rows


# ---------------------------------------------------------------------------
# Dropped Members By Type — header total; grouped by BUSINESS type
# ---------------------------------------------------------------------------
BYTYPE = dict(name=4, mid=8, city=11, dues=13, bm=16)


def parse_drops_by_type(data: bytes) -> List[DropRow]:
    """Same drop universe as the hospitality report, cut by business type.

    'Type' here means Catering / Corporate / Hotel / Individual / Recreational
    / Restaurant — NOT the drop reason. (Verified 2026-07-27: this report's 163
    rows are the 157 non-Retro hospitality records plus 6 Retro Coordinator
    ones — one universe, a different territory scope.)
    """
    sheet = sheet_from_bytes(data)
    rows: List[DropRow] = []
    for i in range(sheet.nrows):
        row = sheet.row_values(i)
        if len(row) <= BYTYPE["bm"]:
            continue
        mid = _text(row[BYTYPE["mid"]])
        if not re.fullmatch(r"0\d{6}", mid):
            continue
        rows.append(DropRow(
            mid=mid, name=_text(row[BYTYPE["name"]]),
            territory="", dues=_num(row[BYTYPE["dues"]]),
            bill_month=_int_or_none(row[BYTYPE["bm"]]), status_reason="",
        ))
    _check(len(rows), sum(r.dues for r in rows), sheet, "Dropped Members By Type")
    return rows


# ---------------------------------------------------------------------------
# Dropped Allied — ROW-DATED (status date); grouped territory → Status Reason
# ---------------------------------------------------------------------------
ALLIED = dict(name=3, city=11, member_type=12, subtype=15, billed=19, bm=21,
              status_date=23, enrolled=25)


def parse_drops_allied(data: bytes) -> List[DropRow]:
    """Allied drops. Carries a real Status Date, so these ARE row-datable.

    No header total in this export; the gate is that every row must land under
    a territory and a status reason. A layout shift breaks the grouping walk
    and leaves rows unattributed, which this catches.
    """
    sheet = sheet_from_bytes(data)
    rows: List[DropRow] = []
    territory, reason, status = "", "", ""
    for i in range(sheet.nrows):
        row = sheet.row_values(i)
        head = _text(row[0]) if row else ""
        if head in TERRITORY:
            territory = canonical_territory(head)
            status = ""
        # The status group (accounts.Status) sits in its own row inside each
        # territory block — same level the hospitality export carries.
        for cell in row:
            if _text(cell) in DROP_STATUS_GROUPS:
                status = _text(cell)
                break
        for cell in row:
            m = _STATUS_REASON_RE.match(_text(cell))
            if m:
                reason = m.group(1).strip()
                break
        if len(row) <= ALLIED["enrolled"]:
            continue
        name = _text(row[ALLIED["name"]])
        billed = _num(row[ALLIED["billed"]])
        sdate = serial_to_date(row[ALLIED["status_date"]])
        if not name or sdate is None:
            continue
        rows.append(DropRow(
            mid="", name=name, territory=territory, dues=billed,
            bill_month=_int_or_none(row[ALLIED["bm"]]), status_reason=reason,
            business_type=_text(row[ALLIED["member_type"]]), status_date=sdate,
            status=status,
        ))
    if not rows:
        raise ReportMismatch("Dropped Allied: no member rows found — layout changed.")
    orphans = [r.name for r in rows if not r.territory or not r.status_reason]
    if orphans and len(orphans) == len(rows):
        # every row orphaned = the layout truly changed; refuse loudly
        raise ReportMismatch(
            f"Dropped Allied: ALL {len(orphans)} row(s) sit under no territory or "
            f"status-reason group (e.g. {orphans[:3]}) — the group headers moved.")
    # 8/10: a FEW orphans are house accounts the export prints outside every
    # group (Adesso/GNSA/TipHaus). They can never land in a territory column,
    # so they ride through for the feed to FLAG — never to count, never to
    # kill the whole overlay.
    return rows


# ---------------------------------------------------------------------------
# Billables — SNAPSHOT; grouped BM → territory → category
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BillableCell:
    bill_month: int
    territory: str
    category: str
    count: float
    dollars: float


def parse_billables(data: bytes) -> List[BillableCell]:
    """Current billable members by bill month, territory and business category.

    The categories are Crystal's taxonomy (Food Service, Hotel, Corporate,
    Allieds, Individual, NonProfits, Others) — NOT our Target/Non-Target split.
    Gate: the category rows must add up to the territory subtotal the report
    prints for itself, both count and dollars.
    """
    sheet = sheet_from_bytes(data)
    cells: List[BillableCell] = []
    bm: Optional[int] = None
    territory = ""
    printed: Optional[tuple] = None      # the CURRENT territory's own subtotal
    pending: List[BillableCell] = []
    mismatches: List[str] = []

    def settle() -> None:
        """Reconcile the categories collected so far against their territory.

        The territory row is a HEADER carrying its own totals, so a block is
        only complete when the NEXT territory (or the end of file) arrives —
        settling on sight would check each territory against the next one's
        numbers.
        """
        if not pending or printed is None:
            pending.clear()
            return
        want_c, want_d = printed
        got_c, got_d = sum(p.count for p in pending), sum(p.dollars for p in pending)
        if abs(got_c - want_c) > 0.5 or abs(got_d - want_d) > 0.5:
            mismatches.append(
                f"BM{pending[0].bill_month} {pending[0].territory}: categories sum to "
                f"{got_c:g}/${got_d:,.0f} but the report prints {want_c:g}/${want_d:,.0f}")
        cells.extend(pending)
        pending.clear()

    for i in range(sheet.nrows):
        row = sheet.row_values(i)
        if len(row) < 19:
            continue
        head = _text(row[0])
        b, bm_total = _num(row[1]), _num(row[14])
        if not head and 1 <= b <= 14 and bm_total:
            settle()
            bm, printed = int(b), None       # BM header row
            continue
        # A group boundary is any LABELLED row carrying subtotals — not just a
        # recognised territory. Crystal also groups by non-territory buckets
        # (e.g. "EF School"), and treating those as ordinary rows folds their
        # members into whichever territory came before.
        if head and (_num(row[7]) or _num(row[12])):
            settle()
            territory = canonical_territory(head) if head in TERRITORY else head
            printed = (_num(row[7]), _num(row[12]))
            continue
        category = _text(row[2])
        if bm is not None and territory and category:
            pending.append(BillableCell(bm, territory, category,
                                        _num(row[11]), _num(row[18])))
    settle()

    if not cells:
        raise ReportMismatch("Billables: no category rows found — layout changed.")
    if mismatches:
        raise ReportMismatch(
            "Billables: the report's own subtotals do not reconcile — "
            + "; ".join(mismatches[:3]))
    return cells


# ---------------------------------------------------------------------------
# Penetration (restaurant / lodging) — SNAPSHOT; grouped territory → status
# ---------------------------------------------------------------------------
PEN_COLS = {
    "restaurant": dict(name=0, size=10, status=14, account=17),
    "lodging":    dict(name=0, size=9,  status=12, account=15),
}


@dataclass(frozen=True)
class PenetrationRow:
    account_id: str
    name: str
    territory: str
    size_band: str
    status: str


def parse_penetration(data: bytes, segment: str) -> List[PenetrationRow]:
    """Every location in the market with its size band and member status.

    Penetration = Active / (Active + Inactive), so both statuses are real data.
    Gate: our per-(territory, status) counts must equal the subtotals the
    report prints under each status heading.
    """
    if segment not in PEN_COLS:
        raise ValueError(f"segment must be one of {sorted(PEN_COLS)}")
    cols = PEN_COLS[segment]
    sheet = sheet_from_bytes(data)
    rows: List[PenetrationRow] = []
    territory, status = "", ""
    printed: dict = {}

    for i in range(sheet.nrows):
        row = sheet.row_values(i)
        head = _text(row[0]) if row else ""
        if head in TERRITORY:
            territory = canonical_territory(head)
            continue
        if head in ("Active", "Inactive"):
            status = head
            subtotal = next((_num(v) for v in row[1:] if _num(v)), 0.0)
            if subtotal:
                printed[(territory, status)] = subtotal
            continue
        if len(row) <= cols["account"]:
            continue
        account = _text(row[cols["account"]])
        if len(account) < 8:
            continue
        rows.append(PenetrationRow(
            account_id=account, name=_text(row[cols["name"]]),
            territory=territory, size_band=_text(row[cols["size"]]),
            status=_text(row[cols["status"]]) or status,
        ))

    if not rows:
        raise ReportMismatch(f"Penetration ({segment}): no location rows — layout changed.")
    bad = []
    for (terr, stat), want in printed.items():
        got = sum(1 for r in rows if r.territory == terr and r.status == stat)
        if abs(got - want) > 0.5:
            bad.append(f"{terr}/{stat}: parsed {got}, report prints {want:g}")
    if bad:
        raise ReportMismatch(
            f"Penetration ({segment}): counts disagree with the report's own "
            f"subtotals — " + "; ".join(bad[:4]))
    return rows


# ---------------------------------------------------------------------------
# Penetration Lodging Count of Rooms — SNAPSHOT; AGGREGATE, not per-account
# ---------------------------------------------------------------------------
def parse_rooms(data: bytes) -> dict:
    """{territory: {'active': rooms, 'inactive': rooms}} — ROOM totals.

    Note this is aggregate: it counts ROOMS per territory, not rooms per hotel,
    so it cannot band individual properties for Target/Non-Target (that comes
    from the penetration Detail exports' size columns). Gate: active + inactive
    must equal the territory total the report prints.
    """
    sheet = sheet_from_bytes(data)
    out: dict = {}
    pending: dict = {}
    for i in range(sheet.nrows):
        row = sheet.row_values(i)
        label = next((_text(v) for v in row if _text(v)), "")
        value = next((_num(v) for v in row if _num(v)), 0.0)
        if label in ("Active", "Inactive"):
            pending[label.lower()] = value
            continue
        if label in TERRITORY and pending:
            territory = canonical_territory(label)
            total = max((_num(v) for v in row if _num(v)), default=0.0)
            got = pending.get("active", 0.0) + pending.get("inactive", 0.0)
            if abs(got - total) > 0.5:
                raise ReportMismatch(
                    f"Rooms ({territory}): active+inactive = {got:g} but the report "
                    f"prints {total:g}.")
            out[territory] = dict(pending)
            pending = {}
    if not out:
        raise ReportMismatch("Rooms: no territory blocks found — layout changed.")
    return out


# ---------------------------------------------------------------------------
# Active Billables By Ac And Fte — SNAPSHOT; the billables source of record
# ---------------------------------------------------------------------------
# Its statewide total was 2,143 on 2026-07-27 — exactly the hospitality
# billables figure Jennifer published in her June MPR, which identifies this as
# the report that number came from. Its FTE bands also hand us the
# Target/Non-Target split without any interpretation: Target = 10 FTE and up.
FTE_TARGET_BANDS = ("FTE 10 to 19", "FTE 20 to 49", "FTE 50 Plus")
FTE_NON_TARGET_BANDS = ("FTE 1 to 4", "FTE 5 to 9")
FTE_UNBANDED = "Others"


@dataclass(frozen=True)
class FteBilling:
    territory: str
    band: str
    count: float
    dollars: float


def parse_billables_fte(data: bytes) -> List[FteBilling]:
    """Active billables per territory, split into the CRM's own FTE bands.

    Gate: the bands must add up to the territory total the report prints for
    itself. 'Others' is members with no FTE recorded (107 statewide) and is
    kept as its own band rather than folded into Non-Target — those members
    are unbanded in the CRM's own view, and pretending otherwise would hide
    the one place our split and theirs genuinely differ.
    """
    sheet = sheet_from_bytes(data)
    rows: List[FteBilling] = []
    territory = ""
    printed: Optional[float] = None
    pending: List[FteBilling] = []
    problems: List[str] = []

    def settle() -> None:
        if pending and printed is not None:
            got = sum(p.count for p in pending)
            if abs(got - printed) > 0.5:
                problems.append(f"{pending[0].territory}: bands sum to {got:g}, "
                                f"report prints {printed:g}")
            rows.extend(pending)
        pending.clear()

    for i in range(sheet.nrows):
        row = sheet.row_values(i)
        if len(row) < 11:
            continue
        head, band = _text(row[0]), _text(row[2])
        count = row[7] if isinstance(row[7], (int, float)) else None
        if head and count:
            settle()
            territory = canonical_territory(head) if head in TERRITORY else head
            printed = float(count)
        elif band and count and territory:
            pending.append(FteBilling(territory, band, float(count), _num(row[10])))
    settle()

    if not rows:
        raise ReportMismatch("Active Billables by FTE: no band rows — layout changed.")
    if problems:
        raise ReportMismatch("Active Billables by FTE: territory totals do not "
                             "reconcile — " + "; ".join(problems[:3]))
    return rows


def fte_target_split(rows: Iterable) -> Dict[str, Dict[str, float]]:
    """{territory: {'target', 'non_target', 'unbanded'}} from the FTE bands."""
    out: Dict[str, Dict[str, float]] = {}
    for r in rows:
        cell = out.setdefault(r.territory, {"target": 0.0, "non_target": 0.0, "unbanded": 0.0})
        if r.band in FTE_TARGET_BANDS:
            cell["target"] += r.count
        elif r.band in FTE_NON_TARGET_BANDS:
            cell["non_target"] += r.count
        else:
            cell["unbanded"] += r.count
    return out
