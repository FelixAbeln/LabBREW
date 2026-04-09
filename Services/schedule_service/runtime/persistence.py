"""State persistence for ScheduleRuntime.

_persist_locked      — serialises runtime state to the JSON store.
_restore_from_store  — rehydrates state on startup.
All methods are mixed into ScheduleRuntime via _PersistenceMixin.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from ..._shared.operator_engine import EvaluationState
from ..._shared.wait_engine import WaitState
from ..models import ScheduleDefinition, StepRuntime


class _PersistenceMixin:
    def _persist_locked(self) -> None:
        schedule = self.repository.get_current()
        payload = {
            "schedule": schedule.to_dict() if schedule else None,
            "state": self._status.state,
            "phase": self._phase,
            "current_step_index": self._step_index,
            "step_started_at_utc": self._step_runtime.started_at_utc,
            "pause_reason": self._status.pause_reason,
            "owned_targets": list(self._status.owned_targets),
            "owned_target_owners": dict(self._owned_target_owners),
            "last_action_result": dict(self._status.last_action_result),
            "data_records": list(self._status.data_records),
            "event_log": list(self._status.event_log),
        }
        self.state_store.save(payload)

    def _restore_from_store(self) -> None:
        payload = self.state_store.load()
        if not isinstance(payload, dict):
            return
        schedule_payload = payload.get("schedule")
        schedule = (
            ScheduleDefinition.from_payload(schedule_payload)
            if isinstance(schedule_payload, dict)
            else None
        )
        if schedule is not None:
            self.repository.save(schedule)
            self._status.schedule_id = schedule.id
            self._status.schedule_name = schedule.name
        self._status.state = payload.get("state", "idle")
        self._phase = payload.get("phase", "idle")
        self._status.phase = self._phase
        self._step_index = int(payload.get("current_step_index", -1))
        self._status.current_step_index = self._step_index
        self._status.pause_reason = payload.get("pause_reason")
        owned_target_owners = payload.get("owned_target_owners")
        if isinstance(owned_target_owners, dict):
            self._owned_target_owners = {
                str(t): str(o) for t, o in owned_target_owners.items()
            }
        else:
            self._owned_target_owners = {
                str(item): self.owner for item in (payload.get("owned_targets") or [])
            }
        self._refresh_owned_targets_locked()
        self._status.last_action_result = dict(payload.get("last_action_result") or {})
        self._status.data_records = [
            dict(item)
            for item in (payload.get("data_records") or [])
            if isinstance(item, dict)
        ][-200:]
        self._status.event_log = [
            str(item) for item in (payload.get("event_log") or [])
        ][-100:]
        self._step_runtime = StepRuntime(
            actions_applied=True,
            started_monotonic=self._restore_started_monotonic(
                payload.get("step_started_at_utc")
            ),
            started_at_utc=payload.get("step_started_at_utc"),
            wait_state=WaitState(condition_state=EvaluationState()),
        )
        if (
            schedule is not None
            and self._phase in {"setup", "plan"}
            and self._step_index >= 0
        ):
            steps = self._phase_steps(schedule)
            if 0 <= self._step_index < len(steps):
                self._status.current_step_name = steps[self._step_index].name
        if self._status.state == "paused" and self._status.pause_reason is None:
            self._status.pause_reason = "restored_paused"
        # Restore wait message to a sensible default.
        if self._status.state == "paused":
            self._status.wait_message = "Paused after restore"
        elif self._status.state == "running" and self._status.current_step_name:
            self._status.wait_message = f"Active step: {self._status.current_step_name}"
        elif self._status.state == "completed":
            self._status.wait_message = "Completed"
        elif self._status.state == "stopped":
            self._status.wait_message = "Run stopped"
        elif self._status.state == "idle":
            self._status.wait_message = "Idle"

    def _restore_started_monotonic(self, started_at_utc: str | None) -> float | None:
        if not started_at_utc:
            return None
        try:
            started = datetime.fromisoformat(started_at_utc.replace("Z", "+00:00"))
            elapsed = max(0.0, (datetime.now(UTC) - started).total_seconds())
            return time.monotonic() - elapsed
        except ValueError:
            return None
