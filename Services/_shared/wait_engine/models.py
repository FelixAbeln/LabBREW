from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


WaitKind = Literal['none', 'elapsed', 'condition', 'all_of', 'any_of', 'rising', 'falling', 'pulse']


@dataclass(frozen=True, slots=True)
class WaitSpec:
    kind: WaitKind = 'none'
    duration_s: float | None = None
    hold_s: float | None = None
    condition: Any | None = None
    child: 'WaitSpec | None' = None
    children: tuple['WaitSpec', ...] = ()
    label: str = ''
    node_id: str | None = None


@dataclass(slots=True)
class EventNodeState:
    previous_child_matched: bool = False
    pulse_started_monotonic: float | None = None


@dataclass(slots=True)
class WaitContext:
    now_monotonic: float
    step_started_monotonic: float | None = None
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WaitState:
    condition_state: Any | None = None
    event_nodes: dict[str, EventNodeState] = field(default_factory=dict)


@dataclass(slots=True)
class WaitResult:
    matched: bool
    message: str
    observed_values: dict[str, Any] = field(default_factory=dict)
    children: list['WaitResult'] = field(default_factory=list)
    next_state: WaitState = field(default_factory=WaitState)
