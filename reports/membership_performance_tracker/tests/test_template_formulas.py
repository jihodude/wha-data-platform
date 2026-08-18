"""Template formula audit — a PERMANENT suite gate (born 8/5).

Jiho's gate-1 skim caught two formula-wiring defect classes the test suite
could never see (formulas live in template.xlsx, not Python): the 8/4 comp
rows each dragged the ENTIRE Non-Target retained revenue along (a
replace-first-occurrence artifact — "Comped Members 511" = 1 member + $510),
and the 8/5 locations rows' quarter cells averaged the BILLABLES row's
months (verbatim relative-formula copy). His words: "this is giving me false
confidence on your meticulousness." The answer is a mechanical gate, not a
promise: every TM-sheet formula is audited on every test run — mixed-metric
pure sums, foreign-row aggregates, naked additions over "-" text.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from tm_formula_audit import audit  # noqa: E402

TEMPLATE = (_ROOT / "reports" / "membership_performance_tracker"
            / "template.xlsx")


def test_every_tm_sheet_formula_passes_the_three_class_audit():
    violations = audit(TEMPLATE)
    assert violations == [], (
        f"{len(violations)} formula defect(s) in template.xlsx — "
        f"first: {violations[0]}")
