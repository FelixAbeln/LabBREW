from __future__ import annotations

from http.server import ThreadingHTTPServer

from ..service_bases.apps.scheduler_base import SchedulerBaseApp, build_scheduler_routes
from ..service_bases.core import run_service_server
from .runtime import FcsRuntimeService


def run_http_server(runtime: FcsRuntimeService, host: str, port: int) -> ThreadingHTTPServer:
    app = SchedulerBaseApp(runtime)
    return run_service_server(build_scheduler_routes(app), host=host, port=port)
