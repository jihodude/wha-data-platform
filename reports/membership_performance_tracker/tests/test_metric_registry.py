"""Every metric must have a trace path — enforced, not promised (Jiho 8/6:
"make sure every metric being made traces back to its sources and
computation logic"). A mapper metric without a registry entry fails the
suite: numbers cannot exist here without an explanation card."""
from reports.membership_performance_tracker.mapper import METRIC_FIELD_MAP
from reports.membership_performance_tracker.metric_registry import REGISTRY, RULES


def test_every_mapper_metric_has_a_registry_entry():
    missing = [m for m in METRIC_FIELD_MAP if m not in REGISTRY]
    assert missing == [], f"metrics without a trace path: {missing}"


def test_every_registry_entry_is_complete_and_rule_refs_resolve():
    for name, e in REGISTRY.items():
        assert e["source"] in ("slx-live", "crystal-export", "admin",
                               "derived", "photo"), name
        assert len(e["card"]) > 20, f"{name}: card too thin to explain anything"
        for r in e["rules"]:
            assert r in RULES, f"{name}: unknown rule tag {r!r}"


def test_registry_has_no_orphan_entries():
    extra = [m for m in REGISTRY if m not in METRIC_FIELD_MAP]
    assert extra == [], f"registry entries for metrics that no longer exist: {extra}"
