"""
test_hub_cache.py — session-cached fetch helper for the admin-inputs download.

The admin console re-renders constantly; without caching it does a live
SharePoint download on every render (~0.5-2s, sluggish). `get_or_fetch` caches
the fetched value in a dict-like store (Streamlit session_state) and only
re-fetches when forced (after an upload, or a manual "refresh" click).
"""

from src.hub.datahub import get_or_fetch


def test_fetches_and_stores_on_miss():
    store = {}
    calls = []

    def fetch():
        calls.append(1)
        return ("DATA", "source")

    value = get_or_fetch(store, "admin", fetch)
    assert value == ("DATA", "source")
    assert store["admin"] == ("DATA", "source")
    assert calls == [1]


def test_returns_cached_without_refetch():
    store = {"admin": ("CACHED", "source")}
    calls = []

    def fetch():
        calls.append(1)
        return ("FRESH", "source")

    value = get_or_fetch(store, "admin", fetch)
    assert value == ("CACHED", "source")  # served from cache
    assert calls == []                     # fetch_fn never called


def test_force_refetches_and_overwrites():
    store = {"admin": ("STALE", "source")}
    calls = []

    def fetch():
        calls.append(1)
        return ("FRESH", "source")

    value = get_or_fetch(store, "admin", fetch, force=True)
    assert value == ("FRESH", "source")
    assert store["admin"] == ("FRESH", "source")
    assert calls == [1]
