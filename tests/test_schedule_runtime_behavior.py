from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from Services.schedule_service.repository import InMemoryScheduleRepository
from Services.schedule_service.runtime.core import ScheduleRuntime


@dataclass
class FakeStateStore:
    payloads: list[dict] = field(default_factory=list)

    def load(self):
        return None

    def save(self, payload: dict):
        self.payloads.append(payload)


@dataclass
class FakeControlClient:
    values: dict[str, float]
    owners: dict[str, str | None] = field(default_factory=dict)
    writes: list[tuple[str, float, str]] = field(default_factory=list)
    manual_release_calls: list[list[str] | None] = field(default_factory=list)

    def release_manual(self, targets=None):
        self.manual_release_calls.append(targets)
        target_filter = set(targets or []) if targets else None
        for target, owner in list(self.owners.items()):
            if owner != "operator":
                continue
            if target_filter is not None and target not in target_filter:
                continue
            self.owners[target] = None
        return {"ok": True}

    def snapshot(self, targets=None):
        source = self.values if targets is None else {name: self.values.get(name) for name in targets}
        return {"ok": True, "values": dict(source)}

    def ownership(self):
        return {
            key: {"owner": value}
            for key, value in self.owners.items()
            if value is not None
        }

    def request_control(self, target: str, owner: str):
        current_owner = self.owners.get(target)
        if current_owner not in (None, owner):
            return {"ok": False, "target": target, "owner": owner, "current_owner": current_owner}
        self.owners[target] = owner
        return {"ok": True, "target": target, "owner": owner}

    def release_control(self, target: str, owner: str):
        if self.owners.get(target) == owner:
            self.owners[target] = None
            return {"ok": True}
        return {"ok": False}

    def write(self, target: str, value: float, owner: str):
        current_owner = self.owners.get(target)
        if current_owner not in (None, owner):
            return {"ok": False, "target": target, "owner": owner, "current_owner": current_owner}
        self.owners[target] = owner
        self.values[target] = value
        self.writes.append((target, value, owner))
        return {"ok": True, "target": target, "value": value, "owner": owner}

    def ramp(self, *, target: str, value, duration_s: float, owner: str):
        current_owner = self.owners.get(target)
        if current_owner not in (None, owner):
            return {"ok": False, "target": target, "owner": owner, "current_owner": current_owner, "duration": duration_s}
        self.owners[target] = owner
        self.values[target] = float(value)
        return {"ok": True, "target": target, "value": value, "owner": owner, "duration": duration_s}

    def read(self, target: str):
        return {"ok": True, "value": self.values.get(target)}


@dataclass
class FakeDataClient:
    recording: bool = False
    setup_calls: list[dict] = field(default_factory=list)
    start_calls: int = 0
    stop_calls: int = 0
    loadstep_calls: list[dict] = field(default_factory=list)
    completed_loadsteps: list[dict] = field(default_factory=list)
    active_loadsteps: list[dict] = field(default_factory=list)
    session_name: str | None = None

    def status(self):
        return {
            "backend_connected": True,
            "recording": self.recording,
            "config": {"session_name": self.session_name} if self.session_name else None,
            "active_loadstep_names": [item["name"] for item in self.active_loadsteps],
            "active_loadsteps": list(self.active_loadsteps),
            "completed_loadsteps": list(self.completed_loadsteps),
        }

    def setup_measurement(self, **kwargs):
        self.setup_calls.append(kwargs)
        self.session_name = kwargs.get("session_name")
        return {"ok": True, "session_name": self.session_name}

    def measure_start(self):
        self.start_calls += 1
        self.recording = True
        return {"ok": True}

    def measure_stop(self):
        self.stop_calls += 1
        self.recording = False
        return {
            "ok": True,
            "archive_file": "test.archive.zip",
            "archived_members": [],
            "samples_recorded": 3,
            "completed_loadsteps": len(self.completed_loadsteps),
        }

    def take_loadstep(self, **kwargs):
        name = kwargs.get("loadstep_name") or "ls"
        self.loadstep_calls.append(kwargs)
        self.active_loadsteps.append({"name": name, "remaining_seconds": 1})
        return {"ok": True, "loadstep_name": name}

    def complete_active_loadsteps(self):
        self.completed_loadsteps.extend({"name": item["name"]} for item in self.active_loadsteps)
        self.active_loadsteps.clear()


def _make_runtime(_tmp_path: Path, *, control: FakeControlClient, data: FakeDataClient) -> ScheduleRuntime:
    state_store = FakeStateStore()
    repo = InMemoryScheduleRepository()
    return ScheduleRuntime(
        control_client=control,
        data_client=data,
        repository=repo,
        state_store=state_store,
        poll_interval_s=0.05,
    )


def test_schedule_runtime_executes_simple_plan_and_finishes(tmp_path: Path) -> None:
    control = FakeControlClient(values={"reactor.temp.setpoint": 20.0})
    data = FakeDataClient()
    runtime = _make_runtime(tmp_path, control=control, data=data)

    payload = {
        "id": "simple-schedule",
        "name": "Simple Schedule",
        "measurement_config": {
            "parameters": ["reactor.temp.setpoint"],
            "output_dir": str(tmp_path),
            "output_format": "jsonl",
            "session_name": "simple_run",
            "hz": 2,
        },
        "plan_steps": [
            {
                "id": "step-1",
                "name": "Set Temperature",
                "actions": [
                    {
                        "kind": "write",
                        "target": "reactor.temp.setpoint",
                        "value": 30.0,
                        "owner": "schedule_service",
                    }
                ],
                "wait": {"kind": "none"},
            }
        ],
    }

    assert runtime.load_schedule(payload)["ok"] is True
    assert runtime.start_run()["ok"] is True

    runtime._tick()

    status = runtime.status()
    assert status["state"] == "completed"
    assert control.values["reactor.temp.setpoint"] == 30.0
    assert data.start_calls == 1
    assert data.stop_calls == 1
    assert any(record["kind"] == "measurement_started" for record in status["data_records"])
    assert any(record["kind"] == "measurement_finalized" for record in status["data_records"])


def test_schedule_runtime_waits_for_before_next_loadstep_completion(tmp_path: Path) -> None:
    control = FakeControlClient(values={"reactor.temp.setpoint": 20.0})
    data = FakeDataClient(recording=True, session_name="existing")
    runtime = _make_runtime(tmp_path, control=control, data=data)

    payload = {
        "id": "loadstep-schedule",
        "name": "Loadstep Schedule",
        "plan_steps": [
            {
                "id": "step-1",
                "name": "Capture Loadstep",
                "actions": [
                    {
                        "kind": "take_loadstep",
                        "params": {
                            "timing": "before_next",
                            "loadstep_name": "ls_step_1",
                            "duration_seconds": 1,
                        },
                    }
                ],
                "wait": {"kind": "elapsed", "duration_s": 0},
            }
        ],
    }

    runtime.load_schedule(payload)
    runtime.start_run()

    runtime._tick()
    status_after_first_tick = runtime.status()
    assert status_after_first_tick["state"] == "running"
    assert "Waiting for loadstep completion" in status_after_first_tick["wait_message"]
    assert data.loadstep_calls and data.loadstep_calls[0]["loadstep_name"] == "ls_step_1"

    data.complete_active_loadsteps()
    runtime._tick()

    final_status = runtime.status()
    assert final_status["state"] == "completed"


def test_schedule_runtime_rising_wait_with_before_next_loadstep_completes(tmp_path: Path) -> None:
    control = FakeControlClient(values={"event.ready": False})
    data = FakeDataClient(recording=True, session_name="existing")
    runtime = _make_runtime(tmp_path, control=control, data=data)

    payload = {
        "id": "event-loadstep-schedule",
        "name": "Event Loadstep Schedule",
        "plan_steps": [
            {
                "id": "step-1",
                "name": "Capture On Edge",
                "actions": [
                    {
                        "kind": "take_loadstep",
                        "params": {
                            "timing": "before_next",
                            "loadstep_name": "ls_event_edge",
                            "duration_seconds": 1,
                        },
                    }
                ],
                "wait": {
                    "kind": "rising",
                    "child": {
                        "kind": "condition",
                        "condition": {"source": "event.ready", "operator": "==", "threshold": True},
                    },
                },
            }
        ],
    }

    runtime.load_schedule(payload)
    runtime.start_run()

    runtime._tick()
    assert runtime.status()["state"] == "running"
    assert not data.loadstep_calls

    control.values["event.ready"] = True
    runtime._tick()
    status_after_edge = runtime.status()
    assert status_after_edge["state"] == "running"
    assert "Waiting for loadstep completion" in status_after_edge["wait_message"]
    assert data.loadstep_calls and data.loadstep_calls[0]["loadstep_name"] == "ls_event_edge"

    data.complete_active_loadsteps()
    runtime._tick()

    assert runtime.status()["state"] == "completed"


def test_schedule_runtime_on_trigger_loadstep_fires_once_on_rising_edge(tmp_path: Path) -> None:
    control = FakeControlClient(values={"event.start": False})
    data = FakeDataClient(recording=True, session_name="existing")
    runtime = _make_runtime(tmp_path, control=control, data=data)

    payload = {
        "id": "trigger-loadstep",
        "name": "Trigger Loadstep",
        "measurement_config": {
            "loadstep_duration_seconds": 12,
        },
        "plan_steps": [
            {
                "id": "p1",
                "name": "Step",
                "actions": [
                    {
                        "kind": "take_loadstep",
                        "params": {
                            "timing": "on_trigger",
                            "trigger_wait": {
                                "kind": "rising",
                                "child": {
                                    "kind": "condition",
                                    "condition": {"source": "event.start", "operator": "==", "threshold": True},
                                },
                            },
                        },
                    }
                ],
                "wait": {"kind": "elapsed", "duration_s": 1000},
            }
        ],
    }

    runtime.load_schedule(payload)
    runtime.start_run()

    runtime._tick()
    assert not data.loadstep_calls

    control.values["event.start"] = True
    runtime._tick()
    assert len(data.loadstep_calls) == 1
    assert data.loadstep_calls[0]["duration_seconds"] == 12.0

    runtime._tick()
    assert len(data.loadstep_calls) == 1
