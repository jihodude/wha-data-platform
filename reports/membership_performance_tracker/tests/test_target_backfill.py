"""
test_target_backfill.py — build_target_map must BACKFILL missing rooms/FTE by
account-Id batches when the per-territory bulk query under-fetches.

Proven live 2026-07-14: the bulk per-rep queries of cMemberGens/cRestProfiles
return incomplete rows (shortfall scales with territory size; Southeast exact),
while per-account-Id fetches are complete (782/782 hotel rooms, 4,907/4,910
restaurant FTE bands). Fix: after the bulk pass, re-fetch ONLY the accounts still
missing size data, in Id-batches — few extra queries, complete classification.
"""
from reports.membership_performance_tracker.logic.target import TARGET, build_target_map


class FakeSLX:
    """Bulk queries (where contains AccountManager) return INCOMPLETE custom-table
    rows; Id-batch queries (where contains Account.Id) return the missing rows."""

    def __init__(self):
        self.id_batch_queries = 0

    def _fetch_all(self, entity, where="", select=None, page_size=200):
        bulk = "AccountManager" in where
        if entity == "accounts":
            return [
                {"$key": "H1", "Id": "H1", "Type": "Hotel"},
                {"$key": "R1", "Id": "R1", "Type": "Restaurant"},
                {"$key": "R2", "Id": "R2", "Type": "Restaurant"},
            ]
        if entity == "cMemberGens":
            if bulk:
                return []  # bulk under-fetch: H1's rooms row missing
            self.id_batch_queries += 1
            assert "Account.Id eq 'H1'" in where
            return [{"Account": {"$key": "H1"}, "Rooms": 319}]
        if entity == "cRestProfiles":
            if bulk:
                # bulk got R1 but MISSED R2
                return [{"Account": {"$key": "R1"}, "Avgrangefteperloc": "20 to 49"}]
            self.id_batch_queries += 1
            assert "Account.Id eq 'R2'" in where and "R1" not in where
            return [{"Account": {"$key": "R2"}, "Avgrangefteperloc": "10 to 19"}]
        raise AssertionError(entity)


def test_backfill_recovers_bulk_underfetch():
    client = FakeSLX()
    tm = build_target_map(client, "U1", status="Active", request_delay=0.0)
    assert tm["H1"] == TARGET, "319-room hotel must classify via Id-batch backfill"
    assert tm["R1"] == TARGET, "bulk-fetched FTE still works"
    assert tm["R2"] == TARGET, "missed restaurant must classify via backfill"
    assert client.id_batch_queries == 2, "one backfill batch per table, only for missing"
