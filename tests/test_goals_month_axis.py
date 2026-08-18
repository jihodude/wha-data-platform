"""
test_goals_month_axis.py — Sales/Member Goals must be parsed BY HEADER NAME,
not by position.

Found 2026-07-14: the live admin_inputs.xlsx still carries SEP-FIRST headers on
the goals sheets (only the Benefit Reviews sheet was migrated in the 6/28 fix),
while the parser assumed Oct-first positions — so every goal (and every
"% to Goal") rendered ONE MONTH LATE (SW June showed May's goal). The June
column of the admin file matches Jen's handmade sheet exactly, so the source is
right; only the axis mapping was wrong.
"""
import openpyxl

from src.parsers.admin_inputs import _parse_territory_month_grid


def _sheet(header_months, sw_values):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=4, column=1, value="Territory")
    for i, m in enumerate(header_months):
        ws.cell(row=4, column=2 + i, value=m)
    ws.cell(row=5, column=1, value="Southwest")
    for i, v in enumerate(sw_values):
        ws.cell(row=5, column=2 + i, value=v)
    return ws


def test_sep_first_legacy_sheet_parses_by_header():
    # the LIVE file's layout: Sep first (legacy generator), values from the real SW row
    header = ["Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"]
    values = [3205, 3205, 3105, 2400, 2600, 2700, 3205, 2025, 3205, 3205, 2403.75, 2403.75]
    got = _parse_territory_month_grid(_sheet(header, values))["Southwest"]
    assert got["Jan"] == 2600, "Jan must be the value under the Jan header (was showing Dec's 2400)"
    assert got["Jun"] == 3205 and got["Apr"] == 2025 and got["Sep"] == 3205


def test_oct_first_sheet_still_parses():
    header = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"]
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    got = _parse_territory_month_grid(_sheet(header, values))["Southwest"]
    assert got["Oct"] == 1 and got["Jan"] == 4 and got["Sep"] == 12
