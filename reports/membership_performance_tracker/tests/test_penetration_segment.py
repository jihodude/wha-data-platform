"""
test_penetration_segment.py — penetration definition fixes (Pen Active automation).

Two evidence-backed corrections, decided 2026-06-04, to make our computed
penetration match Hannah's report (Active / (Active + Inactive)):

  #1 Denominator universe: the "market" must be Active + Inactive members only.
     The old code used build_target_map(status=None), which pulled EVERY SLX
     status (Closed, RRO, ...) — inflating the denominator. (Pierce: ~54 phantom
     Closed/RRO target restaurants.)

  #2 Account-type lumping: Corporate accounts are billing entities, not physical
     locations. Counting them in a location-penetration metric double-counts the
     chain alongside its child locations, so Corporate is excluded from BOTH the
     active numerator and the market denominator. (Pierce: 78 active + 18 inactive
     Corporate were being counted as "restaurants".)
"""

import reports.membership_performance_tracker.logic.target as target_mod
from reports.membership_performance_tracker.logic.billables import _count_target_locations, _count_locations, compute_penetration_by_segment
from reports.membership_performance_tracker.logic.target import TARGET, NON_TARGET, FOOD_SERVICE_TYPES


# ---------------------------------------------------------------------------
# #2 — _count_target_locations: Corporate excluded, hotels → lodging
# ---------------------------------------------------------------------------

def test_corporate_excluded_from_restaurant_count():
    # R1 restaurant (counts), C1 corporate (excluded as a billing entity),
    # H1 hotel (counts as lodging). All three are TARGET.
    type_map  = {"R1": "Restaurant", "C1": "Corporate", "H1": "Hotel"}
    class_map = {"R1": TARGET, "C1": TARGET, "H1": TARGET}

    restaurant, lodging = _count_target_locations(type_map, class_map)

    assert restaurant == 1   # R1 only — Corporate dropped
    assert lodging == 1      # H1


def test_food_service_whitelist_constants():
    # Pin the four types Suzanne's BillablesbyTerritory report defines as
    # food-service (the WHA-internal definition, 2026-06-04). Anything else —
    # Grocery, Non-Commercial, Corporate — must NOT be a restaurant location.
    assert FOOD_SERVICE_TYPES == {"Restaurant", "Catering", "Recreational", "Concession"}


def test_only_food_service_types_count_as_restaurant():
    # The four whitelisted types each contribute one restaurant location;
    # non-whitelisted types (Grocery, Non-Commercial, "Bakery") are excluded
    # even when their classification says TARGET, because per WHA's own type
    # taxonomy they are not food-service.
    type_map = {
        "R1":  "Restaurant",     # ✓ counts
        "CA1": "Catering",       # ✓ counts
        "RE1": "Recreational",   # ✓ counts
        "CO1": "Concession",     # ✓ counts
        "G1":  "Grocery",        # ✗ excluded
        "NC1": "Non-Commercial", # ✗ excluded
        "B1":  "Bakery",         # ✗ excluded (defensive — unknown type)
        "H1":  "Hotel",          # → lodging, not restaurant
    }
    class_map = {aid: TARGET for aid in type_map}

    restaurant, lodging = _count_target_locations(type_map, class_map)

    assert restaurant == 4   # only the four whitelisted food-service types
    assert lodging == 1      # H1


def test_non_target_food_service_still_excluded():
    # No regression: Non-Target classification still wins over the whitelist.
    # A Non-Target Restaurant is excluded even though Restaurant is whitelisted.
    type_map  = {"R1": "Restaurant", "R2": "Restaurant"}
    class_map = {"R1": TARGET, "R2": NON_TARGET}

    restaurant, _lodging = _count_target_locations(type_map, class_map)

    assert restaurant == 1   # only R1


def test_non_target_pool_counts_use_penetration_restaurant_scope():
    # RATIFIED 2026-07-14 ("A"): penetration restaurant scope = Type 'Restaurant'
    # ONLY, matching the CRM penetration report the team trusts (verified
    # 3,331/3,331 of its actives). Catering/Recreational/Concession stay fully
    # counted in billables/retention/new-sales — just not in the restaurant %.
    type_map = {
        "R1": "Restaurant", "CA1": "Catering", "RE1": "Recreational",
        "CO1": "Concession", "G1": "Grocery", "H1": "Hotel",
    }
    class_map = {aid: NON_TARGET for aid in type_map}
    restaurant, lodging = _count_locations(type_map, class_map, target_class=NON_TARGET)
    assert restaurant == 1   # R1 only
    assert lodging == 1      # H1


def test_compute_penetration_returns_both_pools(monkeypatch):
    # End-to-end: compute_penetration_by_segment must surface both pools so
    # the Penetration Report can show Target % AND Non-Target % per segment.
    by_status = {
        "Active": {
            "RT1": ("Restaurant", TARGET),       # target restaurant active
            "RN1": ("Restaurant", NON_TARGET),   # non-target restaurant active
            "RN2": ("Restaurant", NON_TARGET),
            "HT1": ("Hotel",      TARGET),       # target lodging active
        },
        "Inactive": {
            "RT2": ("Restaurant", TARGET),       # adds to target restaurant market
            "RN3": ("Restaurant", NON_TARGET),   # adds to non-target restaurant market
        },
    }

    def fake_build_target_map(client, user_id, status=None, request_delay=0.0):
        return {aid: cls for aid, (_t, cls) in by_status[status].items()}

    def fake_get_type_map(client, user_id, status=None, request_delay=0.0):
        return {aid: t for aid, (t, _cls) in by_status[status].items()}

    def fake_get_subtype_map(client, user_id, status=None, request_delay=0.0):
        # Hotels get a market subtype (the 2026-07-19 lodging-universe rule)
        return {aid: ("Full Service Lodging" if t == "Hotel" else "")
                for aid, (t, _cls) in by_status[status].items()}

    monkeypatch.setattr(target_mod, "build_target_map", fake_build_target_map)
    monkeypatch.setattr(target_mod, "get_type_map", fake_get_type_map)
    monkeypatch.setattr(target_mod, "get_subtype_map", fake_get_subtype_map)

    out = compute_penetration_by_segment(client=None, territory_user_map={"U1": "Pierce"})
    seg = out["Pierce"]

    # Target pool unchanged
    assert seg["restaurant"]["active"] == 1   # RT1
    assert seg["restaurant"]["market"] == 2   # RT1 + RT2
    assert seg["lodging"]["active"]    == 1   # HT1
    assert seg["lodging"]["market"]    == 1

    # Non-Target pool — new keys
    assert seg["restaurant_nt"]["active"] == 2   # RN1 + RN2
    assert seg["restaurant_nt"]["market"] == 3   # RN1 + RN2 + RN3
    assert seg["lodging_nt"]["active"]    == 0
    assert seg["lodging_nt"]["market"]    == 0


def test_grocery_no_longer_counted_was_old_bug():
    # Regression for the documented over-count: pre-narrowing, a Target
    # Grocery account counted as a restaurant location, inflating both
    # numerator and denominator vs Hannah. After narrowing, it must not.
    type_map  = {"G1": "Grocery"}
    class_map = {"G1": TARGET}

    restaurant, lodging = _count_target_locations(type_map, class_map)

    assert restaurant == 0
    assert lodging == 0


# ---------------------------------------------------------------------------
# #1 — market denominator = Active + Inactive (never status=None)
# ---------------------------------------------------------------------------

def test_market_is_active_plus_inactive_never_all_statuses(monkeypatch):
    requested_statuses = []

    # Canned per-status universes. Corporate (C1) present to confirm it is
    # excluded from the resulting counts too.
    by_status = {
        "Active":   {"R1": ("Restaurant", TARGET),
                     "C1": ("Corporate",  TARGET),
                     "H1": ("Hotel",      TARGET)},
        "Inactive": {"R2": ("Restaurant", TARGET)},
    }

    def fake_build_target_map(client, user_id, status=None, request_delay=0.0):
        requested_statuses.append(status)
        # status=None would mean "all statuses" — the bug we are removing.
        assert status is not None, "market pass must not query all statuses"
        return {aid: cls for aid, (_t, cls) in by_status[status].items()}

    def fake_get_type_map(client, user_id, status=None, request_delay=0.0):
        return {aid: t for aid, (t, _cls) in by_status[status].items()}

    def fake_get_subtype_map(client, user_id, status=None, request_delay=0.0):
        # Hotels get a market subtype (the 2026-07-19 lodging-universe rule)
        return {aid: ("Full Service Lodging" if t == "Hotel" else "")
                for aid, (t, _cls) in by_status[status].items()}

    monkeypatch.setattr(target_mod, "build_target_map", fake_build_target_map)
    monkeypatch.setattr(target_mod, "get_type_map", fake_get_type_map)
    monkeypatch.setattr(target_mod, "get_subtype_map", fake_get_subtype_map)

    out = compute_penetration_by_segment(client=None, territory_user_map={"U1": "Pierce"})

    seg = out["Pierce"]
    # active restaurant = R1 (C1 corporate excluded); active lodging = H1
    assert seg["restaurant"]["active"] == 1
    assert seg["lodging"]["active"] == 1
    # market restaurant = R1 + R2 (Active + Inactive); corporate still excluded
    assert seg["restaurant"]["market"] == 2
    assert seg["lodging"]["market"] == 1

    assert set(requested_statuses) == {"Active", "Inactive"}
    assert None not in requested_statuses


# ---------------------------------------------------------------------------
# Lodging market universe = Crystal's SUBTYPE in-list (adopted 2026-07-19).
# Derived empirically from all 782 accounts in the raw Crystal lodging export:
# the report counts only true lodging subtypes; RV parks/campgrounds, vacation
# rentals, and military housing are NOT the hotel market even at 41+ spaces.
# Scope: PENETRATION ONLY — billables T/NT stays rooms-based (7/13 rule).
# ---------------------------------------------------------------------------

def test_lodging_market_subtypes_pin():
    from reports.membership_performance_tracker.logic.target import LODGING_MARKET_SUBTYPES
    assert LODGING_MARKET_SUBTYPES == {
        "Full Service Lodging", "Limited Service Lodging", "Economy Service Lodging",
        "Extended Stay", "Resort", "Gaming",
    }


def test_count_locations_excludes_non_market_lodging_subtypes():
    type_map  = {"H1": "Hotel", "H2": "Hotel", "H3": "Hotel"}
    class_map = {"H1": TARGET, "H2": TARGET, "H3": TARGET}
    subtype_map = {"H1": "Full Service Lodging", "H2": "RV Park or Campground ",  # trailing space = live data
                   "H3": "Vacation Rental"}
    r, l = _count_locations(type_map, class_map, target_class=TARGET, subtype_map=subtype_map)
    assert l == 1, "only the true lodging subtype counts; RV park + vacation rental are out"


def test_count_locations_warns_on_new_unknown_lodging_subtype():
    import warnings as w
    type_map  = {"H1": "Hotel"}
    class_map = {"H1": TARGET}
    with w.catch_warnings(record=True) as caught:
        w.simplefilter("always")
        r, l = _count_locations(type_map, class_map, target_class=TARGET,
                                subtype_map={"H1": "Boutique Capsule Pods"})
    assert l == 0, "unknown subtype must not silently count"
    assert any("Boutique Capsule Pods" in str(x.message) for x in caught)


def test_penetration_segment_applies_subtype_filter_end_to_end():
    """A 60-space ACTIVE RV park must be absent from lodging active AND market;
    a Full Service hotel counts. Restaurant side untouched."""
    class FakeSLX:
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            if entity == "accounts":
                return [
                    {"$key": "HF", "Id": "HF", "Type": "Hotel", "SubType": "Full Service Lodging"},
                    {"$key": "HR", "Id": "HR", "Type": "Hotel", "SubType": "RV Park or Campground"},
                ]
            if entity == "cMemberGens":
                return [{"Account": {"$key": "HF"}, "Rooms": 120},
                        {"Account": {"$key": "HR"}, "Rooms": 60}]
            return []

    seg = compute_penetration_by_segment(FakeSLX(), {"U1": "Pierce"}, request_delay=0.0)
    assert seg["Pierce"]["lodging"] == {"active": 1, "market": 1}, \
        "RV park (60 spaces, Target-sized) must be OUT of both numerator and market"
