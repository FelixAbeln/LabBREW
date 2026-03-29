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


def _build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(agent_api, "SignalClient", StubSignalClient)
    app = agent_api.build_agent_app(
        node_id="node-1",
        node_name="Node 1",
        service_map=lambda: {},
        summary_provider=lambda: {},
        proxy_session=None,
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