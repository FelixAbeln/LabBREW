
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


RunState = Literal['idle', 'running', 'paused', 'completed', 'stopped', 'faulted']
PhaseName = Literal['setup', 'plan', 'idle']


@dataclass(slots=True)
class ScheduleAction:
    kind: str
    target: str | None = None
    value: Any | None = None
    duration_s: float | None = None
    owner: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> 'ScheduleAction':
        return cls(
            kind=str(payload.get('kind', '') or ''),
            target=payload.get('target'),
            value=payload.get('value'),
            duration_s=payload.get('duration_s'),
            owner=payload.get('owner'),
            params=dict(payload.get('params') or {}),
        )


@dataclass(slots=True)
class ScheduleStep:
    id: str
    name: str
    actions: list[ScheduleAction] = field(default_factory=list)
    wait: dict[str, Any] | None = None
    enabled: bool = True

    @classmethod
    def from_payload(cls, payload: dict[str, Any], fallback_id: str) -> 'ScheduleStep':
        return cls(
            id=str(payload.get('id', fallback_id) or fallback_id),
            name=str(payload.get('name', fallback_id) or fallback_id),
            actions=[ScheduleAction.from_payload(item) for item in (payload.get('actions') or []) if isinstance(item, dict)],
            wait=payload.get('wait') if isinstance(payload.get('wait'), dict) else None,
            enabled=bool(payload.get('enabled', True)),
        )


@dataclass(slots=True)
class ScheduleDefinition:
    id: str
    name: str
    setup_steps: list[ScheduleStep] = field(default_factory=list)
    plan_steps: list[ScheduleStep] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> 'ScheduleDefinition':
        setup = [
            ScheduleStep.from_payload(item, fallback_id=f'setup-{idx + 1}')
            for idx, item in enumerate(payload.get('setup_steps') or [])
            if isinstance(item, dict)
        ]
        plan = [
            ScheduleStep.from_payload(item, fallback_id=f'plan-{idx + 1}')
            for idx, item in enumerate(payload.get('plan_steps') or [])
            if isinstance(item, dict)
        ]
        return cls(
            id=str(payload.get('id', 'schedule') or 'schedule'),
            name=str(payload.get('name', 'Schedule') or 'Schedule'),
            setup_steps=setup,
            plan_steps=plan,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StepRuntime:
    actions_applied: bool = False
    started_monotonic: float | None = None
    started_at_utc: str | None = None
    wait_state: Any | None = None
    pending_exit_loadsteps: set[str] = field(default_factory=set)


@dataclass(slots=True)
class RunStatus:
    state: RunState = 'idle'
    phase: PhaseName = 'idle'
    schedule_id: str = ''
    schedule_name: str = ''
    current_step_index: int = -1
    current_step_name: str = ''
    wait_message: str = 'Idle'
    pause_reason: str | None = None
    owned_targets: list[str] = field(default_factory=list)
    last_action_result: dict[str, Any] = field(default_factory=dict)
    event_log: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
