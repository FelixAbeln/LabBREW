"""Target ownership tracking for ScheduleRuntime.

Tracks which targets are currently owned by the scheduler, updates the
owned_targets list on RunStatus, and handles release on run stop/clear.
All methods are mixed into ScheduleRuntime via _OwnershipMixin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import ScheduleStep


class _OwnershipMixin:
    def _ownership_lost(self, step: ScheduleStep) -> bool:
        """Return True if any controlled target was taken by a different owner."""
        ownership = self.control.ownership()
        for action in step.actions:
            if (
                action.kind not in {"request_control", "write", "ramp"}
                or not action.target
            ):
                continue
            if action.target not in self._status.owned_targets:
                continue
            owner_meta = ownership.get(action.target) or {}
            current_owner = (
                owner_meta.get("owner") if isinstance(owner_meta, dict) else None
            )
            expected = self._owned_target_owners.get(
                action.target, action.owner or self.owner
            )
            if current_owner != expected:
                return True
        return False

    def _reclaim_step_ownership_locked(self, step: ScheduleStep) -> dict[str, object]:
        """Re-apply only control-owning actions for the active step
        after manual takeover is released.
        """
        last_result: dict[str, object] = {"ok": True}

        for action in step.actions:
            if action.kind not in {"request_control", "write", "ramp"}:
                continue
            if not action.target:
                return {
                    "ok": False,
                    "error": (
                        "missing target for control-owning action "
                        f"{getattr(action, 'kind', None)}"
                    ),
                }

            owner = action.owner or self.owner
            if action.kind == "request_control":
                last_result = self.control.request_control(action.target, owner)
            elif action.kind == "write":
                last_result = self.control.write(action.target, action.value, owner)
            else:
                last_result = self.control.ramp(
                    target=action.target,
                    value=action.value,
                    duration_s=float(action.duration_s or 0.0),
                    owner=owner,
                )

            if not last_result.get("ok", False):
                return last_result

            self._remember_owned_target_locked(action.target, owner)

        return last_result

    def _release_owned_targets_locked(self, context: str) -> None:
        for target, owner in list(self._owned_target_owners.items()):
            try:
                result = self.control.release_control(target, owner)
                if result.get("ok"):
                    self._append_event(f"{context}; released ownership for {target}")
            except Exception as exc:  # pragma: no cover
                self._append_event(
                    f"{context}; failed to release ownership for {target}: {exc}"
                )
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
