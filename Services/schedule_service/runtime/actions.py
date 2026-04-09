"""Action executor for ScheduleRuntime.

_apply_actions_locked  — dispatches on-enter actions for a step.
_run_exit_actions_locked — fires before_next loadsteps and polls for
                           their completion before allowing step advance.

All methods are mixed into ScheduleRuntime via _ActionsMixin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..._shared.wait_engine import parse_wait_spec

if TYPE_CHECKING:
    from ..models import ScheduleStep


class _ActionsMixin:
    # on-enter actions

    def _apply_actions_locked(self, step: ScheduleStep) -> None:
        last_result: dict[str, Any] = {"ok": True}
        for action in step.actions:
            owner = action.owner or self.owner
            if action.kind == "request_control":
                last_result = self.control.request_control(action.target or "", owner)
                if last_result.get("ok") and action.target:
                    self._remember_owned_target_locked(action.target, owner)
            elif action.kind == "write":
                last_result = self.control.write(
                    action.target or "", action.value, owner
                )
                if last_result.get("ok") and action.target:
                    self._remember_owned_target_locked(action.target, owner)
            elif action.kind == "ramp":
                last_result = self.control.ramp(
                    target=action.target or "",
                    value=action.value,
                    duration_s=float(action.duration_s or 0.0),
                    owner=owner,
                )
                if last_result.get("ok") and action.target:
                    self._remember_owned_target_locked(action.target, owner)
            elif action.kind == "release_control":
                last_result = self.control.release_control(action.target or "", owner)
                if last_result.get("ok") and action.target:
                    self._discard_owned_target_locked(action.target)
            elif action.kind == "global_measurement":
                mode_raw = action.params.get(
                    "mode", action.value if action.value is not None else "start"
                )
                mode = str(mode_raw or "start").strip().lower()
                if mode in {"start", "setup_start"}:
                    last_result = self._start_global_measurement(action, step)
                elif mode == "stop":
                    last_result = self._stop_global_measurement()
                else:
                    raise ValueError(f"Unsupported global_measurement mode: {mode}")
            elif action.kind == "take_loadstep":
                if self._action_timing(action) in {
                    "before_next",
                    "on_exit",
                    "on_trigger",
                }:
                    last_result = {"ok": True, "deferred": True}
                else:
                    last_result = self._take_data_loadstep(action, step)
            else:
                raise ValueError(f"Unsupported action kind: {action.kind}")

            if not last_result.get("ok", False):
                raise RuntimeError(f"Action failed for {action.kind}: {last_result}")

        self._step_runtime.actions_applied = True
        self._status.last_action_result = last_result
        self._append_event(f"Applied step {step.name}")

    # exit (before_next) actions

    def _run_exit_actions_locked(self, step: ScheduleStep) -> bool:
        """Fire before_next loadsteps and block until they complete.

        Returns True when the step is ready to advance, False when still waiting.
        Only runs for natural transitions (wait condition met), never for manual Next.
        """
        exit_actions = [
            action
            for action in step.actions
            if action.kind == "take_loadstep"
            and self._action_timing(action) in {"before_next", "on_exit"}
        ]

        if not exit_actions:
            return True

        # Steps with no real wait criterion should not trigger a conclusion loadstep.
        wait_spec = parse_wait_spec(step.wait)
        if wait_spec is None or wait_spec.kind == "none":
            self._append_event(
                f"Skipped exit loadstep for step {step.name}: no wait criteria defined"
            )
            return True

        # First call: fire the loadsteps and record their names.
        if not self._step_runtime.pending_exit_loadsteps:
            pending_names: set[str] = set()
            for action in exit_actions:
                result = self._take_data_loadstep(action, step)
                if not result.get("ok", False):
                    raise RuntimeError(
                        f"Exit action failed for {action.kind}: {result}"
                    )
                self._status.last_action_result = result
                loadstep_name = str(result.get("loadstep_name") or "").strip()
                if loadstep_name:
                    pending_names.add(loadstep_name)
                    self._append_event(
                        f"Started exit loadstep {loadstep_name} for step {step.name}"
                    )

            if pending_names:
                self._step_runtime.pending_exit_loadsteps = pending_names
                waiting_for = ", ".join(sorted(pending_names))
                self._status.wait_message = (
                    f"Waiting for loadstep completion: {waiting_for}"
                )
                return False

            return True

        # Subsequent calls: poll the data service for completion.
        data_status = self.data.status()
        active_names = {
            str(item)
            for item in (data_status.get("active_loadstep_names") or [])
            if str(item).strip()
        }
        completed_names = {
            str(item.get("name"))
            for item in (data_status.get("completed_loadsteps") or [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }

        pending = set(self._step_runtime.pending_exit_loadsteps)
        if (
            pending
            and pending.issubset(completed_names)
            and not (pending & active_names)
        ):
            finished = ", ".join(sorted(pending))
            self._append_event(f"Exit loadstep completed: {finished}")
            self._step_runtime.pending_exit_loadsteps.clear()
            return True

        # Build a human-readable remaining-time message.
        active_details = []
        for item in data_status.get("active_loadsteps") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name not in pending:
                continue
            remaining = item.get("remaining_seconds")
            if remaining is None:
                active_details.append(name)
            else:
                try:
                    active_details.append(f"{name} ({max(0, round(float(remaining)))}s)")
                except (TypeError, ValueError):
                    active_details.append(name)

        if active_details:
            self._status.wait_message = (
                f"Waiting for loadstep completion: {', '.join(active_details)}"
            )
        else:
            waiting_for = ", ".join(sorted(pending))
            self._status.wait_message = (
                f"Waiting for loadstep completion: {waiting_for}"
            )
        return False
