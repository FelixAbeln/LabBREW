
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from .._shared.operator_engine import ConditionEngine, EvaluationState, load_registry_from_package
from .._shared.wait_engine import WaitContext, WaitEngine, WaitState, parse_wait_spec
from .control_client import ControlClient
from .data_client import DataClient
from .models import RunStatus, ScheduleDefinition, ScheduleStep, StepRuntime
from .repository import InMemoryScheduleRepository, JsonScheduleStateStore


class ScheduleRuntime:
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
        package_root = __package__.rsplit('.', 1)[0]
        registry = load_registry_from_package(f'{package_root}._shared.operator_engine.plugins')
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
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

        self._restore_from_store()

    def start_background(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name='schedule-runtime')
            self._thread.start()

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

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
            self._phase = 'idle'
            self._step_index = -1
            self._step_runtime = StepRuntime(wait_state=WaitState(condition_state=EvaluationState()))
            self._append_event('Schedule cleared')
            self._persist_locked()
        return {'ok': True}

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
            self._status.state = 'running'
            self._status.pause_reason = None
            if self._step_runtime.pending_exit_loadsteps:
                # If we already triggered exit loadsteps, keep waiting for those completions.
                waiting_for = ', '.join(sorted(self._step_runtime.pending_exit_loadsteps))
                self._status.wait_message = f'Waiting for loadstep completion: {waiting_for}'
            else:
                self._reset_step_wait_tracking_locked()
            self._append_event('Run resumed')
            self._persist_locked()
            return {'ok': True}

    def _reset_step_wait_tracking_locked(self) -> None:
        self._step_runtime.started_monotonic = time.monotonic()
        self._step_runtime.started_at_utc = self._utc_now_iso()
        self._step_runtime.wait_state = WaitState(condition_state=EvaluationState())
        self._status.wait_message = (
            f'Active step: {self._status.current_step_name}' if self._status.current_step_name else 'Run resumed'
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

    def _apply_actions_locked(self, step: ScheduleStep) -> None:
        last_result: dict[str, Any] = {'ok': True}
        for action in step.actions:
            owner = action.owner or self.owner
            if action.kind == 'request_control':
                last_result = self.control.request_control(action.target or '', owner)
                if last_result.get('ok') and action.target:
                    self._remember_owned_target_locked(action.target, owner)
            elif action.kind == 'write':
                last_result = self.control.write(action.target or '', action.value, owner)
                if last_result.get('ok') and action.target:
                    self._remember_owned_target_locked(action.target, owner)
            elif action.kind == 'ramp':
                last_result = self.control.ramp(
                    target=action.target or '',
                    value=action.value,
                    duration_s=float(action.duration_s or 0.0),
                    owner=owner,
                )
                if last_result.get('ok') and action.target:
                    self._remember_owned_target_locked(action.target, owner)
            elif action.kind == 'release_control':
                last_result = self.control.release_control(action.target or '', owner)
                if last_result.get('ok') and action.target:
                    self._discard_owned_target_locked(action.target)
            elif action.kind == 'global_measurement':
                mode_raw = action.params.get('mode', action.value if action.value is not None else 'start')
                mode = str(mode_raw or 'start').strip().lower()
                if mode in {'start', 'setup_start'}:
                    last_result = self._start_global_measurement(action, step)
                elif mode == 'stop':
                    last_result = self._stop_global_measurement()
                else:
                    raise ValueError(f'Unsupported global_measurement mode: {mode}')
            elif action.kind == 'take_loadstep':
                if self._action_timing(action) in {'before_next', 'on_exit'}:
                    last_result = {'ok': True, 'deferred': True}
                else:
                    last_result = self._take_data_loadstep(action, step)
            else:
                raise ValueError(f'Unsupported action kind: {action.kind}')

            if not last_result.get('ok', False):
                raise RuntimeError(f'Action failed for {action.kind}: {last_result}')

        self._step_runtime.actions_applied = True
        self._status.last_action_result = last_result
        self._append_event(f'Applied step {step.name}')

    def _run_exit_actions_locked(self, step: ScheduleStep) -> bool:
        exit_actions = [
            action
            for action in step.actions
            if action.kind == 'take_loadstep' and self._action_timing(action) in {'before_next', 'on_exit'}
        ]

        if not exit_actions:
            return True

        wait_spec = parse_wait_spec(step.wait)
        if wait_spec is None or wait_spec.kind == 'none':
            self._append_event(f'Skipped exit loadstep for step {step.name}: no wait criteria defined')
            return True

        # Trigger exit loadsteps exactly once when wait criteria become true.
        if not self._step_runtime.pending_exit_loadsteps:
            pending_names: set[str] = set()
            for action in exit_actions:
                result = self._take_data_loadstep(action, step)
                if not result.get('ok', False):
                    raise RuntimeError(f'Exit action failed for {action.kind}: {result}')
                self._status.last_action_result = result
                loadstep_name = str(result.get('loadstep_name') or '').strip()
                if loadstep_name:
                    pending_names.add(loadstep_name)
                    self._append_event(f'Started exit loadstep {loadstep_name} for step {step.name}')

            if pending_names:
                self._step_runtime.pending_exit_loadsteps = pending_names
                waiting_for = ', '.join(sorted(pending_names))
                self._status.wait_message = f'Waiting for loadstep completion: {waiting_for}'
                return False

            return True

        data_status = self.data.status()
        active_names = {
            str(item)
            for item in (data_status.get('active_loadstep_names') or [])
            if str(item).strip()
        }
        completed_names = {
            str(item.get('name'))
            for item in (data_status.get('completed_loadsteps') or [])
            if isinstance(item, dict) and str(item.get('name') or '').strip()
        }

        pending = set(self._step_runtime.pending_exit_loadsteps)
        if pending and pending.issubset(completed_names) and not (pending & active_names):
            finished = ', '.join(sorted(pending))
            self._append_event(f'Exit loadstep completed: {finished}')
            self._step_runtime.pending_exit_loadsteps.clear()
            return True

        active_details = []
        for item in (data_status.get('active_loadsteps') or []):
            if not isinstance(item, dict):
                continue
            name = str(item.get('name') or '').strip()
            if not name or name not in pending:
                continue
            remaining = item.get('remaining_seconds')
            if remaining is None:
                active_details.append(name)
            else:
                try:
                    active_details.append(f"{name} ({max(0, int(round(float(remaining))))}s)")
                except (TypeError, ValueError):
                    active_details.append(name)

        if active_details:
            self._status.wait_message = f"Waiting for loadstep completion: {', '.join(active_details)}"
        else:
            waiting_for = ', '.join(sorted(pending))
            self._status.wait_message = f'Waiting for loadstep completion: {waiting_for}'
        return False

    def _action_timing(self, action: Any) -> str:
        params = action.params if isinstance(action.params, dict) else {}
        return str(params.get('timing', 'on_enter')).strip().lower()

    def _start_global_measurement(self, action: Any, step: ScheduleStep) -> dict[str, Any]:
        status = self.data.status()
        if bool(status.get('recording')):
            return {'ok': True, 'message': 'Measurement already recording; skipped setup/start'}

        params = action.params if isinstance(action.params, dict) else {}
        configured_parameters = params.get('parameters')
        if isinstance(configured_parameters, list) and configured_parameters:
            parameters = [str(item) for item in configured_parameters if str(item).strip()]
        else:
            snapshot = self.control.snapshot()
            values = snapshot.get('values') if isinstance(snapshot, dict) else {}
            parameters = sorted(values.keys()) if isinstance(values, dict) else []

        if not parameters:
            raise RuntimeError('global_measurement start requires parameters or a non-empty control snapshot')

        hz = float(params.get('hz', 10.0))
        output_dir = str(params.get('output_dir', 'data/measurements'))
        output_format = str(params.get('output_format', 'parquet'))
        session_name = str(params.get('session_name') or self._default_data_name(step, suffix=''))

        setup_result = self.data.setup_measurement(
            parameters=parameters,
            hz=hz,
            output_dir=output_dir,
            output_format=output_format,
            session_name=session_name,
        )
        if not setup_result.get('ok', False):
            raise RuntimeError(f'global_measurement setup failed: {setup_result}')

        start_result = self.data.measure_start()
        if not start_result.get('ok', False):
            raise RuntimeError(f'global_measurement start failed: {start_result}')
        return start_result

    def _stop_global_measurement(self) -> dict[str, Any]:
        status = self.data.status()
        if not bool(status.get('recording')):
            return {'ok': True, 'message': 'Measurement already stopped; skipped stop'}
        return self.data.measure_stop()

    def _take_data_loadstep(self, action: Any, step: ScheduleStep) -> dict[str, Any]:
        params = action.params if isinstance(action.params, dict) else {}
        duration = params.get('duration_seconds', action.duration_s)
        duration_seconds = float(duration if duration is not None else 30.0)
        loadstep_name = str(params.get('loadstep_name') or self._default_data_name(step, suffix='ls'))

        loadstep_parameters_raw = params.get('parameters')
        loadstep_parameters = None
        if isinstance(loadstep_parameters_raw, list):
            parsed = [str(item) for item in loadstep_parameters_raw if str(item).strip()]
            loadstep_parameters = parsed or None

        return self.data.take_loadstep(
            duration_seconds=duration_seconds,
            loadstep_name=loadstep_name,
            parameters=loadstep_parameters,
        )

    def _default_data_name(self, step: ScheduleStep, suffix: str = '') -> str:
        schedule_slug = self._slugify(self._status.schedule_id or 'schedule')
        step_slug = self._slugify(step.id or step.name or f'{self._phase}_{self._step_index}')
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        suffix_part = f'_{suffix}' if suffix else ''
        return f'scheduling_{schedule_slug}_{step_slug}{suffix_part}_{timestamp}'

    def _slugify(self, value: str) -> str:
        cleaned = ''.join(ch if ch.isalnum() else '_' for ch in str(value).strip().lower())
        while '__' in cleaned:
            cleaned = cleaned.replace('__', '_')
        return cleaned.strip('_') or 'item'

    def _collect_values(self, step: ScheduleStep) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for source in self._collect_wait_sources(step.wait):
            values[source] = self.control.read(source).get('value')
        return values

    def _collect_wait_sources(self, payload: dict[str, Any] | None) -> set[str]:
        found: set[str] = set()
        if not isinstance(payload, dict):
            return found
        condition = payload.get('condition')
        if isinstance(condition, dict):
            found |= self._collect_condition_sources(condition)
        for child in payload.get('children') or []:
            if isinstance(child, dict):
                found |= self._collect_wait_sources(child)
        return found

    def _collect_condition_sources(self, payload: dict[str, Any]) -> set[str]:
        found: set[str] = set()
        source = payload.get('source')
        if isinstance(source, str) and source:
            found.add(source)
        for child in payload.get('all') or []:
            if isinstance(child, dict):
                found |= self._collect_condition_sources(child)
        for child in payload.get('any') or []:
            if isinstance(child, dict):
                found |= self._collect_condition_sources(child)
        if isinstance(payload.get('not'), dict):
            found |= self._collect_condition_sources(payload['not'])
        return found

    def _ownership_lost(self, step: ScheduleStep) -> bool:
        ownership = self.control.ownership()
        for action in step.actions:
            if action.kind not in {'request_control', 'write', 'ramp'} or not action.target:
                continue
            if action.target not in self._status.owned_targets:
                continue
            owner_meta = ownership.get(action.target) or {}
            current_owner = owner_meta.get('owner') if isinstance(owner_meta, dict) else None
            expected = self._owned_target_owners.get(action.target, action.owner or self.owner)
            if current_owner != expected:
                return True
        return False

    def _advance_step_locked(self, schedule: ScheduleDefinition, manual: bool = False) -> None:
        steps = self._phase_steps(schedule)
        next_index = self._next_enabled_index(steps, self._step_index + 1)
        if next_index >= 0:
            self._rollover_measurement_for_next_step_locked(steps[next_index])
            self._step_index = next_index
            self._activate_step_locked()
            if manual:
                self._append_event('Moved to next step')
            return
        self._advance_phase_or_complete_locked(schedule)
        if manual and self._status.state != 'completed':
            self._append_event('Moved to next step')

    def _move_previous_locked(self, schedule: ScheduleDefinition) -> bool:
        steps = self._phase_steps(schedule)
        for index in range(self._step_index - 1, -1, -1):
            if steps[index].enabled:
                self._step_index = index
                self._activate_step_locked()
                self._append_event('Moved to previous step')
                return True
        if self._phase == 'plan' and self._enabled_steps(schedule.setup_steps):
            setup_steps = schedule.setup_steps
            for index in range(len(setup_steps) - 1, -1, -1):
                if setup_steps[index].enabled:
                    self._phase = 'setup'
                    self._step_index = index
                    self._activate_step_locked()
                    self._append_event('Moved to previous step')
                    return True
        return False

    def _advance_phase_or_complete_locked(self, schedule: ScheduleDefinition) -> None:
        if self._phase == 'setup' and self._enabled_steps(schedule.plan_steps):
            first_plan_index = self._first_enabled_index(schedule.plan_steps)
            if first_plan_index >= 0:
                self._rollover_measurement_for_next_step_locked(schedule.plan_steps[first_plan_index])
            self._phase = 'plan'
            self._step_index = first_plan_index
            self._activate_step_locked()
            self._append_event('Entered plan phase')
            return
        self._finalize_measurement_if_recording_locked('Run completed')
        self._release_owned_targets_locked('Run completed')
        self._status.state = 'completed'
        self._status.phase = self._phase
        self._status.pause_reason = None
        self._status.wait_message = 'Completed'
        self._append_event('Run completed')

    def _activate_step_locked(self) -> None:
        schedule = self.repository.get_current()
        if schedule is None:
            return
        step = self._phase_steps(schedule)[self._step_index]
        started_at_utc = self._utc_now_iso()
        self._step_runtime = StepRuntime(
            actions_applied=False,
            started_monotonic=time.monotonic(),
            started_at_utc=started_at_utc,
            wait_state=WaitState(condition_state=EvaluationState()),
        )
        self._status.phase = self._phase
        self._status.current_step_index = self._step_index
        self._status.current_step_name = step.name
        self._status.wait_message = f'Active step: {step.name}'
        self._status.pause_reason = None

    def _release_owned_targets_locked(self, context: str) -> None:
        for target, owner in list(self._owned_target_owners.items()):
            try:
                result = self.control.release_control(target, owner)
                if result.get('ok'):
                    self._append_event(f'{context}; released ownership for {target}')
            except Exception as exc:  # pragma: no cover
                self._append_event(f'{context}; failed to release ownership for {target}: {exc}')
        self._owned_target_owners.clear()
        self._refresh_owned_targets_locked()

    def _remove_owned_targets_for_step_locked(self, step: ScheduleStep) -> None:
        for action in step.actions:
            if action.target:
                self._discard_owned_target_locked(action.target)

    def _remember_owned_target_locked(self, target: str, owner: str) -> None:
        self._owned_target_owners[target] = owner
        self._refresh_owned_targets_locked()

    def _discard_owned_target_locked(self, target: str) -> None:
        self._owned_target_owners.pop(target, None)
        self._refresh_owned_targets_locked()

    def _refresh_owned_targets_locked(self) -> None:
        self._status.owned_targets = list(self._owned_target_owners)

    def _append_event(self, text: str) -> None:
        self._status.event_log.append(text)
        self._status.event_log = self._status.event_log[-100:]

    def _finalize_measurement_if_recording_locked(self, context: str) -> None:
        try:
            status = self.data.status()
            if not bool(status.get('recording')):
                return
            result = self.data.measure_stop()
            if result.get('ok', False):
                self._append_event(f'{context}; measurement file finalized')
            else:
                self._append_event(f"{context}; measurement finalize failed: {result}")
        except Exception as exc:  # pragma: no cover
            self._append_event(f'{context}; measurement finalize failed: {exc}')

    def _rollover_measurement_for_next_step_locked(self, next_step: ScheduleStep) -> None:
        try:
            status = self.data.status()
        except Exception as exc:  # pragma: no cover
            self._append_event(f'Measurement rollover skipped; status unavailable: {exc}')
            return

        if not bool(status.get('recording')):
            return

        config = status.get('config') if isinstance(status.get('config'), dict) else {}
        parameters = [str(item) for item in (config.get('parameters') or []) if str(item).strip()]
        hz = float(config.get('hz') or 10.0)
        output_dir = str(config.get('output_dir') or 'data/measurements')
        output_format = str(config.get('output_format') or 'jsonl')

        stop_result = self.data.measure_stop()
        if not stop_result.get('ok', False):
            raise RuntimeError(f'Measurement rollover stop failed: {stop_result}')
        self._append_event(f'Measurement segment finalized before step {next_step.name}')

        if not parameters:
            self._append_event('Measurement rollover skipped restart because parameters are missing')
            return

        session_name = self._default_data_name(next_step, suffix='')
        setup_result = self.data.setup_measurement(
            parameters=parameters,
            hz=hz,
            output_dir=output_dir,
            output_format=output_format,
            session_name=session_name,
        )
        if not setup_result.get('ok', False):
            raise RuntimeError(f'Measurement rollover setup failed: {setup_result}')

        start_result = self.data.measure_start()
        if not start_result.get('ok', False):
            raise RuntimeError(f'Measurement rollover start failed: {start_result}')
        self._append_event(f'Measurement segment started for step {next_step.name}')

    def _persist_locked(self) -> None:
        schedule = self.repository.get_current()
        payload = {
            'schedule': schedule.to_dict() if schedule else None,
            'state': self._status.state,
            'phase': self._phase,
            'current_step_index': self._step_index,
            'step_started_at_utc': self._step_runtime.started_at_utc,
            'pause_reason': self._status.pause_reason,
            'owned_targets': list(self._status.owned_targets),
            'owned_target_owners': dict(self._owned_target_owners),
            'last_action_result': dict(self._status.last_action_result),
            'event_log': list(self._status.event_log),
        }
        self.state_store.save(payload)

    def _restore_from_store(self) -> None:
        payload = self.state_store.load()
        if not isinstance(payload, dict):
            return
        schedule_payload = payload.get('schedule')
        schedule = ScheduleDefinition.from_payload(schedule_payload) if isinstance(schedule_payload, dict) else None
        if schedule is not None:
            self.repository.save(schedule)
            self._status.schedule_id = schedule.id
            self._status.schedule_name = schedule.name
        self._status.state = payload.get('state', 'idle')
        self._phase = payload.get('phase', 'idle')
        self._status.phase = self._phase
        self._step_index = int(payload.get('current_step_index', -1))
        self._status.current_step_index = self._step_index
        self._status.pause_reason = payload.get('pause_reason')
        owned_target_owners = payload.get('owned_target_owners')
        if isinstance(owned_target_owners, dict):
            self._owned_target_owners = {str(target): str(owner) for target, owner in owned_target_owners.items()}
        else:
            self._owned_target_owners = {str(item): self.owner for item in (payload.get('owned_targets') or [])}
        self._refresh_owned_targets_locked()
        self._status.last_action_result = dict(payload.get('last_action_result') or {})
        self._status.event_log = [str(item) for item in (payload.get('event_log') or [])][-100:]
        self._step_runtime = StepRuntime(
            actions_applied=True,
            started_monotonic=self._restore_started_monotonic(payload.get('step_started_at_utc')),
            started_at_utc=payload.get('step_started_at_utc'),
            wait_state=WaitState(condition_state=EvaluationState()),
        )
        if schedule is not None and self._phase in {'setup', 'plan'} and self._step_index >= 0:
            steps = self._phase_steps(schedule)
            if 0 <= self._step_index < len(steps):
                self._status.current_step_name = steps[self._step_index].name
        if self._status.state == 'paused' and self._status.pause_reason is None:
            self._status.pause_reason = 'restored_paused'
        if self._status.state == 'paused':
            self._status.wait_message = 'Paused after restore'
        elif self._status.state == 'running' and self._status.current_step_name:
            self._status.wait_message = f'Active step: {self._status.current_step_name}'
        elif self._status.state == 'completed':
            self._status.wait_message = 'Completed'
        elif self._status.state == 'stopped':
            self._status.wait_message = 'Run stopped'
        elif self._status.state == 'idle':
            self._status.wait_message = 'Idle'

    def _restore_started_monotonic(self, started_at_utc: str | None) -> float | None:
        if not started_at_utc:
            return None
        try:
            started = datetime.fromisoformat(started_at_utc.replace('Z', '+00:00'))
            elapsed = max(0.0, (datetime.now(timezone.utc) - started).total_seconds())
            return time.monotonic() - elapsed
        except ValueError:
            return None

    def _utc_now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    def _phase_steps(self, schedule: ScheduleDefinition) -> list[ScheduleStep]:
        return schedule.setup_steps if self._phase == 'setup' else schedule.plan_steps

    def _enabled_steps(self, steps: list[ScheduleStep]) -> list[ScheduleStep]:
        return [step for step in steps if step.enabled]

    def _first_enabled_index(self, steps: list[ScheduleStep]) -> int:
        return self._next_enabled_index(steps, 0)

    def _next_enabled_index(self, steps: list[ScheduleStep], start: int) -> int:
        for index in range(start, len(steps)):
            if steps[index].enabled:
                return index
        return -1
