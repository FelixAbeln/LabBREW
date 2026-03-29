from __future__ import annotations

import Services.control_service.rules.engine as rule_engine_module
from Services.control_service.rules.engine import RuleEngine


def test_rule_engine_honors_hold_time_and_reuses_state(monkeypatch) -> None:
    now = {"t": 100.0}

    monkeypatch.setattr(rule_engine_module.time, "monotonic", lambda: now["t"])

    engine = RuleEngine()
    rule = {
        "id": "rule-1",
        "condition": {
            "source": "reactor.temp",
            "operator": ">=",
            "params": {"threshold": 10.0},
            "for_s": 2.0,
        },
    }

    first = engine.evaluate(rule, {"reactor.temp": 12.5})
    assert first.raw_matched is True
    assert first.matched is False

    now["t"] = 102.2
    second = engine.evaluate(rule, {"reactor.temp": 12.5})
    assert second.matched is True
    assert second.true_for_s >= 2.0
    assert "rule:rule-1" in second.next_state.nodes


def test_rule_engine_reports_missing_values_without_match() -> None:
    engine = RuleEngine()
    rule = {
        "id": "missing-source",
        "condition": {"source": "unknown", "operator": "==", "params": {"threshold": 1}},
    }

    result = engine.evaluate(rule, {})

    assert result.matched is False
    assert result.raw_matched is False
    assert result.message == "Missing value for unknown"


def test_rule_engine_prunes_state_and_locks_for_removed_rules() -> None:
    engine = RuleEngine()
    engine.evaluate(
        {
            "id": "keep-me",
            "condition": {"source": "x", "operator": "==", "params": {"threshold": 1}},
        },
        {"x": 1},
    )
    engine.evaluate(
        {
            "id": "drop-me",
            "condition": {"source": "x", "operator": "==", "params": {"threshold": 2}},
        },
        {"x": 2},
    )

    engine.prune_rules({"keep-me"})

    assert set(engine._states) == {"keep-me"}
    assert set(engine._rule_locks) == {"keep-me"}