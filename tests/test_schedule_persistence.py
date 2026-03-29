from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from Services.schedule_service.repository import InMemoryScheduleRepository
from Services.schedule_service.runtime.core import ScheduleRuntime


@dataclass
class FakeStateStore:
    payload: dict | None = None
    saved_payloads: list[dict] = field(default_factory=list)

    def load(self):
        return self.payload

    def save(self, payload: dict):
        self.saved_payloads.append(payload)


class FakeControlClient:
    def release_manual(self):
        return {"ok": True}


class FakeDataClient:
    def status(self):
        return {"recording": False, "active_loadsteps": [], "completed_loadsteps": []}


def test_runtime_restores_paused_state_and_schedule_metadata() -> None:
    store = FakeStateStore(
        payload={
            "schedule": {
                "id": "schedule-1",
                "name": "Restore Test",
                "setup_steps": [{"id": "setup-1", "name": "Setup Step", "actions": []}],
                "plan_steps": [{"id": "plan-1", "name": "Plan Step", "actions": []}],
            },
            "state": "paused",
            "phase": "plan",
            "current_step_index": 0,
            "step_started_at_utc": "2026-03-29T12:00:00Z",
            "pause_reason": None,
            "owned_target_owners": {"reactor.temp.setpoint": "schedule_service"},
            "last_action_result": {"ok": True},
            "data_records": [{"kind": "measurement_started"}],
            "event_log": ["Run paused"],
        }
    )

    runtime = ScheduleRuntime(
        control_client=FakeControlClient(),
        data_client=FakeDataClient(),
        repository=InMemoryScheduleRepository(),
        state_store=store,
    )

    status = runtime.status()
    assert status["state"] == "paused"
    assert status["phase"] == "plan"
    assert status["current_step_index"] == 0
    assert status["current_step_name"] == "Plan Step"
    assert status["schedule_id"] == "schedule-1"
    assert status["schedule_name"] == "Restore Test"
    assert status["owned_targets"] == ["reactor.temp.setpoint"]
    assert status["pause_reason"] == "restored_paused"
    assert status["wait_message"] == "Paused after restore"
    assert runtime.repository.get_current() is not None


def test_runtime_restore_truncates_logs_and_handles_invalid_timestamp() -> None:
    store = FakeStateStore(
        payload={
            "schedule": {
                "id": "schedule-2",
                "name": "Truncate Test",
                "plan_steps": [{"id": "plan-1", "name": "Only Step", "actions": []}],
            },
            "state": "running",
            "phase": "plan",
            "current_step_index": 0,
            "step_started_at_utc": "not-a-timestamp",
            "owned_targets": ["pump.speed"],
            "data_records": [{"kind": f"record-{idx}"} for idx in range(250)],
            "event_log": [f"event-{idx}" for idx in range(150)],
        }
    )

    runtime = ScheduleRuntime(
        control_client=FakeControlClient(),
        data_client=FakeDataClient(),
        repository=InMemoryScheduleRepository(),
        state_store=store,
    )

    status = runtime.status()
    assert len(status["data_records"]) == 200
    assert status["data_records"][0] == {"kind": "record-50"}
    assert len(status["event_log"]) == 100
    assert status["event_log"][0] == "event-50"
    assert status["owned_targets"] == ["pump.speed"]
    assert status["wait_message"] == "Active step: Only Step"
    assert runtime._step_runtime.started_monotonic is None


def test_runtime_persist_locked_writes_schedule_and_owner_maps() -> None:
    store = FakeStateStore()
    runtime = ScheduleRuntime(
        control_client=FakeControlClient(),
        data_client=FakeDataClient(),
        repository=InMemoryScheduleRepository(),
        state_store=store,
    )

    runtime.load_schedule(
        {
            "id": "persist-1",
            "name": "Persist Test",
            "plan_steps": [{"id": "p1", "name": "Step", "actions": []}],
        }
    )

    runtime._status.state = "running"
    runtime._phase = "plan"
    runtime._step_index = 0
    runtime._status.current_step_name = "Step"
    runtime._status.pause_reason = None
    runtime._status.owned_targets = ["reactor.temp"]
    runtime._owned_target_owners = {"reactor.temp": "schedule_service"}
    runtime._status.last_action_result = {"ok": True, "kind": "write"}
    runtime._status.data_records = [{"kind": "measurement_started"}]
    runtime._status.event_log = ["run started"]

    runtime._persist_locked()
    payload = store.saved_payloads[-1]

    assert payload["schedule"]["id"] == "persist-1"
    assert payload["state"] == "running"
    assert payload["phase"] == "plan"
    assert payload["current_step_index"] == 0
    assert payload["owned_targets"] == ["reactor.temp"]
    assert payload["owned_target_owners"] == {"reactor.temp": "schedule_service"}
    assert payload["last_action_result"] == {"ok": True, "kind": "write"}


def test_runtime_restore_uses_owned_targets_fallback_and_wait_message_states() -> None:
    base_payload = {
        "schedule": {
            "id": "schedule-3",
            "name": "Fallback Test",
            "plan_steps": [{"id": "p1", "name": "P1", "actions": []}],
        },
        "phase": "plan",
        "current_step_index": 0,
        "owned_targets": ["reactor.temp", "pump.speed"],
        "owned_target_owners": ["invalid-non-dict"],
        "event_log": ["e1"],
        "data_records": [{"kind": "r1"}],
    }

    completed_store = FakeStateStore(payload={**base_payload, "state": "completed"})
    completed_runtime = ScheduleRuntime(
        control_client=FakeControlClient(),
        data_client=FakeDataClient(),
        repository=InMemoryScheduleRepository(),
        state_store=completed_store,
    )
    assert completed_runtime.status()["wait_message"] == "Completed"
    assert completed_runtime.status()["owned_targets"] == ["reactor.temp", "pump.speed"]

    stopped_store = FakeStateStore(payload={**base_payload, "state": "stopped", "phase": "idle", "current_step_index": -1})
    stopped_runtime = ScheduleRuntime(
        control_client=FakeControlClient(),
        data_client=FakeDataClient(),
        repository=InMemoryScheduleRepository(),
        state_store=stopped_store,
    )
    assert stopped_runtime.status()["wait_message"] == "Run stopped"

    idle_store = FakeStateStore(payload={**base_payload, "state": "idle", "phase": "idle", "current_step_index": -1})
    idle_runtime = ScheduleRuntime(
        control_client=FakeControlClient(),
        data_client=FakeDataClient(),
        repository=InMemoryScheduleRepository(),
        state_store=idle_store,
    )
    assert idle_runtime.status()["wait_message"] == "Idle"


def test_restore_started_monotonic_parses_iso_timestamp() -> None:
    runtime = ScheduleRuntime(
        control_client=FakeControlClient(),
        data_client=FakeDataClient(),
        repository=InMemoryScheduleRepository(),
        state_store=FakeStateStore(),
    )

    now_utc = datetime.now(timezone.utc)
    started_iso = now_utc.isoformat().replace("+00:00", "Z")
    restored = runtime._restore_started_monotonic(started_iso)

    assert isinstance(restored, float)