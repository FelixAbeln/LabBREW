from __future__ import annotations

import pytest

from Services._shared.operator_engine import ConditionEngine, EvaluationState, load_registry_from_package
from Services._shared.wait_engine import WaitContext, WaitEngine, parse_condition_node, parse_wait_spec


def _engine() -> WaitEngine:
    registry = load_registry_from_package("Services._shared.operator_engine.plugins")
    return WaitEngine(ConditionEngine(registry))


def test_parse_wait_spec_and_condition_node_support_nested_payloads() -> None:
    spec = parse_wait_spec(
        {
            "kind": "all_of",
            "children": [
                {"kind": "elapsed", "duration_s": 1.5},
                {
                    "kind": "condition",
                    "condition": {
                        "all": [
                            {"source": "temp", "operator": ">=", "threshold": 10},
                            {"not": {"source": "alarm", "operator": "==", "threshold": True}},
                        ]
                    },
                },
            ],
        }
    )

    assert spec is not None
    assert spec.kind == "all_of"
    assert spec.children[0].kind == "elapsed"
    condition = parse_condition_node({"source": "temp", "operator": ">=", "threshold": 10})
    assert condition.params == {"threshold": 10}


def test_wait_engine_elapsed_requires_started_time() -> None:
    result = _engine().evaluate(
        parse_wait_spec({"kind": "elapsed", "duration_s": 3.0}),
        context=WaitContext(now_monotonic=10.0, step_started_monotonic=None),
    )

    assert result.matched is False
    assert result.message == "Step not started"


def test_wait_engine_condition_honors_hold_time_between_evaluations() -> None:
    engine = _engine()
    spec = parse_wait_spec(
        {
            "kind": "condition",
            "condition": {"source": "temp", "operator": ">=", "threshold": 10, "for_s": 2.0},
        }
    )

    first = engine.evaluate(
        spec,
        context=WaitContext(now_monotonic=100.0, values={"temp": 12.0}),
    )
    second = engine.evaluate(
        spec,
        context=WaitContext(now_monotonic=102.1, values={"temp": 12.0}),
        previous_state=first.next_state,
    )

    assert first.matched is False
    assert second.matched is True
    assert second.next_state.condition_state is not None


def test_wait_engine_all_of_and_any_of_aggregate_children() -> None:
    engine = _engine()

    all_result = engine.evaluate(
        parse_wait_spec(
            {
                "kind": "all_of",
                "children": [
                    {"kind": "elapsed", "duration_s": 1.0},
                    {"kind": "condition", "condition": {"source": "temp", "operator": ">", "threshold": 5}},
                ],
            }
        ),
        context=WaitContext(now_monotonic=5.0, step_started_monotonic=3.0, values={"temp": 7}),
        previous_state=None,
    )

    any_result = engine.evaluate(
        parse_wait_spec(
            {
                "kind": "any_of",
                "children": [
                    {"kind": "condition", "condition": {"source": "temp", "operator": "<", "threshold": 0}},
                    {"kind": "condition", "condition": {"source": "temp", "operator": ">", "threshold": 5}},
                ],
            }
        ),
        context=WaitContext(now_monotonic=5.0, values={"temp": 7}),
        previous_state=None,
    )

    assert all_result.matched is True
    assert len(all_result.children) == 2
    assert "all_of" in all_result.message
    assert any_result.matched is True
    assert any_result.observed_values["temp"] == 7


def test_parse_wait_spec_rejects_unsupported_kind() -> None:
    with pytest.raises(ValueError):
        parse_wait_spec({"kind": "later"})