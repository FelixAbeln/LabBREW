from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..application.fermenter_registry import FermenterRegistry
from ..infrastructure.discovery import MdnsDiscoveryBrowser
from ..infrastructure.http_proxy import HttpServiceProxy
from .routes import build_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    browser = MdnsDiscoveryBrowser()
    browser.start()
    app.state.discovery_browser = browser
    app.state.registry = FermenterRegistry(browser)
    app.state.proxy = HttpServiceProxy(timeout_s=8.0)
    try:
        yield
    finally:
        app.state.proxy.close()
        app.state.registry.close()
        browser.close()


def create_app() -> FastAPI:
    app = FastAPI(title='Brew Supervisor', version='0.1.0', lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )
    app.include_router(build_router())
    return app


app = create_app()
