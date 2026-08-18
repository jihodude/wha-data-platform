"""
test_fetch_by_id_batches.py — locks in the SData under-fetch workaround
(2026-07-17 consolidation). The per-territory join under-fetches custom tables;
the fix is to re-fetch by account Id in batches, one `Account.Id eq 'X' or ...`
where-clause per chunk. This was pasted in retention / target-backfill /
attribution; it's now ONE standalone `fetch_by_id_batches(client, ...)`.

Standalone (not a method) is deliberate: any object implementing `_fetch_all`
— including the FakeSLX test doubles — must work unchanged. Regression guards:
  1. ids are chunked by `batch_size` (partial final chunk included).
  2. each chunk's where is exactly `(Account.Id eq 'a' or Account.Id eq 'b' …)`.
     If this format ever drifts, every per-territory join silently under-fetches
     again — the exact bug this works around.
  3. results come back FLAT across chunks; `page_size` is threaded through.
"""
from src.slx.client import fetch_by_id_batches


class RecordingClient:
    """Minimal `_fetch_all` provider — proves the helper needs nothing else."""

    def __init__(self):
        self.calls = []  # (entity, where, page_size)

    def _fetch_all(self, entity, where="", select=None, page_size=200):
        self.calls.append((entity, where, page_size))
        # one record per id in the chunk, echoing the account key
        ids = [tok.split("'")[1] for tok in where.split(" or ")]
        return [{"Account": {"$key": a}, "n": i} for i, a in enumerate(ids)]


def test_chunks_by_batch_size_including_partial_final():
    client = RecordingClient()
    ids = [f"A{i}" for i in range(25)]
    out = fetch_by_id_batches(client, "cMemberGens", ids, batch_size=10, page_size=100)
    # 25 ids / 10 => chunks of 10, 10, 5
    assert [len(c[1].split(" or ")) for c in client.calls] == [10, 10, 5]
    # every account came back, flat, once
    assert sorted(r["Account"]["$key"] for r in out) == sorted(ids)
    assert len(out) == 25


def test_where_clause_is_id_disjunction_and_page_size_threaded():
    client = RecordingClient()
    fetch_by_id_batches(client, "AccountExtension", ["H1", "H2"],
                        batch_size=20, page_size=40)
    entity, where, page_size = client.calls[0]
    assert entity == "AccountExtension"
    assert where == "(Account.Id eq 'H1' or Account.Id eq 'H2')"
    assert page_size == 40


def test_empty_ids_makes_no_calls():
    client = RecordingClient()
    out = fetch_by_id_batches(client, "cMemberGens", [], batch_size=20)
    assert out == []
    assert client.calls == []
