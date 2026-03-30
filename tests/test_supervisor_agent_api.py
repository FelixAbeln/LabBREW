from __future__ import annotations

from fastapi.testclient import TestClient

from Supervisor.infrastructure import agent_api


class StubSignalClient:
    def __init__(self, host: str, port: int, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def create_parameter(self, name, parameter_type, *, value=None, config=None, metadata=None):
        return {
            "name": name,
            "parameter_type": parameter_type,
            "value": value,
            "config": config or {},
            "metadata": metadata or {},
        }

    def import_snapshot(self, snapshot, *, replace_existing=True, save_to_disk=True):
        return {
            "imported": True,
            "snapshot": snapshot,
            "replace_existing": replace_existing,
            "save_to_disk": save_to_disk,
        }

    def describe(self):
        return {}

    def graph_info(self):
        return {}

    def stats(self):
        return {}

    def export_snapshot(self):
        return {"snapshot": {}}

    def list_parameter_type_ui(self):
        return []

    def get_parameter_type_ui(self, parameter_type):
        return {"parameter_type": parameter_type}

    def set_value(self, name, value):
        return True

    def update_config(self, name, **config):
        return True

    def update_metadata(self, name, **metadata):
        return True

    def delete_parameter(self, name):
        return True

    def list_source_types_ui(self):
        return []

    def get_source_type_ui(self, source_type, name=None, mode=None):
        return {"source_type": source_type, "name": name, "mode": mode}

    def list_sources(self):
        return []

    def create_source(self, name, source_type, config=None):
        return True

    def update_source(self, name, config=None):
        return True

    def delete_source(self, name):
        return True


def _build_client(monkeypatch, *, update_status_provider=None, apply_update_action=None) -> TestClient:
    monkeypatch.setattr(agent_api, "SignalClient", StubSignalClient)
    app = agent_api.build_agent_app(
        node_id="node-1",
        node_name="Node 1",
        service_map=lambda: {},
        summary_provider=lambda: {},
        proxy_session=None,
        update_status_provider=update_status_provider,
        apply_update_action=apply_update_action,
    )
    return TestClient(app)


def test_create_param_reads_json_body(monkeypatch) -> None:
    client = _build_client(monkeypatch)

    response = client.post(
        "/parameterdb/params",
        json={
            "name": "test.param",
            "parameter_type": "static",
            "value": 7,
            "config": {},
            "metadata": {},
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_import_snapshot_reads_json_body(monkeypatch) -> None:
    client = _build_client(monkeypatch)

    response = client.post(
        "/parameterdb/snapshot-file",
        json={
            "snapshot": {"version": 1, "params": []},
            "replace_existing": True,
            "save_to_disk": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["imported"] is True


def test_agent_repo_status_endpoint_uses_provider(monkeypatch) -> None:
    calls: list[bool] = []

    def _status(force: bool) -> dict:
        calls.append(force)
        return {"outdated": True, "local_revision": "abc", "remote_revision": "def"}

    client = _build_client(monkeypatch, update_status_provider=_status)
    response = client.get("/agent/repo/status?force=1")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["status"]["outdated"] is True
    assert calls == [True]


def test_agent_repo_update_endpoint_uses_update_action(monkeypatch) -> None:
    client = _build_client(
        monkeypatch,
        apply_update_action=lambda: {"ok": True, "updated": True, "after": {"outdated": False}},
    )
    response = client.post("/agent/repo/update")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["updated"] is True


def test_agent_repo_endpoints_return_501_when_unconfigured(monkeypatch) -> None:
    client = _build_client(monkeypatch)

    status_resp = client.get("/agent/repo/status")
    update_resp = client.post("/agent/repo/update")

    assert status_resp.status_code == 501
    assert update_resp.status_code == 501


def test_agent_repo_update_failure_surfaces_detail(monkeypatch) -> None:
    client = _build_client(
        monkeypatch,
        apply_update_action=lambda: {"ok": False, "reason": "pip project install failed: wheel build error"},
    )

    response = client.post("/agent/repo/update")

    assert response.status_code == 500
    detail = response.json().get("detail")
    assert isinstance(detail, dict)
    assert detail.get("reason", "").startswith("pip project install failed")