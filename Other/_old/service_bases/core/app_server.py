from __future__ import annotations

import json
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Iterable
from urllib.parse import urlparse


JsonDict = dict[str, Any]
HandlerFn = Callable[[JsonDict], JsonDict]


@dataclass(frozen=True, slots=True)
class Route:
    method: str
    path: str
    handler: HandlerFn


class ServiceServer:
    def __init__(self, routes: Iterable[Route]) -> None:
        self._route_map: dict[tuple[str, str], HandlerFn] = {
            (route.method.upper(), route.path): route.handler for route in routes
        }

    def build_handler(self):
        route_map = self._route_map

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, status: int, payload: JsonDict) -> None:
                raw = json.dumps(payload).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _read_payload(self) -> JsonDict:
                size = int(self.headers.get('Content-Length', '0') or '0')
                raw = self.rfile.read(size) if size > 0 else b'{}'
                if not raw:
                    return {}
                return json.loads(raw.decode('utf-8'))

            def _dispatch(self, method: str) -> None:
                path = urlparse(self.path).path
                handler = route_map.get((method, path))
                if handler is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {'ok': False, 'message': f'Unknown path: {path}'})
                    return
                try:
                    payload = {} if method == 'GET' else self._read_payload()
                    response = handler(payload)
                    if not isinstance(response, dict):
                        response = {'ok': True, 'data': response}
                    self._send_json(HTTPStatus.OK, response)
                except Exception as exc:  # pragma: no cover
                    self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {'ok': False, 'message': str(exc)})

            def do_GET(self) -> None:
                self._dispatch('GET')

            def do_POST(self) -> None:
                self._dispatch('POST')

            def log_message(self, format: str, *args):
                return

        return Handler


def run_service_server(routes: Iterable[Route], host: str, port: int) -> ThreadingHTTPServer:
    server = ServiceServer(routes)
    return ThreadingHTTPServer((host, port), server.build_handler())
