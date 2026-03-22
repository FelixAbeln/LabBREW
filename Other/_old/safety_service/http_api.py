from __future__ import annotations

from http.server import ThreadingHTTPServer

from ..service_bases.apps.safety_base import SafetyBaseApp, build_safety_routes
from ..service_bases.core import run_service_server
from .service import SafetyRuleEngine


def run_http_server(engine: SafetyRuleEngine, host: str, port: int) -> ThreadingHTTPServer:
    app = SafetyBaseApp(engine)
    return run_service_server(build_safety_routes(app), host=host, port=port)
