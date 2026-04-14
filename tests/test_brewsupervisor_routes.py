from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
import requests
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from BrewSupervisor.api import routes as supervisor_routes
from BrewSupervisor.api.routes import build_router


class StubRegistry:
    def __init__(self, nodes):
        self._nodes = list(nodes)

    def snapshot(self):
        return list(self._nodes)

    def get_node(self, fermenter_id: str):
        for node in self._nodes:
            if node.id == fermenter_id:
                return node
        return None

    def get_node_for_service(self, fermenter_id: str, service_name: str):
        matching = [node for node in self._nodes if node.id == fermenter_id]
        if not matching:
            return None
        service_matching = [
            node
            for node in matching
            if service_name in (getattr(node, "service_agents", {}) or {})
            or service_name in (getattr(node, "services", {}) or {})
            or service_name in (getattr(node, "services_hint", []) or [])
        ]
        return (service_matching or matching)[0]


class StubProxy:
    def __init__(self):
        self.calls = []

    def request(self, *, method, url, params=None, json_body=None, data_body=None, headers=None):
        self.calls.append((method, url, params, json_body, data_body, headers))

        if url.endswith("/proxy/schedule_service/schedule/status"):
            return 200, {"owned_targets": ["reactor.temp.setpoint"]}
        if url.endswith("/proxy/schedule_service/schedule"):
            return 200, {"schedule": {"id": "sched-1"}}
        if url.endswith("/proxy/control_service/control/read/reactor.temp.setpoint"):
            return 200, {"ok": True, "value": 32.0, "current_owner": "schedule"}

        if "/proxy/control_service/control/" in url and method == "POST":
            return 200, {"ok": True, "echo": json_body if json_body is not None else json.loads((data_body or b'{}').decode('utf-8'))}

        body = json_body
        if body is None and data_body:
            try:
                body = json.loads(data_body.decode('utf-8'))
            except Exception:
                body = {'raw_size': len(data_body)}
        return 200, {"ok": True, "url": url, "method": method, "params": params, "json": body}

    def request_raw(self, *, method, url, params=None, json_body=None, data_body=None, headers=None, stream=False):
        self.calls.append((f"raw:{method}", url, params, json_body, data_body, headers, stream))

        class _RawResponse:
            status_code = 200
            headers: ClassVar[dict[str, str]] = {
                "content-type": "application/zip",
                "content-disposition": 'attachment; filename="archive.zip"',
                "content-length": "4",
            }

            def iter_content(self, chunk_size=65536):
                _ = chunk_size
                yield b"PK\x03\x04"

            def close(self):
                return None

        return _RawResponse()



def _make_node(node_id: str = "01"):
    return SimpleNamespace(
        id=node_id,
        name="Test Fermenter",
        address="127.0.0.1:8780",
        host="127.0.0.1",
        online=True,
        agent_base_url="http://127.0.0.1:8780",
        services_hint=["control_service", "schedule_service", "data_service"],
        services={"control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"}},
        service_agents={"control_service": "http://127.0.0.1:8780"},
        summary={"schedule_available": True, "control_available": True},
        last_error=None,
    )


def _client(nodes=None, proxy=None) -> TestClient:
    app = FastAPI()
    app.include_router(build_router())
    app.state.registry = StubRegistry(nodes or [])
    app.state.proxy = proxy or StubProxy()
    return TestClient(app)


def test_health_endpoint() -> None:
    response = _client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": "true"}


def test_fermenters_list_and_get() -> None:
    node = _make_node()
    client = _client(nodes=[node])

    listed = client.get("/fermenters")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == "01"

    single = client.get("/fermenters/01")
    assert single.status_code == 200
    assert single.json()["name"] == "Test Fermenter"


def test_fermenter_not_found_returns_404() -> None:
    response = _client().get("/fermenters/missing")
    assert response.status_code == 404


def test_proxy_control_forwards_payload_and_query() -> None:
    proxy = StubProxy()
    client = _client(nodes=[_make_node()], proxy=proxy)

    response = client.post(
        "/fermenters/01/control/write",
        params={"source": "ui"},
        json={"target": "reactor.temp.setpoint", "value": 30.0, "owner": "operator"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True

    method, url, params, json_body, data_body, headers = proxy.calls[-1]
    assert method == "POST"
    assert url.endswith("/proxy/control_service/control/write")
    assert params == {"source": "ui"}
    assert json_body is None
    assert json.loads(data_body.decode("utf-8"))["target"] == "reactor.temp.setpoint"
    assert headers["content-type"].startswith("application/json")


def test_proxy_parameterdb_forwards_payload_and_query() -> None:
    proxy = StubProxy()
    client = _client(nodes=[_make_node()], proxy=proxy)

    response = client.post(
        "/fermenters/01/parameterdb/params",
        params={"source": "ui"},
        json={"name": "test.param", "parameter_type": "static", "value": 12.3, "config": {}, "metadata": {}},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True

    method, url, params, json_body, data_body, headers = proxy.calls[-1]
    assert method == "POST"
    assert url.endswith("/parameterdb/params")
    assert params == {"source": "ui"}
    assert json_body is None
    assert json.loads(data_body.decode("utf-8"))["name"] == "test.param"
    assert headers["content-type"].startswith("application/json")


def test_dashboard_aggregates_best_effort_data() -> None:
    client = _client(nodes=[_make_node()], proxy=StubProxy())

    response = client.get("/fermenters/01/dashboard")
    assert response.status_code == 200
    body = response.json()

    assert body["fermenter"]["id"] == "01"
    assert body["schedule"]["owned_targets"] == ["reactor.temp.setpoint"]
    assert body["schedule_definition"]["id"] == "sched-1"
    assert body["owned_target_values"][0]["value"] == 32.0


def test_agent_info_services_and_summary_proxy() -> None:
    proxy = StubProxy()
    client = _client(nodes=[_make_node()], proxy=proxy)

    for path in [
        "/fermenters/01/agent/info",
        "/fermenters/01/agent/services",
        "/fermenters/01/agent/persistence",
        "/fermenters/01/summary",
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["ok"] is True


def test_agent_repo_status_and_update_proxy() -> None:
    proxy = StubProxy()
    client = _client(nodes=[_make_node()], proxy=proxy)

    status_response = client.get("/fermenters/01/agent/repo/status?force=1")
    update_response = client.post("/fermenters/01/agent/repo/update")

    assert status_response.status_code == 200
    assert update_response.status_code == 200

    status_call = proxy.calls[-2]
    update_call = proxy.calls[-1]

    assert status_call[0] == "GET"
    assert status_call[1].endswith("/agent/repo/status")
    assert status_call[2] == {"force": "1"}

    assert update_call[0] == "POST"
    assert update_call[1].endswith("/agent/repo/update")


def test_workspace_layouts_round_trip(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(supervisor_routes, "storage_path", lambda *parts: tmp_path.joinpath(*parts))
    client = _client(nodes=[_make_node()])

    body = {
        "tabs": [
            {
                "id": "workspace-1",
                "label": "Workspace 1",
                "widgets": [
                    {
                        "id": "widget-1",
                        "type": "data-snapshot",
                        "x": 1,
                        "y": 1,
                        "cols": 12,
                        "rows": 4,
                    }
                ],
            }
        ],
        "active_tab": "workspace-1",
        "control_card_order": ["brewcan", "chiller"],
    }

    put_response = client.put("/fermenters/01/workspace-layouts", json=body)
    assert put_response.status_code == 200
    saved_layout = put_response.json()["workspace_layout"]
    assert saved_layout["tabs"][0]["label"] == "Workspace 1"
    assert saved_layout["active_tab"] == "workspace-1"
    assert saved_layout["control_card_order"] == ["brewcan", "chiller"]

    get_response = client.get("/fermenters/01/workspace-layouts")
    assert get_response.status_code == 200
    loaded_layout = get_response.json()["workspace_layout"]
    assert loaded_layout["tabs"][0]["widgets"][0]["type"] == "data-snapshot"
    assert loaded_layout["fermenter_name"] == "Test Fermenter"


def test_workspace_layouts_use_atomic_json_write(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(supervisor_routes, "storage_path", lambda *parts: tmp_path.joinpath(*parts))
    calls: list[tuple[Path, dict[str, object]]] = []

    def fake_atomic_write_json(path: Path, payload: dict[str, object], **_kwargs) -> None:
        calls.append((path, payload))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(supervisor_routes, "atomic_write_json", fake_atomic_write_json, raising=False)
    client = _client(nodes=[_make_node()])

    response = client.put(
        "/fermenters/01/workspace-layouts",
        json={"tabs": [{"id": "w1", "label": "Workspace", "widgets": []}]},
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0][0].name == "supervisor_workspace_layouts.json"
    assert "01" in calls[0][1]


def test_agent_endpoints_return_404_for_missing_node() -> None:
    client = _client(nodes=[], proxy=StubProxy())
    response = client.get("/fermenters/missing/agent/info")
    assert response.status_code == 404


def test_proxy_routes_cover_service_wrappers() -> None:
    proxy = StubProxy()
    client = _client(nodes=[_make_node()], proxy=proxy)

    paths = [
        "/fermenters/01/services/control_service/read/reactor.temp.setpoint",
        "/fermenters/01/schedule/status",
        "/fermenters/01/control/read/reactor.temp.setpoint",
        "/fermenters/01/rules/list",
        "/fermenters/01/system/health",
        "/fermenters/01/data/status",
        "/fermenters/01/ws/state",
        "/fermenters/01/parameterdb/spec",
    ]

    for path in paths:
        response = client.get(path)
        assert response.status_code == 200


def test_split_service_routing_targets_service_specific_agent() -> None:
    control_payload = _make_node("01").__dict__.copy()
    control_payload.update({
        "agent_base_url": "http://10.0.0.10:8780",
        "services_hint": ["control_service"],
        "services": {"control_service": {"healthy": True}},
        "service_agents": {"control_service": "http://10.0.0.10:8780"},
    })
    control_node = SimpleNamespace(**control_payload)

    schedule_payload = _make_node("01").__dict__.copy()
    schedule_payload.update({
        "agent_base_url": "http://10.0.0.11:8780",
        "services_hint": ["schedule_service"],
        "services": {"schedule_service": {"healthy": True}},
        "service_agents": {"schedule_service": "http://10.0.0.11:8780"},
    })
    schedule_node = SimpleNamespace(**schedule_payload)
    proxy = StubProxy()
    client = _client(nodes=[control_node, schedule_node], proxy=proxy)

    control_response = client.get("/fermenters/01/control/read/reactor.temp.setpoint")
    schedule_response = client.get("/fermenters/01/schedule/status")

    assert control_response.status_code == 200
    assert schedule_response.status_code == 200

    control_call = next(call for call in proxy.calls if call[1].endswith("/proxy/control_service/control/read/reactor.temp.setpoint"))
    schedule_call = next(call for call in proxy.calls if call[1].endswith("/proxy/schedule_service/schedule/status"))

    assert control_call[1].startswith("http://10.0.0.10:8780")
    assert schedule_call[1].startswith("http://10.0.0.11:8780")


def test_data_archive_routing_targets_data_service_agent() -> None:
    data_payload = _make_node("01").__dict__.copy()
    data_payload.update({
        "agent_base_url": "http://10.0.0.12:8780",
        "services_hint": ["data_service"],
        "services": {"data_service": {"healthy": True}},
        "service_agents": {"data_service": "http://10.0.0.12:8780"},
    })
    data_node = SimpleNamespace(**data_payload)

    control_payload = _make_node("01").__dict__.copy()
    control_payload.update({
        "agent_base_url": "http://10.0.0.10:8780",
        "services_hint": ["control_service"],
        "services": {"control_service": {"healthy": True}},
        "service_agents": {"control_service": "http://10.0.0.10:8780"},
    })
    control_node = SimpleNamespace(**control_payload)

    proxy = StubProxy()
    client = _client(nodes=[control_node, data_node], proxy=proxy)

    response = client.get("/fermenters/01/data/archives/download/session.zip")
    assert response.status_code == 200

    raw_call = next(call for call in proxy.calls if call[0] == "raw:GET")
    assert raw_call[1].startswith("http://10.0.0.12:8780/proxy/data_service/archives/download/")


def test_datasource_fmu_gateway_targets_datasource_agent() -> None:
    datasource_payload = _make_node("01").__dict__.copy()
    datasource_payload.update({
        "agent_base_url": "http://10.0.0.30:8780",
        "services_hint": ["ParameterDB_DataSource"],
        "services": {"ParameterDB_DataSource": {"healthy": True}},
        "service_agents": {"ParameterDB_DataSource": "http://10.0.0.30:8780"},
    })
    datasource_node = SimpleNamespace(**datasource_payload)

    control_payload = _make_node("01").__dict__.copy()
    control_payload.update({
        "agent_base_url": "http://10.0.0.10:8780",
        "services_hint": ["control_service"],
        "services": {"control_service": {"healthy": True}},
        "service_agents": {"control_service": "http://10.0.0.10:8780"},
    })
    control_node = SimpleNamespace(**control_payload)

    proxy = StubProxy()
    client = _client(nodes=[control_node, datasource_node], proxy=proxy)

    list_response = client.get("/fermenters/01/datasource-files/fmu")
    assert list_response.status_code == 200

    upload_response = client.post(
        "/fermenters/01/datasource-files/fmu",
        files={"file": ("controller.fmu", b"FMU_BYTES", "application/octet-stream")},
    )
    assert upload_response.status_code == 200

    list_call = next(call for call in proxy.calls if call[0] == "GET" and "/parameterdb/fmu-files" in call[1])
    upload_call = next(call for call in proxy.calls if call[0] == "POST" and "/parameterdb/fmu-files" in call[1])

    assert list_call[1].startswith("http://10.0.0.30:8780")
    assert upload_call[1].startswith("http://10.0.0.30:8780")


def test_agent_storage_overview_and_actions_route_to_selected_agent() -> None:
    agent_a_payload = _make_node("01").__dict__.copy()
    agent_a_payload.update({
        "agent_base_url": "http://10.0.0.31:8780",
        "services_hint": ["control_service"],
        "services": {"control_service": {"healthy": True}},
        "service_agents": {"control_service": "http://10.0.0.31:8780"},
    })
    agent_a = SimpleNamespace(**agent_a_payload)

    agent_b_payload = _make_node("01").__dict__.copy()
    agent_b_payload.update({
        "agent_base_url": "http://10.0.0.32:8780",
        "services_hint": ["ParameterDB_DataSource"],
        "services": {"ParameterDB_DataSource": {"healthy": True}},
        "service_agents": {"ParameterDB_DataSource": "http://10.0.0.32:8780"},
    })
    agent_b = SimpleNamespace(**agent_b_payload)

    proxy = StubProxy()
    client = _client(nodes=[agent_a, agent_b], proxy=proxy)

    overview = client.get("/fermenters/01/agents/storage")
    assert overview.status_code == 200

    action = client.post(
        "/fermenters/01/agents/storage/list",
        json={
            "agent_base_url": "http://10.0.0.32:8780",
            "root": "data",
            "path": "",
        },
    )
    assert action.status_code == 200

    storage_roots_calls = [call for call in proxy.calls if call[0] == "GET" and call[1].endswith("/agent/storage/roots")]
    assert len(storage_roots_calls) == 2
    assert any(call[1].startswith("http://10.0.0.31:8780") for call in storage_roots_calls)
    assert any(call[1].startswith("http://10.0.0.32:8780") for call in storage_roots_calls)

    list_call = next(call for call in proxy.calls if call[0] == "POST" and call[1].endswith("/agent/storage/list"))
    assert list_call[1].startswith("http://10.0.0.32:8780")


def test_agent_storage_network_drive_broadcasts_to_all_agents() -> None:
    agent_a_payload = _make_node("01").__dict__.copy()
    agent_a_payload.update({
        "agent_base_url": "http://10.0.0.31:8780",
        "services_hint": ["control_service"],
        "services": {"control_service": {"healthy": True}},
        "service_agents": {"control_service": "http://10.0.0.31:8780"},
    })
    agent_a = SimpleNamespace(**agent_a_payload)

    agent_b_payload = _make_node("01").__dict__.copy()
    agent_b_payload.update({
        "agent_base_url": "http://10.0.0.32:8780",
        "services_hint": ["ParameterDB_DataSource"],
        "services": {"ParameterDB_DataSource": {"healthy": True}},
        "service_agents": {"ParameterDB_DataSource": "http://10.0.0.32:8780"},
    })
    agent_b = SimpleNamespace(**agent_b_payload)

    proxy = StubProxy()
    client = _client(nodes=[agent_a, agent_b], proxy=proxy)

    response = client.post(
        "/fermenters/01/agents/storage/network-drive",
        json={"name": "shared", "path": r"\\server\brewshare"},
    )

    assert response.status_code == 200
    drive_calls = [call for call in proxy.calls if call[0] == "POST" and call[1].endswith("/agent/storage/network-drive")]
    assert len(drive_calls) == 2
    assert any(call[1].startswith("http://10.0.0.31:8780") for call in drive_calls)
    assert any(call[1].startswith("http://10.0.0.32:8780") for call in drive_calls)


def test_agent_storage_file_routes_target_selected_agent() -> None:
    agent_payload = _make_node("01").__dict__.copy()
    agent_payload.update({
        "agent_base_url": "http://10.0.0.32:8780",
        "services_hint": ["ParameterDB_DataSource"],
        "services": {"ParameterDB_DataSource": {"healthy": True}},
        "service_agents": {"ParameterDB_DataSource": "http://10.0.0.32:8780"},
    })
    agent_node = SimpleNamespace(**agent_payload)

    proxy = StubProxy()
    client = _client(nodes=[agent_node], proxy=proxy)

    read_response = client.post(
        "/fermenters/01/agents/storage/read-file",
        json={
            "agent_base_url": "http://10.0.0.32:8780",
            "root": "data",
            "path": "system_topology.yaml",
        },
    )
    write_response = client.post(
        "/fermenters/01/agents/storage/write-file",
        json={
            "agent_base_url": "http://10.0.0.32:8780",
            "root": "data",
            "path": "system_topology.yaml",
            "content": "services: {}\n",
        },
    )
    download_response = client.get(
        "/fermenters/01/agents/storage/download",
        params={
            "agent_base_url": "http://10.0.0.32:8780",
            "root": "data",
            "path": "system_topology.yaml",
        },
    )

    assert read_response.status_code == 200
    assert write_response.status_code == 200
    assert download_response.status_code == 200

    read_call = next(call for call in proxy.calls if call[0] == "POST" and call[1].endswith("/agent/storage/read-file"))
    write_call = next(call for call in proxy.calls if call[0] == "POST" and call[1].endswith("/agent/storage/write-file"))
    raw_call = next(call for call in proxy.calls if call[0] == "raw:GET" and call[1].endswith("/agent/storage/download"))

    assert read_call[1].startswith("http://10.0.0.32:8780")
    assert write_call[1].startswith("http://10.0.0.32:8780")
    assert raw_call[1].startswith("http://10.0.0.32:8780")


def test_build_service_proxy_url_uses_service_agent_mapping() -> None:
    node = SimpleNamespace(
        agent_base_url="http://10.0.0.1:8780",
        service_agents={"schedule_service": "http://10.0.0.11:8780"},
    )

    schedule_url = supervisor_routes._build_service_proxy_url(node, "schedule_service", "schedule/status")
    control_url = supervisor_routes._build_service_proxy_url(node, "control_service", "control/read/x")

    assert schedule_url == "http://10.0.0.11:8780/proxy/schedule_service/schedule/status"
    assert control_url == "http://10.0.0.1:8780/proxy/control_service/control/read/x"


def test_get_service_node_falls_back_for_legacy_registry() -> None:
    class LegacyRegistry:
        def __init__(self, node):
            self.node = node

        def get_node(self, fermenter_id: str):
            return self.node if fermenter_id == "01" else None

    node = _make_node("01")
    registry = LegacyRegistry(node)

    resolved = supervisor_routes._get_service_node(registry, "01", "control_service")
    missing = supervisor_routes._get_service_node(registry, "missing", "control_service")

    assert resolved is node
    assert missing is None


def test_download_data_archive_streaming_passthrough_headers() -> None:
    proxy = StubProxy()
    client = _client(nodes=[_make_node()], proxy=proxy)

    response = client.get("/fermenters/01/data/archives/download/session.zip?token=abc")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.content.startswith(b"PK")


def test_helper_read_functions_raise_http_502_on_request_exception() -> None:
    class FailingProxy:
        def request(self, **_kwargs):
            raise requests.RequestException("boom")

        def request_raw(self, **_kwargs):
            raise requests.RequestException("boom")

    with pytest.raises(HTTPException) as json_exc:
        supervisor_routes._read_json_response(FailingProxy(), method="GET", url="http://x")
    assert json_exc.value.status_code == 502

    with pytest.raises(HTTPException) as raw_exc:
        supervisor_routes._read_raw_response(FailingProxy(), method="GET", url="http://x")
    assert raw_exc.value.status_code == 502


def test_schedule_import_returns_422_when_validation_fails(monkeypatch) -> None:
    proxy = StubProxy()
    client = _client(nodes=[_make_node()], proxy=proxy)

    def _parse_schedule(_bytes, filename=None):
        _ = filename
        return {"id": "imported", "plan_steps": [], "setup_steps": [], "measurement_config": {}}

    monkeypatch.setattr(supervisor_routes, "parse_schedule_workbook", _parse_schedule)
    monkeypatch.setattr(
        supervisor_routes,
        "collect_workbook_parameter_references",
        lambda _bytes: set(),
    )
    monkeypatch.setattr(
        supervisor_routes,
        "_get_available_backend_parameters",
        lambda _proxy, _node: ({"reactor.temp.setpoint"}, None),
    )
    monkeypatch.setattr(
        supervisor_routes,
        "validate_schedule_payload",
        lambda *_args, **_kwargs: {
            "valid": False,
            "errors": ["bad schedule"],
            "warnings": [],
            "error_codes": ["BAD_SCHEDULE"],
            "warning_codes": [],
            "issues": [{"level": "error", "code": "BAD_SCHEDULE", "message": "bad schedule"}],
        },
    )

    response = client.put(
        "/fermenters/01/schedule/import",
        files={"file": ("plan.xlsx", b"dummy", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 422
    assert response.json()["ok"] is False


def test_validate_schedule_import_includes_backend_issue(monkeypatch) -> None:
    proxy = StubProxy()
    client = _client(nodes=[_make_node()], proxy=proxy)

    def _parse_schedule(_bytes, filename=None):
        _ = filename
        return {"id": "imported", "plan_steps": [], "setup_steps": []}

    monkeypatch.setattr(supervisor_routes, "parse_schedule_workbook", _parse_schedule)
    monkeypatch.setattr(supervisor_routes, "collect_workbook_parameter_references", lambda _bytes: set())
    monkeypatch.setattr(
        supervisor_routes,
        "_get_available_backend_parameters",
        lambda _proxy, _node: (
            None,
            {
                "level": "error",
                "code": "BACKEND_UNREACHABLE",
                "message": "Could not reach control backend for parameter validation",
            },
        ),
    )
    monkeypatch.setattr(
        supervisor_routes,
        "validate_schedule_payload",
        lambda *_args, **_kwargs: {
            "valid": True,
            "errors": [],
            "warnings": [],
            "error_codes": [],
            "warning_codes": [],
            "issues": [],
        },
    )

    response = client.put(
        "/fermenters/01/schedule/validate-import",
        files={"file": ("plan.xlsx", b"dummy", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert "BACKEND_UNREACHABLE" in body["error_codes"]
