"""S5 — the receipts carry must harvest each close's OWN month exactly once.

The failure mode this guards first happens at the AUGUST close (~Sep 5, after
handoff): with TWO sealed months, the original inline code tested rows against
the ACCUMULATING month set, so July's rows carried from both July's and
August's sealed editions — every July cell doubled, and the September build
hard-stopped on the conservation gate. Only July is sealed today, so the bug
is unobservable in production until the exact moment nobody is watching.

Mechanically drives the two-sealed-months future the way the FY-rollover and
autoseal tests do, against the REAL functions (extracted from main() on 8/12
for exactly this purpose).
"""
import json

from scripts.build_receipts import harvest_sealed_carry, merge_sealed


def _seed(tmp_path, period, month, rows):
    closes = tmp_path / "closes"; closes.mkdir(exist_ok=True)
    receipts = tmp_path / "receipts"; receipts.mkdir(exist_ok=True)
    (closes / f"close_{period}.json").write_text(json.dumps(
        {"period": period, "month": month, "frozen": {},
         "sealed": {"drops_target": {"TKP": {month: 1}}}}))
    (receipts / f"receipts_{period}.json").write_text(json.dumps({"rows": rows}))
    return closes, receipts


def _row(month, member, metric="Retention"):
    return {"metric": metric, "month": month, "member": member,
            "territory": "TKP", "counted": True}


def test_two_sealed_months_carry_each_month_exactly_once(tmp_path):
    """The September-build scenario: July AND August sealed."""
    jul_rows = [_row("Jul", "July Member A"), _row("Jul", "July Member B")]
    aug_rows = [_row("Jul", "July Member A"),      # August's edition ALSO
                _row("Jul", "July Member B"),      # contains July's rows —
                _row("Aug", "August Member")]      # that is what receipts ARE
    closes, receipts = _seed(tmp_path, "2026-07", "Jul", jul_rows)
    _seed(tmp_path, "2026-08", "Aug", aug_rows)

    sealed, by_fm, fresh = harvest_sealed_carry(closes, receipts, "2026-09")
    assert sealed == {"Jul", "Aug"}
    # July harvested ONLY from July's edition; August only from August's
    assert len(by_fm[("Retention", "Jul")]) == 2, (
        "July doubled — the accumulating-set bug is back")
    assert len(by_fm[("Retention", "Aug")]) == 1

    merged = merge_sealed([_row("Sep", "Fresh Sep Member")], "Retention",
                          sealed, by_fm, fresh)
    months = sorted(r["month"] for r in merged)
    assert months == ["Aug", "Jul", "Jul", "Sep"], f"got {months}"


def test_one_sealed_month_unchanged_behavior(tmp_path):
    closes, receipts = _seed(tmp_path, "2026-07", "Jul",
                             [_row("Jul", "July Member A")])
    sealed, by_fm, fresh = harvest_sealed_carry(closes, receipts, "2026-08")
    merged = merge_sealed([_row("Jul", "STALE fresh render"),
                           _row("Aug", "Aug fresh")], "Retention",
                          sealed, by_fm, fresh)
    by = {r["member"]: r for r in merged}
    # The sealed month's own rows are the record: they carry verbatim and the
    # fresh render never counts over them.
    assert by["July Member A"]["counted"] is not False
    assert by["Aug fresh"], "open months still render fresh"
    # REFINED 8/13 — a fresh row for a sealed month is no longer thrown away.
    # It used to vanish from both sides at once (gone from the month it left,
    # absent from the sealed month it arrived in), which is how two real drops
    # went missing with nothing to show for it. It is kept, NOT counted, so no
    # published number or gate can move, and it says what to do about it.
    stray = by["STALE fresh render"]
    assert stray["counted"] is False, (
        "a stray must never count — the sealed numbers are the record")
    assert "closed" in stray["qualifies"], "it must explain why it isn't counted"


def test_unsealed_close_carries_nothing(tmp_path):
    closes = tmp_path / "closes"; closes.mkdir()
    receipts = tmp_path / "receipts"; receipts.mkdir()
    (closes / "close_2026-07.json").write_text(json.dumps(
        {"period": "2026-07", "month": "Jul", "frozen": {}}))   # no seal
    sealed, by_fm, fresh = harvest_sealed_carry(closes, receipts, "2026-08")
    assert sealed == set() and by_fm == {}
