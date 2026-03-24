"""Schedule service runtime - thin orchestrator.

Public API (load/start/pause/resume/stop/next/previous/status) and the
main poll loop live here. All domain logic is delegated to mixin modules:

    utils.py       - naming helpers, phase helpers, value collection
    ownership.py   - target ownership tracking
    measurement.py - measurement / loadstep lifecycle
    actions.py     - on-enter and exit action execution
    navigation.py  - step / phase navigation
    persistence.py - state serialise / restore
"""
from __future__ import annotations

import threading
import time
from typing import Any

from ..._shared.operator_engine import ConditionEngine, EvaluationState, load_registry_from_package
from ..._shared.wait_engine import WaitContext, WaitEngine, WaitState, parse_wait_spec
from ..control_client import ControlClient
from ..data_client import DataClient
from ..models import RunStatus, ScheduleDefinition, StepRuntime
from ..repository import InMemoryScheduleRepository, JsonScheduleStateStore
from .actions import _ActionsMixin
from .measurement import _MeasurementMixin
from .navigation import _NavigationMixin
from .ownership import _OwnershipMixin
from .persistence import _PersistenceMixin
from .utils import _UtilsMixin


class ScheduleRuntime(
    _UtilsMixin,
    _OwnershipMixin,
    _MeasurementMixin,
    _ActionsMixin,
    _NavigationMixin,
    _PersistenceMixin,
):
    """Orchestrates a loaded schedule.

    Manages the background poll loop, exposes the public control API, and
    delegates all domain logic to the mixin modules listed in the module
    docstring above.
    """

    def __init__(
        self,
        *,
        control_client: ControlClient,
        data_client: DataClient,
        repository: InMemoryScheduleRepository | None = None,
        state_store: JsonScheduleStateStore | None = None,
        owner: str = 'schedule_service',
        poll_interval_s: float = 0.2,
    ) -> None:
        top_package = __package__.split('.', 1)[0]
        registry = load_registry_from_package(f'{top_package}._shared.operator_engine.plugins')
        self.wait_engine = WaitEngine(ConditionEngine(registry))
        self.control = control_client
        self.data = data_client
        self.repository = repository or InMemoryScheduleRepository()
        self.state_store = state_store or JsonScheduleStateStore()
        self.owner = owner
        self.poll_interval_s = max(0.05, float(poll_interval_s))

        self._status = RunStatus()
        self._phase = 'idle'
        self._step_index = -1
        self._step_runtime = StepRuntime(wait_state=WaitState(condition_state=EvaluationState()))
        self._owned_target_owners: dict[str, str] = {}
        self._run_log_path: str | None = None
        self._schedule_export_path: str | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

        self._restore_from_store()

    # ------------------------------------------------------------------ lifecycle

    def start_background(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name='schedule-runtime'
            )
            self._thread.start()

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    # ------------------------------------------------------------------ schedule API

    def load_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        schedule = ScheduleDefinition.from_payload(payload)
        with self._lock:
            self.repository.save(schedule)
            self._status = RunStatus(
                state='idle',
                phase='idle',
                schedule_id=schedule.id,
                schedule_name=schedule.name,
                wait_message='Idle',
            )
            self._owned_target_owners = {}
            self._run_log_path = None
            self._schedule_export_path = None
            self._phase = 'idle'
            self._step_index = -1
            self._step_runtime = StepRuntime(wait_state=WaitState(condition_state=EvaluationState()))
            self._append_event(f'Loaded schedule {schedule.name}')
            self._persist_locked()
        return {'ok': True, 'schedule': schedule.to_dict()}

    def get_schedule(self) -> dict[str, Any]:
        schedule = self.repository.get_current()
        return {'ok': True, 'schedule': schedule.to_dict() if schedule else None}

    def clear_schedule(self) -> dict[str, Any]:
        with self._lock:
            self._release_owned_targets_locked('Schedule cleared')
            self.repository.clear()
            self._status = RunStatus(wait_message='Schedule cleared')
            self._owned_target_owners = {}
            self._run_log_path = None
            self._schedule_export_path = None
            self._phase = 'idle'
            self._step_index = -1
            self._step_runtime = StepRuntime(wait_state=WaitState(condition_state=EvaluationState()))
            self._append_event('Schedule cleared')
            self._persist_locked()
        return {'ok': True}

    # ------------------------------------------------------------------ run control

    def start_run(self) -> dict[str, Any]:
        with self._lock:
            schedule = self.repository.get_current()
            if schedule is None:
                return {'ok': False, 'message': 'No schedule loaded'}
            if self._status.state == 'running':
                return {'ok': False, 'message': 'Already running'}

            self._status.schedule_id = schedule.id
            self._status.schedule_name = schedule.name
            self._status.pause_reason = None
            if self._enabled_steps(schedule.setup_steps):
                self._phase = 'setup'
                self._step_index = self._first_enabled_index(schedule.setup_steps)
            else:
                self._phase = 'plan'
                self._step_index = self._first_enabled_index(schedule.plan_steps)

            if self._step_index < 0:
                return {'ok': False, 'message': 'No enabled steps'}

            self._status.state = 'running'
            self._status.phase = self._phase
            self._activate_step_locked()
            self._auto_start_measurement_locked(schedule)
            self._append_event('Run started')
            self._persist_locked()
            return {'ok': True, 'message': 'Run started'}

    def pause_run(self) -> dict[str, Any]:
        with self._lock:
            if self._status.state != 'running':
                return {'ok': False, 'message': 'Run is not active'}
            self._status.state = 'paused'
            self._status.pause_reason = 'manual'
            self._status.wait_message = 'Paused manually'
            self._append_event('Run paused')
            self._persist_locked()
            return {'ok': True}

    def resume_run(self) -> dict[str, Any]:
        with self._lock:
            if self._status.state != 'paused':
                return {'ok': False, 'message': 'Run is not paused'}
            schedule = self.repository.get_current()
            if schedule is None:
                return {'ok': False, 'message': 'No schedule loaded'}
            self._status.state = 'running'
            self._status.pause_reason = None
            if self._step_runtime.pending_exit_loadsteps:
                # Preserve the loadstep wait — don't zero the timer.
                waiting_for = ', '.join(sorted(self._step_runtime.pending_exit_loadsteps))
                self._status.wait_message = f'Waiting for loadstep completion: {waiting_for}'
            else:
                self._reset_step_wait_tracking_locked()
            # Keep fermentation logging continuous across pause/resume.
            # If recording was interrupted while paused, resume will restart it.
            self._auto_start_measurement_locked(schedule)
            self._append_event('Run resumed')
            self._persist_locked()
            return {'ok': True}

    def _reset_step_wait_tracking_locked(self) -> None:
        """Zero all elapsed/condition tracking so timers restart after pause."""
        self._step_runtime.started_monotonic = time.monotonic()
        self._step_runtime.started_at_utc = self._utc_now_iso()
        self._step_runtime.wait_state = WaitState(condition_state=EvaluationState())
        self._status.wait_message = (
            f'Active step: {self._status.current_step_name}'
            if self._status.current_step_name
            else 'Run resumed'
        )

    def stop_run(self) -> dict[str, Any]:
        with self._lock:
            self._finalize_measurement_if_recording_locked('Run stopped')
            self._release_owned_targets_locked('Run stopped')
            self._phase = 'idle'
            self._step_index = -1
            self._step_runtime = StepRuntime(wait_state=WaitState(condition_state=EvaluationState()))
            self._status.state = 'stopped'
            self._status.phase = 'idle'
            self._status.current_step_index = -1
            self._status.current_step_name = ''
            self._status.pause_reason = None
            self._status.wait_message = 'Run stopped'
            self._append_event('Run stopped')
            self._persist_locked()
            return {'ok': True}

    def next_step(self) -> dict[str, Any]:
        with self._lock:
            schedule = self.repository.get_current()
            if schedule is None:
                return {'ok': False, 'message': 'No schedule loaded'}
            if self._status.state not in {'running', 'paused'}:
                return {'ok': False, 'message': 'Run is not active'}
            self._advance_step_locked(schedule, manual=True)
            self._persist_locked()
            return {'ok': True, 'message': 'Moved to next step'}

    def previous_step(self) -> dict[str, Any]:
        with self._lock:
            schedule = self.repository.get_current()
            if schedule is None:
                return {'ok': False, 'message': 'No schedule loaded'}
            if self._status.state not in {'running', 'paused'}:
                return {'ok': False, 'message': 'Run is not active'}
            if self._status.state == 'running':
                self._status.state = 'paused'
                self._status.pause_reason = 'Manual step back'
                self._append_event('Run paused for previous step')
            moved = self._move_previous_locked(schedule)
            if not moved:
                return {'ok': False, 'message': 'No previous step'}
            self._persist_locked()
            return {'ok': True, 'message': 'Moved to previous step'}

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status.to_dict()

    # ------------------------------------------------------------------ poll loop

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:  # pragma: no cover
                with self._lock:
                    self._status.state = 'faulted'
                    self._status.pause_reason = None
                    self._status.wait_message = f'Fault: {exc}'
                    self._append_event(f'Fault: {exc}')
                    self._persist_locked()
            time.sleep(self.poll_interval_s)

    def _tick(self) -> None:
        with self._lock:
            if self._status.state != 'running':
                return
            schedule = self.repository.get_current()
            if schedule is None:
                self._status.state = 'faulted'
                self._status.wait_message = 'Schedule missing'
                self._persist_locked()
                return
            steps = self._phase_steps(schedule)
            if self._step_index < 0 or self._step_index >= len(steps):
                self._advance_phase_or_complete_locked(schedule)
                self._persist_locked()
                return

            step = steps[self._step_index]
            if not self._step_runtime.actions_applied:
                self._apply_actions_locked(step)

            values = self._collect_values(step)
            wait_spec = parse_wait_spec(step.wait)
            wait_result = self.wait_engine.evaluate(
                wait_spec,
                context=WaitContext(
                    now_monotonic=time.monotonic(),
                    step_started_monotonic=self._step_runtime.started_monotonic,
                    values=values,
                ),
                previous_state=self._step_runtime.wait_state,
            )
            self._step_runtime.wait_state = wait_result.next_state
            self._status.wait_message = wait_result.message

            if self._ownership_lost(step):
                self._status.state = 'paused'
                self._status.pause_reason = 'ownership_lost'
                self._status.wait_message = 'Ownership lost; paused'
                self._remove_owned_targets_for_step_locked(step)
                self._append_event('Ownership lost; scheduler paused')
                self._persist_locked()
                return

            if wait_result.matched:
                ready_for_next = self._run_exit_actions_locked(step)
                if ready_for_next:
                    self._advance_step_locked(schedule)
                self._persist_locked()
                return

            self._persist_locked()
