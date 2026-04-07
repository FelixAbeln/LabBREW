from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from BrewSupervisor.api import app as app_module


def test_create_app_includes_router_and_cors(monkeypatch) -> None:
    router = APIRouter()

    @router.get("/ping")
    def ping():
        return {"ok": True}

    monkeypatch.setattr(app_module, "build_router", lambda: router)

    app = app_module.create_app()
    client = TestClient(app)
    response = client.get("/ping")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert any(m.cls.__name__ == "CORSMiddleware" for m in app.user_middleware)


def test_lifespan_sets_state_and_closes_resources(monkeypatch) -> None:
    calls = []

    class _Browser:
        def __init__(self):
            self.started = False
            self.closed = False

        def start(self):
            self.started = True
            calls.append("browser.start")

        def close(self):
            self.closed = True
            calls.append("browser.close")

    class _Registry:
        def __init__(self, browser):
            self.browser = browser
            self.closed = False
            calls.append("registry.init")

        def close(self):
            self.closed = True
            calls.append("registry.close")

    class _Proxy:
        def __init__(self, timeout_s):
            self.timeout_s = timeout_s
            self.closed = False
            calls.append(f"proxy.init:{timeout_s}")

        def close(self):
            self.closed = True
            calls.append("proxy.close")

    monkeypatch.setattr(app_module, "MdnsDiscoveryBrowser", _Browser)
    monkeypatch.setattr(app_module, "FermenterRegistry", _Registry)
    monkeypatch.setattr(app_module, "HttpServiceProxy", _Proxy)

    app = FastAPI()

    async def _run() -> None:
        async with app_module.lifespan(app):
            assert app.state.discovery_browser.started is True
            assert app.state.registry.browser is app.state.discovery_browser
            assert app.state.proxy.timeout_s == 8.0

    asyncio.run(_run())

    assert "browser.start" in calls
    assert "registry.init" in calls
    assert "proxy.init:8.0" in calls
    assert "proxy.close" in calls
    assert "registry.close" in calls
    assert "browser.close" in calls


def test_lifespan_passes_mdns_timing_env_to_browser(monkeypatch) -> None:
    calls = []

    class _Browser:
        def __init__(self, restart_cooldown_s: float = 0.0, rebrowse_interval_s: float = 0.0):
            self.restart_cooldown_s = restart_cooldown_s
            self.rebrowse_interval_s = rebrowse_interval_s
            calls.append(f"browser.init:{restart_cooldown_s}:{rebrowse_interval_s}")

        def start(self):
            calls.append("browser.start")

        def close(self):
            calls.append("browser.close")

    class _Registry:
        def __init__(self, browser, snapshot_cache_ttl_s: float = 0.0):
            self.browser = browser
            self.snapshot_cache_ttl_s = snapshot_cache_ttl_s

        def close(self):
            pass

    class _Proxy:
        def __init__(self, timeout_s):
            self.timeout_s = timeout_s

        def close(self):
            pass

    monkeypatch.setenv("MDNS_RESTART_COOLDOWN_S", "2.5")
    monkeypatch.setenv("MDNS_REBROWSE_INTERVAL_S", "15")
    monkeypatch.setenv("REGISTRY_CACHE_TTL_S", "1.25")
    monkeypatch.setattr(app_module, "MdnsDiscoveryBrowser", _Browser)
    monkeypatch.setattr(app_module, "FermenterRegistry", _Registry)
    monkeypatch.setattr(app_module, "HttpServiceProxy", _Proxy)

    app = FastAPI()

    async def _run() -> None:
        async with app_module.lifespan(app):
            assert app.state.discovery_browser.restart_cooldown_s == 2.5
            assert app.state.discovery_browser.rebrowse_interval_s == 15.0
            assert app.state.registry.snapshot_cache_ttl_s == 1.25

    asyncio.run(_run())

    assert "browser.init:2.5:15.0" in calls
    assert "browser.start" in calls
    assert "browser.close" in calls


def test_lifespan_ignores_bad_mdns_env_without_dropping_other_values(monkeypatch) -> None:
    class _Browser:
        def __init__(self, restart_cooldown_s: float = 0.0, rebrowse_interval_s: float = 0.0):
            self.restart_cooldown_s = restart_cooldown_s
            self.rebrowse_interval_s = rebrowse_interval_s

        def start(self):
            pass

        def close(self):
            pass

    class _Registry:
        def __init__(self, browser, snapshot_cache_ttl_s: float = 0.0):
            self.browser = browser
            self.snapshot_cache_ttl_s = snapshot_cache_ttl_s

        def close(self):
            pass

    class _Proxy:
        def __init__(self, timeout_s):
            self.timeout_s = timeout_s

        def close(self):
            pass

    monkeypatch.setenv("MDNS_RESTART_COOLDOWN_S", "bad-value")
    monkeypatch.setenv("MDNS_REBROWSE_INTERVAL_S", "15")
    monkeypatch.setenv("REGISTRY_CACHE_TTL_S", "1.25")
    monkeypatch.setattr(app_module, "MdnsDiscoveryBrowser", _Browser)
    monkeypatch.setattr(app_module, "FermenterRegistry", _Registry)
    monkeypatch.setattr(app_module, "HttpServiceProxy", _Proxy)

    app = FastAPI()

    async def _run() -> None:
        async with app_module.lifespan(app):
            assert app.state.discovery_browser.restart_cooldown_s == 0.0
            assert app.state.discovery_browser.rebrowse_interval_s == 15.0
            assert app.state.registry.snapshot_cache_ttl_s == 1.25

    asyncio.run(_run())


def test_lifespan_preserves_browser_defaults_when_mdns_env_is_unset(monkeypatch) -> None:
    class _Browser:
        def __init__(self, restart_cooldown_s: float = 10.0, rebrowse_interval_s: float = 120.0):
            self.restart_cooldown_s = restart_cooldown_s
            self.rebrowse_interval_s = rebrowse_interval_s

        def start(self):
            pass

        def close(self):
            pass

    class _Registry:
        def __init__(self, browser, snapshot_cache_ttl_s: float = 0.0):
            self.browser = browser
            self.snapshot_cache_ttl_s = snapshot_cache_ttl_s

        def close(self):
            pass

    class _Proxy:
        def __init__(self, timeout_s):
            self.timeout_s = timeout_s

        def close(self):
            pass

    monkeypatch.delenv("MDNS_RESTART_COOLDOWN_S", raising=False)
    monkeypatch.delenv("MDNS_REBROWSE_INTERVAL_S", raising=False)
    monkeypatch.setattr(app_module, "MdnsDiscoveryBrowser", _Browser)
    monkeypatch.setattr(app_module, "FermenterRegistry", _Registry)
    monkeypatch.setattr(app_module, "HttpServiceProxy", _Proxy)

    app = FastAPI()

    async def _run() -> None:
        async with app_module.lifespan(app):
            assert app.state.discovery_browser.restart_cooldown_s == 10.0
            assert app.state.discovery_browser.rebrowse_interval_s == 120.0

    asyncio.run(_run())
