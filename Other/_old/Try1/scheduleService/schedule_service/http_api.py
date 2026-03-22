from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlparse

from .runtime import FcsRuntimeService


def build_handler(runtime: FcsRuntimeService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FcsRuntime/0.2"

        def _json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8")) if raw else {}

        def _send(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/status":
                self._send(runtime.status())
                return
            if parsed.path == "/health":
                self._send({"ok": True, "backend_connected": runtime.backend.connected()})
                return
            if parsed.path == "/schedule/current":
                payload = runtime.current_schedule_payload()
                self._send({"ok": True, "schedule": payload, "has_schedule": bool(payload.get("startup_steps") or payload.get("plan_steps"))})
                return
            self._send({"ok": False, "message": "Not found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            body = self._json_body()
            route_map: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
                "/schedule/validate": lambda p: runtime.validate_schedule_payload(p),
                "/schedule/upload": lambda p: runtime.upload_schedule(p),
                "/run/start": lambda _p: runtime.start_run(),
                "/run/pause": lambda _p: runtime.pause_run(),
                "/run/resume": lambda _p: runtime.resume_run(),
                "/run/stop": lambda _p: runtime.stop_run(),
                "/run/confirm": lambda _p: runtime.confirm_step(),
                "/run/next": lambda _p: runtime.next_step(),
                "/run/previous": lambda _p: runtime.previous_step(),
            }
            handler = route_map.get(parsed.path)
            if handler is None:
                self._send({"ok": False, "message": "Not found"}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                self._send(handler(body))
            except Exception as exc:
                self._send({"ok": False, "message": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


def run_http_server(runtime: FcsRuntimeService, host: str = "127.0.0.1", port: int = 8769) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), build_handler(runtime))
