"""pulled_at — only a live SLX pull may set it (Jiho's 8/6 catch: 'was
cache really made 0s ago?' — a cosmetic rebuild had re-stamped the data's
timestamp, so the console claimed a fresh pull that never happened).
Rebuild saves must carry the original pull time forward untouched."""
import json
from pathlib import Path

from reports.membership_performance_tracker.logic.cache import save_scoreboard
from reports.membership_performance_tracker.logic.model import empty_scoreboard

_FY = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
       "Apr", "May", "Jun", "Jul", "Aug", "Sep"]


def test_live_pull_sets_pulled_at_and_rebuilds_preserve_it(tmp_path):
    p = tmp_path / "scoreboard_2026-07.json"
    d = empty_scoreboard(_FY)

    save_scoreboard(d, p, source="slx-preoverlay")
    first = json.loads(p.read_text())["_meta"]
    assert first.get("pulled_at"), "a live pull must stamp pulled_at"

    save_scoreboard(d, p, source="sp-published")
    second = json.loads(p.read_text())["_meta"]
    assert second["pulled_at"] == first["pulled_at"], \
        "a rebuild must NEVER move the pull time"
    assert second["saved_at"] >= first["saved_at"]

    save_scoreboard(d, p, source="slx-preoverlay")
    third = json.loads(p.read_text())["_meta"]
    assert third["pulled_at"] >= second["pulled_at"], \
        "a NEW live pull moves pulled_at forward"
