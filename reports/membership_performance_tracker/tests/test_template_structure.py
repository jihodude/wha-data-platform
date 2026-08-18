"""Structural checks that keep Excel from repairing the workbook on open.

Both defects here shipped to users as the same message —
"Removed Records: Cell information from /xl/worksheets/sheetN.xml part" — and
neither is visible from Python: openpyxl reads and writes both happily.

1. Overlapping <col> ranges (shipped 2026-08-05 to 08-13). A template edit
   widened the month columns by adding per-column entries but left the
   quarter-group entry spanning the whole quarter, so two entries claimed the
   same column.

2. <row> records past row 1,048,576 (shipped 2026-08-12 to 08-13).
   add_new_bobs_row.py shifted every row dimension down by one, pushing the
   sheets' trailing empty formatting record one row past the end of the
   spreadsheet.

Any script that inserts rows or touches column widths must leave both clean.
`scripts/fix_overlapping_cols.py` and `scripts/fix_row_overflow.py` repair a
workbook that isn't.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[1] / "template.xlsx"
SHEET_PART = re.compile(r"^xl/worksheets/sheet\d+\.xml$")
COL_TAG = re.compile(r"<col\s[^>/]*/?>")


def _col_ranges(xml: str) -> list[tuple[int, int]]:
    spans = []
    for tag in COL_TAG.findall(xml):
        lo = re.search(r'min="(\d+)"', tag)
        hi = re.search(r'max="(\d+)"', tag)
        if lo and hi:
            spans.append((int(lo.group(1)), int(hi.group(1))))
    return sorted(spans)


def _overlaps(spans: list[tuple[int, int]]) -> list[tuple]:
    return [
        (spans[i], spans[i + 1])
        for i in range(len(spans) - 1)
        if spans[i][1] >= spans[i + 1][0]
    ]


@pytest.mark.skipif(not TEMPLATE.exists(), reason="template.xlsx not present")
def test_template_column_ranges_are_disjoint():
    offenders = {}
    with zipfile.ZipFile(TEMPLATE) as z:
        for name in z.namelist():
            if not SHEET_PART.match(name):
                continue
            bad = _overlaps(_col_ranges(z.read(name).decode("utf8")))
            if bad:
                offenders[name] = bad
    assert not offenders, (
        "overlapping <col> ranges will make Excel repair the workbook on open: "
        f"{offenders} — run scripts/fix_overlapping_cols.py on the template"
    )


EXCEL_MAX_ROW = 1_048_576
ROW_INDEX = re.compile(r'<row [^>]*?r="(\d+)"')


@pytest.mark.skipif(not TEMPLATE.exists(), reason="template.xlsx not present")
def test_no_rows_past_the_last_row_of_a_worksheet():
    offenders = {}
    with zipfile.ZipFile(TEMPLATE) as z:
        for name in z.namelist():
            if not SHEET_PART.match(name):
                continue
            bad = [
                int(r)
                for r in ROW_INDEX.findall(z.read(name).decode("utf8"))
                if int(r) > EXCEL_MAX_ROW
            ]
            if bad:
                offenders[name] = bad
    assert not offenders, (
        f"rows past {EXCEL_MAX_ROW} are not valid and make Excel repair the "
        f"workbook on open: {offenders} — run scripts/fix_row_overflow.py. "
        "A row-inserting script most likely shifted a trailing formatting "
        "record off the end of the sheet."
    )
