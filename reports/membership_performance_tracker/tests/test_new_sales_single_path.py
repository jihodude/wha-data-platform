"""New sales: the published number and its member list are one pass.

2026-08-18: the nightly published NorthKing Aug new-sales revenue as 2,924.00
while the member rows behind it summed to 4,678.50 — and the CRM's own New
Member Sales export agreed with the member rows to the penny (3,795.00 +
883.50). The loop wrote the cell and recorded the row as two separate acts,
and they drifted. The conservation gate refused every receipt in the artifact
over that one cell.

Same structural cure as drops (2026-08-14): the loop now produces only member
rows; `aggregate_new_sales` sums the published cells FROM those rows. These
tests pin the equivalence.
"""
from reports.membership_performance_tracker.logic.revenue import aggregate_new_sales
from reports.membership_performance_tracker.logic import receipts_render as rr

WINDOWS = [(m, None, None) for m in
           ("Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
            "Apr", "May", "Jun", "Jul", "Aug", "Sep")]


def zero_row():
    return {"total": 0.0, "target": 0.0, "non_target": 0.0, "unknown": 0.0,
            "bob": 0.0, "bob_target": 0.0, "bob_non_target": 0.0,
            "count_total": 0, "count_target": 0,
            "count_non_target": 0, "count_unknown": 0,
            "count_bob": 0, "comped_new": 0.0}


def row(terr, month, band, amount, counted=True, bob=0.0):
    return {"territory": terr, "month": month, "band": band,
            "amount": amount, "bob": bob, "ask": amount,
            "counted": counted, "first_pay": "2026-08-05"}


def test_the_cell_is_the_sum_of_its_member_rows():
    """The 8/18 shape, replayed: two Target members sold into NorthKing."""
    rows = [row("NorthKing", "Aug", "target", 3795.0),
            row("NorthKing", "Aug", "target", 883.5)]
    result = aggregate_new_sales(rows, {}, WINDOWS, zero_row)
    cell = result["NorthKing"]["Aug"]
    assert cell["target"] == 4678.5 and cell["total"] == 4678.5
    assert cell["count_total"] == 2 and cell["count_target"] == 2


def test_number_and_receipts_cannot_disagree():
    """The whole point: run the REAL conservation gate over rows rendered from
    the same objects the cells were summed from — zero errors, always."""
    rows = [row("NorthKing", "Aug", "target", 3795.0),
            row("NorthKing", "Aug", "target", 883.5),
            row("Snohomish", "Aug", "non_target", 730.0),
            row("Pierce", "Jul", "unknown", 510.0),          # folds NT
            row("EastKing", "Aug", "non_target", 505.0, bob=505.0)]
    result = aggregate_new_sales(rows, {}, WINDOWS, zero_row)

    # publish exactly as the engine does (unknown folds Non-Target)
    fields = {"revenue_target": {}, "revenue_non_target": {},
              "new_members_target": {}, "new_members_non_target": {},
              "revenue_bob_target": {}, "revenue_bob_non_target": {}}
    for terr, months in result.items():
        for m, b in months.items():
            fields["revenue_target"].setdefault(terr, {})[m] = b["target"]
            fields["revenue_non_target"].setdefault(terr, {})[m] = (
                b["non_target"] + b["unknown"])
            fields["new_members_target"].setdefault(terr, {})[m] = b["count_target"]
            fields["new_members_non_target"].setdefault(terr, {})[m] = (
                b["count_non_target"] + b["count_unknown"])
            fields["revenue_bob_target"].setdefault(terr, {})[m] = b["bob_target"]
            fields["revenue_bob_non_target"].setdefault(terr, {})[m] = b["bob_non_target"]

    # render exactly as the receipts renderer does
    raw = {"families": {"new_members": {
        f"A{i}|{r['month']}": r for i, r in enumerate(rows)}}}
    rendered = rr.render_new_members(raw, lambda a: a)
    assert rr.gate_new_members(rendered, fields) == [], \
        "cells summed from the rows must reconcile with rows rendered from them"


def test_double_processing_cannot_double_count():
    """If discovery ever visits one account twice, last write wins in BOTH the
    capture and the cells — because they are the same dict."""
    member_rows = {}
    member_rows["A1|Aug"] = row("NorthKing", "Aug", "target", 2040.5)
    member_rows["A1|Aug"] = row("NorthKing", "Aug", "target", 3795.0)
    result = aggregate_new_sales(member_rows.values(), {}, WINDOWS, zero_row)
    cell = result["NorthKing"]["Aug"]
    assert cell["target"] == 3795.0 and cell["count_total"] == 1


def test_comped_new_flag_dollars_survive_aggregation():
    """The comp-tripwire line is written into cells before aggregation; the
    aggregation must add into those cells, never replace them."""
    pre = {"Pierce": {m: zero_row() for m, _s, _e in WINDOWS}}
    pre["Pierce"]["Aug"]["comped_new"] = 730.0
    result = aggregate_new_sales([row("Pierce", "Aug", "target", 510.0)],
                                 pre, WINDOWS, zero_row)
    assert result["Pierce"]["Aug"]["comped_new"] == 730.0
    assert result["Pierce"]["Aug"]["target"] == 510.0
