from __future__ import annotations

import threading
import time
from .excel_loader import ExcelScheduleLoader
from .models import RunState, RunStatus, ScheduleStep, StartupStatus, StepAction
from .schedule_codec import ScheduleCodec
from ..shared_service.backend import SignalStoreBackend
from ..shared_service.condition_engine import evaluate_step_wait
from ..shared_service.operators import OperatorRegistry, build_default_operator_registry


class FcsRuntimeService:
    def __init__(self, backend: SignalStoreBackend, poll_interval_s: float = 0.25) -> None:
        self.backend = backend
        self.loader = ExcelScheduleLoader()
        self.codec = ScheduleCodec()
        self.poll_interval_s = max(0.05, float(poll_interval_s))
        self.operator_registry: OperatorRegistry = build_default_operator_registry()

        self._startup_steps: list[ScheduleStep] = []
        self._plan_steps: list[ScheduleStep] = []
        self._active_steps: list[ScheduleStep] = []
        self._active_phase = "idle"
        self._status = RunStatus()

        self._step_started_monotonic: float | None = None
        self._hold_started_monotonic: float | None = None
        self._action_ramp_state: dict[str, tuple[float, float]] = {}
        self._last_applied_values: dict[str, Any] = {}

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def start_background(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, name="fcs-runtime", daemon=True)
            self._thread.start()

    def shutdown(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    def validate_schedule_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.codec.validate_payload(payload)

    def upload_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        startup_steps, plan_steps, metadata, source = self.codec.parse_payload(payload)
        source_name = str(source.get("name", "uploaded schedule") or "uploaded schedule")
        startup_sheet = str(metadata.get("startup_sheet", "StartupRoutine") or "StartupRoutine")
        plan_sheet = str(metadata.get("plan_sheet", "Plan") or "Plan")
        workbook_name = str(metadata.get("workbook_name", source_name) or source_name)
        with self._lock:
            self._apply_loaded_schedule_locked(
                startup_steps=startup_steps,
                plan_steps=plan_steps,
                workbook_path=workbook_name,
                startup_sheet=startup_sheet,
                plan_sheet=plan_sheet,
                source_kind=str(source.get("kind", "api_upload") or "api_upload"),
                source_name=source_name,
                event_message=f"Loaded schedule upload: {workbook_name}",
            )
            return {
                "ok": True,
                "message": f"Loaded schedule upload: {workbook_name}",
                "startup_steps": [self._step_to_view(step) for step in startup_steps],
                "plan_steps": [self._step_to_view(step) for step in plan_steps],
                "schedule": self.current_schedule_payload(),
            }

    def current_schedule_payload(self) -> dict[str, Any]:
        with self._lock:
            return self.codec.build_payload(
                startup_steps=self._startup_steps,
                plan_steps=self._plan_steps,
                metadata={
                    "workbook_name": self._status.workbook_path,
                    "startup_sheet": self._status.startup_sheet_name or "StartupRoutine",
                    "plan_sheet": self._status.plan_sheet_name or "Plan",
                },
                source={
                    "kind": getattr(self, "_schedule_source_kind", "runtime_memory"),
                    "name": getattr(self, "_schedule_source_name", self._status.workbook_path),
                },
            )

    def start_run(self) -> dict[str, Any]:
        with self._lock:
            if self._status.state in {RunState.STARTUP.value, RunState.RUNNING.value, RunState.WAITING_CONFIRMATION.value}:
                return {"ok": False, "message": "Run already active"}
            if not self._plan_steps:
                return {"ok": False, "message": "No plan loaded"}

            startup_first = self._first_enabled_step_index(self._startup_steps)
            if startup_first >= 0:
                self._switch_phase_locked("startup", start_index=startup_first)
                self._status.state = RunState.STARTUP.value
                self._status.startup = StartupStatus(active=True, stage="running", message="Executing StartupRoutine")
            else:
                plan_first = self._first_enabled_step_index(self._plan_steps)
                if plan_first < 0:
                    return {"ok": False, "message": "No enabled steps in plan"}
                self._switch_phase_locked("plan", start_index=plan_first)
                self._status.state = RunState.RUNNING.value
                self._status.startup = StartupStatus(active=False, stage="completed", message="No startup routine")

            self._append_event(f"Run started in phase {self._active_phase}")
            return {"ok": True, "message": "Run started"}

    def pause_run(self) -> dict[str, Any]:
        with self._lock:
            if self._status.state not in {RunState.RUNNING.value, RunState.STARTUP.value}:
                return {"ok": False, "message": "Run is not active"}
            self._status.state = RunState.PAUSED.value
            self._append_event("Run paused")
            return {"ok": True, "message": "Paused"}

    def resume_run(self) -> dict[str, Any]:
        with self._lock:
            if self._status.state != RunState.PAUSED.value:
                return {"ok": False, "message": "Run is not paused"}
            self._status.state = RunState.STARTUP.value if self._active_phase == "startup" else RunState.RUNNING.value
            self._append_event("Run resumed")
            return {"ok": True, "message": "Resumed"}

    def stop_run(self) -> dict[str, Any]:
        with self._lock:
            self._status.state = RunState.STOPPED.value
            self._status.phase = self._active_phase or "idle"
            self._status.wait_reason = "Stopped"
            self._status.awaiting_confirmation = False
            self._status.confirmation_message = ""
            self._status.startup = StartupStatus()
            self._status.active_actions = []
            self._append_event("Run stopped")
            return {"ok": True, "message": "Stopped"}

    def confirm_step(self) -> dict[str, Any]:
        with self._lock:
            if self._status.state != RunState.WAITING_CONFIRMATION.value:
                return {"ok": False, "message": "Not waiting for confirmation"}
            self._status.awaiting_confirmation = False
            self._status.confirmation_message = ""
            self._status.state = RunState.STARTUP.value if self._active_phase == "startup" else RunState.RUNNING.value
            self._append_event("Operator confirmation received")
            self._advance_to_next_step_locked()
            return {"ok": True, "message": "Confirmed"}

    def next_step(self) -> dict[str, Any]:
        with self._lock:
            return self._manual_jump_locked(+1)

    def previous_step(self) -> dict[str, Any]:
        with self._lock:
            return self._manual_jump_locked(-1)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status.to_dict()

    def _apply_loaded_schedule_locked(
        self,
        *,
        startup_steps: list[ScheduleStep],
        plan_steps: list[ScheduleStep],
        workbook_path: str,
        startup_sheet: str,
        plan_sheet: str,
        source_kind: str,
        source_name: str,
        event_message: str,
    ) -> None:
        self._startup_steps = startup_steps
        self._plan_steps = plan_steps
        self._active_steps = []
        self._active_phase = "idle"
        self._schedule_source_kind = source_kind
        self._schedule_source_name = source_name
        self._reset_runtime_counters_locked(clear_loaded_steps=False)
        self._status.workbook_path = workbook_path
        self._status.startup_sheet_name = startup_sheet
        self._status.plan_sheet_name = plan_sheet
        self._status.startup_steps = [self._step_to_view(step) for step in self._startup_steps]
        self._status.plan_steps = [self._step_to_view(step) for step in self._plan_steps]
        self._status.steps = list(self._status.plan_steps)
        self._append_event(event_message)


    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:  # pragma: no cover
                with self._lock:
                    self._status.state = RunState.FAULTED.value
                    self._status.wait_reason = f"Fault: {exc}"
                    self._append_event(f"Fault: {exc}")
            time.sleep(self.poll_interval_s)

    def _tick(self) -> None:
        with self._lock:
            if self._status.state not in {RunState.STARTUP.value, RunState.RUNNING.value}:
                return

            idx = self._status.current_step_index
            if idx < 0 or idx >= len(self._active_steps):
                self._on_phase_complete_locked()
                return

            now = time.monotonic()
            step = self._active_steps[idx]
            if self._step_started_monotonic is None:
                self._activate_step_locked(idx)

            self._status.step_elapsed_s = max(0.0, now - float(self._step_started_monotonic or now))
            self._apply_actions_locked(step, now)
            ready, reason = self._step_ready_to_advance_locked(step, now)
            self._status.wait_reason = reason

            if ready:
                if step.require_confirmation:
                    self._status.state = RunState.WAITING_CONFIRMATION.value
                    self._status.awaiting_confirmation = True
                    self._status.confirmation_message = step.confirmation_message or f"Confirm completion of {step.name}"
                    self._append_event(f"Waiting for confirmation: {self._status.confirmation_message}")
                else:
                    self._advance_to_next_step_locked()

    def _switch_phase_locked(self, phase: str, *, start_index: int) -> None:
        self._active_phase = phase
        self._active_steps = self._startup_steps if phase == "startup" else self._plan_steps
        self._status.phase = phase
        self._status.steps = self._status.startup_steps if phase == "startup" else self._status.plan_steps
        self._status.current_step_index = start_index
        self._status.current_step_name = self._active_steps[start_index].name
        self._status.awaiting_confirmation = False
        self._status.confirmation_message = ""
        self._status.wait_reason = f"Preparing {phase}"
        self._status.active_actions = []
        self._step_started_monotonic = None
        self._hold_started_monotonic = None
        self._action_ramp_state.clear()

    def _reset_runtime_counters_locked(self, *, clear_loaded_steps: bool) -> None:
        self._step_started_monotonic = None
        self._hold_started_monotonic = None
        self._action_ramp_state.clear()
        self._status.state = RunState.IDLE.value
        self._status.phase = "idle"
        self._status.current_step_index = -1
        self._status.current_step_name = ""
        self._status.step_elapsed_s = 0.0
        self._status.hold_elapsed_s = 0.0
        self._status.wait_reason = "Idle"
        self._status.awaiting_confirmation = False
        self._status.confirmation_message = ""
        self._status.last_transition = ""
        self._status.startup = StartupStatus()
        self._status.active_actions = []
        if clear_loaded_steps:
            self._status.startup_steps = []
            self._status.plan_steps = []
            self._status.steps = []

    def _activate_step_locked(self, index: int) -> None:
        step = self._active_steps[index]
        self._status.current_step_index = index
        self._status.current_step_name = step.name
        self._step_started_monotonic = time.monotonic()
        self._hold_started_monotonic = None
        self._status.hold_elapsed_s = 0.0
        self._action_ramp_state.clear()
        self._status.last_transition = f"Activated {self._active_phase} step {index + 1}: {step.name}"
        self._append_event(self._status.last_transition)
        self._status.active_actions = [self._action_to_view(action) for action in step.actions]

    def _apply_actions_locked(self, step: ScheduleStep, now: float) -> None:
        active_views: list[dict[str, Any]] = []
        for action in step.actions:
            applied_value = self._resolve_action_value_locked(action, now)
            ok = self.backend.apply_action(action, stepped_value=applied_value)
            view = self._action_to_view(action)
            view["applied_value"] = applied_value
            view["write_ok"] = ok
            active_views.append(view)
            if not ok:
                raise RuntimeError(f"Failed to write {action.target_key}={applied_value}")
            previous = self._last_applied_values.get(action.target_key, object())
            if previous != applied_value:
                self._append_event(f"Applied {action.target_key}={applied_value}")
                self._last_applied_values[action.target_key] = applied_value
        self._status.active_actions = active_views

    def _resolve_action_value_locked(self, action: StepAction, now: float) -> Any:
        if action.ramp_per_s is None or not isinstance(action.value, (int, float)):
            return action.value

        key = action.target_key
        if key not in self._action_ramp_state:
            current = self.backend.get_value(key, action.value)
            start_value = float(current if isinstance(current, (int, float)) else action.value)
            self._action_ramp_state[key] = (start_value, now)

        start_value, started = self._action_ramp_state[key]
        elapsed = max(0.0, now - started)
        target_value = float(action.value)
        step_size = abs(float(action.ramp_per_s)) * elapsed
        if target_value >= start_value:
            return min(target_value, start_value + step_size)
        return max(target_value, start_value - step_size)

    def _step_ready_to_advance_locked(self, step: ScheduleStep, now: float) -> tuple[bool, str]:
        result = evaluate_step_wait(
            step,
            now=now,
            step_started_monotonic=self._step_started_monotonic,
            hold_started_monotonic=self._hold_started_monotonic,
            get_value=self.backend.get_value,
            registry=self.operator_registry,
        )
        if result.hold_started_monotonic is None:
            self._hold_started_monotonic = None
            self._status.hold_elapsed_s = 0.0
        else:
            self._hold_started_monotonic = result.hold_started_monotonic
            self._status.hold_elapsed_s = result.hold_elapsed_s
        return result.ready, result.reason

    def _advance_to_next_step_locked(self) -> None:
        nxt = self._next_enabled_step_index(self._active_steps, self._status.current_step_index)
        if nxt < 0:
            self._status.current_step_index = len(self._active_steps)
            self._on_phase_complete_locked()
            return
        self._activate_step_locked(nxt)
        self._status.state = RunState.STARTUP.value if self._active_phase == "startup" else RunState.RUNNING.value

    def _on_phase_complete_locked(self) -> None:
        if self._active_phase == "startup":
            self._append_event("StartupRoutine complete")
            first = self._first_enabled_step_index(self._plan_steps)
            if first < 0:
                self._status.state = RunState.COMPLETED.value
                self._status.wait_reason = "Startup complete; no enabled plan steps"
                return
            self._status.startup = StartupStatus(active=False, stage="completed", message="StartupRoutine complete")
            self._switch_phase_locked("plan", start_index=first)
            self._status.state = RunState.RUNNING.value
            self._append_event("Transitioned to Plan")
            return
        self._status.state = RunState.COMPLETED.value
        self._status.wait_reason = "Schedule complete"
        self._status.last_transition = f"Completed {self._active_phase} at {self._status.current_step_name}"
        self._status.active_actions = []
        self._append_event(self._status.last_transition)

    def _manual_jump_locked(self, direction: int) -> dict[str, Any]:
        current = self._status.current_step_index
        candidate = self._previous_enabled_step_index(self._active_steps, current) if direction < 0 else self._next_enabled_step_index(self._active_steps, current)
        if candidate < 0:
            return {"ok": False, "message": "No matching step"}
        self._status.state = RunState.STARTUP.value if self._active_phase == "startup" else RunState.RUNNING.value
        self._status.awaiting_confirmation = False
        self._status.confirmation_message = ""
        self._activate_step_locked(candidate)
        return {"ok": True, "message": f"Moved to step {candidate + 1}"}

    @staticmethod
    def _first_enabled_step_index(steps: list[ScheduleStep]) -> int:
        for idx, step in enumerate(steps):
            if step.enabled:
                return idx
        return -1

    @staticmethod
    def _next_enabled_step_index(steps: list[ScheduleStep], current: int) -> int:
        for idx in range(current + 1, len(steps)):
            if steps[idx].enabled:
                return idx
        return -1

    @staticmethod
    def _previous_enabled_step_index(steps: list[ScheduleStep], current: int) -> int:
        for idx in range(max(0, current - 1), -1, -1):
            if steps[idx].enabled:
                return idx
        return -1

    def _append_event(self, message: str) -> None:
        self._status.event_log.append(message)
        self._status.event_log = self._status.event_log[-500:]

    def _action_to_view(self, action: StepAction) -> dict[str, Any]:
        return {
            "target_key": action.target_key,
            "value": action.value,
            "ramp_per_s": action.ramp_per_s,
            "display_text": action.display_text,
        }

    def _step_to_view(self, step: ScheduleStep) -> dict[str, Any]:
        return {
            "index": step.index,
            "enabled": step.enabled,
            "name": step.name,
            "wait_type": step.wait_type,
            "wait_source": step.wait_source,
            "operator": step.operator,
            "threshold": step.threshold,
            "threshold_low": step.threshold_low,
            "threshold_high": step.threshold_high,
            "duration_s": step.duration_s,
            "hold_for_s": step.hold_for_s,
            "valid_sources": step.valid_sources,
            "require_confirmation": step.require_confirmation,
            "confirmation_message": step.confirmation_message,
            "controller_actions": [self._action_to_view(action) for action in step.actions],
            "notes": step.notes,
        }
