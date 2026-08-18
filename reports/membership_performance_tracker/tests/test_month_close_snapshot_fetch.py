"""The snapshot archive is the record; local disk is only a cache.

Found 2026-08-13, live, while recording the SOP: closing August failed with
"No snapshot exists from before 2026-08-13 06:00 — cannot freeze retention for
a pre-ITD state that was never photographed." The photograph HAD been taken —
SharePoint held 31 clean pre-ITD snapshots for August. `choose_snapshot` only
ever globbed a local directory, and Cloud Run empties that on every deploy, so
a freshly deployed console could not close a month at all and told the operator
the snapshot never existed.

It also swallowed the confirmation step: the console shows "Retention will be
saved as of <snapshot>" and only then offers "Confirm — close the month". With
no snapshot to name, the operator saw the error instead of the confirmation and
reasonably read it as the confirmation being missing.
"""
import json
from datetime import date, time
from pathlib import Path

import pytest

from reports.membership_performance_tracker.logic import month_close as mc


class _Hub:
    """Minimal stand-in for the SharePoint hub."""

    def __init__(self, names, payload=b'{"data": {}}'):
        self._names = names
        self._payload = payload
        self.reads = []

    def list_hub_folder(self, folder):
        return [{"name": n} for n in self._names]

    def read_hub_file(self, path):
        self.reads.append(path)
        return self._payload


# 13:00Z is 06:00 Pacific — the ITD cutoff used below.
CLEAN = "snapshot_2026-08_2026-08-13T09-02-48-000000-aaaaZ.json"   # 02:02 PDT
DIRTY = "snapshot_2026-08_2026-08-13T23-47-15-000000-bbbbZ.json"   # 16:47 PDT


def test_the_pre_itd_snapshot_is_fetched_when_local_disk_is_empty(tmp_path):
    d = tmp_path / "2026-08"
    d.mkdir()
    hub = _Hub([CLEAN, DIRTY, "snapshot_2026-08_official.json"])
    chosen = mc.choose_snapshot(d, date(2026, 8, 13), itd_time=time(6, 0), hub=hub)
    assert chosen.name == CLEAN, "must pick the last snapshot BEFORE ITD"
    assert chosen.exists(), "the chosen snapshot must be on disk to be read"
    assert len(hub.reads) == 1, "download exactly the one we need, not the archive"


def test_a_post_itd_snapshot_is_never_chosen_from_the_archive(tmp_path):
    d = tmp_path / "2026-08"
    d.mkdir()
    hub = _Hub([DIRTY])                      # only an after-ITD photo exists
    with pytest.raises(mc.NoCleanSnapshot):
        mc.choose_snapshot(d, date(2026, 8, 13), itd_time=time(6, 0), hub=hub)


def test_local_snapshots_still_win_and_no_fetch_happens(tmp_path):
    d = tmp_path / "2026-08"
    d.mkdir()
    (d / CLEAN).write_text(json.dumps({"data": {}}))
    hub = _Hub([CLEAN, DIRTY])
    chosen = mc.choose_snapshot(d, date(2026, 8, 13), itd_time=time(6, 0), hub=hub)
    assert chosen.name == CLEAN
    assert hub.reads == [], "a cached snapshot must not be re-downloaded"


def test_without_a_hub_the_old_behaviour_is_unchanged(tmp_path):
    d = tmp_path / "2026-08"
    d.mkdir()
    with pytest.raises(mc.NoCleanSnapshot):
        mc.choose_snapshot(d, date(2026, 8, 13), itd_time=time(6, 0))


def test_an_unreachable_archive_reports_no_snapshot_rather_than_crashing(tmp_path):
    d = tmp_path / "2026-08"
    d.mkdir()

    class _Broken:
        def list_hub_folder(self, folder):
            raise RuntimeError("network down")

    with pytest.raises(mc.NoCleanSnapshot):
        mc.choose_snapshot(d, date(2026, 8, 13), itd_time=time(6, 0), hub=_Broken())


# ── The post-ITD drops gate must compare CLOCK TIME, not just the date ───────
# Caught live on 8/13 while recording the SOP. The nightly lands ~02:00-03:00
# and ITD runs in the morning, so the capture that satisfies a date-only check
# is routinely from BEFORE ITD on the ITD date itself. Sealing then locks a
# pre-ITD drops photograph — the failure that put 1 July drop on the report
# where the real class had 16.

def _stub_capture(monkeypatch, day, moment):
    monkeypatch.setattr(mc, "_drops_capture_date_for", lambda p: day)
    monkeypatch.setattr(mc, "_drops_capture_moment_for", lambda p: moment)


def test_a_same_day_capture_taken_before_itd_is_refused(monkeypatch, tmp_path):
    from datetime import datetime
    _stub_capture(monkeypatch, date(2026, 8, 13),
                  datetime(2026, 8, 13, 3, 12))          # the 03:12 nightly
    with pytest.raises(mc.StaleCapture) as e:
        mc.freeze("2026-08", date(2026, 8, 13), itd_time=time(6, 0),
                  closes_dir=tmp_path)
    assert "03:12" in str(e.value), "say WHEN the capture ran"
    assert "pre-ITD" in str(e.value)


def test_a_same_day_capture_taken_after_itd_passes_the_gate(monkeypatch, tmp_path):
    from datetime import datetime
    _stub_capture(monkeypatch, date(2026, 8, 13),
                  datetime(2026, 8, 13, 9, 40))          # after a 06:00 ITD
    with pytest.raises(mc.NoCleanSnapshot):
        # Past the drops gate — it now fails later, on snapshots, which is the
        # proof the capture check let it through.
        mc.freeze("2026-08", date(2026, 8, 13), itd_time=time(6, 0),
                  closes_dir=tmp_path, snapshots_dir=tmp_path / "empty")


def test_the_time_check_is_skipped_when_it_is_not_the_same_day(monkeypatch, tmp_path):
    from datetime import datetime
    # Capture a day LATER than ITD: unambiguously post-ITD whatever the clock.
    _stub_capture(monkeypatch, date(2026, 8, 14),
                  datetime(2026, 8, 14, 2, 5))
    with pytest.raises(mc.NoCleanSnapshot):
        mc.freeze("2026-08", date(2026, 8, 13), itd_time=time(6, 0),
                  closes_dir=tmp_path, snapshots_dir=tmp_path / "empty")
