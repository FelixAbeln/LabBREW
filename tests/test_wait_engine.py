from __future__ import annotations

import pytest

from Services._shared.operator_engine import AtomicCondition, CompositeCondition, ConditionEngine, EvaluationState, load_registry_from_package
from Services._shared.wait_engine import WaitContext, WaitEngine, parse_condition_node, parse_wait_spec
from Services._shared.wait_engine.models import WaitResult, WaitSpec, WaitState


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


def test_wait_engine_none_spec_and_missing_condition_state_paths() -> None:
    engine = _engine()

    none_result = engine.evaluate(
        None,
        context=WaitContext(now_monotonic=1.0),
    )
    condition_result = engine.evaluate(
        WaitSpec(kind="condition", condition={"source": "temp", "operator": ">=", "threshold": 5}),
        context=WaitContext(now_monotonic=2.0, values={"temp": 7}),
        previous_state=WaitState(condition_state=None),
    )

    assert none_result.matched is True
    assert none_result.message == "No wait"
    assert condition_result.matched is True
    assert condition_result.observed_values == {"temp": 7}


def test_wait_engine_any_of_without_child_messages_uses_kind_only() -> None:
    class BlankMessageWaitEngine(WaitEngine):
        def _evaluate(self, spec, *, context, state, path):  # type: ignore[override]
            if path == "root":
                return super()._evaluate(spec, context=context, state=state, path=path)
            result = super()._evaluate(WaitSpec(kind="none"), context=context, state=state, path=path)
            return WaitResult(
                matched=result.matched,
                message="",
                observed_values=result.observed_values,
                children=result.children,
                next_state=result.next_state,
            )

    engine = BlankMessageWaitEngine(_engine()._condition_engine)
    result = engine.evaluate(
        WaitSpec(kind="any_of", children=(WaitSpec(kind="none"), WaitSpec(kind="none"))),
        context=WaitContext(now_monotonic=1.0),
    )

    assert result.matched is True
    assert result.message == "any_of"


def test_wait_engine_rejects_unsupported_wait_kind_directly() -> None:
    with pytest.raises(ValueError, match="Unsupported wait kind"):
        _engine().evaluate(
            WaitSpec(kind="later"),  # type: ignore[arg-type]
            context=WaitContext(now_monotonic=1.0),
        )


def test_parse_wait_spec_and_condition_node_edge_cases() -> None:
    assert parse_wait_spec("") is None
    assert parse_wait_spec(False) is None

    passthrough = AtomicCondition(source="temp", operator=">=")
    assert parse_condition_node(passthrough) is passthrough

    composite_all = parse_condition_node({"all": [{"source": "temp", "operator": ">=", "threshold": 5}], "for_s": 1})
    composite_any = parse_condition_node({"any": [{"source": "temp", "operator": ">=", "threshold": 5}]})
    composite_not = parse_condition_node({"not": {"source": "alarm", "operator": "==", "threshold": True}, "for_s": 2})

    assert isinstance(composite_all, CompositeCondition)
    assert composite_all.kind == "all"
    assert composite_all.for_s == 1.0
    assert isinstance(composite_any, CompositeCondition)
    assert composite_any.kind == "any"
    assert isinstance(composite_not, CompositeCondition)
    assert composite_not.kind == "not"
    assert composite_not.for_s == 2.0

    nested = parse_wait_spec({"kind": "all_of", "children": [None, {"kind": "elapsed", "duration_s": 2}]})
    assert nested is not None
    assert nested.children[0].kind == "none"
    assert nested.children[1].kind == "elapsed"

    with pytest.raises(ValueError, match="wait spec must be a dict"):
        parse_wait_spec(123)

    with pytest.raises(ValueError, match="condition must be a dict"):
        parse_condition_node(123)