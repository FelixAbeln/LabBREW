from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ScenarioRunnerKind = Literal["scripted"]
ScenarioRunState = Literal["idle", "running", "paused", "completed", "stopped", "faulted"]


@dataclass(slots=True)
class ScenarioRunnerSpec:
    kind: str = "scripted"
    entrypoint: str | None = None
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "ScenarioRunnerSpec":
        data = payload if isinstance(payload, dict) else {}
        return cls(
            kind="scripted",
            entrypoint=(
                str(data.get("entrypoint")).strip()
                if data.get("entrypoint") is not None
                else None
            ),
            config=dict(data.get("config") or {}),
        )


@dataclass(slots=True)
class ScenarioPackageDefinition:
    id: str
    name: str
    version: str = "0.1.0"
    description: str = ""
    runner: ScenarioRunnerSpec = field(default_factory=ScenarioRunnerSpec)
    interface: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    editor_spec: dict[str, Any] = field(default_factory=dict)
    endpoint_code: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    program: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ScenarioPackageDefinition":
        if not isinstance(payload, dict):
            payload = {}
        return cls(
            id=str(payload.get("id", "scenario") or "scenario"),
            name=str(payload.get("name", "Scenario") or "Scenario"),
            version=str(payload.get("version", "0.1.0") or "0.1.0"),
            description=str(payload.get("description", "") or ""),
            runner=ScenarioRunnerSpec.from_payload(payload.get("runner")),
            interface=dict(payload.get("interface") or {}),
            validation=dict(payload.get("validation") or {}),
            editor_spec=dict(payload.get("editor_spec") or {}),
            endpoint_code=dict(payload.get("endpoint_code") or {}),
            artifacts=[
                dict(item)
                for item in (payload.get("artifacts") or [])
                if isinstance(item, dict)
            ],
            program=dict(payload.get("program") or {}),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScenarioCompileIssue:
    level: Literal["error", "warning"]
    code: str
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScenarioRunStatus:
    state: ScenarioRunState = "idle"
    package_id: str = ""
    package_name: str = ""
    runner_kind: str = "scripted"
    wait_message: str = "Idle"
    pause_reason: str | None = None
    event_log: list[str] = field(default_factory=list)
    owned_targets: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================================
# Legacy Schedule Service Models (kept for Excel importer compatibility)
# ============================================================================

ScheduleRunState = Literal["idle", "running", "paused", "completed", "stopped", "faulted"]
SchedulePhaseName = Literal["setup", "plan", "idle"]


@dataclass(slots=True)
class ScheduleAction:
    """Models an action within a schedule step (legacy format)."""
    kind: str
    target: str | None = None
    value: Any | None = None
    duration_s: float | None = None
    owner: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ScheduleAction:
        return cls(
            kind=str(payload.get("kind", "") or ""),
            target=payload.get("target"),
            value=payload.get("value"),
            duration_s=payload.get("duration_s"),
            owner=payload.get("owner"),
            params=dict(payload.get("params") or {}),
        )


@dataclass(slots=True)
class ScheduleStep:
    """Models a step within a schedule (legacy format)."""
    id: str
    name: str
    actions: list[ScheduleAction] = field(default_factory=list)
    wait: dict[str, Any] | None = None
    enabled: bool = True

    @classmethod
    def from_payload(cls, payload: dict[str, Any], fallback_id: str) -> ScheduleStep:
        return cls(
            id=str(payload.get("id", fallback_id) or fallback_id),
            name=str(payload.get("name", fallback_id) or fallback_id),
            actions=[
                ScheduleAction.from_payload(item)
                for item in (payload.get("actions") or [])
                if isinstance(item, dict)
            ],
            wait=payload.get("wait") if isinstance(payload.get("wait"), dict) else None,
            enabled=bool(payload.get("enabled", True)),
        )


@dataclass(slots=True)
class ScheduleDefinition:
    """Models a complete schedule with setup and plan phases (legacy format).
    
    Used by Excel importer to parse workbook schedules and convert them to
    scenario package payloads.
    """
    id: str
    name: str
    measurement_config: dict[str, Any] = field(default_factory=dict)
    setup_steps: list[ScheduleStep] = field(default_factory=list)
    plan_steps: list[ScheduleStep] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ScheduleDefinition:
        setup = [
            ScheduleStep.from_payload(item, fallback_id=f"setup-{idx + 1}")
            for idx, item in enumerate(payload.get("setup_steps") or [])
            if isinstance(item, dict)
        ]
        plan = [
            ScheduleStep.from_payload(item, fallback_id=f"plan-{idx + 1}")
            for idx, item in enumerate(payload.get("plan_steps") or [])
            if isinstance(item, dict)
        ]
        return cls(
            id=str(payload.get("id", "schedule") or "schedule"),
            name=str(payload.get("name", "Schedule") or "Schedule"),
            measurement_config=dict(payload.get("measurement_config") or {}),
            setup_steps=setup,
            plan_steps=plan,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
