"""Measurement and loadstep lifecycle for ScheduleRuntime.

Measurement is global: it auto-starts when a run begins (driven by
schedule.measurement_config) and runs continuously until the run stops,
completes, or is cancelled, always saving the file on exit.

Per-step loadsteps (take_loadstep) still fire at step conclusion
(before_next timing) and are handled here too.
All methods are mixed into ScheduleRuntime via _MeasurementMixin.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from typing import TYPE_CHECKING, Any

from ..._shared.storage_paths import default_measurements_dir
from ..._shared.wait_engine import WaitContext, WaitState, parse_wait_spec


DEFAULT_MEASUREMENTS_DIR = default_measurements_dir()

if TYPE_CHECKING:
    from ..models import ScheduleDefinition, ScheduleStep


class _MeasurementMixin:

    def _append_data_record(self, record: dict[str, Any]) -> None:
        """Append a scheduler data-record entry and keep a bounded history."""
        self._status.data_records.append(record)
        self._status.data_records = self._status.data_records[-200:]

    def _prepare_scheduler_sidecar_files(
        self,
        *,
        schedule: ScheduleDefinition,
        output_dir: str,
        session_name: str,
    ) -> list[str]:
        """Create scheduler run sidecars to be archived with measurement data."""
        os.makedirs(output_dir, exist_ok=True)

        schedule_export_path = os.path.join(output_dir, f"{session_name}.schedule.json")
        run_log_path = os.path.join(output_dir, f"{session_name}.run.log")

        # Export the exact schedule payload that is being executed.
        self._atomic_write_json_file(schedule_export_path, schedule.to_dict())

        # Initialize run log with existing in-memory event history.
        bootstrap_lines = [f"{self._utc_now_iso()} scheduler log initialized"]
        bootstrap_lines.extend(f"{self._utc_now_iso()} {entry}" for entry in self._status.event_log)
        self._atomic_write_text_file(run_log_path, "\n".join(bootstrap_lines) + "\n")

        self._schedule_export_path = schedule_export_path
        self._run_log_path = run_log_path

        return [schedule_export_path, run_log_path]

    def _atomic_write_json_file(self, path: str, payload: dict[str, Any]) -> None:
        self._atomic_write_text_file(path, json.dumps(payload, indent=2, sort_keys=True))

    def _atomic_write_text_file(self, path: str, text: str) -> None:
        target = os.path.abspath(path)
        target_dir = os.path.dirname(target) or '.'
        os.makedirs(target_dir, exist_ok=True)

        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{os.path.basename(target)}.",
            suffix='.tmp',
            dir=target_dir,
        )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(tmp_name, target)
        except Exception:
            try:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------ run-level auto-start

    def _auto_start_measurement_locked(self, schedule: ScheduleDefinition) -> None:
        """Start global measurement at run start using schedule.measurement_config.

        Idempotent: does nothing if measurement_config is empty or already recording.
        If measurement_config contains a 'parameters' list, those specific parameters are used.
        Otherwise, parameters are auto-discovered from the control snapshot.
        """
        # Global measurement is always expected while a run is active.
        # If a schedule has no explicit config, defaults are used.
        config = schedule.measurement_config or {}

        try:
            status = self.data.status()
        except Exception as exc:  # pragma: no cover
            self._append_event(f'Global measurement start skipped; status unavailable: {exc}')
            return

        if bool(status.get('recording')):
            self._append_event('Global measurement already recording; skipped auto-start')
            return

        # Use configured parameters if available, otherwise auto-discover from snapshot
        configured_parameters = config.get('parameters')
        if isinstance(configured_parameters, list) and configured_parameters:
            parameters = [str(p).strip() for p in configured_parameters if str(p).strip()]
        else:
            snapshot = self.control.snapshot()
            values = snapshot.get('values') if isinstance(snapshot, dict) else {}
            parameters = sorted(values.keys()) if isinstance(values, dict) else []

        if not parameters:
            self._append_event('Global measurement skipped: no parameters configured or available from control snapshot')
            return

        hz = float(config.get('hz') or 10.0)
        output_dir = str(config.get('output_dir') or DEFAULT_MEASUREMENTS_DIR)
        output_format = str(config.get('output_format') or 'parquet')
        session_name = str(
            config.get('session_name')
            or config.get('name')
            or self._default_data_name()
        )

        include_files = self._prepare_scheduler_sidecar_files(
            schedule=schedule,
            output_dir=output_dir,
            session_name=session_name,
        )

        try:
            setup = self.data.setup_measurement(
                parameters=parameters,
                hz=hz,
                output_dir=output_dir,
                output_format=output_format,
                session_name=session_name,
                include_files=include_files,
            )
            if not setup.get('ok', False):
                self._append_event(f'Global measurement setup failed: {setup}')
                return
            start = self.data.measure_start()
            if start.get('ok', False):
                self._append_data_record({
                    'kind': 'measurement_started',
                    'source': 'schedule_auto_start',
                    'session_name': session_name,
                    'output_dir': output_dir,
                    'output_format': output_format,
                    'parameters_count': len(parameters),
                    'timestamp': self._utc_now_iso(),
                })
                self._append_event(f'Global measurement started ({session_name})')
            else:
                self._append_event(f'Global measurement start failed: {start}')
        except Exception as exc:  # pragma: no cover
            self._append_event(f'Global measurement start failed: {exc}')

    # ------------------------------------------------------------------ manual global_measurement action
    # Kept for JSON schedule compatibility; Excel schedules use auto-start instead.

    def _start_global_measurement(self, action: Any, step: ScheduleStep) -> dict[str, Any]:
        """Handle manual global_measurement=start action from a JSON schedule step.

        Idempotent: skips if already recording.
        """
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
        output_dir = str(params.get('output_dir', DEFAULT_MEASUREMENTS_DIR))
        output_format = str(params.get('output_format', 'parquet'))
        session_name = str(params.get('session_name') or self._default_data_name())

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
        """Idempotent: skips if already stopped."""
        status = self.data.status()
        if not bool(status.get('recording')):
            return {'ok': True, 'message': 'Measurement already stopped; skipped stop'}
        return self.data.measure_stop()

    # ------------------------------------------------------------------ loadstep

    def _ensure_measurement_running_locked(self) -> bool:
        """Best-effort guard to ensure loadsteps have an active measurement session."""
        try:
            status = self.data.status()
            if bool(status.get('recording')):
                return True
        except Exception as exc:  # pragma: no cover
            self._append_event(f'Could not query data service status before loadstep: {exc}')

        schedule = self.repository.get_current()
        if schedule is None:
            self._append_event('Cannot auto-start measurement for loadstep: no schedule loaded')
            return False

        self._auto_start_measurement_locked(schedule)

        try:
            status = self.data.status()
            return bool(status.get('recording'))
        except Exception as exc:  # pragma: no cover
            self._append_event(f'Could not confirm measurement state after auto-start: {exc}')
            return False

    def _take_data_loadstep(self, action: Any, step: ScheduleStep) -> dict[str, Any]:
        if not self._ensure_measurement_running_locked():
            raise RuntimeError('take_loadstep requires an active measurement session, and auto-start failed')

        params = action.params if isinstance(action.params, dict) else {}
        duration = params.get('duration_seconds', action.duration_s)
        if duration in (None, ''):
            schedule = self.repository.get_current()
            if schedule is not None:
                measurement_cfg = schedule.measurement_config if isinstance(schedule.measurement_config, dict) else {}
                duration = measurement_cfg.get('loadstep_duration_seconds')
        duration_seconds = float(duration if duration is not None else 30.0)
        loadstep_name = str(params.get('loadstep_name') or self._default_data_name(suffix='ls'))

        loadstep_parameters_raw = params.get('parameters')
        loadstep_parameters = None
        if isinstance(loadstep_parameters_raw, list):
            parsed = [str(item) for item in loadstep_parameters_raw if str(item).strip()]
            loadstep_parameters = parsed or None

        result = self.data.take_loadstep(
            duration_seconds=duration_seconds,
            loadstep_name=loadstep_name,
            parameters=loadstep_parameters,
        )
        if result.get('ok', False):
            selected_parameters = loadstep_parameters if loadstep_parameters is not None else None
            self._append_data_record({
                'kind': 'loadstep_started',
                'name': str(result.get('loadstep_name') or loadstep_name),
                'duration_seconds': duration_seconds,
                'parameters_count': len(selected_parameters) if isinstance(selected_parameters, list) else None,
                'timestamp': self._utc_now_iso(),
            })
        return result

    def _run_triggered_loadsteps_locked(self, step: ScheduleStep, values: dict[str, Any]) -> None:
        for index, action in enumerate(step.actions):
            if action.kind != 'take_loadstep':
                continue
            if self._action_timing(action) != 'on_trigger':
                continue
            if index in self._step_runtime.fired_loadstep_triggers:
                continue

            params = action.params if isinstance(action.params, dict) else {}
            trigger_wait_payload = params.get('trigger_wait')
            if not isinstance(trigger_wait_payload, dict):
                continue

            trigger_spec = parse_wait_spec(trigger_wait_payload)
            if trigger_spec is None:
                continue

            state_key = f'action[{index}]'
            previous_state = self._step_runtime.loadstep_trigger_states.get(state_key)
            if not isinstance(previous_state, WaitState):
                previous_state = WaitState()

            result = self.wait_engine.evaluate(
                trigger_spec,
                context=WaitContext(
                    now_monotonic=time.monotonic(),
                    step_started_monotonic=self._step_runtime.started_monotonic,
                    values=values,
                ),
                previous_state=previous_state,
            )
            self._step_runtime.loadstep_trigger_states[state_key] = result.next_state

            if not result.matched:
                continue

            loadstep_result = self._take_data_loadstep(action, step)
            if not loadstep_result.get('ok', False):
                raise RuntimeError(f'Action failed for take_loadstep trigger: {loadstep_result}')
            self._step_runtime.fired_loadstep_triggers.add(index)
            self._status.last_action_result = loadstep_result
            loadstep_name = str(loadstep_result.get('loadstep_name') or '').strip()
            if loadstep_name:
                self._append_event(f'Triggered loadstep {loadstep_name} for step {step.name}')

    # ------------------------------------------------------------------ file lifecycle

    def _finalize_measurement_if_recording_locked(self, context: str) -> None:
        """Safely stop and save recording session, logging outcome."""
        try:
            status = self.data.status()
            if not bool(status.get('recording')):
                return
            config = status.get('config') if isinstance(status.get('config'), dict) else {}
            # After finalization, data service keeps only the archive, so avoid
            # appending to removed sidecar files from subsequent events.
            self._run_log_path = None
            self._schedule_export_path = None
            result = self.data.measure_stop()
            if result.get('ok', False):
                self._append_data_record({
                    'kind': 'measurement_finalized',
                    'source': context,
                    'session_name': str(config.get('session_name') or ''),
                    'archive_file': result.get('archive_file') or result.get('file'),
                    'archive_members': result.get('archived_members', []),
                    'samples_recorded': result.get('samples_recorded'),
                    'completed_loadsteps': result.get('completed_loadsteps'),
                    'timestamp': self._utc_now_iso(),
                })
                self._append_event(f'{context}; measurement archive finalized')
            else:
                self._append_event(f'{context}; measurement finalize failed: {result}')
        except Exception as exc:  # pragma: no cover
            self._append_event(f'{context}; measurement finalize failed: {exc}')
