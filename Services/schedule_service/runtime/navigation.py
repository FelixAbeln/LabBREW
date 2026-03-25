"""Step and phase navigation for ScheduleRuntime.

Handles activating a step, advancing forward/backward through steps,
and transitioning between setup → plan → completed.
All methods are mixed into ScheduleRuntime via _NavigationMixin.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ..._shared.operator_engine import EvaluationState
from ..._shared.wait_engine import WaitState
from ..models import StepRuntime

if TYPE_CHECKING:
    from ..models import ScheduleDefinition, ScheduleStep


class _NavigationMixin:

    def _activate_step_locked(self) -> None:
        schedule = self.repository.get_current()
        if schedule is None:
            return
        steps = self._phase_steps(schedule)
        if not (0 <= self._step_index < len(steps)):
            return
        step = steps[self._step_index]
        self._step_runtime = StepRuntime(
            actions_applied=False,
            started_monotonic=time.monotonic(),
            started_at_utc=self._utc_now_iso(),
            wait_state=WaitState(condition_state=EvaluationState()),
        )
        self._status.phase = self._phase
        self._status.current_step_index = self._step_index
        self._status.current_step_name = step.name
        self._status.wait_message = f'Active step: {step.name}'
        self._status.pause_reason = None

    def _advance_step_locked(self, schedule: ScheduleDefinition, manual: bool = False) -> None:
        """Move to the next enabled step (or phase/complete if none remain).

        Measurement runs globally and is NOT rolled over between steps.
        Exit loadsteps are only triggered via the natural _tick path, never on manual Next.
        """
        steps = self._phase_steps(schedule)
        next_index = self._next_enabled_index(steps, self._step_index + 1)
        if next_index >= 0:
            self._step_index = next_index
            self._activate_step_locked()
            if manual:
                self._append_event('Moved to next step')
            return
        self._advance_phase_or_complete_locked(schedule)
        if manual and self._status.state != 'completed':
            self._append_event('Moved to next step')

    def _move_previous_locked(self, schedule: ScheduleDefinition) -> bool:
        """Move back to the nearest previous enabled step, crossing phase boundaries."""
        steps = self._phase_steps(schedule)
        for index in range(self._step_index - 1, -1, -1):
            if steps[index].enabled:
                self._step_index = index
                self._activate_step_locked()
                self._append_event('Moved to previous step')
                return True
        # Cross from plan back into setup if possible.
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
