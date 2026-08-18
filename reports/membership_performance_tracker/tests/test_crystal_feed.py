"""The Crystal feed: the two families Crystal owns, laid over SData's values."""
import json

import pytest

from reports.membership_performance_tracker.logic import crystal_feed as cf
from reports.membership_performance_tracker.logic import crystal_parsers as cp
from reports.membership_performance_tracker.logic import target as target_logic

T, NT, UNK = target_logic.TARGET, target_logic.NON_TARGET, target_logic.UNKNOWN


def _drop(name, territory, bm, dues, reason="Sold"):
    return cp.DropRow(mid="0000001", name=name, territory=territory, dues=dues,
                      bill_month=bm, status_reason=reason)


def _archive(tmp_path, period="2026-07", files=("billables_fte", "drops_hospitality")):
    """A period folder with a manifest naming the exports present."""
    folder = tmp_path / period
    folder.mkdir(parents=True)
    manifest = {}
    for key in files:
        name = f"{key}.xls"
        (folder / name).write_bytes(b"stub")
        manifest[key] = {"file_name": name, "run_date": "2026-07-27", "sha256": "abc"}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path


def test_billables_come_from_the_fte_report_with_size_less_members_in_non_target(monkeypatch, tmp_path):
    """Target = 10 FTE up. The CRM's unbanded 'Others' ride in Non-Target so the
    territory total matches what Jennifer publishes (2,143 statewide includes
    them; 2,036 without is below every month she ever reported)."""
    root = _archive(tmp_path)
    monkeypatch.setattr(cf.cp, "parse_billables_fte", lambda _b: object())
    monkeypatch.setattr(cf.cp, "fte_target_split",
                        lambda _r: {"EastKing": {"target": 129.0, "non_target": 28.0, "unbanded": 13.0}})
    monkeypatch.setattr(cf.cp, "parse_billables", lambda _b: [])

    fields = cf.feed_billables("2026-07", root)

    assert fields["hosp_bills_target"]["EastKing"]["Jul"] == 129.0
    assert fields["hosp_bills_non_target"]["EastKing"]["Jul"] == 41.0
    assert (fields["hosp_bills_target"]["EastKing"]["Jul"]
            + fields["hosp_bills_non_target"]["EastKing"]["Jul"]) == 170.0


def test_billables_write_only_the_snapshot_month():
    """A billables count describes the day it was run — it is not a year."""
    fields = cf._billables_fields({"TKP": {"target": 10.0, "non_target": 2.0, "unbanded": 0.0}},
                                  {}, "Jun")

    assert fields["hosp_bills_target"]["TKP"]["Jun"] == 10.0
    assert fields["hosp_bills_target"]["TKP"]["Jul"] == 0.0


def test_drops_land_on_the_bill_month_and_split_by_band(monkeypatch, tmp_path):
    """Drops file in their FLIP month (event axis, ratified 2026-07-31) —
    the dates here land A/B in April and C in July, and the split follows
    the band exactly as before."""
    from datetime import date as _d
    root = _archive(tmp_path)
    rows = [_drop("A", "Pierce", 4, 1070.0), _drop("B", "Pierce", 4, 510.0),
            _drop("C", "Pierce", 7, 730.0)]
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality", lambda _b: rows)
    band = lambda r: {"A": T, "B": T}.get(r.name, NT)
    when = {"A": _d(2026, 4, 10), "B": _d(2026, 4, 20), "C": _d(2026, 7, 5)}

    fields = cf.feed_drops("2026-07", root, band,
                           drop_date_of=lambda r: when[r.name],
                           today=_d(2026, 7, 31))

    assert fields["drops_target"]["Pierce"]["Apr"] == 2
    assert fields["drops_revenue_target"]["Pierce"]["Apr"] == 1580.0
    assert fields["drops_non_target"]["Pierce"]["Jul"] == 1


def test_drop_reasons_use_crystals_own_vocabulary(monkeypatch, tmp_path):
    """19 real status reasons replace the five buckets SData invented."""
    root = _archive(tmp_path)
    rows = [_drop("A", "Pierce", 4, 0, reason="Out of Business"),
            _drop("B", "Pierce", 4, 0, reason="Out of Business"),
            _drop("C", "TKP", 5, 0, reason="Non-Payment")]
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality", lambda _b: rows)
    from datetime import date as _d
    when = {"A": _d(2026, 4, 2), "B": _d(2026, 4, 9), "C": _d(2026, 5, 4)}

    fields = cf.feed_drops("2026-07", root, lambda _r: T,
                           drop_date_of=lambda r: when[r.name],
                           today=_d(2026, 7, 31))

    assert fields["drops_by_category"]["Out of Business"]["Pierce"]["Apr"] == 2
    assert fields["drops_by_category"]["Non-Payment"]["TKP"]["May"] == 1


def test_overlay_replaces_only_the_one_family_crystal_owns(monkeypatch, tmp_path):
    """SData keeps billables, new members, revenue, retention and penetration.

    Overwriting a family Crystal cannot answer for a past month is exactly the
    2026-07-27 failure (retention 0/10, revenue $0 for five months). Billables
    left the overlay on 2026-07-30 (Jiho: "sdata computes billables").
    """
    root = _archive(tmp_path)
    monkeypatch.setattr(cf, "feed_drops", lambda *a, **k: {"drops_target": {"TKP": {"Jul": 3}}})
    sdata = {"hosp_bills_target": {"TKP": {"Jul": 1}}, "drops_target": {"TKP": {"Jul": 1}},
             "revenue_target": {"TKP": {"Jul": 5000}}, "ret_paid_target": {"TKP": {"Jul": 12}}}

    merged, report = cf.overlay(dict(sdata), "2026-07", root, lambda _r: T)

    assert merged["drops_target"]["TKP"]["Jul"] == 3           # Crystal wins
    assert merged["hosp_bills_target"]["TKP"]["Jul"] == 1      # SData untouched (7/30)
    assert merged["revenue_target"]["TKP"]["Jul"] == 5000      # SData untouched
    assert merged["ret_paid_target"]["TKP"]["Jul"] == 12       # SData untouched
    assert report.applied == ["drops"]


def test_overlay_keeps_sdata_and_says_so_loudly_when_exports_are_missing(tmp_path):
    """A missing export must never look like a successful Crystal run.

    SData's values are valid — just not preferred — so the run continues, but
    the fallback is announced rather than inferred from a silent pass.
    """
    root = _archive(tmp_path, files=())     # manifest with no exports

    with pytest.warns(UserWarning, match="falling back to SData"):
        merged, report = cf.overlay({"drops_target": {"TKP": {"Jul": 1}}},
                                    "2026-07", root, lambda _r: T)

    assert merged["drops_target"]["TKP"]["Jul"] == 1
    assert report.applied == []
    assert "drops" in report.skipped
    assert "billables" not in report.skipped     # no longer Crystal's family


def test_drops_may_use_a_later_export_because_the_report_is_fy_windowed(monkeypatch, tmp_path):
    """A drops export covers the WHOLE fiscal year, so July's file serves June.

    Its StatusDate window starts at the FY boundary, so every row from October
    onward is in it and each row carries its own bill month. Billables cannot
    do this — a billables count describes the day it ran — which is why only
    drops gets the fallback.
    """
    root = _archive(tmp_path, period="2026-07", files=("drops_hospitality",))
    rows = [_drop("A", "Pierce", 6, 1070.0)]
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality", lambda _b: rows)

    from datetime import date as _d
    fields = cf.feed_drops("2026-06", root, lambda _r: T,      # asking for JUNE
                           drop_date_of=lambda r: _d(2026, 6, 12),
                           today=_d(2026, 7, 31))

    assert fields["drops_target"]["Pierce"]["Jun"] == 1


def test_billables_never_borrow_another_months_export(tmp_path):
    """A snapshot describes one day. Borrowing July's for June would be a lie.

    Since 2026-07-30 the overlay does not carry billables AT ALL (Jiho: "drop
    the crystal overlay, sdata computes billables") — so the stronger property
    now holds: an archived billables export, right month or wrong, changes
    nothing and is not even mentioned.
    """
    root = _archive(tmp_path, period="2026-07", files=("billables_fte",))

    with pytest.warns(UserWarning, match="falling back to SData"):
        _, report = cf.overlay({}, "2026-06", root, lambda _r: T)

    assert "billables" not in report.applied
    assert "billables" not in report.skipped     # not Crystal's family anymore
    assert "drops" in report.skipped             # genuinely absent export


def test_fy_windowed_fallback_never_crosses_a_fiscal_year(monkeypatch, tmp_path):
    """A later FY's export contains NONE of this FY's rows.

    The drops StatusDate window is moved to the new FY each October, so an
    FY26-27 export starts at 2026-10-01 and holds nothing from June 2026.
    Reaching for "the newest archive" would silently produce an empty grid for
    every historical month once the next year begins — a bug that would only
    appear in October and look like data loss.
    """
    _archive(tmp_path, period="2026-06", files=("drops_hospitality",))
    _archive(tmp_path, period="2026-11", files=("drops_hospitality",))   # next FY

    folder, manifest = cf._latest_in_same_fy("drops_hospitality", tmp_path, "2026-06")

    assert folder.name == "2026-06", "must not borrow the FY26-27 export"


def test_fy_windowed_fallback_uses_a_later_month_of_the_SAME_fiscal_year(tmp_path):
    """Within one FY the window is identical, so any of its exports serves."""
    _archive(tmp_path, period="2026-07", files=("drops_hospitality",))

    folder, manifest = cf._latest_in_same_fy("drops_hospitality", tmp_path, "2026-06")

    assert folder.name == "2026-07"


def test_a_snapshot_family_is_declared_and_never_borrows(tmp_path):
    """Semantics are declared per family, not decided per month."""
    assert cf.FAMILY_SEMANTICS["billables"] == cf.SNAPSHOT
    assert cf.FAMILY_SEMANTICS["drops"] == cf.FY_WINDOWED


def test_overlay_records_provenance_from_the_manifest_it_actually_used(monkeypatch, tmp_path):
    """The FY-windowed fallback reads a DIFFERENT period's manifest.

    Recording provenance from the requested period's manifest instead of the
    one actually read raises KeyError and takes the whole run down — which is
    exactly what happened on the first live June validation. The direct
    feed_drops test could not catch it, and the overlay test monkeypatched the
    feeds away, so nothing exercised fallback-plus-overlay together.
    """
    root = _archive(tmp_path, period="2026-07", files=("drops_hospitality",))
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality",
                        lambda _b: [_drop("A", "Pierce", 6, 1070.0)])

    merged, report = cf.overlay({}, "2026-06", root, lambda _r: T)

    assert report.applied == ["drops"]
    assert report.sources["drops"]["drops_hospitality"]["run_date"] == "2026-07-27"
    assert merged["drops_target"]["Pierce"]["Jul"] == 1   # dateless bm6 files at its July close


def _srow(status, bm, name="m", terr="Pierce", dues=100.0, reason="Sold"):
    return cp.DropRow(mid="0000009", name=name, territory=terr, dues=dues,
                      bill_month=bm, status_reason=reason, business_type="Restaurant",
                      status=status)


def test_rro_rows_are_never_counted_and_surface_as_fyi(monkeypatch, tmp_path):
    """Jen, 2026-07-30 (recorded): "RRO statuses I would not include in dropped
    member reports... They're not a dropped. RRO is not a dropped." The rows
    are on her export "just as FYI" — so they must reach the flag list and
    never the counts, in either band, in any month.
    """
    rows = [
        _srow("Inactive", 4, name="real one", dues=730.0),
        _srow("RRO", 6, name="fyi one", dues=8215.0),
        _srow("RRO LNI Active", 5, name="fyi two", dues=4944.0),
    ]
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality", lambda _b: rows)
    _archive(tmp_path, "2026-07", files=("drops_hospitality",))

    flags = {}
    fields = cf.feed_drops("2026-07", root=tmp_path, band=lambda r: "Target",
                           flags_out=flags)

    total = sum(v for g in ("drops_target", "drops_non_target")
                for terr in fields[g].values() for v in terr.values())
    dollars = sum(v for g in ("drops_revenue_target", "drops_revenue_non_target")
                  for terr in fields[g].values() for v in terr.values())
    assert total == 1, "only the Inactive row counts"
    assert dollars == 730.0, "RRO dues must never be valued"
    assert [f["name"] for f in flags["rro_fyi"]] == ["fyi one", "fyi two"]


def test_bill_month_14_moves_out_even_when_status_is_closed(monkeypatch, tmp_path):
    """Shannon's synthesis, Jen confirming, 2026-07-30: "if it's 14, it moves
    completely out of the calculation. If it's anything other than 14, then it
    is part of the calculation." Status does not rescue a 14.
    """
    rows = [
        _srow("Closed", 14, name="retro-territory closed", dues=2495.5),
        _srow("Closed", 3, name="ordinary closed", dues=355.0),
    ]
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality", lambda _b: rows)
    _archive(tmp_path, "2026-07", files=("drops_hospitality",))

    with pytest.warns(UserWarning, match="no usable bill month"):
        fields = cf.feed_drops("2026-07", root=tmp_path, band=lambda r: "Target")

    total = sum(v for terr in fields["drops_target"].values() for v in terr.values())
    assert total == 1


def test_overlay_no_longer_touches_billables(monkeypatch, tmp_path):
    """Jiho, 2026-07-30: "drop the crystal overlay, sdata computes billables"
    — reconciling against Crystal would assert it is more accurate than the
    computation. The overlay must leave every billables field exactly as the
    engine wrote it, even when a billables export is archived and parsable.
    """
    _archive(tmp_path, "2026-07", files=("billables_fte", "drops_hospitality"))
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality",
                        lambda _b: [_srow("Inactive", 4)])

    sentinel = {"EastKing": {"Jul": 999.0}}
    fields = {"hosp_bills_target": dict(sentinel),
              "hosp_bills_non_target": dict(sentinel),
              "allied_bills": dict(sentinel)}
    out, report = cf.overlay(fields, "2026-07", root=tmp_path, band=lambda r: "Target")

    assert out["hosp_bills_target"] == sentinel
    assert out["allied_bills"] == sentinel
    assert "billables" not in report.applied


def test_allied_drops_are_listed_but_never_counted(monkeypatch, tmp_path):
    """RULED 2026-08-14: allied leaves the drop COUNTS, stays fully visible.

    Follows the same day's retention ruling. A member who never counted as
    retained must not count against a TM on the way out — that asymmetry is
    worth money on a commission line. The Allied export is still parsed and
    every row still appears, under `allied_drops`, so the drop detail can show
    which losses were allied ("we'll see which one is an allied, which one is
    a hospitality member" — Steven).

    Supersedes the T/NT lock that merged them into the Non-Target grids.
    """
    hosp = [_srow("Inactive", 4, name="hosp real", dues=730.0)]
    allied = [
        cp.DropRow(mid="", name="Mautone", territory="EastKing", dues=505.0,
                   bill_month=1, status_reason="No Answer", status="Inactive"),
        cp.DropRow(mid="", name="allied rro", territory="EastKing", dues=100.0,
                   bill_month=1, status_reason="Sold", status="RRO"),
    ]
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality", lambda _b: hosp)
    monkeypatch.setattr(cf.cp, "parse_drops_allied", lambda _b: allied)
    _archive(tmp_path, "2026-07", files=("drops_hospitality", "drops_allied"))

    flags = {}
    fields = cf.feed_drops("2026-07", root=tmp_path, band=lambda r: "Target",
                           flags_out=flags)

    # Not a single allied dollar or head reaches the published grids.
    assert fields["drops_non_target"]["EastKing"]["Feb"] == 0
    assert fields["drops_revenue_non_target"]["EastKing"]["Feb"] == 0
    # The hospitality row is untouched — dateless rows still take the
    # conditional fallback (event axis, 2026-07-31): class 4 closed end of May.
    assert fields["drops_target"]["Pierce"]["May"] == 1, "hosp row still bands normally"
    assert {f["name"] for f in flags["drop_date_fallback"]} == {"hosp real"}

    # Visible, both of them — including the RRO row, which the allied rule now
    # claims first. Nothing from the Allied export disappears silently.
    assert {f["name"] for f in flags["allied_drops"]} == {"Mautone", "allied rro"}
    assert "rro_fyi" not in flags


def test_missing_allied_export_degrades_loudly_not_fatally(monkeypatch, tmp_path):
    """Hospitality alone is a valid (under-counting) answer; silence is not."""
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality",
                        lambda _b: [_srow("Inactive", 4)])
    _archive(tmp_path, "2026-07", files=("drops_hospitality",))

    with pytest.warns(UserWarning, match="Allied"):
        fields = cf.feed_drops("2026-07", root=tmp_path, band=lambda r: "Target")
    assert sum(v for t in fields["drops_target"].values() for v in t.values()) == 1


def test_hygiene_checker_excludes_stale_strays_by_name(monkeypatch, tmp_path):
    """The billed-last-cycle test, demoted to hygiene (BUILD-PLAN D1): a real-
    block row whose last dues invoice predates its own previous cycle — or who
    was never invoiced at all — is excluded FROM THE HEADLINE and named in the
    flags. It must never rescue nor touch RRO rows (they are already out).
    """
    rows = [
        _srow("Inactive", 4, name="genuine drop"),
        _srow("Closed", 3, name="brooklyn class"),
    ]
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality", lambda _b: rows)
    _archive(tmp_path, "2026-07", files=("drops_hospitality",))

    def hygiene(row):
        return "last invoice 2003 — left in an earlier year" \
            if row.name == "brooklyn class" else None

    flags = {}
    with pytest.warns(UserWarning, match="Allied"):
        fields = cf.feed_drops("2026-07", root=tmp_path, band=lambda r: "Target",
                               flags_out=flags, hygiene=hygiene)

    total = sum(v for t in fields["drops_target"].values() for v in t.values())
    assert total == 1
    assert flags["hygiene"][0]["name"] == "brooklyn class"
    assert "2003" in flags["hygiene"][0]["reason"]


def test_hygiene_verdict_logic():
    from datetime import date
    from reports.membership_performance_tracker.logic import drops_hygiene as dh

    assert dh.verdict(6, 2025, None) is not None          # never invoiced
    assert dh.verdict(6, 2025, date(2003, 11, 4)) is not None   # decades stale
    assert dh.verdict(6, 2025, date(2025, 6, 1)) is None  # billed last cycle
    assert dh.verdict(11, 2025, date(2024, 10, 15)) is None  # prev Nov cycle ok


# ---------------------------------------------------------------------------
# Drops file by FLIP DATE (ratified 2026-07-31, Jiho) — the team's own axis.
# Jen's SOP runs the dropped-member report "1st through last day of the month":
# a drop belongs to the month the status actually changed. The bill-month axis
# had no year on it, which filed nine-month-old September-class failures under
# NEXT September's column (the invisible 23).
# ---------------------------------------------------------------------------
from datetime import date as _date


def _file(bm, drop_date, today=_date(2026, 7, 31)):
    from reports.membership_performance_tracker.logic.crystal_feed import _file_month
    return _file_month(bm, drop_date, fy_start_year=2025, today=today)


def test_flip_date_files_in_its_own_month():
    """Auld Holland Inn class: September-class member flipped Nov 2025 —
    files under Nov, this fiscal year, where the event actually happened."""
    assert _file(9, _date(2025, 11, 14)) == ("Nov", None)


def test_stale_date_falls_back_to_the_class_close():
    """The 41-stale-dates class (7/27): a 2013 flip date on a member billed in
    FY26 is a lie — treat as dateless. Class 9's window closed Oct 31 2025,
    which is behind us, so they file at the close, flagged."""
    month, why = _file(9, _date(2013, 6, 24))
    assert month == "Oct" and why is not None


def test_dateless_closed_class_files_at_its_close():
    """No date, class 4: the window closed May 31 2026 — non-payer shape."""
    month, why = _file(4, None)
    assert month == "May" and why is not None


def test_dateless_open_class_files_now_not_in_the_future():
    """No date, class 7: its window closes Sep 30 2026 — still collectible, so
    they cannot have failed it. We learned of the loss NOW; file it now.
    (Jiho: 'we could probably find out based on the current month.')"""
    month, why = _file(7, None)
    assert month == "Jul" and why is not None


def test_future_date_is_implausible_and_falls_back():
    month, why = _file(4, _date(2026, 9, 15))
    assert month == "May" and why is not None


def test_next_fy_flip_date_never_files_into_the_fy_being_rebuilt():
    """S3 hole 2 (overnight review 8/11): the FY window is enforced on its
    LOWER edge only — `fy_lo <= d <= today`. `today` is the wall clock, so
    rebuilding a CLOSED fiscal year (the amendment / repair-from-archive path)
    lets a NEXT-FY flip date through and files it into this FY's column as a
    TRUSTED date, no fallback reason. Reachable: the drops schedule's own
    window runs 2025-10-01 → 2030-12-31, so the export really does carry
    later-FY rows.

    An FY26-27 date is not a fact about FY25-26. Treat it exactly like the
    41-stale-dates class — dateless, filed at the class close, flagged.
    """
    month, why = _file(3, _date(2026, 10, 20), today=_date(2026, 11, 15))
    assert month == "Apr" and why is not None


def test_the_last_day_of_the_fiscal_year_is_still_inside_the_window():
    """The other side of that boundary: Sep 30 IS this fiscal year. Guards the
    upper bound against an off-by-one that would drop every September drop."""
    assert _file(3, _date(2026, 9, 30), today=_date(2026, 11, 15)) == ("Sep", None)


def test_december_class_close_wraps_into_january():
    month, why = _file(12, None)
    assert month == "Jan" and why is not None


def test_stale_billing_drop_with_fy_flip_date_counts_at_flip(monkeypatch, tmp_path):
    """D2 AMENDMENT (approved 2026-08-04): a member whose status flipped
    inside the FY counts as a drop in the flip month REGARDLESS of billing
    recency — valued at Dues Level (the export's dues column). The hygiene
    test stops being an exclusion and becomes a flag ('counted, billing
    stale'). Columbia Tower class: real closure, ancient billing."""
    from datetime import date as _d
    root = _archive(tmp_path)
    rows = [_drop("Columbia Tower Club", "NorthKing", 4, 1070.0,
                  reason="Out of Business")]
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality", lambda _b: rows)
    flags = {}

    fields = cf.feed_drops("2026-07", root, lambda _r: NT,
                           flags_out=flags,
                           hygiene=lambda r: "last WRA dues invoice 2019 — stale",
                           drop_date_of=lambda r: _d(2026, 4, 15),
                           today=_d(2026, 7, 31))

    assert fields["drops_non_target"]["NorthKing"]["Apr"] == 1, \
        "flip inside the FY -> counts in the flip month"
    assert fields["drops_revenue_non_target"]["NorthKing"]["Apr"] == 1070.0
    assert flags.get("hygiene_counted"), "the stale-billing note must survive as a flag"


def test_stale_drop_without_plausible_flip_date_stays_out(monkeypatch, tmp_path):
    """Brooklyn Bros class (status date 2003): no plausible FY flip date ->
    excluded exactly as before. The D4 window-leak guard survives."""
    root = _archive(tmp_path)
    rows = [_drop("Brooklyn Bros Pizzeria", "SouthKing", 4, 510.0,
                  reason="Out of Business")]
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality", lambda _b: rows)
    from datetime import date as _d
    flags = {}

    fields = cf.feed_drops("2026-07", root, lambda _r: NT,
                           flags_out=flags,
                           hygiene=lambda r: "last WRA dues invoice 2003 — stale",
                           drop_date_of=lambda r: None,     # 2003 = implausible, treated dateless
                           today=_d(2026, 7, 31))

    assert fields["drops_non_target"]["SouthKing"].get("Apr", 0) == 0, \
        "no plausible flip date -> still excluded"
    assert flags.get("hygiene"), "still excluded under the hygiene flag"


def test_allied_parser_flags_ungrouped_rows_instead_of_refusing():
    """8/10: three house-account rows (no territory group in the export)
    killed the whole allied parse — and with it the entire drops overlay.
    Rows outside group headers can never land in a territory column, so
    they must become FLAGGED orphans, not a hard refusal; refusal is still
    right when EVERY row is orphaned (true layout change)."""
    from reports.membership_performance_tracker.logic import crystal_parsers as cp
    from pathlib import Path
    f = Path("data/raw/crystal/2026-08/DroppedAlliedReport_JihoBae_202608_10_1230.xls")
    if not f.exists():
        import pytest
        pytest.skip("no archived 8/10 allied export on this machine")
    rows = cp.parse_drops_allied(f.read_bytes())
    orphans = [r for r in rows if not r.territory or not r.status_reason]
    grouped = [r for r in rows if r.territory and r.status_reason]
    assert grouped, "grouped rows must still parse"
    assert orphans, "the 3 house rows must survive as orphans, not kill the file"
    assert {r.name for r in orphans} >= {"Adesso Capital"}


def test_admin_housekeeping_reasons_are_not_drops_on_the_crystal_path(monkeypatch, tmp_path):
    """The ruling exists (`drops.ADMIN_REASONS`, ratified 13:40): admin and
    record-housekeeping reasons are EXCLUDED from the counts and kept in the
    detail. It lived ONLY in the SData path — the Crystal overlay, which is
    what actually publishes, never applied it.

    Live rows counted on 2026-08-11 that the ruling excludes:
      · 0066494 Cheeky Noodles, Southwest, $730 — "New Lead"
      · 0066581 Gill Brothers LLC, NorthCentral, $510 — "New Record from a
        Closed/ Sold"

    A lead that never became a member cannot be a member loss.
    """
    from reports.membership_performance_tracker.logic.drops import ADMIN_REASONS
    rows = [
        _srow("Inactive", 4, name="real loss", dues=730.0, reason="Non-Payment"),
        _srow("Inactive", 4, name="cheeky noodles", dues=730.0, reason="New Lead"),
        _srow("Inactive", 4, name="gill brothers", dues=510.0,
              reason="New Record from a Closed/ Sold"),
    ]
    assert {"New Lead", "New Record from a Closed/ Sold"} <= ADMIN_REASONS
    monkeypatch.setattr(cf.cp, "parse_drops_hospitality", lambda _b: rows)
    _archive(tmp_path, "2026-07", files=("drops_hospitality",))

    flags = {}
    fields = cf.feed_drops("2026-07", root=tmp_path, band=lambda r: "Target",
                           flags_out=flags)

    total = sum(v for g in ("drops_target", "drops_non_target")
                for terr in fields[g].values() for v in terr.values())
    dollars = sum(v for g in ("drops_revenue_target", "drops_revenue_non_target")
                  for terr in fields[g].values() for v in terr.values())
    assert total == 1, "only the real loss counts"
    assert dollars == 730.0, "the admin rows carry no dropped revenue"
    named = " ".join(str(r) for r in flags.get("admin_reason_excluded") or [])
    assert "cheeky noodles" in named and "gill brothers" in named, \
        "excluded rows must be disclosed, not silently dropped"


def test_the_territory_collision_guard_survives_a_spelling_difference():
    """The (territory, name) key is the ONLY guard against same-name members in
    different territories taking each other's band and flip date. It was
    inoperative for three territories: the SData drops detail spells them
    "East King"/"North King"/"South King" while the Crystal exports spell them
    "EastKing"/"NorthKing"/"SouthKing", so the pair NEVER matched and 177 of
    331 rows fell through to global first-match name matching — the exact thing
    the 8/10 note says never to do.

    Live cost (2026-08-11): Bob's Burgers & Brew — two distinct WRA members
    share that name in NorthCentral, and first-wins handed both rows the wrong
    member's flip date, filing $2,775 in January instead of July.
    """
    from reports.membership_performance_tracker.logic import crystal_banding as cb

    # ORDER MATTERS — this is the live shape. NorthCentral is inserted first,
    # so it wins the name-only key; East King's row can then only be reached
    # through the PAIR key, which the spelling difference breaks.
    detail = [
        {"account_name": "Same Name Cafe", "territory": "NorthCentral",
         "is_target": "N", "drop_date": "2026-07-31"},
        {"account_name": "Same Name Cafe", "territory": "East King",
         "is_target": "Y", "drop_date": "2026-01-08"},
    ]

    class Row:
        def __init__(self, name, territory):
            self.name, self.territory = name, territory

    band = cb.band_from_detail(detail)
    when = cb.drop_dates_from_detail(detail)

    # The export spells it "EastKing"; the detail spells it "East King".
    ek = Row("Same Name Cafe", "EastKing")
    nc = Row("Same Name Cafe", "NorthCentral")

    assert band(ek) == target_logic.TARGET, \
        "EastKing must resolve to its OWN row, not the first-inserted one"
    assert band(nc) == target_logic.NON_TARGET
    assert str(when(ek)) == "2026-01-08"
    assert str(when(nc)) == "2026-07-31", \
        "NorthCentral must get its own flip date, not East King's"


# ── ONE PATH FOR THE NUMBER AND ITS EXPLANATION (ruled 2026-08-14) ───────────
# docs/superpowers/specs/2026-08-14-receipts-single-path.md
#
# The published drop counts and the member list that explains them used to be
# two loops over the same export. Twice this month one loop learned a rule the
# other did not — the allied ruling, and the admin-reason exclusion — and the
# conservation gate refused every receipt for two runs running. A detector
# cannot prevent that class; only structure can. These tests pin the structure.

from datetime import date


def _ledger_rows():
    """A row of every kind the classifier can meet, including the two that
    used to vanish silently."""
    from types import SimpleNamespace

    def row(name, status="Inactive", reason="Non-Payment", bm=4, terr="Pierce",
            dues=730.0):
        return SimpleNamespace(name=name, mid=name, territory=terr, dues=dues,
                               bill_month=bm, status=status,
                               status_reason=reason, business_type="",
                               status_date=None)
    return [
        row("Counted Co"),
        row("Retro Co", status="RRO Active"),
        row("Housekeeping Co", reason="New Lead"),
        row("Odd Status Co", status="Prospect"),          # used to vanish
        row("No Cycle Co", bm=None),
        row("Ungrouped Co", terr="", reason=""),          # allied, used to vanish
    ]


def test_every_exported_row_leaves_the_ledger_with_a_reason():
    """TOTALITY. An export row with no receipt is a row nobody can ask about.

    Two branches used to `continue` without emitting anything — an unknown
    status, and an allied row printed outside every group header. Those members
    were excluded from the count with no way for a reader to find out why."""
    from reports.membership_performance_tracker.logic import crystal_feed as cf

    rows = _ledger_rows()
    entries = [cf.classify_drop(r, r.name == "Ungrouped Co", fy_start=2025,
                                today=date(2026, 8, 14)) for r in rows]

    assert len(entries) == len(rows), "one entry per exported row, always"
    for e in entries:
        assert e["explain"], f"{e['row'].name} left with no explanation"
    by = {e["row"].name: e for e in entries}
    assert by["Odd Status Co"]["counted"] is False
    assert "Prospect" in by["Odd Status Co"]["explain"]
    assert by["Ungrouped Co"]["counted"] is False
    assert "territory" in by["Ungrouped Co"]["explain"]
    assert by["Counted Co"]["counted"] is True


def test_the_count_and_the_member_list_are_the_same_objects():
    """The single path, stated as an equality.

    `feed_drops` sums the counted ledger entries; `render_drops` renders every
    entry. Both read one `drop_ledger`. So the published cell and the rows
    behind it cannot disagree — not because a gate checks, but because there is
    nothing left to disagree with."""
    from reports.membership_performance_tracker.logic import crystal_feed as cf
    from reports.membership_performance_tracker.logic import receipts_render as rr

    entries = [cf.classify_drop(r, r.name == "Ungrouped Co", fy_start=2025,
                                today=date(2026, 8, 14))
               for r in _ledger_rows()]
    grids = cf.aggregate_drops(entries, {})
    rendered = [{"metric": "Drops", "month": e["month"], "band": e["band"],
                 "territory": e["row"].territory, "counted": e["counted"],
                 "amount": round(e["row"].dues or 0.0, 2)} for e in entries]

    assert not rr.gate_drops(rendered, grids), \
        "the rows and the grids came from one ledger; they must reconcile"


def test_a_new_rule_cannot_reach_the_number_without_reaching_the_receipt():
    """The regression guard for the whole build.

    The allied ruling is the worked example: it lives in `classify_drop` once,
    so the count drops the member AND the Trace page says why. If a future
    change puts a rule back in `feed_drops` or `render_drops`, the flagged row
    and the uncounted receipt stop agreeing and this fails."""
    from reports.membership_performance_tracker.logic import crystal_feed as cf

    from types import SimpleNamespace
    allied = SimpleNamespace(name="Allied Co", mid="A1", territory="Pierce",
                             dues=505.0, bill_month=4, status="Inactive",
                             status_reason="Non-Payment", business_type="",
                             status_date=None)
    e = cf.classify_drop(allied, True, fy_start=2025, today=date(2026, 8, 14))

    assert e["counted"] is False, "allied is out of the drop counts (8/14)"
    assert "allied" in e["explain"].lower()
    assert e["flag"][0] == "allied_drops"
    # the flag a maintainer reads and the row a member reads say the same thing
    assert e["flag"][1]["note"] == e["explain"]
