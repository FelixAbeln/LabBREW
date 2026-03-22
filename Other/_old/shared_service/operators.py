from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from schedule_service.models import ScheduleStep

Evaluator = Callable[[Any, dict[str, Any]], bool]


@dataclass(frozen=True, slots=True)
class OperatorDef:
    name: str
    evaluator: Evaluator
    description: str = ""
    arg_schema: dict[str, str] | None = None

    def evaluate(self, value: Any, params: dict[str, Any] | None = None) -> bool:
        return self.evaluator(value, params or {})


class OperatorRegistry:
    def __init__(self) -> None:
        self._operators: dict[str, OperatorDef] = {}

    def register(self, operator: OperatorDef) -> None:
        self._operators[operator.name] = operator

    def get(self, name: str) -> OperatorDef:
        if name not in self._operators:
            raise KeyError(f"Unknown operator: {name}")
        return self._operators[name]

    def evaluate(self, name: str, value: Any, params: dict[str, Any] | None = None) -> bool:
        return self.get(name).evaluate(value, params)

    def names(self) -> list[str]:
        return sorted(self._operators)


def _to_float(value: Any) -> float:
    return float(value)


def _cmp(expected_key: str, predicate: Callable[[float, float], bool]) -> Evaluator:
    def evaluate(value: Any, params: dict[str, Any]) -> bool:
        return predicate(_to_float(value), _to_float(params[expected_key]))

    return evaluate


def _in_range(value: Any, params: dict[str, Any]) -> bool:
    return _to_float(params["min"]) <= _to_float(value) <= _to_float(params["max"])


def _out_of_range(value: Any, params: dict[str, Any]) -> bool:
    return not _in_range(value, params)


def _loosely_equal(left: Any, right: Any) -> bool:
    try:
        return _to_float(left) == _to_float(right)
    except Exception:
        return left == right


def _equals(value: Any, params: dict[str, Any]) -> bool:
    return _loosely_equal(value, params["threshold"])


def _not_equals(value: Any, params: dict[str, Any]) -> bool:
    return not _equals(value, params)


def _valid_for(value: Any, params: dict[str, Any]) -> bool:
    return bool(value)


def build_default_operator_registry() -> OperatorRegistry:
    registry = OperatorRegistry()
    registry.register(OperatorDef(">=", _cmp("threshold", lambda a, b: a >= b), "value >= threshold", {"threshold": "number"}))
    registry.register(OperatorDef(">", _cmp("threshold", lambda a, b: a > b), "value > threshold", {"threshold": "number"}))
    registry.register(OperatorDef("<=", _cmp("threshold", lambda a, b: a <= b), "value <= threshold", {"threshold": "number"}))
    registry.register(OperatorDef("<", _cmp("threshold", lambda a, b: a < b), "value < threshold", {"threshold": "number"}))
    registry.register(OperatorDef("==", _equals, "threshold == expected", {"threshold": "any"}))
    registry.register(OperatorDef("!=", _not_equals, "threshold != expected", {"threshold": "any"}))
    registry.register(OperatorDef("in_range", _in_range, "min <= value <= max", {"min": "number", "max": "number"}))
    registry.register(OperatorDef("out_of_range", _out_of_range, "value outside inclusive range", {"min": "number", "max": "number"}))
    registry.register(OperatorDef("valid_for", _valid_for, "truthy value placeholder for validity holds", {}))
    return registry


def params_from_schedule_step(step: "ScheduleStep") -> dict[str, Any]:
    operator = str(getattr(step, "operator", "") or "")
    if operator in {"in_range", "out_of_range"}:
        return {"min": getattr(step, "threshold_low", None), "max": getattr(step, "threshold_high", None)}
    threshold = getattr(step, "threshold", None)
    return {"threshold": threshold}


def evaluate_schedule_condition(
    step: "ScheduleStep",
    value: Any,
    *,
    registry: OperatorRegistry | None = None,
) -> bool:
    if value is None:
        return False
    operator = str(getattr(step, "operator", "") or "").strip()
    if not operator:
        return False

    active_registry = registry or build_default_operator_registry()
    params = params_from_schedule_step(step)

    if operator in {"in_range", "out_of_range"}:
        if params.get("min") is None or params.get("max") is None:
            return False
    elif operator in {">=", ">", "<=", "<", "==", "!="}:
        required_key = "threshold"
        if params.get(required_key) is None:
            return False

    try:
        return active_registry.evaluate(operator, value, params)
    except Exception:
        return False
