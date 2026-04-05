from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Services.control_service.api import routes_control, routes_system


class StubRuntime:
    def __init__(self):
        self.snapshot_targets = None
        self.control_ui_include_empty_cards = None

    def get_live_snapshot(self, *, targets):
        self.snapshot_targets = targets
        return {"ok": True, "targets": targets}

    def get_control_contract_snapshot(self):
        return {"contract": True}

    def get_datasource_contract_snapshot(self):
        return {"datasource": True}

    def get_control_ui_spec(self, include_empty_cards: bool = False):
        self.control_ui_include_empty_cards = include_empty_cards
        return {"cards": [], "include_empty_cards": include_empty_cards}


def _client(runtime: StubRuntime | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(routes_system.router)
    if runtime is not None:
        routes_control.set_runtime(runtime)
    return TestClient(app)


def test_system_health() -> None:
    response = _client().get("/system/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_snapshot_requires_runtime() -> None:
    response = _client().get("/system/snapshot")
    assert response.status_code == 503


def test_snapshot_normalizes_targets() -> None:
    runtime = StubRuntime()
    response = _client(runtime).get("/system/snapshot", params={"targets": " temp, pressure ,,rpm "})

    assert response.status_code == 200
    assert runtime.snapshot_targets == ["temp", "pressure", "rpm"]
    assert response.json()["targets"] == ["temp", "pressure", "rpm"]


def test_operators_uses_registry_loader(monkeypatch) -> None:
    class StubRegistry:
        def list_metadata(self):
            return [{"name": "operator_x"}]

    monkeypatch.setattr(routes_system, "load_registry", lambda: StubRegistry())

    response = _client().get("/system/operators")
    assert response.status_code == 200
    assert response.json() == [{"name": "operator_x"}]


def test_rule_dir_uses_storage_path(monkeypatch) -> None:
    monkeypatch.setattr(routes_system, "get_rule_dir", lambda: Path("data/Rules"))

    response = _client().get("/system/rule-dir")
    assert response.status_code == 200
    assert Path(response.json()["rule_dir"]).as_posix() == "data/Rules"


def test_system_schema_contains_manual_control_paths() -> None:
    response = _client().get("/system/schema")
    assert response.status_code == 200
    schema = response.json()
    assert schema["manual_control"]["write_path"] == "/control/manual-write"
    assert schema["manual_control"]["release_path"] == "/control/release-manual"
    assert schema["manual_control"]["pin_path"] == "/control/manual-map/pin"
    assert schema["manual_control"]["unpin_path"] == "/control/manual-map/unpin"


def test_snapshot_with_empty_targets_uses_none() -> None:
    runtime = StubRuntime()
    response = _client(runtime).get("/system/snapshot", params={"targets": ""})

    assert response.status_code == 200
    assert runtime.snapshot_targets is None
    assert response.json()["targets"] is None


def test_contract_and_ui_spec_endpoints_delegate_to_runtime() -> None:
    runtime = StubRuntime()
    client = _client(runtime)

    assert client.get("/system/control-contract").json() == {"contract": True}
    assert client.get("/system/datasource-contract").json() == {"datasource": True}
    assert client.get("/system/control-ui-spec").json() == {"cards": [], "include_empty_cards": False}
    assert runtime.control_ui_include_empty_cards is False

    assert client.get("/system/control-ui-spec", params={"include_empty_cards": "true"}).json() == {
        "cards": [],
        "include_empty_cards": True,
    }
    assert runtime.control_ui_include_empty_cards is True
