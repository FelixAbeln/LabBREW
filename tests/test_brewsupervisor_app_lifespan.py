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
