from __future__ import annotations

from types import SimpleNamespace

from BrewSupervisor.application.fermenter_registry import FermenterRegistry
from BrewSupervisor.infrastructure import discovery as discovery_module
from BrewSupervisor.infrastructure import http_proxy as http_proxy_module


class _FakeResponse:
    def __init__(self, *, status_code=200, headers=None, payload=None, text="", raises=False):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload
        self.text = text
        self._raises = raises

    def raise_for_status(self):
        if self._raises:
            raise RuntimeError("status error")

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self):
        self.mounted = []
        self.calls = []
        self.closed = False
        self._responses = []

    def mount(self, prefix, adapter):
        self.mounted.append((prefix, adapter))

    def queue(self, response):
        self._responses.append(response)

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        return self._responses.pop(0)

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)

    def close(self):
        self.closed = True


def test_http_service_proxy_json_text_and_raw_paths(monkeypatch) -> None:
    fake_session = _FakeSession()
    fake_session.queue(_FakeResponse(status_code=201, headers={"content-type": "application/json"}, payload={"ok": True}))
    fake_session.queue(_FakeResponse(status_code=202, headers={"content-type": "text/plain"}, text="done"))
    fake_session.queue(_FakeResponse(status_code=203, headers={}, text="raw"))

    monkeypatch.setattr(http_proxy_module.requests, "Session", lambda: fake_session)
    proxy = http_proxy_module.HttpServiceProxy(timeout_s=2.5)

    code_json, payload_json = proxy.request(method="get", url="http://x/a", params={"q": 1}, json_body={"a": 1})
    code_text, payload_text = proxy.request(method="post", url="http://x/b")
    raw = proxy.request_raw(method="put", url="http://x/c", stream=True)

    assert code_json == 201
    assert payload_json == {"ok": True}
    assert code_text == 202
    assert payload_text == {"text": "done"}
    assert raw.status_code == 203

    assert fake_session.calls[0]["method"] == "GET"
    assert fake_session.calls[1]["method"] == "POST"
    assert fake_session.calls[2]["method"] == "PUT"
    assert fake_session.calls[2]["stream"] is True

    proxy.close()
    assert fake_session.closed is True


def test_fermenter_registry_fetch_build_snapshot_get_and_close(monkeypatch) -> None:
    browser = SimpleNamespace(snapshot=lambda: [])
    registry = FermenterRegistry(browser)
    fake_session = _FakeSession()
    registry._session = fake_session

    fake_session.queue(_FakeResponse(payload={"k": 1}))
    assert registry._fetch_json("http://x") == {"k": 1}

    fake_session.queue(_FakeResponse(payload=[1, 2]))
    assert registry._fetch_json("http://x") == {"value": [1, 2]}

    agent = discovery_module.DiscoveredAgent(
        service_name="svc",
        node_id="id1",
        node_name="Node 1",
        address="127.0.0.1",
        host="host1",
        port=8780,
        proto="http",
        api_path="/agent/info",
        summary_path="/agent/summary",
        services_hint=["control_service"],
    )

    # info + summary success
    fake_session.queue(_FakeResponse(payload={"node_id": "id-updated", "node_name": "Renamed", "services": {"x": {}}}))
    fake_session.queue(_FakeResponse(payload={"health": "ok"}))
    node = registry._build_node(agent)
    assert node.id == "id-updated"
    assert node.name == "Renamed"
    assert node.services == {"x": {}}
    assert node.summary == {"health": "ok"}
    assert node.online is True

    # info failure => offline
    fake_session.queue(_FakeResponse(raises=True))
    node_offline = registry._build_node(agent)
    assert node_offline.online is False
    assert node_offline.last_error is not None

    # summary failure keeps online but sets last_error
    fake_session.queue(_FakeResponse(payload={"services": {}}))
    fake_session.queue(_FakeResponse(raises=True))
    node_summary_fail = registry._build_node(agent)
    assert node_summary_fail.online is True
    assert node_summary_fail.last_error is not None

    browser.snapshot = lambda: [agent]
    fake_session.queue(_FakeResponse(payload={"services": {}}))
    fake_session.queue(_FakeResponse(payload={"ok": True}))
    snap = registry.snapshot()
    assert len(snap) == 1

    fake_session.queue(_FakeResponse(payload={"services": {}}))
    fake_session.queue(_FakeResponse(payload={"ok": True}))
    found = registry.get_node(snap[0].id)
    assert found is not None

    fake_session.queue(_FakeResponse(payload={"services": {}}))
    fake_session.queue(_FakeResponse(payload={"ok": True}))
    missing = registry.get_node("missing")
    assert missing is None

    registry.close()
    assert fake_session.closed is True


def test_fermenter_registry_merges_split_service_advertisements(monkeypatch) -> None:
    agent_control = discovery_module.DiscoveredAgent(
        service_name="svc-control",
        node_id="01",
        node_name="Fermenter 01",
        address="10.0.0.10",
        host="ctrl",
        port=8780,
        proto="http",
        api_path="/agent/info",
        summary_path="/agent/summary",
        services_hint=["control_service"],
    )
    agent_schedule = discovery_module.DiscoveredAgent(
        service_name="svc-schedule",
        node_id="01",
        node_name="Fermenter 01",
        address="10.0.0.11",
        host="sched",
        port=8780,
        proto="http",
        api_path="/agent/info",
        summary_path="/agent/summary",
        services_hint=["schedule_service"],
    )
    browser = SimpleNamespace(snapshot=lambda: [agent_control, agent_schedule])
    registry = FermenterRegistry(browser)
    fake_session = _FakeSession()
    registry._session = fake_session

    fake_session.queue(_FakeResponse(payload={"services": {"control_service": {"healthy": True}}}))
    fake_session.queue(_FakeResponse(payload={"control_available": True}))
    fake_session.queue(_FakeResponse(payload={"services": {"schedule_service": {"healthy": True}}}))
    fake_session.queue(_FakeResponse(payload={"schedule_available": True}))

    snapshot = registry.snapshot()
    assert len(snapshot) == 1
    node = snapshot[0]
    assert sorted(node.services.keys()) == ["control_service", "schedule_service"]
    assert node.service_agents["control_service"] == "http://10.0.0.10:8780"
    assert node.service_agents["schedule_service"] == "http://10.0.0.11:8780"

    schedule_node = registry.get_node_for_service("01", "schedule_service")
    assert schedule_node is not None
    assert schedule_node.service_agents["schedule_service"] == "http://10.0.0.11:8780"


def test_fermenter_registry_prefers_online_agent_when_merging(monkeypatch) -> None:
    agent_offline = discovery_module.DiscoveredAgent(
        service_name="svc-offline",
        node_id="01",
        node_name="Fermenter 01",
        address="10.0.0.10",
        host="offline-host",
        port=8780,
        proto="http",
        api_path="/agent/info",
        summary_path="/agent/summary",
        services_hint=["control_service"],
    )
    agent_online = discovery_module.DiscoveredAgent(
        service_name="svc-online",
        node_id="01",
        node_name="Fermenter 01",
        address="10.0.0.11",
        host="online-host",
        port=8780,
        proto="http",
        api_path="/agent/info",
        summary_path="/agent/summary",
        services_hint=["schedule_service"],
    )
    browser = SimpleNamespace(snapshot=lambda: [agent_offline, agent_online])
    registry = FermenterRegistry(browser)
    fake_session = _FakeSession()
    registry._session = fake_session

    fake_session.queue(_FakeResponse(raises=True))
    fake_session.queue(_FakeResponse(payload={"services": {"schedule_service": {"healthy": True}}}))
    fake_session.queue(_FakeResponse(payload={"schedule_available": True}))

    snapshot = registry.snapshot()
    assert len(snapshot) == 1
    merged = snapshot[0]
    assert merged.online is True
    assert merged.address == "10.0.0.11"
    assert merged.host == "online-host"


def test_fermenter_registry_all_offline_merges_errors(monkeypatch) -> None:
    agent_a = discovery_module.DiscoveredAgent(
        service_name="svc-a",
        node_id="01",
        node_name="Fermenter 01",
        address="10.0.0.10",
        host="a",
        port=8780,
        proto="http",
        api_path="/agent/info",
        summary_path="/agent/summary",
        services_hint=["control_service"],
    )
    agent_b = discovery_module.DiscoveredAgent(
        service_name="svc-b",
        node_id="01",
        node_name="Fermenter 01",
        address="10.0.0.11",
        host="b",
        port=8780,
        proto="http",
        api_path="/agent/info",
        summary_path="/agent/summary",
        services_hint=["schedule_service"],
    )
    browser = SimpleNamespace(snapshot=lambda: [agent_a, agent_b])
    registry = FermenterRegistry(browser)
    fake_session = _FakeSession()
    registry._session = fake_session

    fake_session.queue(_FakeResponse(raises=True))
    fake_session.queue(_FakeResponse(raises=True))

    snapshot = registry.snapshot()
    assert len(snapshot) == 1
    merged = snapshot[0]
    assert merged.online is False
    assert merged.last_error is not None
    assert "status error" in merged.last_error


def test_get_node_for_service_falls_back_when_service_unknown(monkeypatch) -> None:
    agent = discovery_module.DiscoveredAgent(
        service_name="svc",
        node_id="01",
        node_name="Fermenter 01",
        address="10.0.0.10",
        host="host",
        port=8780,
        proto="http",
        api_path="/agent/info",
        summary_path="/agent/summary",
        services_hint=["control_service"],
    )
    browser = SimpleNamespace(snapshot=lambda: [agent])
    registry = FermenterRegistry(browser)
    fake_session = _FakeSession()
    registry._session = fake_session

    fake_session.queue(_FakeResponse(payload={"services": {"control_service": {"healthy": True}}}))
    fake_session.queue(_FakeResponse(payload={"control_available": True}))

    selected = registry.get_node_for_service("01", "unknown_service")
    assert selected is not None
    assert selected.id == "01"


def test_fermenter_registry_snapshot_cache_avoids_duplicate_fetches(monkeypatch) -> None:
    agent = discovery_module.DiscoveredAgent(
        service_name="svc",
        node_id="01",
        node_name="Fermenter 01",
        address="10.0.0.10",
        host="host",
        port=8780,
        proto="http",
        api_path="/agent/info",
        summary_path="/agent/summary",
        services_hint=["control_service"],
    )
    browser = SimpleNamespace(snapshot=lambda: [agent])
    registry = FermenterRegistry(browser, snapshot_cache_ttl_s=5.0)
    fake_session = _FakeSession()
    registry._session = fake_session

    fake_session.queue(_FakeResponse(payload={"services": {"control_service": {"healthy": True}}}))
    fake_session.queue(_FakeResponse(payload={"control_available": True}))

    first = registry.snapshot()
    second = registry.snapshot()

    assert len(first) == 1
    assert len(second) == 1
    assert len(fake_session.calls) == 2


def test_fermenter_registry_prefers_stable_order_when_multiple_online() -> None:
    browser = SimpleNamespace(snapshot=lambda: [])
    registry = FermenterRegistry(browser)

    node_b = SimpleNamespace(name="Fermenter", host="b-host", address="10.0.0.20", agent_base_url="http://10.0.0.20:8780", online=True)
    node_a = SimpleNamespace(name="Fermenter", host="a-host", address="10.0.0.10", agent_base_url="http://10.0.0.10:8780", online=True)

    picked = registry._pick_preferred_node([node_b, node_a])
    assert picked is node_a


def test_discovery_decode_urls_start_refresh_remove_snapshot_and_close(monkeypatch) -> None:
    assert discovery_module._decode_property(b"abc") == "abc"
    assert discovery_module._decode_property(None) == ""

    agent = discovery_module.DiscoveredAgent(
        service_name="svc",
        node_id="n1",
        node_name="Node",
        address="10.0.0.2",
        host="host",
        port=9000,
        proto="http",
        api_path="agent/info",
        summary_path="summary",
        services_hint=[],
    )
    assert agent.base_url == "http://10.0.0.2:9000"
    assert agent.info_url.endswith("/agent/info")

    browser = discovery_module.MdnsDiscoveryBrowser()

    monkeypatch.setattr(discovery_module, "Zeroconf", None)
    monkeypatch.setattr(discovery_module, "ServiceBrowser", None)
    assert browser.start() is False

    class _FakeInfo:
        def __init__(self, props, addresses=None, port=8765, server="node.local."):
            self.properties = props
            self._addresses = addresses if addresses is not None else ["127.0.0.1"]
            self.port = port
            self.server = server

        def parsed_addresses(self):
            return self._addresses

    class _FakeZeroconf:
        def __init__(self):
            self.closed = False
            self.info = None
            self.raise_get = False

        def get_service_info(self, _stype, _name, timeout=1000):
            _ = timeout
            if self.raise_get:
                raise RuntimeError("boom")
            return self.info

        def close(self):
            self.closed = True

    class _FakeBrowser:
        def __init__(self, zeroconf, service_type, listener):
            self.zeroconf = zeroconf
            self.service_type = service_type
            self.listener = listener

    monkeypatch.setattr(discovery_module, "Zeroconf", _FakeZeroconf)
    monkeypatch.setattr(discovery_module, "ServiceBrowser", _FakeBrowser)

    browser2 = discovery_module.MdnsDiscoveryBrowser()
    assert browser2.start() is True
    assert browser2.start() is True

    # no-zeroconf guard
    browser3 = discovery_module.MdnsDiscoveryBrowser()
    browser3._refresh_service("x")

    # get_service_info exception and None info paths
    browser2.zeroconf.raise_get = True
    browser2._refresh_service("svc._fcs._tcp.local.")
    browser2.zeroconf.raise_get = False
    browser2.zeroconf.info = None
    browser2._refresh_service("svc._fcs._tcp.local.")

    # role mismatch removes existing
    browser2._agents["svc"] = agent
    browser2.zeroconf.info = _FakeInfo({b"role": b"other"})
    browser2._refresh_service("svc")
    assert "svc" not in browser2._agents

    # expected role with defaults and services parsing
    browser2.zeroconf.info = _FakeInfo(
        {
            b"role": b"fermenter_agent",
            b"node_id": b"node-1",
            b"node_name": b"Fermenter 1",
            b"proto": b"http",
            b"api": b"/agent/info",
            b"summary": b"/agent/summary",
            b"services": b"control_service, schedule_service",
            b"hostname": b"fermenter-host",
        },
        addresses=["10.0.0.5"],
        port=8780,
    )
    browser2._refresh_service("svc")
    assert "svc" in browser2._agents

    # snapshot sort + remove service
    browser2._agents["a"] = discovery_module.DiscoveredAgent(
        service_name="a",
        node_id="a",
        node_name="A",
        address="10.0.0.3",
        host="h3",
        port=1,
        proto="http",
        api_path="/agent/info",
        summary_path="/agent/summary",
        services_hint=[],
    )
    snapshot = browser2.snapshot()
    assert len(snapshot) >= 1

    browser2._remove_service("svc")
    assert "svc" not in browser2._agents

    # close with zeroconf.close exception should still clear state
    class _BadZc:
        def close(self):
            raise RuntimeError("close failed")

    browser2.zeroconf = _BadZc()
    browser2.close()
    assert browser2.zeroconf is None
    assert browser2.listener is None
    assert browser2.browser is None


def test_discovery_snapshot_restarts_when_empty(monkeypatch) -> None:
    starts = {"count": 0}

    class _FakeZeroconf:
        def close(self):
            pass

    class _FakeBrowser:
        def __init__(self, zeroconf, service_type, listener):
            _ = (zeroconf, service_type, listener)

    def _factory():
        starts["count"] += 1
        return _FakeZeroconf()

    monkeypatch.setattr(discovery_module, "Zeroconf", _factory)
    monkeypatch.setattr(discovery_module, "ServiceBrowser", _FakeBrowser)

    browser = discovery_module.MdnsDiscoveryBrowser(restart_cooldown_s=0.0)
    assert browser.start() is True
    assert starts["count"] == 1

    assert browser.snapshot() == []
    assert starts["count"] == 2
