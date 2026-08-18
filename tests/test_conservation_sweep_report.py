"""The sweep must never let a display cap hide a whole family.

2026-08-12: the sweep printed `problems[:40]`, and the list is built family by
family in the order Billables, Drops, New Members, Penetration, Retention. With
209 problems the cap ran out inside Drops, so **every Retention failure was
invisible** — 69 cells, all of them the Allied mismatch Jiho was staring at on
the console. The sweep said "209 PROBLEMS" and then showed none of the ones
that mattered.

The verdict count was always right; only the printout lied. That is worse than
a wrong number, because it reads as a complete list.

Fix: a per-family tally is printed ALWAYS, before the capped detail, so a
truncated sample can never be mistaken for full coverage.
"""
from scripts.trace_conservation_sweep import family_tally


def _problems(*pairs):
    return [(fam, "TKP", "Oct", f"msg {i}") for i, fam in enumerate(pairs)]


def test_every_family_is_counted_even_beyond_the_print_cap():
    problems = _problems(*(["Billables"] * 45 + ["Retention"] * 69))
    tally = family_tally(problems)
    assert tally["Retention"] == 69, "the family past the cap vanished"
    assert tally["Billables"] == 45
    assert sum(tally.values()) == len(problems)


def test_tally_is_ordered_worst_first():
    problems = _problems(*(["Drops"] * 3 + ["Retention"] * 69 + ["Billables"] * 12))
    assert [f for f, _ in family_tally(problems).most_common()][0] == "Retention"


def test_no_problems_gives_an_empty_tally():
    assert family_tally([]) == {}


def test_the_real_shape_that_hid_the_allied_failures():
    """The exact 2026-08 distribution: the cap fell inside Drops and Retention
    never printed a single line."""
    problems = _problems(*(["Billables"] * 4 + ["Drops"] * 36
                           + ["New Members / New Sales"] * 2 + ["Retention"] * 69))
    tally = family_tally(problems)
    printed = {f for f, _t, _m, _msg in problems[:40]}
    assert "Retention" not in printed, "premise: the cap hid Retention"
    assert tally["Retention"] == 69, "the tally must surface it anyway"
