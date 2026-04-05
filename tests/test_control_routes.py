from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Services.control_service.api import routes_control


class StubOwnership:
    def __init__(self, owners: dict[str, str | None] | None = None):
        self._owners = owners or {}
        self.requested: list[tuple[str, str]] = []

    def snapshot(self) -> dict[str, dict[str, str | None]]:
        return {
            key: {"owner": value}
            for key, value in self._owners.items()
        }

    def get_owner(self, target: str) -> str | None:
        return self._owners.get(target)

    def request(self, target: str, owner: str) -> None:
        self.requested.append((target, owner))
        self._owners[target] = owner


class StubRuntime:
    def __init__(self, owners: dict[str, str | None] | None = None):
        self.ownership = StubOwnership(owners)
        self.backend = SimpleNamespace(snapshot=lambda targets: {name: 12.5 for name in targets})
        self.manual_calls: list[dict[str, object]] = []
        self.release_manual_targets: list[list[str] | None] = []
        self.pin_calls: list[dict[str, object]] = []
        self.unpin_calls: list[str] = []
        self.ramp_calls: list[tuple[dict[str, object], dict[str, float]]] = []
        self.request_calls: list[tuple[str, str]] = []
        self.release_calls: list[tuple[str, str]] = []
        self.force_takeover_calls: list[tuple[str, str, str]] = []
        self.reset_calls: list[str] = []
        self.clear_calls = 0
        self.read_calls: list[str] = []
        self.write_calls: list[dict[str, object]] = []

    def request_control(self, target: str, owner: str) -> dict[str, object]:
        self.request_calls.append((target, owner))
        return {"ok": True, "target": target, "owner": owner}

    def release_control(self, target: str, owner: str) -> dict[str, object]:
        self.release_calls.append((target, owner))
        return {"ok": True, "target": target, "owner": owner}

    def force_takeover(self, target: str, owner: str, *, reason: str) -> dict[str, object]:
        self.force_takeover_calls.append((target, owner, reason))
        return {"ok": True, "target": target, "owner": owner, "reason": reason}

    def reset_target(self, target: str) -> dict[str, object]:
        self.reset_calls.append(target)
        return {"ok": True, "target": target}

    def clear_all_ownership(self) -> dict[str, object]:
        self.clear_calls += 1
        return {"ok": True}

    def read_parameter(self, target: str) -> dict[str, object]:
        self.read_calls.append(target)
        return {"ok": True, "target": target, "value": 12.5}

    def set_parameter(self, *, target: str, value: object, owner: str) -> dict[str, object]:
        payload = {"target": target, "value": value, "owner": owner}
        self.write_calls.append(payload)
        return {"ok": True, **payload}

    def manual_set_parameter(self, *, target: str, value: object, owner: str, reason: str) -> dict[str, object]:
        payload = {
            "target": target,
            "value": value,
            "owner": owner,
            "reason": reason,
        }
        self.manual_calls.append(payload)
        return {"ok": True, **payload}

    def release_manual_controls(self, *, targets: list[str] | None) -> dict[str, object]:
        self.release_manual_targets.append(targets)
        return {"ok": True, "targets": targets}

    def pin_control_parameter(self, **payload: object) -> dict[str, object]:
        self.pin_calls.append(payload)
        return {"ok": True, **payload}

    def unpin_control_parameter(self, *, target: str) -> dict[str, object]:
        self.unpin_calls.append(target)
        return {"ok": True, "target": target}

    def start_ramp(self, data: dict[str, object], *, values: dict[str, float]) -> dict[str, object]:
        self.ramp_calls.append((data, values))
        return {"ok": True, "values": values}


def _client(runtime: StubRuntime | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(routes_control.router)
    if runtime is not None:
        routes_control.set_runtime(runtime)
    return TestClient(app)


def test_ownership_requires_runtime() -> None:
    response = _client().get("/control/ownership")
    assert response.status_code == 503
    assert "not initialized" in response.json()["detail"].lower()


def test_ownership_returns_runtime_snapshot() -> None:
    runtime = StubRuntime(owners={"reactor.temp.setpoint": "operator"})
    response = _client(runtime).get("/control/ownership")

    assert response.status_code == 200
    assert response.json() == {"reactor.temp.setpoint": {"owner": "operator"}}


def test_manual_write_uses_operator_owner() -> None:
    runtime = StubRuntime()
    response = _client(runtime).post(
        "/control/manual-write",
        json={"target": "reactor.temp.setpoint", "value": 35.0, "owner": "custom-owner"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["owner"] == "operator"
    assert runtime.manual_calls[-1]["owner"] == "operator"


def test_release_manual_normalizes_target_list() -> None:
    runtime = StubRuntime()
    response = _client(runtime).post(
        "/control/release-manual",
        json={"targets": [" reactor.temp.setpoint ", "", "agitator.rpm", "  "]},
    )

    assert response.status_code == 200
    assert response.json()["targets"] == ["reactor.temp.setpoint", "agitator.rpm"]
    assert runtime.release_manual_targets[-1] == ["reactor.temp.setpoint", "agitator.rpm"]


def test_release_manual_without_valid_targets_passes_none() -> None:
    runtime = StubRuntime()
    response = _client(runtime).post(
        "/control/release-manual",
        json={"targets": "not-a-list"},
    )

    assert response.status_code == 200
    assert response.json()["targets"] is None
    assert runtime.release_manual_targets[-1] is None


def test_basic_control_endpoints_delegate_to_runtime() -> None:
    runtime = StubRuntime()
    client = _client(runtime)

    assert client.post("/control/request", json={"target": "t1", "owner": "alice"}).json() == {
        "ok": True,
        "target": "t1",
        "owner": "alice",
    }
    assert client.post("/control/release", json={"target": "t1", "owner": "alice"}).json() == {
        "ok": True,
        "target": "t1",
        "owner": "alice",
    }
    assert client.post("/control/force-takeover", json={"target": "t1", "owner": "alice"}).json() == {
        "ok": True,
        "target": "t1",
        "owner": "alice",
        "reason": "",
    }
    assert client.post("/control/reset", json={"target": "t1"}).json() == {"ok": True, "target": "t1"}
    assert client.post("/control/clear-ownership").json() == {"ok": True}
    assert client.get("/control/read/t1").json() == {"ok": True, "target": "t1", "value": 12.5}
    assert client.post("/control/write", json={"target": "t1", "value": 7.5, "owner": "alice"}).json() == {
        "ok": True,
        "target": "t1",
        "value": 7.5,
        "owner": "alice",
    }

    assert runtime.request_calls == [("t1", "alice")]
    assert runtime.release_calls == [("t1", "alice")]
    assert runtime.force_takeover_calls == [("t1", "alice", "")]
    assert runtime.reset_calls == ["t1"]
    assert runtime.clear_calls == 1
    assert runtime.read_calls == ["t1"]
    assert runtime.write_calls == [{"target": "t1", "value": 7.5, "owner": "alice"}]


def test_manual_map_pin_delegates_to_runtime() -> None:
    runtime = StubRuntime()
    response = _client(runtime).post(
        "/control/manual-map/pin",
        json={
            "target": "reactor.temp.setpoint",
            "label": "Temp",
            "group": "manual",
            "pin_scope": "manual",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert runtime.pin_calls[-1]["target"] == "reactor.temp.setpoint"
    assert runtime.pin_calls[-1]["label"] == "Temp"


def test_manual_map_unpin_delegates_to_runtime() -> None:
    runtime = StubRuntime()
    response = _client(runtime).post(
        "/control/manual-map/unpin",
        json={"target": "reactor.temp.setpoint"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "target": "reactor.temp.setpoint"}
    assert runtime.unpin_calls == ["reactor.temp.setpoint"]


def test_ramp_requires_owner() -> None:
    runtime = StubRuntime()
    response = _client(runtime).post(
        "/control/ramp",
        json={"target": "reactor.temp.setpoint", "value": 50.0, "duration": 60},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": False, "error": "owner required"}


def test_ramp_rejects_conflicting_owner() -> None:
    runtime = StubRuntime(owners={"reactor.temp.setpoint": "schedule"})
    response = _client(runtime).post(
        "/control/ramp",
        json={
            "target": "reactor.temp.setpoint",
            "value": 50.0,
            "duration": 60,
            "owner": "operator",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "owned by schedule" in response.json()["error"]


def test_ramp_requires_target_or_targets() -> None:
    runtime = StubRuntime()
    response = _client(runtime).post(
        "/control/ramp",
        json={"value": 50.0, "duration": 60, "owner": "operator"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": False, "error": "target or targets required"}


def test_ramp_accepts_targets_list_and_uses_backend_snapshot() -> None:
    runtime = StubRuntime()
    response = _client(runtime).post(
        "/control/ramp",
        json={
            "targets": ["reactor.temp.setpoint", None, "agitator.rpm"],
            "value": 50.0,
            "duration": 60,
            "owner": "operator",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "values": {"reactor.temp.setpoint": 12.5, "agitator.rpm": 12.5},
    }
    assert runtime.ownership.requested == [
        ("reactor.temp.setpoint", "operator"),
        (None, "operator"),
        ("agitator.rpm", "operator"),
    ]
    assert runtime.ramp_calls == [
        (
            {
                "targets": ["reactor.temp.setpoint", None, "agitator.rpm"],
                "value": 50.0,
                "duration": 60,
                "owner": "operator",
            },
            {"reactor.temp.setpoint": 12.5, "agitator.rpm": 12.5},
        )
    ]
