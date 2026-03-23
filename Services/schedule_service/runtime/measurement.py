"""Measurement and loadstep lifecycle for ScheduleRuntime.

Measurement is global: it auto-starts when a run begins (driven by
schedule.measurement_config) and runs continuously until the run stops,
completes, or is cancelled, always saving the file on exit.

Per-step loadsteps (take_loadstep) still fire at step conclusion
(before_next timing) and are handled here too.
All methods are mixed into ScheduleRuntime via _MeasurementMixin.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..models import ScheduleDefinition, ScheduleStep


class _MeasurementMixin:

    # ------------------------------------------------------------------ run-level auto-start

    def _auto_start_measurement_locked(self, schedule: ScheduleDefinition) -> None:
        """Start global measurement at run start using schedule.measurement_config.

        Idempotent: does nothing if measurement_config is empty or already recording.
        Parameters are auto-discovered from the control snapshot.
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

        snapshot = self.control.snapshot()
        values = snapshot.get('values') if isinstance(snapshot, dict) else {}
        parameters = sorted(values.keys()) if isinstance(values, dict) else []

        if not parameters:
            self._append_event('Global measurement skipped: no parameters available from control snapshot')
            return

        hz = float(config.get('hz') or 10.0)
        output_dir = str(config.get('output_dir') or 'data/measurements')
        output_format = str(config.get('output_format') or 'parquet')
        session_name = str(
            config.get('session_name')
            or config.get('name')
            or self._default_data_name()
        )

        try:
            setup = self.data.setup_measurement(
                parameters=parameters,
                hz=hz,
                output_dir=output_dir,
                output_format=output_format,
                session_name=session_name,
            )
            if not setup.get('ok', False):
                self._append_event(f'Global measurement setup failed: {setup}')
                return
            start = self.data.measure_start()
            if start.get('ok', False):
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
        output_dir = str(params.get('output_dir', 'data/measurements'))
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
        duration_seconds = float(duration if duration is not None else 30.0)
        loadstep_name = str(params.get('loadstep_name') or self._default_data_name(suffix='ls'))

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

    # ------------------------------------------------------------------ file lifecycle

    def _finalize_measurement_if_recording_locked(self, context: str) -> None:
        """Safely stop and save recording session, logging outcome."""
        try:
            status = self.data.status()
            if not bool(status.get('recording')):
                return
            result = self.data.measure_stop()
            if result.get('ok', False):
                self._append_event(f'{context}; measurement file finalized')
            else:
                self._append_event(f'{context}; measurement finalize failed: {result}')
        except Exception as exc:  # pragma: no cover
            self._append_event(f'{context}; measurement finalize failed: {exc}')
