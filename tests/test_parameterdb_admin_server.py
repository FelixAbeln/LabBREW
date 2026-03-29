from __future__ import annotations

from io import BytesIO
import socketserver

import pytest

import Services.parameterDB.parameterdb_sources.admin_server as admin_server_module
from Services.parameterDB.parameterdb_core.protocol import decode_message_bytes, encode_message, make_request
from Services.parameterDB.parameterdb_sources.admin_server import SourceAdminTCPServer, SourceRequestHandler


def _decode_framed(stream: BytesIO) -> list[dict]:
    data = stream.getvalue()
    out: list[dict] = []
    index = 0
    while index + 4 <= len(data):
        size = int.from_bytes(data[index:index + 4], byteorder="big")
        index += 4
        body = data[index:index + size]
        index += size
        out.append(decode_message_bytes(body))
    return out


def _server_with_runner(runner):
    server = SourceAdminTCPServer.__new__(SourceAdminTCPServer)
    server.runner = runner
    return server


def test_source_admin_dispatch_and_api_commands() -> None:
    class Runner:
        def __init__(self) -> None:
            self.registry = self
            self.calls: list[tuple] = []

        def list_ui(self):
            return {"fake": {"display_name": "Fake"}}

        def get_ui_spec(self, source_type: str, *, record=None, mode=None):
            return {"source_type": source_type, "record": record, "mode": mode}

        def get_source_record(self, name: str):
            if name == "missing":
                raise KeyError(name)
            return {"name": name}

        def list_sources(self):
            return {"a": {"name": "a"}}

        def create_source(self, name: str, source_type: str, *, config: dict):
            self.calls.append(("create", name, source_type, dict(config)))

        def update_source(self, name: str, *, config: dict):
            self.calls.append(("update", name, dict(config)))

        def delete_source(self, name: str):
            self.calls.append(("delete", name))

    runner = Runner()
    server = _server_with_runner(runner)

    assert server.dispatch("ping", {}) == "pong"
    assert server.api_list_source_types_ui({}) == {"fake": {"display_name": "Fake"}}
    assert server.api_get_source_type_ui({"source_type": "fake", "name": "alpha", "mode": "edit"}) == {
        "source_type": "fake",
        "record": {"name": "alpha"},
        "mode": "edit",
    }
    assert server.api_get_source_type_ui({"source_type": "fake", "name": "missing"})["record"] is None
    assert server.api_list_sources({}) == {"a": {"name": "a"}}

    assert server.api_create_source({"name": "n1", "source_type": "fake", "config": {"x": 1}}) is True
    assert server.api_update_source({"name": "n1", "config": {"x": 2}}) is True
    assert server.api_delete_source({"name": "n1"}) is True
    assert runner.calls == [
        ("create", "n1", "fake", {"x": 1}),
        ("update", "n1", {"x": 2}),
        ("delete", "n1"),
    ]

    with pytest.raises(ValueError):
        server.dispatch("missing", {})

    with pytest.raises(ValueError):
        server._require_str({}, "name")

    with pytest.raises(ValueError):
        server.api_create_source({"name": "n1", "source_type": "fake", "config": "bad"})

    with pytest.raises(ValueError):
        server.api_update_source({"name": "n1", "config": "bad"})


def test_source_request_handler_writes_success_and_error_responses() -> None:
    class FakeServer:
        def dispatch(self, cmd: str, payload: dict):
            if cmd == "ping":
                return {"ok": True, "echo": payload}
            raise ValueError("bad command")

    request_bytes = b"".join(
        [
            encode_message(make_request("ping", {"a": 1}, req_id="r1")),
            encode_message(make_request("boom", {}, req_id="r2")),
        ]
    )

    handler = SourceRequestHandler.__new__(SourceRequestHandler)
    handler.server = FakeServer()
    handler.rfile = BytesIO(request_bytes)
    handler.wfile = BytesIO()

    handler.handle()

    messages = _decode_framed(handler.wfile)
    assert messages[0]["ok"] is True
    assert messages[0]["req_id"] == "r1"
    assert messages[0]["result"] == {"ok": True, "echo": {"a": 1}}
    assert messages[1]["ok"] is False
    assert messages[1]["req_id"] == "r2"
    assert messages[1]["error"]["type"] == "ValueError"


def test_source_request_handler_protocol_error_has_no_req_id() -> None:
    bad_envelope = encode_message({"v": 1, "payload": {}})

    class FakeServer:
        def dispatch(self, cmd: str, payload: dict):
            raise AssertionError((cmd, payload))

    handler = SourceRequestHandler.__new__(SourceRequestHandler)
    handler.server = FakeServer()
    handler.rfile = BytesIO(bad_envelope)
    handler.wfile = BytesIO()

    handler.handle()
    messages = _decode_framed(handler.wfile)

    assert messages[0]["ok"] is False
    assert messages[0]["req_id"] is None
    assert messages[0]["error"]["type"] == "ProtocolError"


def test_source_admin_server_constructor_sets_runner(monkeypatch) -> None:
    init_args: dict[str, object] = {}

    def _fake_init(self, server_address, request_handler):
        init_args["server_address"] = server_address
        init_args["request_handler"] = request_handler

    monkeypatch.setattr(socketserver.ThreadingTCPServer, "__init__", _fake_init)

    runner = object()
    server = SourceAdminTCPServer("127.0.0.1", 8766, runner)

    assert init_args["server_address"] == ("127.0.0.1", 8766)
    assert init_args["request_handler"] is admin_server_module.SourceRequestHandler
    assert server.runner is runner
