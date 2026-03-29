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
        self.ramp_calls: list[tuple[dict[str, object], dict[str, float]]] = []

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
