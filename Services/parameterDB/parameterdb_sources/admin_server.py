from __future__ import annotations

import socketserver
from typing import Any

from ..parameterdb_core.protocol import (
    encode_message,
    make_error_response,
    make_response,
    read_message,
    validate_request_envelope,
)


class SourceRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        while True:
            req_id: str | None = None
            try:
                req = read_message(self.rfile)
                if req is None:
                    break
                cmd, req_id, payload = validate_request_envelope(req)
                result = self.server.dispatch(cmd, payload)  # type: ignore[attr-defined]
                resp = make_response(req_id=req_id, result=result)
            except Exception as exc:
                resp = make_error_response(
                    req_id=req_id, error_type=exc.__class__.__name__, message=str(exc)
                )
            self.wfile.write(encode_message(resp))
            self.wfile.flush()


class SourceAdminTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, host: str, port: int, runner: Any) -> None:
        super().__init__((host, port), SourceRequestHandler)
        self.runner = runner

    def dispatch(self, cmd: str, payload: dict[str, Any]) -> Any:
        handler = getattr(self, f"api_{cmd}", None)
        if handler is None:
            raise ValueError(f"Unknown command '{cmd}'")
        return handler(payload)

    def _require_str(self, payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing or invalid '{key}'")
        return value.strip()

    def api_ping(self, _payload: dict[str, Any]) -> str:
        return "pong"

    def api_list_source_types_ui(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return self.runner.registry.list_ui()

    def api_get_source_type_ui(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_type = self._require_str(payload, "source_type")
        record = None
        name = payload.get("name")
        if isinstance(name, str) and name.strip():
            try:
                record = self.runner.get_source_record(name.strip())
            except Exception:
                record = None
        return self.runner.registry.get_ui_spec(
            source_type,
            record=record,
            mode=str(payload.get("mode") or "").strip() or None,
        )

    def api_list_sources(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return self.runner.list_sources()

    def api_create_source(self, payload: dict[str, Any]) -> bool:
        name = self._require_str(payload, "name")
        source_type = self._require_str(payload, "source_type")
        config = payload.get("config") or {}
        if not isinstance(config, dict):
            raise ValueError("Invalid 'config'")
        self.runner.create_source(name, source_type, config=config)
        return True

    def api_update_source(self, payload: dict[str, Any]) -> bool:
        name = self._require_str(payload, "name")
        config = payload.get("config") or {}
        if not isinstance(config, dict):
            raise ValueError("Invalid 'config'")
        self.runner.update_source(name, config=config)
        return True

    def api_delete_source(self, payload: dict[str, Any]) -> bool:
        name = self._require_str(payload, "name")
        self.runner.delete_source(name)
        return True
