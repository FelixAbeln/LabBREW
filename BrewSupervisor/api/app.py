from __future__ import annotations

import inspect
import math
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..application.fermenter_registry import FermenterRegistry
from ..infrastructure.discovery import MdnsDiscoveryBrowser
from ..infrastructure.http_proxy import HttpServiceProxy
from .routes import build_router


def _read_float_env(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        return default
    if not math.isfinite(value):
        return default
    return value


def _read_optional_float_env(name: str) -> float | None:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return value


@asynccontextmanager
async def lifespan(app: FastAPI):
    browser_kwargs: dict[str, float] = {}
    try:
        browser_params = inspect.signature(MdnsDiscoveryBrowser).parameters
        if "restart_cooldown_s" in browser_params:
            restart_cooldown_s = _read_optional_float_env("MDNS_RESTART_COOLDOWN_S")
            if restart_cooldown_s is not None:
                browser_kwargs["restart_cooldown_s"] = restart_cooldown_s
        if "rebrowse_interval_s" in browser_params:
            rebrowse_interval_s = _read_optional_float_env("MDNS_REBROWSE_INTERVAL_S")
            if rebrowse_interval_s is not None:
                browser_kwargs["rebrowse_interval_s"] = rebrowse_interval_s
    except (TypeError, ValueError):
        # Some test doubles may not expose an inspectable signature.
        pass

    browser = MdnsDiscoveryBrowser(**browser_kwargs)
    browser.start()
    app.state.discovery_browser = browser
    registry_kwargs: dict[str, float] = {}
    try:
        params = inspect.signature(FermenterRegistry).parameters
        if "timeout_s" in params:
            registry_kwargs["timeout_s"] = _read_float_env("REGISTRY_TIMEOUT_S", 0.6)
        if "snapshot_cache_ttl_s" in params:
            registry_kwargs["snapshot_cache_ttl_s"] = _read_float_env(
                "REGISTRY_CACHE_TTL_S", 0.5
            )
        if "stale_snapshot_grace_s" in params:
            registry_kwargs["stale_snapshot_grace_s"] = _read_float_env(
                "REGISTRY_STALE_GRACE_S", 20.0
            )
    except (TypeError, ValueError):
        # Some test doubles may not expose an inspectable signature.
        pass

    app.state.registry = FermenterRegistry(browser, **registry_kwargs)
    app.state.proxy = HttpServiceProxy(timeout_s=8.0)
    try:
        yield
    finally:
        app.state.proxy.close()
        app.state.registry.close()
        browser.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Brew Supervisor", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(build_router())
    return app


app = create_app()
