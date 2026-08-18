"""
test_target_join_robustness.py — duplicate cMemberGens/cRestProfiles rows must not
wipe a real Rooms/FTE value with a null.

Known dataset pattern (same as the retention Sage-sync duplicates): an account can
have 2+ rows in the custom tables, one populated and one null. build_target_map
used last-row-wins, so a trailing null row erased the value → account classified
Unknown → dropped from penetration (suspected mechanism behind the 276 missing
hotels / FTE-blank restaurants found 2026-07-13). Prefer non-null across rows.
"""
from reports.membership_performance_tracker.logic.target import (
    TARGET,
    build_target_map,
)


class FakeSLX:
    def __init__(self, accounts, membergens, restprofiles):
        self._t = {
            "accounts": accounts,
            "cMemberGens": membergens,
            "cRestProfiles": restprofiles,
        }

    def _fetch_all(self, entity, where="", select=None, page_size=200):
        return self._t[entity]


def test_null_duplicate_row_does_not_wipe_rooms():
    accounts = [{"$key": "H1", "Id": "H1", "Type": "Hotel"}]
    membergens = [
        {"Account": {"$key": "H1"}, "Rooms": 319},   # real value first
        {"Account": {"$key": "H1"}, "Rooms": None},  # trailing null duplicate
    ]
    tm = build_target_map(FakeSLX(accounts, membergens, []), "U1", status="Active",
                          request_delay=0.0)
    assert tm["H1"] == TARGET, "319-room hotel must stay Target despite a null dup row"


def test_null_duplicate_row_does_not_wipe_fte():
    accounts = [{"$key": "R1", "Id": "R1", "Type": "Restaurant"}]
    restprofiles = [
        {"Account": {"$key": "R1"}, "Avgrangefteperloc": "20 to 49"},
        {"Account": {"$key": "R1"}, "Avgrangefteperloc": None},
    ]
    tm = build_target_map(FakeSLX(accounts, [], restprofiles), "U2", status="Active",
                          request_delay=0.0)
    assert tm["R1"] == TARGET, "20-49 FTE restaurant must stay Target despite a null dup row"
