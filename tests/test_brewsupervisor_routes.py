from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
import requests

from BrewSupervisor.api import routes as supervisor_routes
from BrewSupervisor.api.routes import build_router


class StubRegistry:
    def __init__(self, nodes):
        self._nodes = {node.id: node for node in nodes}

    def snapshot(self):
        return list(self._nodes.values())

    def get_node(self, fermenter_id: str):
        return self._nodes.get(fermenter_id)


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
            body = json.loads(data_body.decode('utf-8'))
        return 200, {"ok": True, "url": url, "method": method, "params": params, "json": body}

    def request_raw(self, *, method, url, params=None, json_body=None, data_body=None, headers=None, stream=False):
        self.calls.append((f"raw:{method}", url, params, json_body, data_body, headers, stream))

        class _RawResponse:
            status_code = 200
            headers = {
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

    monkeypatch.setattr(
        supervisor_routes,
        "parse_schedule_workbook",
        lambda _bytes, filename=None: {"id": "imported", "plan_steps": [], "setup_steps": [], "measurement_config": {}},
    )
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

    monkeypatch.setattr(
        supervisor_routes,
        "parse_schedule_workbook",
        lambda _bytes, filename=None: {"id": "imported", "plan_steps": [], "setup_steps": []},
    )
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
