from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..models import OperatorMetadata


def as_float(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value)


def loosely_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return bool(left) is bool(right)
    try:
        return as_float(left) == as_float(right)
    except Exception:
        return left == right


@dataclass(frozen=True, slots=True)
class CallableOperator:
    metadata: OperatorMetadata
    fn: Callable[[Any, dict[str, Any]], bool]

    def evaluate(self, value: Any, params: dict[str, Any]) -> bool:
        return bool(self.fn(value, params))
