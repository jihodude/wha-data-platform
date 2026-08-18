"""
retention_detail — Member collections / unpaid-dues report.

TEMPLATE FOR NEW REPORTS — copy this folder, rename, modify.
This is the reference implementation of a WHA sub-report:

  data.py   — pure transforms (testable offline) + thin SLX collector on top
  writer.py — openpyxl single-sheet xlsx writer with formatting
  runner.py — CLI args → collect_drilldown() → write_drilldown() → SP publish

When building a new report (dues_analysis, commissions, etc.):
  1. cp -r reports/retention_detail reports/<new_report>
  2. Rename the package in __init__.py, data.py, writer.py, runner.py
  3. Replace collect_drilldown() with the new SLX queries
  4. Replace build_member_rows() / summarize_territory() with new transforms
  5. Rework write_drilldown() columns + section headers in writer.py
  6. Keep the TDD pattern: pure transforms tested in tests/test_data.py first,
     live collector only wired in runner.py

The split between pure transforms and the SLX collector is intentional —
tests run fast (no SLX, no network) while the live path is a thin wrapper.
"""
