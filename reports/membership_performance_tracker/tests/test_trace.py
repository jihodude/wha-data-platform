"""The Trace API — the transparency layer's core (ruled by Jiho 8/6).

A published cell → its constituents + conservation against the published
cache. Substrate: data/receipts/receipts_<period>.json — the rendered
member rows the pipeline itself produced (never re-derived in parallel).
Fixture = the REAL July data, pinned to the SouthKing story that took an
hour of forensics on 8/6 and must now take one call.
"""
import pytest
from pathlib import Path

from reports.membership_performance_tracker.logic import trace as T

ROOT = Path(__file__).resolve().parents[3]
HAVE = (ROOT / "data" / "receipts" / "receipts_2026-07.json").exists()
pytestmark = pytest.mark.skipif(not HAVE, reason="no local July receipts")


def test_retention_trace_reproduces_southking_may():
    out = T.trace("2026-07", "Retention", "SouthKing", "May")
    rows = out["members"]
    cohort = [r for r in rows if T._in_cohort(r)]
    paid = [r for r in cohort if r["counted"]]
    assert len(cohort) == 15 and len(paid) == 12
    assert out["published"]["ret_billed"] == 15
    assert out["published"]["ret_paid"] == 12
    assert out["conservation"]["ok"], out["conservation"]
    # exclusions are rows with reasons, never silent absence
    assert all(r.get("qualifies") for r in rows if not T._in_cohort(r))
    assert any("first cycle" in str(r["qualifies"]) for r in rows)


def test_conservation_trips_on_mismatch():
    out = T.trace("2026-07", "Retention", "SouthKing", "May")
    assert out["conservation"]["ok"]
    bad = T._conserve(out["members"], {"ret_billed": 99, "ret_paid": 12,
                                       "rev_up": 1.0, "rev_retained": 1.0},
                      "Retention")
    assert not bad["ok"] and bad["problems"]


def test_drops_and_billables_families_answer_too():
    d = T.trace("2026-07", "Drops", "SouthKing", "May")
    assert d["members"], "drops must trace to named members"
    b = T.trace("2026-07", "Billables", "SouthKing", "Jul")
    assert len([r for r in b["members"] if r["counted"]]) > 50


def test_full_grid_conserves_across_all_traceable_families():
    """The whole-report conservation sweep as a permanent gate: every
    retention, drops and new-sales cell must reproduce from its member
    list. 8/6: first full run caught the BOB-filter bug in the checker
    itself; steady state is ZERO."""
    rows, fields = T._load("2026-07")
    months = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
              "Apr", "May", "Jun", "Jul"]
    terrs = sorted({r["territory"] for r in rows
                    if r["territory"] in fields["ret_billed"]})
    bad = []
    for fam in ("Retention", "Drops", "New Members / New Sales"):
        for t in terrs:
            for m in months:
                out = T.trace("2026-07", fam, t, m)
                if not (any(v not in (None, 0)
                            for v in out["published"].values())
                        or out["members"]):
                    continue
                if not out["conservation"]["ok"]:
                    bad.append((fam, t, m, out["conservation"]["problems"]))
    # photo families: billables at the capture month; penetration accepts a
    # mismatch ONLY where the rows carry the dated-drift annotation (the
    # 8/6 requery label) — silent drift stays a failure
    for t in terrs:
        out = T.trace("2026-07", "Billables", t, "Jul")
        if out["members"] and not out["conservation"]["ok"]:
            bad.append(("Billables", t, "Jul", out["conservation"]["problems"]))
        pen = T.trace("2026-07", "Penetration", t, None)
        if pen["members"] and not pen["conservation"]["ok"]:
            annotated = any("sealed 8/5 count differs" in str(r.get("qualifies"))
                            for r in pen["members"])
            if not annotated:
                bad.append(("Penetration", t, None, pen["conservation"]["problems"]))
    assert bad == [], f"{len(bad)} cells fail conservation: {bad[:4]}"


def test_load_heals_missing_scoreboard_from_sp(tmp_path, monkeypatch):
    """A fresh cloud instance only session-syncs the VIEWED month's
    scoreboard, but this page's picker spans every month with receipts —
    a missing local scoreboard must heal from the SP snapshot (8/10)."""
    import json as _json
    receipts, cache = tmp_path / "receipts", tmp_path / "cache"
    receipts.mkdir(); cache.mkdir()
    (receipts / "receipts_2099-01.json").write_text(_json.dumps({"rows": []}))
    monkeypatch.setattr(T, "RECEIPTS_DIR", receipts)
    monkeypatch.setattr(T, "CACHE_DIR", cache)
    envelope = {"data": {"ret_billed_target": {"SouthKing": {"May": 1}}},
                "captured_at": "2026-08-10T09:00:00+00:00"}
    monkeypatch.setattr(T, "_fetch_sp_snapshot", lambda p: envelope,
                        raising=False)
    rows, fields = T._load("2099-01")
    assert fields["ret_billed_target"]["SouthKing"]["May"] == 1
    healed = cache / "scoreboard_2099-01.json"
    assert healed.exists()
    meta = _json.loads(healed.read_text())["_meta"]
    assert meta["source"] == "sp-published"
    assert meta["saved_at"] == "2026-08-10T09:00:00+00:00"


def test_frozen_note_reaches_a_LATER_build_not_only_the_sealed_period():
    """A sealed month must explain itself on every build of its fiscal year.

    `apply_frozen` month-slices retention onto EVERY build in the same FY, so
    on the 2026-08 report July's face is the seal. The note was gated on
    `doc["period"] == period`, which is false on exactly those later builds,
    so the page said nothing at all about a month that cannot move (found
    2026-08-12 on July retention).

    Guards the gate, not the wording: July must carry the note on the 2026-08
    build, and a month that was never sealed must NOT (or an open month would
    be described as closed).

    The wording itself was rewritten 2026-08-14 — it used to explain a
    discrepancy in pre-ITD / post-ITD terms, on a strip that only ever renders
    when the numbers RECONCILE. Assert the plain facts a reader needs, and
    assert the jargon is gone, but never the exact sentence.
    """
    if not (ROOT / "data" / "receipts" / "receipts_2026-08.json").exists():
        pytest.skip("no local August receipts")
    jul = T.trace("2026-08", "Retention", "TKP", "Jul")
    assert jul.get("frozen_note"), \
        "July retention is frozen on the 2026-08 build; the note must say so"
    note = jul["frozen_note"]
    assert "Jul" in note and "closed" in note.lower(), \
        "the note must name the month and say, in plain words, that it is closed"
    for jargon in ("ITD", "two-photograph", "snapshot_", ".json"):
        assert jargon not in note, (
            f"{jargon!r} is repo vocabulary, not reader vocabulary — this strip "
            f"is read by TMs (no-jargon rule)")

    unsealed = T.trace("2026-08", "Retention", "TKP", "May")
    assert not unsealed.get("frozen_note"), \
        "May was never sealed — a mismatch there must still alarm, not be excused"


# ---------------------------------------------------------------------------
# "Total" territory (Jiho 8/12): the dropdown gains an all-territories view —
# published = the sum of every territory's cell, members = every territory's
# rows, conservation must still hold. Real-data fixture like everything above.
# ---------------------------------------------------------------------------

def _territories(family, month):
    rows, _ = T._load("2026-07")
    return sorted({r["territory"] for r in rows
                   if r.get("metric") == family and r.get("territory")})


def test_total_retention_is_the_sum_of_every_territory():
    total = T.trace("2026-07", "Retention", T.TOTAL_TERRITORY, "May")
    per = [T.trace("2026-07", "Retention", t, "May")
           for t in _territories("Retention", "May")]
    for key in ("ret_billed", "ret_paid"):
        assert total["published"][key] == sum(p["published"][key] for p in per)
    assert total["conservation"]["ok"], total["conservation"]
    assert len(total["members"]) == sum(len(p["members"]) for p in per)


def test_total_penetration_sums_the_photo():
    total = T.trace("2026-07", "Penetration", T.TOTAL_TERRITORY, None)
    per = [T.trace("2026-07", "Penetration", t, None)
           for t in _territories("Penetration", None)]
    key = "active_target_restaurant"
    expected = sum(p["published"][key] or 0 for p in per)
    assert total["published"][key] == expected and expected > 0


# ---------------------------------------------------------------------------
# NO ALARM (Jiho, 8/13): the page used to shout "needs investigating" at a
# reader who cannot act on it. The causes are fixed at the source instead —
# a sealed month now carries only the member lists whose numbers are truly
# frozen, so its lists and its face agree — and the page simply confirms
# reconciliation or says nothing. Only frozen_note survives, as context on
# the success line.
# ---------------------------------------------------------------------------


def test_trace_carries_no_alarm_fields():
    out = T.trace("2026-07", "Retention", "SouthKing", "May")
    assert "stale_note" not in out and "closed_note" not in out


def test_a_cell_that_cannot_reconcile_stays_silent():
    """The one known seam (Spokane/NE Jul new sales: the face recomputes a
    late-settling sale, the member list is carried from the seal — STAGED
    section F, Jiho's call). It must not shout: the page shows the members
    and the published number and lets them speak."""
    out = T.trace("2026-08", "New Members / New Sales", "Spokane/NE", "Jul")
    assert "stale_note" not in out and "closed_note" not in out
    assert out["published"].get("new_members") is not None
