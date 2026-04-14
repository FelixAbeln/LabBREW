from __future__ import annotations

import json

from fastapi.testclient import TestClient

from Supervisor.infrastructure import agent_api


class StubSignalClient:
    deleted_source_calls: list[tuple[str, bool]] = []
    ui_action_calls: list[tuple[str, str, dict, str | None]] = []
    snapshot_payload: dict = {"format_version": 1, "parameters": {"reactor.temp": {"value": 21.0}}}
    snapshot_stats_payload: dict = {
        "backend": "postgres",
        "available": True,
        "healthy": True,
        "last_save_ok": True,
        "last_success_at": 123.0,
        "last_error": None,
        "postgres": {"host": "db.internal", "port": 5432, "database": "labbrew", "table_prefix": "runtime"},
    }
    datasource_stats_payload: dict = {
        "backend": "postgres",
        "available": True,
        "healthy": True,
        "last_save_ok": True,
        "last_success_at": 456.0,
        "last_error": None,
        "postgres": {"host": "db.internal", "port": 5432, "database": "labbrew", "table_prefix": "datasource"},
    }
    imported_snapshot_calls: list[dict] = []

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
        StubSignalClient.imported_snapshot_calls.append(
            {
                "snapshot": snapshot,
                "replace_existing": replace_existing,
                "save_to_disk": save_to_disk,
            }
        )
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
        if self.port == 8766:
            return {"source_persistence": dict(StubSignalClient.datasource_stats_payload)}
        return {"snapshot_persistence": dict(StubSignalClient.snapshot_stats_payload)}

    def export_snapshot(self):
        return {
            "snapshot": dict(StubSignalClient.snapshot_payload),
            "snapshot_stats": dict(StubSignalClient.snapshot_stats_payload),
        }

    def list_parameter_type_ui(self):
        return []

    def get_parameter_type_ui(self, parameter_type):
        return {"parameter_type": parameter_type}

    def set_value(self, _name, _value):
        return True

    def update_config(self, _name, **_config):
        return True

    def update_metadata(self, _name, **_metadata):
        return True

    def delete_parameter(self, _name):
        return True

    def list_source_types_ui(self):
        return []

    def get_source_type_ui(self, source_type, name=None, mode=None):
        return {"source_type": source_type, "name": name, "mode": mode, "graph": {"depends_on": ["relay.ch1"]}}

    def list_sources(self):
        return {"relay": {"source_type": "modbus_relay", "running": True, "config": {"parameter_prefix": "relay"}}}

    def create_source(self, _name, _source_type, _config=None):
        return True

    def update_source(self, _name, _config=None):
        return True

    def delete_source(self, name, *, delete_owned_parameters=False):
        StubSignalClient.deleted_source_calls.append((name, bool(delete_owned_parameters)))
        return True

    def invoke_source_type_ui_action(self, source_type, action, *, payload=None, name=None):
        payload_dict = dict(payload or {})
        StubSignalClient.ui_action_calls.append((source_type, action, payload_dict, name))
        return {"ok": True, "source_type": source_type, "action": action, "payload": payload_dict, "name": name}


class _FakeProxyResponse:
    def __init__(self, *, status_code: int = 200, payload: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}
        self.headers = headers or {"content-type": "application/json"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

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
        url = str(kwargs.get("url") or "")
        if url.endswith("/system/rules-persistence"):
            return _FakeProxyResponse(payload={"backend": "postgres", "available": True, "healthy": True, "last_save_ok": True, "last_success_at": 789.0, "last_error": None, "postgres": {"host": "db.internal", "port": 5432, "database": "labbrew", "table_prefix": "control_rules"}})
        return _FakeProxyResponse()


def _build_client(monkeypatch, *, update_status_provider=None, apply_update_action=None, service_map=None, proxy_session=None) -> TestClient:
    monkeypatch.setattr(agent_api, "SignalClient", StubSignalClient)
    if service_map is None:
        def service_map():
            return {}
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
    StubSignalClient.imported_snapshot_calls = []
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
    assert StubSignalClient.imported_snapshot_calls[-1]["replace_existing"] is True


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


def test_agent_persistence_endpoint_returns_parameterdb_status(monkeypatch) -> None:
    client = _build_client(
        monkeypatch,
        service_map=lambda: {
            "ParameterDB": {"healthy": True, "base_url": "http://127.0.0.1:8765"},
            "ParameterDB_DataSource": {"healthy": True, "base_url": "http://127.0.0.1:8766"},
            "control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"},
        },
    )

    response = client.get("/agent/persistence")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["persistence"]["backend"] == "postgres"
    assert body["persistence"]["healthy"] is True
    assert body["persistence"]["postgres"]["host"] == "db.internal"
    assert body["datasource_persistence"]["backend"] == "postgres"
    assert body["rules_persistence"]["backend"] == "postgres"


def test_agent_summary_includes_persistence_status(monkeypatch) -> None:
    monkeypatch.setattr(agent_api, "SignalClient", StubSignalClient)
    app = agent_api.build_agent_app(
        node_id="node-1",
        node_name="Node 1",
        service_map=lambda: {
            "ParameterDB": {"healthy": True, "base_url": "http://127.0.0.1:8765"},
            "ParameterDB_DataSource": {"healthy": True, "base_url": "http://127.0.0.1:8766"},
            "control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"},
        },
        summary_provider=lambda: {"node_id": "node-1", "services": {}},
        proxy_session=_FakeProxySession(),
    )
    client = TestClient(app)

    response = client.get("/agent/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["persistence"]["backend"] == "postgres"
    assert body["persistence"]["healthy"] is True
    assert body["datasource_persistence"]["backend"] == "postgres"
    assert body["datasource_persistence"]["last_success_at"] == 456.0
    assert body["rules_persistence"]["backend"] == "postgres"
    assert body["rules_persistence"]["last_success_at"] == 789.0


def test_agent_snapshot_export_import_round_trip(monkeypatch) -> None:
    StubSignalClient.imported_snapshot_calls = []
    StubSignalClient.snapshot_payload = {
        "format_version": 1,
        "parameters": {
            "reactor.temp": {
                "parameter_type": "static",
                "value": 21.5,
                "config": {},
                "state": {},
                "metadata": {},
            }
        },
    }
    client = _build_client(monkeypatch)

    exported = client.get("/parameterdb/snapshot-file")
    assert exported.status_code == 200
    exported_body = exported.json()
    assert exported_body["ok"] is True
    assert exported_body["snapshot"]["parameters"]["reactor.temp"]["value"] == 21.5

    imported = client.post(
        "/parameterdb/snapshot-file",
        json={
            "snapshot": exported_body["snapshot"],
            "replace_existing": False,
            "save_to_disk": True,
        },
    )

    assert imported.status_code == 200
    assert imported.json()["ok"] is True
    assert StubSignalClient.imported_snapshot_calls[-1]["snapshot"] == exported_body["snapshot"]
    assert StubSignalClient.imported_snapshot_calls[-1]["replace_existing"] is False


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


def test_parameterdb_delete_source_accepts_cascade_query(monkeypatch) -> None:
    StubSignalClient.deleted_source_calls = []
    client = _build_client(monkeypatch)

    response = client.delete("/parameterdb/sources/demo?delete_owned_parameters=true")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert StubSignalClient.deleted_source_calls[-1] == ("demo", True)


def test_parameterdb_source_type_module_action(monkeypatch) -> None:
    StubSignalClient.ui_action_calls = []
    client = _build_client(monkeypatch)

    response = client.post(
        "/parameterdb/source-types/modbus_relay/module-actions/scan",
        json={"name": "relay", "payload": {"host": "127.0.0.1", "port": 502}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["result"]["source_type"] == "modbus_relay"
    assert body["result"]["action"] == "scan"
    assert StubSignalClient.ui_action_calls[-1] == (
        "modbus_relay",
        "scan",
        {"host": "127.0.0.1", "port": 502},
        "relay",
    )


def test_agent_bridge_returns_404_when_service_unavailable(monkeypatch) -> None:
    client = _build_client(
        monkeypatch,
        service_map=lambda: {
            "control_service": {"healthy": False, "base_url": "http://127.0.0.1:8767"},
        },
    )

    response = client.get("/control/read/reactor.temp")
    assert response.status_code == 404


def test_agent_proxy_service_root_route_forwards_without_path(monkeypatch) -> None:
    proxy_session = _FakeProxySession()
    client = _build_client(
        monkeypatch,
        proxy_session=proxy_session,
        service_map=lambda: {
            "control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"},
        },
    )

    response = client.get("/proxy/control_service")

    assert response.status_code == 200
    assert proxy_session.calls
    assert proxy_session.calls[-1]["url"] == "http://127.0.0.1:8767"


def test_agent_proxy_rejects_websocket_upgrade(monkeypatch) -> None:
    proxy_session = _FakeProxySession()
    client = _build_client(
        monkeypatch,
        proxy_session=proxy_session,
        service_map=lambda: {
            "control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"},
        },
    )

    response = client.get(
        "/proxy/control_service/ws/live",
        headers={"Connection": "Upgrade", "Upgrade": "websocket"},
    )

    assert response.status_code == 501
    assert "WebSocket upgrade" in response.json().get("detail", "")


def test_parameterdb_fmu_file_endpoints_round_trip(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(agent_api, "storage_subdir", lambda name: tmp_path / name)
    client = _build_client(monkeypatch)

    upload = client.post(
        "/parameterdb/fmu-files",
        files={"file": ("controller.fmu", b"FMU_BYTES", "application/octet-stream")},
    )
    assert upload.status_code == 200
    uploaded = upload.json()["file"]
    assert uploaded["name"] == "controller.fmu"
    assert uploaded["local_path"].lower().endswith("controller.fmu")

    listed = client.get("/parameterdb/fmu-files")
    assert listed.status_code == 200
    assert any(item["name"] == "controller.fmu" for item in listed.json().get("files", []))

    downloaded = client.get("/parameterdb/fmu-files/controller.fmu/download")
    assert downloaded.status_code == 200
    assert downloaded.content == b"FMU_BYTES"

    deleted = client.delete("/parameterdb/fmu-files/controller.fmu")
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True


def test_parameterdb_fmu_file_endpoint_rejects_non_fmu(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(agent_api, "storage_subdir", lambda name: tmp_path / name)
    client = _build_client(monkeypatch)

    response = client.post(
        "/parameterdb/fmu-files",
        files={"file": ("not_allowed.txt", b"nope", "text/plain")},
    )
    assert response.status_code == 400
    assert "Only .fmu files are allowed" in response.json().get("detail", "")


def test_agent_storage_endpoints_manage_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(agent_api, "storage_subdir", lambda name: tmp_path / name)
    client = _build_client(monkeypatch)

    roots = client.get("/agent/storage/roots")
    assert roots.status_code == 200
    root_keys = {item["key"] for item in roots.json().get("roots", [])}
    assert root_keys == {"data"}

    create = client.post(
        "/agent/storage/mkdir",
        json={"root": "data", "path": "", "name": "models"},
    )
    assert create.status_code == 200

    listing = client.post(
        "/agent/storage/list",
        json={"root": "data", "path": ""},
    )
    assert listing.status_code == 200
    assert any(item["name"] == "models" and item["kind"] == "directory" for item in listing.json().get("entries", []))

    src_file = tmp_path / "models" / "demo.fmu"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_bytes(b"abc")

    moved = client.post(
        "/agent/storage/move",
        json={
            "root": "data",
            "src_path": "models/demo.fmu",
            "dst_path": "models/demo-renamed.fmu",
        },
    )
    assert moved.status_code == 200

    deleted = client.post(
        "/agent/storage/delete",
        json={"root": "data", "path": "models", "recursive": True},
    )
    assert deleted.status_code == 200

    listing_after = client.post(
        "/agent/storage/list",
        json={"root": "data", "path": ""},
    )
    assert listing_after.status_code == 200
    assert not any(item["name"] == "models" for item in listing_after.json().get("entries", []))


def test_agent_storage_network_drive_endpoint(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(agent_api, "storage_subdir", lambda name: tmp_path / name)
    seen: list[tuple[str, str]] = []

    def _fake_add(name: str, path: str):
      seen.append((name, path))
      return {"name": name, "path": path}

    monkeypatch.setattr(agent_api, "add_network_drive_to_topology", _fake_add)
    monkeypatch.setattr(agent_api, "configured_network_drives", lambda: [{"name": "shared", "path": str(tmp_path / "shared") }])
    client = _build_client(monkeypatch)

    response = client.post(
        "/agent/storage/network-drive",
        json={"name": "shared", "path": r"\\server\brewshare"},
    )

    assert response.status_code == 200
    assert seen == [("shared", r"\\server\brewshare")]

    roots = client.get("/agent/storage/roots")
    assert roots.status_code == 200
    assert any(item["key"] == "drive:shared" for item in roots.json().get("roots", []))


def test_agent_storage_file_read_write_and_download(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(agent_api, "storage_subdir", lambda name: tmp_path / name)
    sample = tmp_path / "config.json"
    sample.write_text('{"enabled":true}\n', encoding="utf-8")
    client = _build_client(monkeypatch)

    read_response = client.post(
        "/agent/storage/read-file",
        json={"root": "data", "path": "config.json"},
    )
    assert read_response.status_code == 200
    assert '"enabled":true' in read_response.json()["content"]

    write_response = client.post(
        "/agent/storage/write-file",
        json={"root": "data", "path": "config.json", "content": '{"enabled": false}\n'},
    )
    assert write_response.status_code == 200
    assert sample.read_text(encoding="utf-8") == '{"enabled": false}\n'

    download_response = client.get(
        "/agent/storage/download",
        params={"root": "data", "path": "config.json"},
    )
    assert download_response.status_code == 200
    assert download_response.content == b'{"enabled": false}\n'


def test_agent_storage_yaml_write_validates_and_formats(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(agent_api, "storage_subdir", lambda name: tmp_path / name)
    sample = tmp_path / "system_topology.yaml"
    sample.write_text("services: {}\n", encoding="utf-8")
    client = _build_client(monkeypatch)

    formatted = client.post(
        "/agent/storage/write-file",
        json={
            "root": "data",
            "path": "system_topology.yaml",
            "content": "services:\n  alpha:\n    module: demo\n",
        },
    )
    assert formatted.status_code == 200
    assert formatted.json()["content"].endswith("\n")
    assert "alpha:" in formatted.json()["content"]

    invalid = client.post(
        "/agent/storage/write-file",
        json={
            "root": "data",
            "path": "system_topology.yaml",
            "content": "services: [unterminated\n",
        },
    )
    assert invalid.status_code == 400
    assert "Invalid YAML" in invalid.json().get("detail", "")
