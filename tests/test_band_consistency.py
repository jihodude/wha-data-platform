"""Combined == Target + Non-Target, every field, every cell — permanent.

Born 8/6 from the Velvet's Big Easy bug: a rule (BOB at face) lived in the
combined path but not the split path the sheets read, and NO gate compared
the two. This is that gate. It also catches cache drift against the seal
(it caught the SP-official revert within the hour of its first run).
"""
import json
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache" / "scoreboard_2026-07.json"
pytestmark = pytest.mark.skipif(not CACHE.exists(), reason="no local cache")

PAIRS = [("ret_paid", "ret_paid_target", "ret_paid_non_target"),
         ("ret_billed", "ret_billed_target", "ret_billed_non_target"),
         ("new_members", "new_members_target", "new_members_non_target"),
         ("hosp_bills", "hosp_bills_target", "hosp_bills_non_target"),
         ("ret_comped", "ret_comped_target", "ret_comped_non_target"),
         ("ret_comped_dollars", "ret_comped_dollars_target",
          "ret_comped_dollars_non_target")]


def test_every_combined_cell_equals_its_band_split():
    c = json.loads(CACHE.read_text())["fields"]
    bad = []
    for comb, t_f, nt_f in PAIRS:
        for terr, months in (c.get(comb) or {}).items():
            if not isinstance(months, dict):
                continue
            for m, v in months.items():
                if v is None:
                    continue
                t = ((c.get(t_f) or {}).get(terr) or {}).get(m)
                nt = ((c.get(nt_f) or {}).get(terr) or {}).get(m)
                if t is None and nt is None:
                    continue
                if abs((t or 0) + (nt or 0) - v) > 0.011:
                    bad.append((comb, terr, m, t, nt, v))
    assert bad == [], f"{len(bad)} combined/split mismatches: {bad[:5]}"
