"""
Multi-device split-topology simulation tests.

Simulates a LabBREW deployment where services are spread across two physical
devices (Device A and Device B), without any real network connections:

    BrewSupervisor   (gateway layer)
         │   _MultiAgentProxy — dispatches by URL prefix
         ├──► Agent A  http://10.0.0.10:8780
         │        service_map: {control_service: http://127.0.0.1:8767}
         │        proxy_session → _StubServiceSession (control stub)
         └──► Agent B  http://10.0.0.11:8780
                  service_map: {schedule_service: ...:8768, data_service: ...:8769}
                  proxy_session → _StubServiceSession (schedule/data stubs)

Gateway-to-gateway bridge (service on B calling a service on A):
    Agent B bridge /control/... ─► (Agent B proxy_session) ─► Agent A
    Verified by calling Agent A's bridge path directly, as any service
    on Device B would do when using Agent A as its backend URL.

Groups
------
1. Snapshot cache  — TTL deduplication, expiry, force-refresh, zero-TTL, close
2. Agent bridge    — bridge routes forward to the right service stub
3. Multi-device routing — BrewSupervisor routes each service to the correct agent
4. Full end-to-end — 3-layer chain: Supervisor → real Agent TestClient → service stub
5. Regression guards — agent_port param in topology validation
"""
from __future__ import annotations

import json
import time as _time_module
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from BrewSupervisor.api.routes import build_router
from Supervisor.infrastructure import agent_api


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

class _MockRequestsResponse:
    """Minimal requests.Response-compatible object."""

    def __init__(self, status_code: int = 200, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}
        self.headers = {"content-type": "application/json"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._payload

    def iter_content(self, chunk_size: int = 65536):
        yield json.dumps(self._payload).encode()

    def close(self) -> None:
        pass


class _StubServiceSession:
    """
    Stand-in for requests.Session inside an Agent app.

    ``routes`` maps URL prefixes to either a plain dict (returned as-is)
    or a callable(method, path, kwargs) -> dict.
    Calls are recorded in ``.calls`` for assertion.
    """

    def __init__(self, routes: dict[str, Any]) -> None:
        self.calls: list[dict] = []
        self._routes = routes

    def mount(self, *_: Any, **__: Any) -> None:  # noqa: D105
        pass

    def request(self, **kwargs: Any) -> _MockRequestsResponse:
        url: str = kwargs.get("url", "")
        method: str = str(kwargs.get("method", "GET")).upper()
        self.calls.append(dict(kwargs))
        for prefix, handler in self._routes.items():
            if url.startswith(prefix):
                path = url[len(prefix):]
                payload = handler(method, path, kwargs) if callable(handler) else dict(handler)
                return _MockRequestsResponse(200, payload)
        return _MockRequestsResponse(404, {"detail": f"no stub for {url!r}"})

    def close(self) -> None:
        pass


class _RawProxyResponse:
    """Wraps a TestClient httpx Response as a streaming-compatible object."""

    def __init__(self, resp: Any) -> None:
        self.status_code = resp.status_code
        self.headers = dict(resp.headers)
        self._content = resp.content

    def iter_content(self, chunk_size: int = 65536):
        yield self._content

    def close(self) -> None:
        pass


class _MultiAgentProxy:
    """
    BrewSupervisor proxy stub that dispatches requests to real Agent
    TestClients based on URL prefix.

    Implements the same interface as ``HttpServiceProxy``
    (``request()``, ``request_raw()``).
    """

    def __init__(self, agents: dict[str, TestClient]) -> None:
        self._agents = agents

    def _find(self, url: str) -> tuple[str, TestClient]:
        for base, client in self._agents.items():
            if url.startswith(base):
                return base, client
        raise ConnectionError(f"no registered agent for {url!r}")

    def _call(
        self,
        method: str,
        url: str,
        params: dict | None,
        content: bytes | None,
        headers: dict | None,
    ) -> Any:
        base, client = self._find(url)
        path = url[len(base):] or "/"
        return client.request(
            method.upper(),
            path,
            params=params or {},
            content=content,
            headers=headers or {},
        )

    def request(
        self,
        *,
        method: str,
        url: str,
        params: dict | None = None,
        json_body: Any = None,
        data_body: bytes | None = None,
        headers: dict | None = None,
    ) -> tuple[int, Any]:
        content = data_body
        if json_body is not None and content is None:
            content = json.dumps(json_body).encode()
        resp = self._call(method, url, params, content, headers)
        ct = resp.headers.get("content-type", "")
        if "application/json" in ct:
            return resp.status_code, resp.json()
        return resp.status_code, {"text": resp.text}

    def request_raw(
        self,
        *,
        method: str,
        url: str,
        params: dict | None = None,
        json_body: Any = None,
        data_body: bytes | None = None,
        headers: dict | None = None,
        stream: bool = False,
    ) -> _RawProxyResponse:
        content = data_body
        if json_body is not None and content is None:
            content = json.dumps(json_body).encode()
        resp = self._call(method, url, params, content, headers)
        return _RawProxyResponse(resp)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def _make_agent_client(
    monkeypatch: Any,
    *,
    service_map: dict[str, dict[str, Any]],
    service_sessions: dict[str, Any] | None = None,
) -> tuple[TestClient, _StubServiceSession]:
    """Build an Agent app TestClient with stubbed service sessions."""
    monkeypatch.setattr(agent_api, "SignalClient", lambda *a, **kw: None)
    stub_session = _StubServiceSession(service_sessions or {})
    app = agent_api.build_agent_app(
        node_id="node-sim",
        node_name="Sim Node",
        service_map=lambda: service_map,
        summary_provider=lambda: {"simulated": True},
        proxy_session=stub_session,
    )
    return TestClient(app, raise_server_exceptions=False), stub_session


def _make_node(
    node_id: str = "01",
    *,
    agent_base_url: str = "http://10.0.0.10:8780",
    service_agents: dict[str, str] | None = None,
    services: dict[str, Any] | None = None,
    services_hint: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=node_id,
        name="Sim Fermenter",
        address="10.0.0.10:8780",
        host="10.0.0.10",
        online=True,
        agent_base_url=agent_base_url,
        services_hint=services_hint or [],
        services=services or {},
        service_agents=service_agents or {},
        summary={},
        last_error=None,
    )


class _SimpleRegistry:
    def __init__(self, nodes: list) -> None:
        self._nodes = list(nodes)

    def snapshot(self) -> list:
        return list(self._nodes)

    def get_node(self, node_id: str):
        return next((n for n in self._nodes if n.id == node_id), None)

    def get_node_for_service(self, node_id: str, service_name: str):
        matching = [n for n in self._nodes if n.id == node_id]
        if not matching:
            return None
        hit = next(
            (n for n in matching if service_name in (getattr(n, "service_agents", {}) or {})),
            None,
        )
        return hit or matching[0]


def _supervisor_client(nodes: list, proxy: _MultiAgentProxy) -> TestClient:
    app = FastAPI()
    app.include_router(build_router())
    app.state.registry = _SimpleRegistry(nodes)
    app.state.proxy = proxy
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helper used by cache tests
# ---------------------------------------------------------------------------

class _CountingBrowser:
    """mDNS browser stub that counts how many times snapshot() is called."""

    def __init__(self) -> None:
        self.call_count = 0

    def snapshot(self) -> list:
        self.call_count += 1
        return []


# ===========================================================================
# GROUP 1 — Snapshot cache behaviour
# ===========================================================================

def test_snapshot_cache_deduplicates_within_ttl() -> None:
    """Two snapshot() calls within the TTL window hit the browser only once."""
    from BrewSupervisor.application.fermenter_registry import FermenterRegistry

    browser = _CountingBrowser()
    registry = FermenterRegistry(browser, snapshot_cache_ttl_s=60.0)
    registry._session = _StubServiceSession({})

    registry.snapshot()
    registry.snapshot()

    assert browser.call_count == 1, "second call within TTL must use cache"


def test_snapshot_cache_refreshes_after_ttl_expires(monkeypatch: Any) -> None:
    """snapshot() after TTL expiry performs a fresh browser fetch."""
    from BrewSupervisor.application.fermenter_registry import FermenterRegistry

    browser = _CountingBrowser()
    registry = FermenterRegistry(browser, snapshot_cache_ttl_s=0.1)
    registry._session = _StubServiceSession({})

    registry.snapshot()
    assert browser.call_count == 1

    # Advance monotonic clock past the 0.1 s TTL.
    _real_now = _time_module.monotonic()
    monkeypatch.setattr(_time_module, "monotonic", lambda: _real_now + 1.0)

    registry.snapshot()
    assert browser.call_count == 2, "expired TTL must trigger a fresh fetch"


def test_snapshot_force_refresh_bypasses_cache() -> None:
    """force_refresh=True always re-fetches, even within the TTL window."""
    from BrewSupervisor.application.fermenter_registry import FermenterRegistry

    browser = _CountingBrowser()
    registry = FermenterRegistry(browser, snapshot_cache_ttl_s=60.0)
    registry._session = _StubServiceSession({})

    registry.snapshot()
    registry.snapshot(force_refresh=True)

    assert browser.call_count == 2


def test_snapshot_zero_ttl_never_caches() -> None:
    """TTL of 0.0 disables caching; every call fetches fresh."""
    from BrewSupervisor.application.fermenter_registry import FermenterRegistry

    browser = _CountingBrowser()
    registry = FermenterRegistry(browser, snapshot_cache_ttl_s=0.0)
    registry._session = _StubServiceSession({})

    registry.snapshot()
    registry.snapshot()

    assert browser.call_count == 2


def test_snapshot_close_invalidates_cache() -> None:
    """close() clears the snapshot cache so the next call re-fetches."""
    from BrewSupervisor.application.fermenter_registry import FermenterRegistry

    browser = _CountingBrowser()
    registry = FermenterRegistry(browser, snapshot_cache_ttl_s=60.0)
    registry._session = _StubServiceSession({})

    registry.snapshot()
    assert browser.call_count == 1

    registry.close()
    # Replace closed session so the registry is usable again.
    registry._session = _StubServiceSession({})

    registry.snapshot()
    assert browser.call_count == 2, "cache cleared by close() — must re-fetch"


# ===========================================================================
# GROUP 2 — Agent bridge routes (real Agent TestClient + service stubs)
# ===========================================================================

def test_agent_bridge_control_route_calls_control_service(monkeypatch: Any) -> None:
    """/control/{path} proxies to control_service preserving the full path."""
    paths_seen: list[str] = []

    def _handler(method: str, path: str, _kw: dict) -> dict:
        paths_seen.append(path)
        return {"ok": True, "echoed_path": path}

    client, _ = _make_agent_client(
        monkeypatch,
        service_map={"control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"}},
        service_sessions={"http://127.0.0.1:8767": _handler},
    )

    resp = client.get("/control/read/reactor.temp")

    assert resp.status_code == 200
    assert paths_seen, "control_service stub must have been called"
    assert "control/read/reactor.temp" in paths_seen[0]


def test_agent_bridge_schedule_route_calls_schedule_service(monkeypatch: Any) -> None:
    """/schedule/status proxies to schedule_service."""
    paths_seen: list[str] = []

    client, _ = _make_agent_client(
        monkeypatch,
        service_map={"schedule_service": {"healthy": True, "base_url": "http://127.0.0.1:8768"}},
        service_sessions={"http://127.0.0.1:8768": lambda m, p, _: paths_seen.append(p) or {"ok": True}},
    )

    resp = client.get("/schedule/status")

    assert resp.status_code == 200
    assert paths_seen


def test_agent_bridge_data_route_calls_data_service(monkeypatch: Any) -> None:
    """/data/archives proxies to data_service."""
    client, session = _make_agent_client(
        monkeypatch,
        service_map={"data_service": {"healthy": True, "base_url": "http://127.0.0.1:8769"}},
        service_sessions={"http://127.0.0.1:8769": {"ok": True, "archives": []}},
    )

    resp = client.get("/data/archives")

    assert resp.status_code == 200
    assert session.calls, "data_service stub must have been called"


def test_agent_bridge_rules_route_uses_control_service(monkeypatch: Any) -> None:
    """/rules/{path} targets control_service, not a separate rules service."""
    paths_seen: list[str] = []

    client, _ = _make_agent_client(
        monkeypatch,
        service_map={"control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"}},
        service_sessions={"http://127.0.0.1:8767": lambda m, p, _: paths_seen.append(p) or {"ok": True, "rules": []}},
    )

    resp = client.get("/rules/list")

    assert resp.status_code == 200
    assert any("rules" in p for p in paths_seen)


def test_agent_bridge_system_route_uses_control_service(monkeypatch: Any) -> None:
    """/system/{path} targets control_service."""
    paths_seen: list[str] = []

    client, _ = _make_agent_client(
        monkeypatch,
        service_map={"control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"}},
        service_sessions={"http://127.0.0.1:8767": lambda m, p, _: paths_seen.append(p) or {"ok": True}},
    )

    resp = client.get("/system/health")

    assert resp.status_code == 200
    assert any("system" in p for p in paths_seen)


def test_agent_bridge_post_body_forwarded_to_service(monkeypatch: Any) -> None:
    """POST body is forwarded byte-for-byte through the agent bridge."""
    bodies_received: list[bytes] = []

    def _handler(method: str, path: str, kwargs: dict) -> dict:
        bodies_received.append(kwargs.get("data") or b"")
        return {"ok": True}

    client, _ = _make_agent_client(
        monkeypatch,
        service_map={"control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"}},
        service_sessions={"http://127.0.0.1:8767": _handler},
    )

    payload = {"target": "reactor.temp.setpoint", "value": 22.5}
    resp = client.post(
        "/control/write",
        content=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )

    assert resp.status_code == 200
    assert bodies_received
    forwarded = json.loads(bodies_received[0])
    assert forwarded["value"] == pytest.approx(22.5)


def test_agent_bridge_query_params_forwarded_to_service(monkeypatch: Any) -> None:
    """Query-string parameters pass through the bridge unchanged."""
    params_seen: list[Any] = []

    def _handler(method: str, path: str, kwargs: dict) -> dict:
        # The agent calls requests.Session.request(params=...) separately from the URL.
        params_seen.append(kwargs.get("params"))
        return {"ok": True}

    client, _ = _make_agent_client(
        monkeypatch,
        service_map={"schedule_service": {"healthy": True, "base_url": "http://127.0.0.1:8768"}},
        service_sessions={"http://127.0.0.1:8768": _handler},
    )

    resp = client.get("/schedule/status", params={"verbose": "1", "page": "2"})

    assert resp.status_code == 200
    assert params_seen
    # params is a QueryParams / MultiDict object; convert to string for inspection
    params_str = str(params_seen[0])
    assert "verbose" in params_str
    assert "page" in params_str


def test_agent_bridge_propagates_service_response_body(monkeypatch: Any) -> None:
    """The body produced by the service stub is returned, not altered by the bridge."""
    expected = {"ok": True, "value": 42.7, "unit": "degC"}

    client, _ = _make_agent_client(
        monkeypatch,
        service_map={"control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"}},
        service_sessions={"http://127.0.0.1:8767": expected},
    )

    resp = client.get("/control/read/reactor.temp")

    assert resp.status_code == 200
    assert resp.json() == expected


def test_agent_bridge_returns_404_when_service_unhealthy(monkeypatch: Any) -> None:
    """Bridge returns 404 when the target service is marked unhealthy."""
    client, _ = _make_agent_client(
        monkeypatch,
        service_map={"control_service": {"healthy": False, "base_url": "http://127.0.0.1:8767"}},
        service_sessions={},
    )

    resp = client.get("/control/read/reactor.temp")

    assert resp.status_code == 404


def test_agent_bridge_returns_404_when_service_absent(monkeypatch: Any) -> None:
    """Bridge returns 404 when the service_map has no entry for the service."""
    client, _ = _make_agent_client(
        monkeypatch,
        service_map={},
        service_sessions={},
    )

    resp = client.get("/schedule/status")

    assert resp.status_code == 404


# ===========================================================================
# GROUP 3 — Multi-device routing (BrewSupervisor with two real Agent clients)
# ===========================================================================

def test_supervisor_routes_control_to_device_a_not_device_b(monkeypatch: Any) -> None:
    """BrewSupervisor sends /control/* to Device A's agent; Device B is not touched."""
    a_calls: list[str] = []
    b_calls: list[str] = []

    agent_a, _ = _make_agent_client(
        monkeypatch,
        service_map={"control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"}},
        service_sessions={"http://127.0.0.1:8767": lambda m, p, _: a_calls.append(p) or {"ok": True, "device": "A"}},
    )
    agent_b, _ = _make_agent_client(
        monkeypatch,
        service_map={"schedule_service": {"healthy": True, "base_url": "http://127.0.0.1:8768"}},
        service_sessions={"http://127.0.0.1:8768": lambda m, p, _: b_calls.append(p) or {"ok": True, "device": "B"}},
    )

    node = _make_node(
        "01",
        service_agents={
            "control_service": "http://10.0.0.10:8780",
            "schedule_service": "http://10.0.0.11:8780",
        },
    )
    proxy = _MultiAgentProxy({"http://10.0.0.10:8780": agent_a, "http://10.0.0.11:8780": agent_b})
    client = _supervisor_client([node], proxy)

    resp = client.get("/fermenters/01/control/read/reactor.temp")

    assert resp.status_code == 200
    assert resp.json().get("device") == "A"
    assert a_calls, "control_service stub (Device A) must be called"
    assert not b_calls, "schedule_service stub (Device B) must NOT be called"


def test_supervisor_routes_schedule_to_device_b_not_device_a(monkeypatch: Any) -> None:
    """BrewSupervisor sends /schedule/* to Device B's agent; Device A is not touched."""
    a_calls: list[str] = []
    b_calls: list[str] = []

    agent_a, _ = _make_agent_client(
        monkeypatch,
        service_map={"control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"}},
        service_sessions={"http://127.0.0.1:8767": lambda m, p, _: a_calls.append(p) or {"device": "A"}},
    )
    agent_b, _ = _make_agent_client(
        monkeypatch,
        service_map={"schedule_service": {"healthy": True, "base_url": "http://127.0.0.1:8768"}},
        service_sessions={"http://127.0.0.1:8768": lambda m, p, _: b_calls.append(p) or {"ok": True, "device": "B"}},
    )

    node = _make_node(
        "01",
        service_agents={
            "control_service": "http://10.0.0.10:8780",
            "schedule_service": "http://10.0.0.11:8780",
        },
    )
    proxy = _MultiAgentProxy({"http://10.0.0.10:8780": agent_a, "http://10.0.0.11:8780": agent_b})
    client = _supervisor_client([node], proxy)

    resp = client.get("/fermenters/01/schedule/status")

    assert resp.status_code == 200
    assert resp.json().get("device") == "B"
    assert b_calls, "schedule_service stub (Device B) must be called"
    assert not a_calls, "control_service stub (Device A) must NOT be called"


def test_supervisor_three_services_three_devices_no_cross_routing(monkeypatch: Any) -> None:
    """
    Three services each hosted on a separate device agent.
    Every request must reach exactly the responsible device and nothing else.
    """
    hits: dict[str, int] = {"A": 0, "B": 0, "C": 0}

    def _device_handler(label: str):
        def _h(m: str, p: str, _: dict) -> dict:
            hits[label] += 1
            return {"ok": True, "device": label}
        return _h

    agent_a, _ = _make_agent_client(
        monkeypatch,
        service_map={"control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"}},
        service_sessions={"http://127.0.0.1:8767": _device_handler("A")},
    )
    agent_b, _ = _make_agent_client(
        monkeypatch,
        service_map={"schedule_service": {"healthy": True, "base_url": "http://127.0.0.1:8768"}},
        service_sessions={"http://127.0.0.1:8768": _device_handler("B")},
    )
    agent_c, _ = _make_agent_client(
        monkeypatch,
        service_map={"data_service": {"healthy": True, "base_url": "http://127.0.0.1:8769"}},
        service_sessions={"http://127.0.0.1:8769": _device_handler("C")},
    )

    node = _make_node(
        "01",
        agent_base_url="http://10.0.0.10:8780",
        service_agents={
            "control_service": "http://10.0.0.10:8780",
            "schedule_service": "http://10.0.0.11:8780",
            "data_service": "http://10.0.0.12:8780",
        },
    )
    proxy = _MultiAgentProxy({
        "http://10.0.0.10:8780": agent_a,
        "http://10.0.0.11:8780": agent_b,
        "http://10.0.0.12:8780": agent_c,
    })
    client = _supervisor_client([node], proxy)

    client.get("/fermenters/01/control/read/reactor.temp")
    client.get("/fermenters/01/schedule/status")
    client.get("/fermenters/01/data/archives")

    assert hits == {"A": 1, "B": 1, "C": 1}, (
        "each service must be routed to exactly its own device — no cross-routing"
    )


def test_supervisor_returns_404_for_unknown_fermenter(monkeypatch: Any) -> None:
    """BrewSupervisor returns 404 when fermenter_id does not match any node."""
    agent_a, _ = _make_agent_client(
        monkeypatch,
        service_map={"control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"}},
        service_sessions={},
    )
    node = _make_node("01", service_agents={"control_service": "http://10.0.0.10:8780"})
    proxy = _MultiAgentProxy({"http://10.0.0.10:8780": agent_a})
    client = _supervisor_client([node], proxy)

    resp = client.get("/fermenters/unknown-node/control/read/reactor.temp")
    assert resp.status_code == 404


# ===========================================================================
# GROUP 4 — Full end-to-end chain simulation
# ===========================================================================

def test_full_chain_response_body_propagates_through_all_layers(monkeypatch: Any) -> None:
    """
    Full 3-layer chain:  BrewSupervisor → Agent A → control_service stub.
    The exact response body from the stub must reach the BrewSupervisor caller.
    """
    agent_a, _ = _make_agent_client(
        monkeypatch,
        service_map={"control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"}},
        service_sessions={"http://127.0.0.1:8767": {"ok": True, "value": 18.5, "unit": "degC"}},
    )
    node = _make_node("01", service_agents={"control_service": "http://10.0.0.10:8780"})
    proxy = _MultiAgentProxy({"http://10.0.0.10:8780": agent_a})
    client = _supervisor_client([node], proxy)

    resp = client.get("/fermenters/01/control/read/reactor.temp")

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("value") == pytest.approx(18.5)
    assert body.get("unit") == "degC"


def test_full_chain_all_services_two_devices(monkeypatch: Any) -> None:
    """
    Full chain with two devices carrying three services.
    Each service request must propagate the correct device-specific payload.
    """
    agent_a, _ = _make_agent_client(
        monkeypatch,
        service_map={"control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"}},
        service_sessions={"http://127.0.0.1:8767": {"ok": True, "service": "control", "device": "A"}},
    )
    agent_b, _ = _make_agent_client(
        monkeypatch,
        service_map={
            "schedule_service": {"healthy": True, "base_url": "http://127.0.0.1:8768"},
            "data_service": {"healthy": True, "base_url": "http://127.0.0.1:8769"},
        },
        service_sessions={
            "http://127.0.0.1:8768": {"ok": True, "service": "schedule", "device": "B"},
            "http://127.0.0.1:8769": {"ok": True, "service": "data", "device": "B"},
        },
    )

    node = _make_node(
        "01",
        agent_base_url="http://10.0.0.10:8780",
        service_agents={
            "control_service": "http://10.0.0.10:8780",
            "schedule_service": "http://10.0.0.11:8780",
            "data_service": "http://10.0.0.11:8780",
        },
    )
    proxy = _MultiAgentProxy({"http://10.0.0.10:8780": agent_a, "http://10.0.0.11:8780": agent_b})
    client = _supervisor_client([node], proxy)

    ctrl = client.get("/fermenters/01/control/read/reactor.temp")
    sched = client.get("/fermenters/01/schedule/status")
    data = client.get("/fermenters/01/data/archives")

    assert ctrl.json() == {"ok": True, "service": "control", "device": "A"}
    assert sched.json() == {"ok": True, "service": "schedule", "device": "B"}
    assert data.json() == {"ok": True, "service": "data", "device": "B"}


def test_gateway_to_gateway_agent_bridge_path(monkeypatch: Any) -> None:
    """
    Gateway-to-gateway bridge simulation.

    Tests the path that a service on Device B would use when it has
    Agent A's URL injected as its backend URL (the url_flag pattern):

        service on B → (HTTP) → Agent A /control/read/x → control_service stub

    Agent A's bridge endpoint is called directly, verifying the full
    bridge-to-service forwarding works end-to-end.
    """
    service_payload = {"ok": True, "value": 55.0, "path": "setpoint"}

    agent_a, session_a = _make_agent_client(
        monkeypatch,
        service_map={"control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"}},
        service_sessions={"http://127.0.0.1:8767": service_payload},
    )

    # A service on Device B calls Agent A's bridge URL directly.
    resp = agent_a.get("/control/read/setpoint")

    assert resp.status_code == 200
    assert resp.json() == service_payload
    assert session_a.calls, "control_service must have been reached via Agent A's bridge"


def test_full_supervisor_plus_gateway_to_gateway_bridge(monkeypatch: Any) -> None:
    """
    Complete gateway-to-gateway simulation covering all three layers.

    Layer 1: BrewSupervisor routes /control/... to Agent A and /schedule/... to Agent B.
    Layer 2: Both agents bridge correctly to their respective service stubs.
    Layer 3: A direct call to Agent A's bridge path verifies the cross-device
             backend URL pattern (the path any service on Device B would call when
             Agent A is injected as its control backend URL).

    All three verified in one test to guard against regressions that break
    any segment of the chain simultaneously.
    """
    a_calls: list[str] = []
    b_calls: list[str] = []

    agent_a, _ = _make_agent_client(
        monkeypatch,
        service_map={"control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"}},
        service_sessions={"http://127.0.0.1:8767": lambda m, p, _: a_calls.append(p) or {"ok": True, "layer": "control", "device": "A"}},
    )
    agent_b, _ = _make_agent_client(
        monkeypatch,
        service_map={"schedule_service": {"healthy": True, "base_url": "http://127.0.0.1:8768"}},
        service_sessions={"http://127.0.0.1:8768": lambda m, p, _: b_calls.append(p) or {"ok": True, "layer": "schedule", "device": "B"}},
    )

    node = _make_node(
        "01",
        agent_base_url="http://10.0.0.10:8780",
        service_agents={
            "control_service": "http://10.0.0.10:8780",
            "schedule_service": "http://10.0.0.11:8780",
        },
    )
    proxy = _MultiAgentProxy({"http://10.0.0.10:8780": agent_a, "http://10.0.0.11:8780": agent_b})
    supervisor = _supervisor_client([node], proxy)

    # --- Layer 1 + 2: BrewSupervisor routing ---
    ctrl_resp = supervisor.get("/fermenters/01/control/read/reactor.temp")
    assert ctrl_resp.status_code == 200
    assert ctrl_resp.json()["device"] == "A"
    assert a_calls, "control_service must be reached via Agent A"

    sched_resp = supervisor.get("/fermenters/01/schedule/status")
    assert sched_resp.status_code == 200
    assert sched_resp.json()["device"] == "B"
    assert b_calls, "schedule_service must be reached via Agent B"

    # --- Layer 3: gateway-to-gateway bridge ---
    # Simulates a service on Device B calling Agent A's bridge URL as its control backend.
    a_pre = len(a_calls)
    bridge_resp = agent_a.get("/control/read/reactor.temp")
    assert bridge_resp.status_code == 200
    assert bridge_resp.json()["device"] == "A"
    assert len(a_calls) == a_pre + 1, "gateway-to-gateway call must reach control_service again"


def test_full_chain_post_request_body_survives_all_layers(monkeypatch: Any) -> None:
    """
    POST from BrewSupervisor → Agent → service stub:
    the request body must arrive at the stub intact.
    """
    bodies_at_service: list[dict] = []

    def _handler(method: str, path: str, kwargs: dict) -> dict:
        raw = kwargs.get("data") or b"{}"
        bodies_at_service.append(json.loads(raw))
        return {"ok": True}

    agent_a, _ = _make_agent_client(
        monkeypatch,
        service_map={"control_service": {"healthy": True, "base_url": "http://127.0.0.1:8767"}},
        service_sessions={"http://127.0.0.1:8767": _handler},
    )

    node = _make_node("01", service_agents={"control_service": "http://10.0.0.10:8780"})
    proxy = _MultiAgentProxy({"http://10.0.0.10:8780": agent_a})
    client = _supervisor_client([node], proxy)

    payload = {"target": "reactor.temp.setpoint", "value": 30.0, "owner": "schedule"}
    resp = client.post(
        "/fermenters/01/control/write",
        json=payload,
    )

    assert resp.status_code == 200
    assert bodies_at_service, "service stub must have received the POST body"
    assert bodies_at_service[0]["target"] == "reactor.temp.setpoint"
    assert bodies_at_service[0]["value"] == pytest.approx(30.0)


# ===========================================================================
# GROUP 5 — Regression guards
# ===========================================================================

def test_topology_agent_port_used_in_url_flag_validation() -> None:
    """
    agent_port is forwarded to the config loader's url_flag enforcement.
    A custom port matching the external endpoint must be accepted;
    the default 8780 must still reject a non-matching endpoint port.
    """
    import pathlib
    import tempfile
    from Supervisor.infrastructure.config_loader import YamlTopologyLoader

    yaml_text = """
external_capabilities:
  database.local:
    endpoint:
      host: 10.10.0.20
      port: 9999
      proto: http
      path: /data
services:
  schedule_service:
    module: Services.schedule_service.service
    listen:
      host: 0.0.0.0
      port: 8768
      proto: http
      path: /
    backends:
      database.local:
        url_flag: --data-backend-url
""".strip()

    with tempfile.TemporaryDirectory() as tmp:
        cfg = pathlib.Path(tmp) / "topology.yaml"
        cfg.write_text(yaml_text, encoding="utf-8")

        # Default agent_port=8780 — endpoint is on 9999 — must raise.
        with pytest.raises(ValueError) as exc_default:
            YamlTopologyLoader().load(cfg)
        assert "9999" not in str(exc_default.value)  # message reports 8780

        # Custom agent_port=9999 matching the endpoint — must NOT raise.
        YamlTopologyLoader().load(cfg, agent_port=9999)  # no exception

        # Custom agent_port=7777 still doesn't match — must raise with 7777 in msg.
        with pytest.raises(ValueError) as exc_custom:
            YamlTopologyLoader().load(cfg, agent_port=7777)
        assert "7777" in str(exc_custom.value)


def test_multi_node_same_id_service_routing_is_deterministic(monkeypatch: Any) -> None:
    """
    When two mDNS advertisements carry the same node_id, snapshot() merges
    them and get_node_for_service() returns the correct per-service agent.
    This is the core registry contract for the split-device topology.
    """
    from BrewSupervisor.application.fermenter_registry import FermenterRegistry
    from BrewSupervisor.infrastructure.discovery import DiscoveredAgent

    def _make_agent(svc_name: str, address: str, host: str) -> DiscoveredAgent:
        return DiscoveredAgent(
            service_name=f"svc-{svc_name}",
            node_id="01",
            node_name="Fermenter 01",
            address=address,
            host=host,
            port=8780,
            proto="http",
            api_path="/agent/info",
            summary_path="/agent/summary",
            services_hint=[svc_name],
        )

    agent_ctrl = _make_agent("control_service", "10.0.0.10", "ctrl-host")
    agent_sched = _make_agent("schedule_service", "10.0.0.11", "sched-host")

    browser = SimpleNamespace(snapshot=lambda: [agent_ctrl, agent_sched])
    registry = FermenterRegistry(browser, snapshot_cache_ttl_s=0.0)

    fake_session = type("S", (), {
        "calls": [],
        "mount": lambda s, *a, **kw: None,
        "closed": False,
        "close": lambda s: setattr(s, "closed", True),
    })()

    responses = [
        # agent_ctrl: info + summary
        SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"services": {"control_service": {"healthy": True}}},
        ),
        SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"control_available": True}),
        # agent_sched: info + summary
        SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"services": {"schedule_service": {"healthy": True}}},
        ),
        SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"schedule_available": True}),
    ]
    fake_session.get = lambda url, timeout: responses.pop(0)
    registry._session = fake_session

    snap = registry.snapshot()
    assert len(snap) == 1, "two agents with same node_id must merge into one node"
    merged = snap[0]
    assert "control_service" in merged.service_agents
    assert "schedule_service" in merged.service_agents
    assert merged.service_agents["control_service"] == "http://10.0.0.10:8780"
    assert merged.service_agents["schedule_service"] == "http://10.0.0.11:8780"

    # get_node_for_service must return the correct agent base URL.
    # (uses a fresh snapshot; repopulate response queue)
    responses.extend([
        SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"services": {"control_service": {"healthy": True}}}),
        SimpleNamespace(raise_for_status=lambda: None, json=lambda: {}),
        SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"services": {"schedule_service": {"healthy": True}}}),
        SimpleNamespace(raise_for_status=lambda: None, json=lambda: {}),
    ])
    svc_node = registry.get_node_for_service("01", "schedule_service")
    assert svc_node is not None
    assert svc_node.service_agents.get("schedule_service") == "http://10.0.0.11:8780"
