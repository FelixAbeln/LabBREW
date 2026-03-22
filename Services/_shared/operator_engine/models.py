from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ValueType = Literal['number', 'bool', 'any']


@dataclass(frozen=True, slots=True)
class OperatorMetadata:
    name: str
    label: str
    description: str
    value_type: ValueType = 'any'
    param_schema: dict[str, dict[str, Any]] = field(default_factory=dict)
    supports_for_s: bool = True


@dataclass(frozen=True, slots=True)
class AtomicCondition:
    source: str
    operator: str
    params: dict[str, Any] = field(default_factory=dict)
    for_s: float = 0.0
    node_id: str | None = None
    label: str = ''


@dataclass(frozen=True, slots=True)
class CompositeCondition:
    kind: Literal['all', 'any', 'not']
    children: tuple['ConditionNode', ...]
    for_s: float = 0.0
    node_id: str | None = None
    label: str = ''


ConditionNode = AtomicCondition | CompositeCondition


@dataclass(slots=True)
class NodeState:
    true_since_monotonic: float | None = None
    last_raw_matched: bool | None = None


@dataclass(slots=True)
class EvaluationState:
    nodes: dict[str, NodeState] = field(default_factory=dict)

    def get_or_create(self, node_id: str) -> NodeState:
        state = self.nodes.get(node_id)
        if state is None:
            state = NodeState()
            self.nodes[node_id] = state
        return state


@dataclass(slots=True)
class EvaluationResult:
    matched: bool
    raw_matched: bool
    true_for_s: float
    node_id: str
    message: str
    observed_values: dict[str, Any] = field(default_factory=dict)
    children: list['EvaluationResult'] = field(default_factory=list)
    next_state: EvaluationState = field(default_factory=EvaluationState)
