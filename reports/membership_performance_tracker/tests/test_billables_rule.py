"""
test_billables_rule.py — billable = ACTIVE account carrying a MembershipProduct.

SOLVED 2026-07-14 (probe): actives-with-product matched the CRM by-territory
billables EXACTLY in 10/10 territories (Pierce 239=239, EastKing 185=185...,
statewide 2,294 vs 2,293). Child locations with their own product count
(Jen-confirmed). bm>12 is NOT an NRA marker (BMs 13-16 = unrelated special
groups); NRA lives in the Majors/NRA column via the house-user mapping.
Also: lodging Target = 41+ rooms (agreed 2026-07-13).
"""
from reports.membership_performance_tracker.logic.billables import (
    compute_billables_by_target,
)
from reports.membership_performance_tracker.logic.target import (
    NON_TARGET,
    TARGET,
    _classify_one,
)


def test_hotel_39_rooms_is_non_target():
    # 2026-07-21 Jennifer confirmed: 40 or more = Target, 39 or fewer = NT
    # (supersedes the 7/19 "41+" reading; matches the CRM penetration report)
    assert _classify_one("Hotel", rooms=39, fte_range=None) == NON_TARGET


def test_hotel_40_rooms_is_target():
    assert _classify_one("Hotel", rooms=40, fte_range=None) == TARGET


def _mg(key, prod):
    return {"Account": {"$key": key}, "MembershipProduct": prod, "Rooms": None,
            "Duesbillmonth": None}


class FakeSLXPerUser:
    def __init__(self, per_user):
        self._per_user = per_user

    def _fetch_all(self, entity, where="", select=None, page_size=200):
        for uid, tables in self._per_user.items():
            if uid in where:
                return tables.get(entity, [])
        return []


def test_billables_counts_product_carriers():
    u1 = {
        "accounts": [
            {"$key": "A1", "Id": "A1", "Type": "Restaurant"},  # product -> hosp Target
            {"$key": "A2", "Id": "A2", "Type": "Restaurant"},  # CHILD w/ product -> hosp NT
            {"$key": "A3", "Id": "A3", "Type": "Restaurant"},  # NO product -> not billable
            {"$key": "A4", "Id": "A4", "Type": "Allied"},      # product -> allied
        ],
        "cMemberGens": [_mg("A1", "Full Membership"), _mg("A2", "Full Membership"),
                        _mg("A3", None), _mg("A4", "Allied Membership"),
                        _mg("A1", "")],  # blank dup row must not matter
        "cRestProfiles": [
            {"Account": {"$key": "A1"}, "Avgrangefteperloc": "20 to 49"},
            {"Account": {"$key": "A2"}, "Avgrangefteperloc": "5 to 9"},
        ],
    }
    result = compute_billables_by_target(FakeSLXPerUser({"U1": u1}), {"U1": "Pierce"},
                                         request_delay=0.0)
    p = result["Pierce"]
    assert p["hospitality"] == 2, "A1 + A2 (product carriers); A3 has no product"
    assert p["allied"] == 1
    assert p["hospitality_target"] == 1 and p["hospitality_non_target"] == 1


def test_two_users_same_territory_counts_merge_not_overwrite():
    u1 = {"accounts": [{"$key": "M1", "Id": "M1", "Type": "Restaurant"}],
          "cMemberGens": [_mg("M1", "Full")],
          "cRestProfiles": [{"Account": {"$key": "M1"}, "Avgrangefteperloc": "20 to 49"}]}
    u2 = {"accounts": [{"$key": "N1", "Id": "N1", "Type": "Restaurant"},
                        {"$key": "N2", "Id": "N2", "Type": "Restaurant"}],
          "cMemberGens": [_mg("N1", "NRA"), _mg("N2", "NRA")],
          "cRestProfiles": []}
    result = compute_billables_by_target(
        FakeSLXPerUser({"U1": u1, "U2": u2}),
        {"U1": "Majors/NRA", "U2": "Majors/NRA"}, request_delay=0.0)
    m = result["Majors/NRA"]
    assert m["hospitality"] == 3, "U1's 1 + U2's 2 must merge, not overwrite"
    assert m["hospitality_target"] == 1


def test_allied_by_product_name_not_account_type():
    """D2 (2026-07-16, from Jen's own BillableByBMDetailAllied PDF): HER allied
    basis = the membership PRODUCT ("Allied Full"; Harbor Foods Group is Type
    Corporate but product 'Allied Corporate' → counted allied). Ours must match:
    allied = product name contains 'Allied', resolved via the products entity
    (live payloads carry the product as a nav {$key} object, not a name)."""
    class FakeWithProducts(FakeSLXPerUser):
        def _fetch_all(self, entity, where="", select=None, page_size=200):
            if entity == "products":
                return [{"$key": "P9", "Name": "Allied Corporate Dues"},
                        {"$key": "P1", "Name": "Full Membership Dues"}]
            return super()._fetch_all(entity, where, select, page_size)

    u1 = {
        "accounts": [
            {"$key": "HF", "Id": "HF", "Type": "Corporate"},   # Harbor Foods case
            {"$key": "R1", "Id": "R1", "Type": "Restaurant"},
        ],
        "cMemberGens": [_mg("HF", {"$key": "P9"}), _mg("R1", {"$key": "P1"})],
        "cRestProfiles": [
            {"Account": {"$key": "R1"}, "Avgrangefteperloc": "20 to 49"},
        ],
    }
    result = compute_billables_by_target(FakeWithProducts({"U1": u1}),
                                         {"U1": "Pierce"}, request_delay=0.0)
    p = result["Pierce"]
    assert p["allied"] == 1, "Corporate-typed account with Allied product = allied (her basis)"
    assert p["hospitality"] == 1


def test_billables_exclude_members_enrolled_after_the_reported_month():
    """Jen, 2026-07-30 (recorded, 33:19): "The hard part would be new members
    that join between the 1st and the 5th, because I don't activate them —
    I don't want them counted yet." And at 34:46: "**I would love to be able to
    activate members right away. So if we can fix that, that would be great.**"

    Billables is a live snapshot, so a member activated on August 3rd lands in
    the July snapshot and inflates it. Shannon's step 8: solve it by excluding
    records whose enroll date falls after the reported month, rather than by
    making Jen withhold activation.
    """
    from datetime import date
    from reports.membership_performance_tracker.logic.billables import (
        enrolled_after_period)

    period_end = date(2026, 7, 31)
    assert enrolled_after_period({"EnrolledDate": "/Date(1785801600000)/"},
                                 period_end) is True    # 2026-08-04 → excluded
    assert enrolled_after_period({"EnrolledDate": "/Date(1784073600000)/"},
                                 period_end) is False   # 2026-07-15 → kept
    # A member with no enroll date is KEPT — absence of evidence is not evidence
    # of a July sale, and dropping them would silently shrink the base.
    assert enrolled_after_period({}, period_end) is False
    assert enrolled_after_period({"EnrolledDate": None}, period_end) is False
