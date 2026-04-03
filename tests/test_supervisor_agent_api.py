from __future__ import annotations

import json

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
        return {"source_type": source_type, "name": name, "mode": mode, "graph": {"depends_on": ["relay.ch1"]}}

    def list_sources(self):
        return {"relay": {"source_type": "modbus_relay", "running": True, "config": {"parameter_prefix": "relay"}}}

    def create_source(self, name, source_type, config=None):
        return True

    def update_source(self, name, config=None):
        return True

    def delete_source(self, name):
        return True


class _FakeProxyResponse:
    def __init__(self, *, status_code: int = 200, payload: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}
        self.headers = headers or {"content-type": "application/json"}

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=65536):
        _ = chunk_size
        yield json.dumps(self._payload).encode("utf-8")

    def close(self):
        return None


class _FakeProxySession:
    def __init__(self):
        self.calls: list[dict] = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeProxyResponse()


def _build_client(monkeypatch, *, update_status_provider=None, apply_update_action=None, service_map=None, proxy_session=None) -> TestClient:
    monkeypatch.setattr(agent_api, "SignalClient", StubSignalClient)
    if service_map is None:
        service_map = lambda: {}
    if proxy_session is None:
        proxy_session = _FakeProxySession()
    app = agent_api.build_agent_app(
        node_id="node-1",
        node_name="Node 1",
        service_map=service_map,
        summary_provider=lambda: {},
        proxy_session=proxy_session,
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


def test_graph_endpoint_enriches_graph_with_source_metadata(monkeypatch) -> None:
    client = _build_client(monkeypatch)

    response = client.get("/parameterdb/graph")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["graph"]["sources"]["relay"]["source_type"] == "modbus_relay"
    assert body["graph"]["sources"]["relay"]["graph"]["depends_on"] == ["relay.ch1"]


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


def test_agent_bridge_control_route_proxies_to_control_service(monkeypatch) -> None:
    proxy_session = _FakeProxySession()
    client = _build_client(
        monkeypatch,
        proxy_session=proxy_session,
        service_map=lambda: {
            "control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"},
        },
    )

    response = client.get("/control/read/reactor.temp")

    assert response.status_code == 200
    assert proxy_session.calls
    assert proxy_session.calls[-1]["url"] == "http://127.0.0.1:8767/control/read/reactor.temp"


def test_agent_bridge_data_route_proxies_to_data_service(monkeypatch) -> None:
    proxy_session = _FakeProxySession()
    client = _build_client(
        monkeypatch,
        proxy_session=proxy_session,
        service_map=lambda: {
            "data_service": {"healthy": True, "base_url": "http://10.0.0.20:8769"},
        },
    )

    response = client.get("/data/archives")

    assert response.status_code == 200
    assert proxy_session.calls[-1]["url"] == "http://10.0.0.20:8769/archives"


def test_agent_bridge_returns_404_when_service_unavailable(monkeypatch) -> None:
    client = _build_client(
        monkeypatch,
        service_map=lambda: {
            "control_service": {"healthy": False, "base_url": "http://127.0.0.1:8767"},
        },
    )

    response = client.get("/control/read/reactor.temp")
    assert response.status_code == 404