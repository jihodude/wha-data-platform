"""Crystal parser gates: the report's own printed total must reconcile."""
from datetime import date

import pytest

from reports.membership_performance_tracker.logic import crystal_parsers as cp


class FakeSheet:
    """Stands in for an xlrd sheet so tests need no binary fixtures.

    (The real exports carry member names and dues — PII we deliberately keep
    out of the repo.)
    """

    def __init__(self, rows):
        self._rows = [list(r) for r in rows]
        self.nrows = len(self._rows)
        self.ncols = max((len(r) for r in self._rows), default=0)

    def row_values(self, i):
        return self._rows[i]


def _hosp_sheet(printed_count, printed_dollars, members):
    """A miniature Dropped Members - Hospitality sheet."""
    width = 18
    def blank():
        return [""] * width
    rows = [blank()]
    header = blank()
    header[2] = f" Month:  {printed_count} Records representing ${printed_dollars:,.2f} in dues income."
    rows.append(header)
    for reason, mid, name, terr, dues, bm in members:
        if reason:
            r = blank(); r[1] = f"Status Reason: {reason}"; rows.append(r)
        r = blank()
        r[cp.HOSP["name"]] = name
        r[cp.HOSP["mid"]] = mid
        r[cp.HOSP["territory"]] = terr
        r[cp.HOSP["dues"]] = dues
        r[cp.HOSP["bm"]] = bm
        rows.append(r)
    return FakeSheet(rows)


def test_serial_dates_use_the_1899_12_30_epoch():
    """Excel's epoch absorbs the 1900 leap-year bug; 12-31 would shift every date.

    46192.52 is Red Twig's enroll stamp in the 2026-07-26 export, and that row
    also carries Bill Month 6 — so June 2026 is the answer the file itself
    corroborates.
    """
    assert cp.serial_to_date(46192.52) == date(2026, 6, 19)
    assert cp.serial_to_date("") is None
    assert cp.serial_to_date(None) is None


def test_printed_totals_reads_both_header_dialects():
    drops = FakeSheet([["", "", " Month:  264 Records representing $269,277.00 in dues income."]])
    sales = FakeSheet([["", "197 members joined from 10/1/2025"]])

    assert cp.printed_totals(drops) == (264, 269277.00)
    assert cp.printed_totals(sales) == (197, None)


def test_drops_parser_carries_the_group_status_reason_onto_rows(monkeypatch):
    """The drop vocabulary arrives as a GROUP HEADER, not a column.

    Losing it would flatten 19 distinct reasons into one bucket, which is the
    whole 'why did we lose them' half of the report.
    """
    sheet = _hosp_sheet(2, 1600.0, [
        ("Out of Business", "0058246", "Ballard Burgers", "Pierce Territory", 1070.0, 4),
        ("Sold", "0050811", "Evergreen Restaurant", "TKP Territory", 530.0, 7),
    ])
    monkeypatch.setattr(cp, "sheet_from_bytes", lambda _d: sheet)

    rows = cp.parse_drops_hospitality(b"")

    assert [r.status_reason for r in rows] == ["Out of Business", "Sold"]
    assert [r.territory for r in rows] == ["Pierce", "TKP"]
    assert rows[0].dues == 1070.0


def test_parser_raises_when_row_count_disagrees_with_the_printed_total(monkeypatch):
    """A moved column reads fewer rows and would otherwise undercount silently."""
    sheet = _hosp_sheet(99, 1600.0, [
        ("Out of Business", "0058246", "Ballard Burgers", "Pierce Territory", 1070.0, 4),
        ("Sold", "0050811", "Evergreen Restaurant", "TKP Territory", 530.0, 7),
    ])
    monkeypatch.setattr(cp, "sheet_from_bytes", lambda _d: sheet)

    with pytest.raises(cp.ReportMismatch, match="parsed 2 rows but the report prints 99"):
        cp.parse_drops_hospitality(b"")


def test_parser_raises_when_dollars_disagree(monkeypatch):
    """Right row count, wrong dollar column — the subtler drift."""
    sheet = _hosp_sheet(2, 999999.0, [
        ("Out of Business", "0058246", "Ballard Burgers", "Pierce Territory", 1070.0, 4),
        ("Sold", "0050811", "Evergreen Restaurant", "TKP Territory", 530.0, 7),
    ])
    monkeypatch.setattr(cp, "sheet_from_bytes", lambda _d: sheet)

    with pytest.raises(cp.ReportMismatch, match="Wrong dollar column"):
        cp.parse_drops_hospitality(b"")


def test_parser_refuses_a_file_with_no_printed_total(monkeypatch):
    """No header total = we cannot check it = we do not trust it."""
    monkeypatch.setattr(cp, "sheet_from_bytes", lambda _d: FakeSheet([["some other report"]]))

    with pytest.raises(cp.ReportMismatch, match="states no record total"):
        cp.parse_drops_hospitality(b"")


def test_scope_to_fy_keeps_the_year_and_drops_undated_rows():
    """From 2026-10-01 one file holds two fiscal years — see module docstring.

    An undated row cannot be proven to belong to the year, and keeping it is
    exactly how a rollover silently sums FY25-26 into FY26-27.
    """
    def sale(d):
        return cp.MemberSale(mid="0000001", name="x", territory="Pierce", rep="",
                             billed=0, paid=0, enroll_date=d, bill_month=None,
                             reinstate_date=None)
    rows = [sale(date(2025, 10, 1)), sale(date(2026, 9, 30)),
            sale(date(2026, 10, 1)), sale(date(2025, 9, 30)), sale(None)]

    kept = cp.scope_to_fy(rows, 2025, "enroll_date")

    assert [r.enroll_date for r in kept] == [date(2025, 10, 1), date(2026, 9, 30)]


def test_unknown_territory_label_warns_instead_of_passing_quietly():
    """Crystal spells Spokane both ways; an unmapped label must not go quiet.

    A silently unmapped label becomes its own pseudo-territory and splits a
    real territory's numbers in two — invisible in the output.
    """
    assert cp.canonical_territory("SpokaneNE Territory") == "Spokane/NE"
    assert cp.canonical_territory("Spokane/NE Territory") == "Spokane/NE"

    with pytest.warns(UserWarning, match="UNRECOGNIZED territory"):
        assert cp.canonical_territory("Atlantis Territory") == "Atlantis Territory"


def _billables_sheet(blocks):
    """Miniature Billables sheet: BM header → group header(+subtotals) → categories."""
    width = 19
    def blank():
        return [""] * width
    rows = []
    for bm, groups in blocks:
        h = blank(); h[1] = bm; h[14] = 999999.0
        rows.append(h)
        for label, sub_count, sub_dollars, cats in groups:
            g = blank(); g[0] = label; g[7] = sub_count; g[12] = sub_dollars
            rows.append(g)
            for name, cnt, dol in cats:
                c = blank(); c[2] = name; c[11] = cnt; c[18] = dol
                rows.append(c)
    return FakeSheet(rows)


def test_billables_settles_each_group_against_its_own_subtotal(monkeypatch):
    """The group row is a HEADER carrying its own totals.

    Settling on sight would check each group against the NEXT group's numbers —
    an off-by-one that reconciles nothing while looking like it does.
    """
    sheet = _billables_sheet([(11, [
        ("EastKing Territory", 12, 16855.0, [("Food Service", 5, 5260.0),
                                             ("Corporate", 5, 10585.0),
                                             ("Allieds", 2, 1010.0)]),
        ("NorthCentral Territory", 7, 7400.0, [("Food Service", 7, 7400.0)]),
    ])])
    monkeypatch.setattr(cp, "sheet_from_bytes", lambda _d: sheet)

    cells = cp.parse_billables(b"")

    assert sum(c.count for c in cells if c.territory == "EastKing") == 12
    assert {c.territory for c in cells} == {"EastKing", "NorthCentral"}


def test_billables_treats_a_non_territory_group_as_its_own_bucket(monkeypatch):
    """Crystal also groups by non-territory buckets — the live one is 'EF School'.

    Treating such a row as ordinary data folds its members into whichever
    territory preceded it (EastKing read 21 members instead of 12).
    """
    sheet = _billables_sheet([(11, [
        ("EastKing Territory", 12, 16855.0, [("Food Service", 12, 16855.0)]),
        ("EF School", 9, 1395.0, [("Others", 9, 1395.0)]),
    ])])
    monkeypatch.setattr(cp, "sheet_from_bytes", lambda _d: sheet)

    cells = cp.parse_billables(b"")

    assert sum(c.count for c in cells if c.territory == "EastKing") == 12
    assert sum(c.count for c in cells if c.territory == "EF School") == 9


def test_billables_raises_when_categories_miss_their_subtotal(monkeypatch):
    sheet = _billables_sheet([(1, [
        ("Pierce Territory", 99, 99999.0, [("Hotel", 2, 1000.0)]),
    ])])
    monkeypatch.setattr(cp, "sheet_from_bytes", lambda _d: sheet)

    with pytest.raises(cp.ReportMismatch, match="categories sum to"):
        cp.parse_billables(b"")


def test_retention_gate_is_the_reports_own_billed_equals_paid_plus_balance(monkeypatch):
    """This export prints no header total, so its per-row arithmetic is the gate."""
    width = 33
    def member(mid, billed, paid, balance):
        r = [""] * width
        r[cp.RET["mid"]] = mid; r[cp.RET["name"]] = "X"
        r[cp.RET["territory"]] = "Pierce Territory"
        r[cp.RET["billed"]] = billed; r[cp.RET["paid"]] = paid
        r[cp.RET["balance"]] = balance; r[cp.RET["bm"]] = 5
        r[cp.RET["subtype"]] = "Restaurant, Full Service"
        return r

    good = FakeSheet([member("0000537", 1070.0, 500.0, 570.0)])
    monkeypatch.setattr(cp, "sheet_from_bytes", lambda _d: good)
    rows = cp.parse_retention(b"")
    assert rows[0].paid == 500.0 and rows[0].territory == "Pierce"

    bad = FakeSheet([member("0000537", 1070.0, 500.0, 999.0)])
    monkeypatch.setattr(cp, "sheet_from_bytes", lambda _d: bad)
    with pytest.raises(cp.ReportMismatch, match="billed = paid \\+ balance"):
        cp.parse_retention(b"")


def _fte_sheet(territories):
    """Miniature Active Billables by AC and FTE sheet."""
    width = 21
    def blank():
        return [""] * width
    rows = []
    for name, total, bands in territories:
        t = blank(); t[0] = name; t[7] = total; t[10] = total * 1000
        rows.append(t)
        for band, count in bands:
            b = blank(); b[2] = band; b[7] = count; b[10] = count * 1000
            rows.append(b)
    return FakeSheet(rows)


def test_fte_billables_splits_target_by_the_crms_own_bands(monkeypatch):
    """Target = 10 FTE and up, straight from the CRM's own banding.

    'Others' stays its own bucket rather than folding into Non-Target: those
    members are unbanded in the CRM's view too, and hiding that would mask the
    one place our split and theirs genuinely differ.
    """
    sheet = _fte_sheet([("EastKing Territory", 170, [
        ("FTE 1 to 4", 8), ("FTE 5 to 9", 20), ("FTE 10 to 19", 42),
        ("FTE 20 to 49", 44), ("FTE 50 Plus", 43), ("Others", 13)])])
    monkeypatch.setattr(cp, "sheet_from_bytes", lambda _d: sheet)

    split = cp.fte_target_split(cp.parse_billables_fte(b""))

    assert split["EastKing"] == {"target": 129.0, "non_target": 28.0, "unbanded": 13.0}


def test_fte_billables_raises_when_bands_miss_the_territory_total(monkeypatch):
    sheet = _fte_sheet([("Pierce Territory", 999, [("FTE 1 to 4", 8)])])
    monkeypatch.setattr(cp, "sheet_from_bytes", lambda _d: sheet)

    with pytest.raises(cp.ReportMismatch, match="bands sum to 8"):
        cp.parse_billables_fte(b"")


def _hosp_sheet_with_status_groups(printed_count, printed_dollars, groups):
    """A miniature sheet with the STATUS level above the reason level.

    Real layout (2026-07-26 export): the status group label sits in the NAME
    column with a 'N Records representing...' note beside it, then Status
    Reason sub-headers, then member rows.
    """
    width = 18
    def blank():
        return [""] * width
    rows = [blank()]
    header = blank()
    header[2] = f" Month:  {printed_count} Records representing ${printed_dollars:,.2f} in dues income."
    rows.append(header)
    for status, members in groups:
        g = blank()
        g[cp.HOSP["name"]] = status
        g[5] = " 9 Records representing 9,999.00in dues income."
        rows.append(g)
        for reason, mid, name, terr, dues, bm in members:
            if reason:
                r = blank(); r[cp.HOSP["name"]] = f"Status Reason: {reason}"; rows.append(r)
            r = blank()
            r[cp.HOSP["name"]] = name
            r[cp.HOSP["mid"]] = mid
            r[cp.HOSP["territory"]] = terr
            r[cp.HOSP["dues"]] = dues
            r[cp.HOSP["bm"]] = bm
            rows.append(r)
    return FakeSheet(rows)


def test_drops_parser_stamps_the_status_group_onto_rows(monkeypatch):
    """accounts.Status is the level ABOVE the reason, and it decides whether a
    row is a membership loss at all (Jen, 2026-07-30: "RRO is not a dropped").
    Every parse before 2026-07-29 skipped this level entirely.
    """
    sheet = _hosp_sheet_with_status_groups(3, 2130.0, [
        ("Inactive", [("No Answer", "0058246", "Ballard Burgers", "Pierce Territory", 1070.0, 4)]),
        ("RRO", [("Sold", "0050811", "Evergreen Restaurant", "TKP Territory", 530.0, 14)]),
        ("RRO LNI Active", [("Sold", "0056734", "Hilton Employer", "EKing Territory", 530.0, 14)]),
    ])
    monkeypatch.setattr(cp, "sheet_from_bytes", lambda _d: sheet)

    rows = cp.parse_drops_hospitality(b"")

    assert [r.status for r in rows] == ["Inactive", "RRO", "RRO LNI Active"]
    assert [r.status_reason for r in rows] == ["No Answer", "Sold", "Sold"]
