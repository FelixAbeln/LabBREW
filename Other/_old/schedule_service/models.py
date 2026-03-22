from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any




def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    txt = str(value).strip().lower()
    if txt in {"1", "true", "yes", "y", "on"}:
        return True
    if txt in {"0", "false", "no", "n", "off"}:
        return False
    return default

class RunState(str, Enum):
    IDLE = "idle"
    STARTUP = "startup"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAULTED = "faulted"
    STOPPED = "stopped"


@dataclass(slots=True)
class StepAction:
    """A direct write to a ParameterDB / SignalStore key."""

    target_key: str
    value: Any
    ramp_per_s: float | None = None
    raw_value: str = ""

    @property
    def display_text(self) -> str:
        if self.ramp_per_s is None:
            return f"{self.target_key}:{self.value}"
        return f"{self.target_key}:{self.value}:{self.ramp_per_s}"

    def to_payload(self) -> dict[str, Any]:
        return {
            "target_key": self.target_key,
            "value": self.value,
            "ramp_per_s": self.ramp_per_s,
            "raw_value": self.raw_value,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "StepAction":
        return cls(
            target_key=str(payload.get("target_key", "") or ""),
            value=payload.get("value"),
            ramp_per_s=_float_or_none(payload.get("ramp_per_s")),
            raw_value=str(payload.get("raw_value", "") or ""),
        )


@dataclass(slots=True)
class ScheduleStep:
    index: int
    enabled: bool = True
    name: str = ""
    wait_type: str = "elapsed_time"
    wait_source: str = ""
    operator: str = ">="
    threshold: float | bool | str | None = None
    threshold_low: float | None = None
    threshold_high: float | None = None
    duration_s: float | None = None
    hold_for_s: float = 0.0
    valid_sources: list[str] = field(default_factory=list)
    require_confirmation: bool = False
    confirmation_message: str = ""
    actions: list[StepAction] = field(default_factory=list)
    notes: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "enabled": self.enabled,
            "name": self.name,
            "wait_type": self.wait_type,
            "wait_source": self.wait_source,
            "operator": self.operator,
            "threshold": self.threshold,
            "threshold_low": self.threshold_low,
            "threshold_high": self.threshold_high,
            "duration_s": self.duration_s,
            "hold_for_s": self.hold_for_s,
            "valid_sources": list(self.valid_sources),
            "require_confirmation": self.require_confirmation,
            "confirmation_message": self.confirmation_message,
            "actions": [action.to_payload() for action in self.actions],
            "notes": self.notes,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any], fallback_index: int = 0) -> "ScheduleStep":
        valid_sources = payload.get("valid_sources") or []
        if not isinstance(valid_sources, list):
            valid_sources = [part.strip() for part in str(valid_sources).split(",") if part.strip()]
        actions = payload.get("actions") or payload.get("controller_actions") or []
        return cls(
            index=int(payload.get("index", fallback_index) or fallback_index),
            enabled=_bool_value(payload.get("enabled"), default=True),
            name=str(payload.get("name", "") or f"Step {fallback_index + 1}"),
            wait_type=str(payload.get("wait_type", "elapsed_time") or "elapsed_time"),
            wait_source=str(payload.get("wait_source", "") or ""),
            operator=str(payload.get("operator", ">=") or ">="),
            threshold=payload.get("threshold"),
            threshold_low=_float_or_none(payload.get("threshold_low")),
            threshold_high=_float_or_none(payload.get("threshold_high")),
            duration_s=_float_or_none(payload.get("duration_s")),
            hold_for_s=float(_float_or_none(payload.get("hold_for_s")) or 0.0),
            valid_sources=[str(item).strip() for item in valid_sources if str(item).strip()],
            require_confirmation=_bool_value(payload.get("require_confirmation"), default=bool(payload.get("confirmation_message"))),
            confirmation_message=str(payload.get("confirmation_message", "") or ""),
            actions=[StepAction.from_payload(item) for item in actions if isinstance(item, dict)],
            notes=str(payload.get("notes", "") or ""),
        )


@dataclass(slots=True)
class StartupStatus:
    active: bool = False
    stage: str = "idle"
    message: str = ""


@dataclass(slots=True)
class RunStatus:
    state: str = RunState.IDLE.value
    phase: str = "idle"
    workbook_path: str = ""
    startup_sheet_name: str = ""
    plan_sheet_name: str = ""
    current_step_index: int = -1
    current_step_name: str = ""
    step_elapsed_s: float = 0.0
    hold_elapsed_s: float = 0.0
    wait_reason: str = "Idle"
    awaiting_confirmation: bool = False
    confirmation_message: str = ""
    last_transition: str = ""
    startup: StartupStatus = field(default_factory=StartupStatus)
    active_actions: list[dict[str, Any]] = field(default_factory=list)
    startup_steps: list[dict[str, Any]] = field(default_factory=list)
    plan_steps: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    event_log: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
