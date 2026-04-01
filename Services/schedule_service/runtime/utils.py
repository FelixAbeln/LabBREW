"""Utility helpers for ScheduleRuntime.

Covers: naming / slugify, phase helpers, step-index helpers, event log,
wait-source collection, and action-timing lookup.
All methods are mixed into ScheduleRuntime via _UtilsMixin.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..models import ScheduleDefinition, ScheduleStep


class _UtilsMixin:
    # ------------------------------------------------------------------ naming

    def _default_data_name(self, suffix: str = '') -> str:
        schedule_slug = self._slugify(self._status.schedule_id or 'schedule')
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        suffix_part = f'_{suffix}' if suffix else ''
        return f'scheduling_{schedule_slug}{suffix_part}_{timestamp}'

    def _slugify(self, value: str) -> str:
        cleaned = ''.join(ch if ch.isalnum() else '_' for ch in str(value).strip().lower())
        while '__' in cleaned:
            cleaned = cleaned.replace('__', '_')
        return cleaned.strip('_') or 'item'

    def _utc_now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    # ------------------------------------------------------------------ phase / step index helpers

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

    # ------------------------------------------------------------------ event log

    def _append_event(self, text: str) -> None:
        self._status.event_log.append(text)
        self._status.event_log = self._status.event_log[-100:]
        run_log_path = getattr(self, '_run_log_path', None)
        if run_log_path:
            try:
                with open(run_log_path, 'a', encoding='utf-8') as handle:
                    handle.write(f"{self._utc_now_iso()} {text}\n")
            except OSError as exc:
                # Emit one warning into the in-memory event log to avoid flooding while
                # still giving operators visibility that file logging is currently broken.
                if not getattr(self, '_run_log_write_error_reported', False):
                    self._run_log_write_error_reported = True
                    warning = f"Run log write failed ({run_log_path}): {exc}"
                    self._status.event_log.append(warning)
                    self._status.event_log = self._status.event_log[-100:]

    # ------------------------------------------------------------------ wait-source collection

    def _collect_values(self, step: ScheduleStep) -> dict[str, Any]:
        values: dict[str, Any] = {}
        sources = set(self._collect_wait_sources(step.wait))
        for action in getattr(step, 'actions', []) or []:
            if action.kind != 'take_loadstep' or self._action_timing(action) != 'on_trigger':
                continue
            params = action.params if isinstance(action.params, dict) else {}
            trigger_wait = params.get('trigger_wait')
            if isinstance(trigger_wait, dict):
                sources |= self._collect_wait_sources(trigger_wait)

        for source in sources:
            values[source] = self.control.read(source).get('value')
        return values

    def _collect_wait_sources(self, payload: dict[str, Any] | None) -> set[str]:
        found: set[str] = set()
        if not isinstance(payload, dict):
            return found
        condition = payload.get('condition')
        if isinstance(condition, dict):
            found |= self._collect_condition_sources(condition)
        child = payload.get('child')
        if isinstance(child, dict):
            found |= self._collect_wait_sources(child)
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

    # ------------------------------------------------------------------ action helpers

    def _action_timing(self, action: Any) -> str:
        params = action.params if isinstance(action.params, dict) else {}
        return str(params.get('timing', 'on_enter')).strip().lower()
