"""Banding: the member-id bridge, and the gates that keep it honest."""
import pytest

from reports.membership_performance_tracker.logic import crystal_banding as cb
from reports.membership_performance_tracker.logic import crystal_parsers as cp
from reports.membership_performance_tracker.logic import target as target_logic


class FakeClient:
    def __init__(self, records):
        self.records = records
        self.queries = []

    def _fetch_all(self, entity, where=None, page_size=None, **kw):
        self.queries.append((entity, where, kw))
        return self.records


def _acct(account_id, name):
    return {"$key": account_id, "AccountName": name}


def _drop(mid, territory="Pierce", dues=1070.0):
    return cp.DropRow(mid=mid, name=f"m{mid}", territory=territory, dues=dues,
                      bill_month=4, status_reason="Sold")


def _pen(territory, status):
    return cp.PenetrationRow(account_id="A" * 12, name="x", territory=territory,
                             size_band="20 to 49", status=status)


def test_name_normalization_folds_only_meaningless_differences():
    """Crystal and SData return the same string, but punctuation still differs."""
    assert cb.normalize_name("Smitty's Pancake House") == cb.normalize_name("Smittys Pancake House")
    assert cb.normalize_name("Bruno & Sons, Inc.") == cb.normalize_name("Bruno and Sons Inc")
    assert cb.normalize_name("A  B") == "a b"
    assert cb.normalize_name("Blue Diner") != cb.normalize_name("Red Diner")


def test_bridge_is_built_per_territory_so_names_cannot_collide_across_them():
    """A global name index would let same-named businesses swap bands."""
    client = FakeClient([_acct("ACC1", "Smitty's Pancake House")])

    bridge = cb.build_name_bridge(client, "U6UJ9A00006I")

    entity, where, kw = client.queries[0]
    assert entity == "accounts"
    assert "U6UJ9A00006I" in where
    assert bridge == {"smittys pancake house": "ACC1"}


def test_bridge_keeps_the_first_of_duplicate_names():
    client = FakeClient([_acct("ACC1", "Same Name"), _acct("ACC_LATER", "Same Name")])

    assert cb.build_name_bridge(client, "U") == {"same name": "ACC1"}


def test_unreachable_member_bands_as_unknown_not_non_target():
    """An unbanded member must be visible, never absorbed into a band.

    Defaulting to Non-Target would move real Target members into the wrong
    column and still add up, so nothing would look wrong.
    """
    bridge = {"ballard burgers": "ACC1"}
    target_map = {"ACC1": target_logic.TARGET}

    assert cb.band_member("Ballard Burgers", bridge, target_map) == target_logic.TARGET
    assert cb.band_member("Nowhere Cafe", bridge, target_map) == target_logic.UNKNOWN


def test_band_rows_splits_parsed_crystal_rows():
    bridge = {"m0000001": "A1", "m0000002": "A2", "m0000003": "A3"}
    target_map = {"A1": target_logic.TARGET, "A2": target_logic.NON_TARGET}

    banded = cb.band_rows([_drop("0000001"), _drop("0000002"), _drop("0000003")],
                          bridge, target_map)

    assert cb.totals(banded) == cb.BandedTotals(target=1, non_target=1, unknown=1)


def test_penetration_gate_passes_when_counts_agree_and_raises_when_they_drift():
    """The cross-source rule: our Target actives must equal the report's own.

    This held exactly on 2026-07-19 (TKP 56/56), so any divergence is new.
    """
    rows = [_pen("TKP", "Active")] * 56 + [_pen("TKP", "Inactive")] * 9

    cb.check_against_penetration({"TKP": 56}, rows)

    with pytest.raises(cb.BandingMismatch, match="ours 55 vs the report's 56"):
        cb.check_against_penetration({"TKP": 55}, rows)


def test_penetration_gate_flags_a_territory_we_produced_nothing_for():
    rows = [_pen("Southeast", "Active")] * 3

    with pytest.raises(cb.BandingMismatch, match="no Target count"):
        cb.check_against_penetration({}, rows)


def test_a_wave_of_unknowns_warns_because_they_count_in_neither_band():
    banded = {target_logic.TARGET: [1], target_logic.NON_TARGET: [],
              target_logic.UNKNOWN: [1, 2, 3]}

    with pytest.warns(UserWarning, match="counted in NEITHER band"):
        cb.warn_on_unknowns(banded, "drops")


def test_a_few_unknowns_stay_quiet():
    banded = {target_logic.TARGET: list(range(99)), target_logic.NON_TARGET: [],
              target_logic.UNKNOWN: [1]}

    import warnings as w
    with w.catch_warnings(record=True) as caught:
        w.simplefilter("always")
        cb.warn_on_unknowns(banded, "drops")
    assert not caught


# ---------------------------------------------------------------------------
# Banding from SData's own drops detail (2026-07-28)
# ---------------------------------------------------------------------------
# The name-bridge bander needs a live SLX client, so on the --from-cache path it
# could not band at all: every row read UNKNOWN, folded into Non-Target, and the
# report published "Target: 0" without a word.
#
# But SData's drops_detail already carries is_target per member, computed by the
# SAME target logic every other family uses — and it is in the cache. Measured
# against the live July export: 263 of 264 Crystal rows band from it (99.6%).
# The single miss is Todd's Crab Cracker, the ownerless account that no
# territory-keyed query can reach (SOURCE-DATA-AUDIT 1.2) — the one row that
# fails is the one the CRM itself cannot represent.



def _row(name, territory):
    class R:
        pass
    r = R()
    r.name, r.territory = name, territory
    return r


def _detail(name, territory, is_target):
    return {"account_name": name, "territory": territory, "is_target": is_target}


def test_bands_from_the_detail_list_with_no_client():
    band = cb.band_from_detail([
        _detail("Cafe Alpha", "TKP", "Y"),
        _detail("Pub Beta", "TKP", "N"),
    ])

    assert band(_row("Cafe Alpha", "TKP")) == target_logic.TARGET
    assert band(_row("Pub Beta", "TKP")) == target_logic.NON_TARGET


def test_territory_and_name_wins_over_name_alone():
    """Two members can share a name across territories; the pair is the better
    key. Measured on live data, the pair resolves 43% and the name-only
    fallback carries the rest."""
    band = cb.band_from_detail([
        _detail("Harbor Grill", "TKP", "Y"),
        _detail("Harbor Grill", "Pierce", "N"),
    ])

    assert band(_row("Harbor Grill", "Pierce")) == target_logic.NON_TARGET


def test_falls_back_to_name_when_the_territory_differs():
    """Crystal and SData disagree about a member's territory more often than
    not, so a territory mismatch must not lose the band."""
    band = cb.band_from_detail([_detail("Rickshaw LLC", "NorthKing", "Y")])

    assert band(_row("Rickshaw LLC", "EastKing")) == target_logic.TARGET


def test_punctuation_and_case_do_not_break_the_match():
    band = cb.band_from_detail([_detail("Smitty's Bar & Grill", "TKP", "Y")])

    assert band(_row("SMITTYS BAR AND GRILL", "TKP")) == target_logic.TARGET


def test_an_unmatched_member_is_unknown_not_guessed():
    """Todd's Crab Cracker: ownerless, unreachable, absent from the detail.
    UNKNOWN keeps it in the total (as Non-Target) without claiming a size we
    never established."""
    band = cb.band_from_detail([_detail("Cafe Alpha", "TKP", "Y")])

    assert band(_row("Todd's Crab Cracker", "EastKing")) == target_logic.UNKNOWN


def test_rows_without_a_target_flag_are_ignored_rather_than_read_as_non_target():
    """A blank is_target means SData never classified them — that is not
    evidence of Non-Target."""
    band = cb.band_from_detail([
        _detail("No Flag Diner", "TKP", None),
        _detail("No Flag Diner", "TKP", "Y"),      # a later row DID classify
    ])

    assert band(_row("No Flag Diner", "TKP")) == target_logic.TARGET


def test_an_empty_detail_list_yields_no_bander():
    """Nothing to band from is the GATE B case: return None so the overlay keeps
    SData's split instead of publishing a fabricated one."""
    assert cb.band_from_detail([]) is None


# ---------------------------------------------------------------------------
# C3 (2026-08-12) — the WRA bridge. Name matching has NO answer for two
# same-named members in the SAME territory: Bob's Burgers & Brew exists twice
# in NorthCentral, and first-wins gave both Crystal rows one member's flip
# date, publishing $2,775 in January instead of July. The Crystal export
# carries the member's WRA number (mid); detail rows fetched since C3 carry
# theirs (wra, read off the same invoice fetch renewal-year already makes).
# An exact id match now beats every name heuristic; old caches without wra
# fall back to the name path unchanged.
# ---------------------------------------------------------------------------

def _row_mid(name, territory, mid):
    r = _row(name, territory)
    r.mid = mid
    return r


def _detail_wra(name, territory, is_target, wra, drop_date=None):
    d = _detail(name, territory, is_target)
    d["wra"] = wra
    if drop_date:
        d["drop_date"] = drop_date
    return d


def test_same_name_same_territory_twins_band_by_wra():
    band = cb.band_from_detail([
        _detail_wra("Bob's Burgers & Brew", "NorthCentral", "Y", "0056458"),
        _detail_wra("Bob's Burgers & Brew", "NorthCentral", "N", "0055444"),
    ])
    assert band(_row_mid("Bobs Burgers & Brew", "NC", "0056458")) \
        == target_logic.TARGET
    assert band(_row_mid("Bobs Burgers & Brew", "NC", "0055444")) \
        == target_logic.NON_TARGET


def test_same_name_twins_get_their_own_flip_dates_by_wra():
    from datetime import date
    dates = cb.drop_dates_from_detail([
        _detail_wra("Bob's Burgers & Brew", "NorthCentral", "Y", "0056458",
                    drop_date="2026-07-31"),
        _detail_wra("Bob's Burgers & Brew", "NorthCentral", "Y", "0055444",
                    drop_date="2025-12-31"),
    ])
    assert dates(_row_mid("Bobs Burgers & Brew", "NC", "0056458")) \
        == date(2026, 7, 31)
    assert dates(_row_mid("Bobs Burgers & Brew", "NC", "0055444")) \
        == date(2025, 12, 31)


def test_wra_match_survives_leading_zero_disagreement():
    band = cb.band_from_detail([
        _detail_wra("Cafe Alpha", "TKP", "Y", "0054855")])
    assert band(_row_mid("Cafe Alpha", "TKP", "54855")) == target_logic.TARGET


def test_rows_without_mid_still_use_the_name_path():
    band = cb.band_from_detail([
        _detail_wra("Cafe Alpha", "TKP", "Y", "0054855")])
    assert band(_row("Cafe Alpha", "TKP")) == target_logic.TARGET


def test_old_caches_without_wra_are_unchanged():
    band = cb.band_from_detail([_detail("Cafe Alpha", "TKP", "Y")])
    assert band(_row_mid("Cafe Alpha", "TKP", "0054855")) == target_logic.TARGET
