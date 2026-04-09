from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from Services._shared.operator_engine.evaluator import ConditionEngine
from Services._shared.operator_engine.models import (
    AtomicCondition,
    CompositeCondition,
    EvaluationState,
    OperatorMetadata,
)
from Services._shared.operator_engine.registry import OperatorRegistry


@dataclass
class StubOperator:
    metadata: OperatorMetadata

    def evaluate(self, value: Any, params: dict[str, Any]) -> bool:
        threshold = params.get("threshold")
        if threshold is None:
            return bool(value)
        return value >= threshold


def _engine() -> ConditionEngine:
    registry = OperatorRegistry()
    registry.register(
        StubOperator(
            OperatorMetadata(
                name=">=",
                label="Greater Than Or Equal",
                description="Numeric threshold comparison",
                value_type="number",
                supports_for_s=True,
                param_schema={"threshold": {"type": "number", "required": True}},
            )
        )
    )
    registry.register(
        StubOperator(
            OperatorMetadata(
                name="truthy",
                label="Truthy",
                description="Truthy check",
                value_type="any",
                supports_for_s=False,
            )
        )
    )
    return ConditionEngine(registry)


def test_available_operators_exports_registry_metadata() -> None:
    operators = _engine().available_operators()

    assert operators == [
        {
            "name": ">=",
            "label": "Greater Than Or Equal",
            "description": "Numeric threshold comparison",
            "value_type": "number",
            "supports_for_s": True,
            "param_schema": {"threshold": {"type": "number", "required": True}},
        },
        {
            "name": "truthy",
            "label": "Truthy",
            "description": "Truthy check",
            "value_type": "any",
            "supports_for_s": False,
            "param_schema": {},
        },
    ]


def test_evaluate_atomic_missing_value_returns_non_match() -> None:
    result = _engine().evaluate(
        AtomicCondition(source="temp", operator=">=", params={"threshold": 10}, node_id="temp-check"),
        values={},
        now_monotonic=5.0,
    )

    assert result.matched is False
    assert result.raw_matched is False
    assert result.true_for_s == 0.0
    assert result.node_id == "temp-check"
    assert result.message == "Missing value for temp"
    assert result.observed_values == {"temp": None}


def test_evaluate_composite_any_and_not_aggregate_children() -> None:
    engine = _engine()
    any_result = engine.evaluate(
        CompositeCondition(
            kind="any",
            children=(
                AtomicCondition(source="temp", operator=">=", params={"threshold": 10}, node_id="hot"),
                AtomicCondition(source="running", operator="truthy", node_id="running"),
            ),
            node_id="root-any",
        ),
        values={"temp": 7, "running": True},
        now_monotonic=10.0,
    )

    not_result = engine.evaluate(
        CompositeCondition(
            kind="not",
            children=(AtomicCondition(source="temp", operator=">=", params={"threshold": 10}, node_id="temp-high"),),
            node_id="root-not",
        ),
        values={"temp": 7},
        now_monotonic=12.0,
        previous_state=EvaluationState(),
    )

    assert any_result.matched is True
    assert any_result.observed_values == {"temp": 7, "running": True}
    assert len(any_result.children) == 2
    assert any_result.message == "any condition"

    assert not_result.matched is True
    assert not_result.raw_matched is True
    assert not_result.message == "not condition"
    assert not_result.children[0].matched is False


def test_evaluate_composite_all_requires_all_children_to_match() -> None:
    result = _engine().evaluate(
        CompositeCondition(
            kind="all",
            children=(
                AtomicCondition(source="temp", operator=">=", params={"threshold": 10}),
                AtomicCondition(source="pressure", operator=">=", params={"threshold": 5}),
            ),
            node_id="root-all",
        ),
        values={"temp": 12, "pressure": 7},
        now_monotonic=3.0,
    )

    assert result.matched is True
    assert result.raw_matched is True
    assert result.observed_values == {"temp": 12, "pressure": 7}
    assert result.message == "all condition"


def test_evaluate_composite_not_requires_single_child() -> None:
    engine = _engine()

    with pytest.raises(ValueError, match="exactly one child"):
        engine.evaluate(
            CompositeCondition(
                kind="not",
                children=(
                    AtomicCondition(source="a", operator="truthy"),
                    AtomicCondition(source="b", operator="truthy"),
                ),
            ),
            values={"a": True, "b": False},
            now_monotonic=1.0,
        )


def test_evaluate_composite_rejects_unsupported_kind() -> None:
    engine = _engine()

    with pytest.raises(ValueError, match="Unsupported composite kind"):
        engine.evaluate(
            CompositeCondition(  # type: ignore[arg-type]
                kind="xor",
                children=(AtomicCondition(source="a", operator="truthy"),),
            ),
            values={"a": True},
            now_monotonic=1.0,
        )
