"""
test_hub_fallback.py — backward-compatible path resolution for the SP migration.

During the SharePoint folder restructure, admin inputs move from the flat root
(`Internal Dept Files/Membership Data Hub/admin_inputs.xlsx`) to the structured
location (`.../Inputs/admin_inputs.xlsx`). To migrate code-first without
breaking the live app, reads must try the NEW location first and fall back to the
OLD flat location. `resolve_first_available` pins that contract.
"""

import pytest

from src.hub.datahub import resolve_first_available


def test_returns_first_candidate_when_present():
    # New location exists → use it, never touch the fallback.
    store = {"new/admin.xlsx": b"NEW"}
    reads = []

    def read_fn(path):
        reads.append(path)
        if path in store:
            return store[path]
        raise FileNotFoundError(path)

    data, used = resolve_first_available(read_fn, ["new/admin.xlsx", "old/admin.xlsx"])
    assert data == b"NEW"
    assert used == "new/admin.xlsx"
    assert reads == ["new/admin.xlsx"]  # short-circuits, doesn't read the old path


def test_falls_back_to_second_candidate():
    # New location missing → fall back to the old flat path.
    store = {"old/admin.xlsx": b"OLD"}

    def read_fn(path):
        if path in store:
            return store[path]
        raise FileNotFoundError(path)

    data, used = resolve_first_available(read_fn, ["new/admin.xlsx", "old/admin.xlsx"])
    assert data == b"OLD"
    assert used == "old/admin.xlsx"


def test_returns_none_when_all_missing():
    def read_fn(path):
        raise FileNotFoundError(path)

    data, used = resolve_first_available(read_fn, ["new/admin.xlsx", "old/admin.xlsx"])
    assert data is None
    assert used is None


def test_non_filenotfound_errors_also_fall_through():
    # SharePoint can raise auth/transient errors, not just FileNotFoundError;
    # a failure on one candidate must not abort the whole resolution.
    def read_fn(path):
        if path == "new/admin.xlsx":
            raise RuntimeError("transient SharePoint error")
        return b"OLD"

    data, used = resolve_first_available(read_fn, ["new/admin.xlsx", "old/admin.xlsx"])
    assert data == b"OLD"
    assert used == "old/admin.xlsx"
