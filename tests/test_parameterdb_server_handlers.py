from __future__ import annotations

from io import BytesIO
from typing import Any

import pytest

from Services.parameterDB.parameterdb_core.errors import ProtocolError
from Services.parameterDB.parameterdb_core.protocol import (
    decode_message_bytes,
    encode_message,
    make_request,
)
from Services.parameterDB.parameterdb_service.engine import ScanEngine
from Services.parameterDB.parameterdb_service.event_broker import EventBroker
from Services.parameterDB.parameterdb_service.plugin_api import ParameterBase, PluginSpec
from Services.parameterDB.parameterdb_service.server import RequestHandler, SignalTCPServer
from Services.parameterDB.parameterdb_service.store import ParameterStore


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self.audit_external_writes = False

    def log(self, **entry: Any) -> None:
        self.entries.append(dict(entry))


class FakeParam(ParameterBase):
    parameter_type = "fake"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.added = False
        self.removed = False

    def on_added(self, store: ParameterStore) -> None:
        self.added = True

    def on_removed(self, store: ParameterStore) -> None:
        self.removed = True

    def scan(self, ctx) -> None:
        return None


class FakeSpec(PluginSpec):
    parameter_type = "fake"

    def create(self, name: str, *, config: dict[str, Any] | None = None, value: Any = None, metadata: dict[str, Any] | None = None) -> ParameterBase:
        return FakeParam(name, config=config, value=value, metadata=metadata)


class FakeRegistry:
    def __init__(self) -> None:
        self.spec = FakeSpec()

    def get(self, parameter_type: str) -> FakeSpec:
        if parameter_type != "fake":
            raise ValueError("unknown")
        return self.spec

    def list_types(self) -> dict[str, dict[str, Any]]:
        return {"fake": {"display_name": "Fake"}}

    def list_ui(self) -> dict[str, dict[str, Any]]:
        return {"fake": {"parameter_type": "fake", "display_name": "Fake", "description": "Fake"}}

    def get_ui_spec(self, parameter_type: str) -> dict[str, Any]:
        if parameter_type != "fake":
            raise ValueError("unknown")
        return {"parameter_type": "fake", "controls": []}


class FakeQueue:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = list(events)

    def get(self) -> dict[str, Any]:
        if self.events:
            return self.events.pop(0)
        raise BrokenPipeError("done")


class FakeBroker(EventBroker):
    def __init__(self) -> None:
        super().__init__()
        self.unsubscribed: list[str] = []

    def unsubscribe(self, token: str) -> None:
        self.unsubscribed.append(token)
        super().unsubscribe(token)


class FakeDispatcher:
    def __init__(self, streaming_handler=None) -> None:
        self.streaming_handler = streaming_handler

    def get_streaming_handler(self, cmd: str):
        if cmd == "subscribe":
            return self.streaming_handler
        return None


def _build_server() -> SignalTCPServer:
    server = SignalTCPServer.__new__(SignalTCPServer)
    server.engine = ScanEngine(period_s=0.01, store=ParameterStore())
    server.registry = FakeRegistry()
    server.event_broker = FakeBroker()
    server.audit_log = FakeAudit()
    server.dispatcher = FakeDispatcher()
    return server


def _decode_framed_messages(stream: BytesIO) -> list[dict[str, Any]]:
    data = stream.getvalue()
    out: list[dict[str, Any]] = []
    index = 0
    while index + 4 <= len(data):
        size = int.from_bytes(data[index:index + 4], byteorder="big")
        index += 4
        body = data[index:index + size]
        index += size
        out.append(decode_message_bytes(body))
    return out



def test_api_create_update_delete_parameter_roundtrip() -> None:
    server = _build_server()

    created = server.api_create_parameter(
        {
            "name": "reactor.temp",
            "parameter_type": "fake",
            "value": 20.0,
            "config": {"unit": "C"},
            "metadata": {"source": "test"},
        }
    )
    written = server.api_set_value({"name": "reactor.temp", "value": 21.5})
    config_updated = server.api_update_config({"name": "reactor.temp", "changes": {"unit": "degC"}})
    metadata_updated = server.api_update_metadata({"name": "reactor.temp", "changes": {"operator": "pytest"}})
    deleted = server.api_delete_parameter({"name": "reactor.temp"})

    assert created is True
    assert written is True
    assert config_updated is True
    assert metadata_updated is True
    assert deleted is True
    assert server.engine.store.get_value("reactor.temp", default="missing") == "missing"



def test_api_stats_and_plugin_listing_handlers() -> None:
    server = _build_server()

    stats = server.api_stats({})
    listed = server.api_list_parameter_types({})
    listed_ui = server.api_list_parameter_type_ui({})
    one_ui = server.api_get_parameter_type_ui({"parameter_type": "fake"})

    assert "subscriber_count" in stats
    assert listed == {"fake": {"display_name": "Fake"}}
    assert "fake" in listed_ui
    assert one_ui["parameter_type"] == "fake"



def test_api_load_parameter_type_folder_logs_change(monkeypatch, tmp_path) -> None:
    server = _build_server()

    def _fake_load(folder, registry):
        assert registry is server.registry
        return "loaded.type"

    import Services.parameterDB.parameterdb_service.server as server_module

    monkeypatch.setattr(server_module, "load_parameter_type_folder", _fake_load)

    result = server.api_load_parameter_type_folder({"folder": str(tmp_path)})

    assert result == "loaded.type"
    assert any(entry.get("action") == "parameter_type_folder_loaded" for entry in server.audit_log.entries)



def test_api_subscribe_sends_initial_and_event_then_unsubscribes() -> None:
    server = _build_server()
    server.engine.store.add(FakeParam("a", value=1))

    broker = server.event_broker

    def _subscribe(names, max_queue=1000):
        return "token-1", FakeQueue([{"event": "value_changed", "name": "a", "value": 2}]), max_queue

    broker.subscribe = _subscribe  # type: ignore[assignment]

    class FakeRequestHandler:
        def __init__(self):
            self.wfile = BytesIO()

    handler = FakeRequestHandler()

    server.api_subscribe(
        handler,  # type: ignore[arg-type]
        req_id="req-1",
        payload={"names": ["a"], "send_initial": True, "max_queue": 10},
    )

    messages = _decode_framed_messages(handler.wfile)

    assert messages[0]["ok"] is True
    assert messages[0]["result"]["status"] == "subscribed"
    assert any(item.get("event") == "parameter_snapshot" for item in messages)
    assert any(item.get("event") == "value_changed" for item in messages)
    assert broker.unsubscribed == ["token-1"]



def test_request_handler_returns_error_envelope_on_dispatch_exception() -> None:
    req_bytes = encode_message(make_request("set_value", payload={"name": "x", "value": 1}, req_id="r1"))

    class FakeServer:
        def __init__(self):
            self.audit_log = FakeAudit()
            self.dispatcher = FakeDispatcher()

        def dispatch(self, cmd, payload):
            raise RuntimeError("boom")

    handler = RequestHandler.__new__(RequestHandler)
    handler.server = FakeServer()
    handler.client_address = ("127.0.0.1", 1234)
    handler.rfile = BytesIO(req_bytes)
    handler.wfile = BytesIO()

    handler.handle()

    responses = _decode_framed_messages(handler.wfile)

    assert len(responses) == 1
    assert responses[0]["ok"] is False
    assert responses[0]["error"]["type"] == "RuntimeError"
    assert responses[0]["error"]["message"] == "boom"



def test_request_handler_handles_bad_envelope_as_protocol_error() -> None:
    bad_request = encode_message({"v": 1, "req_id": "r1", "payload": {}})

    class FakeServer:
        def __init__(self):
            self.audit_log = FakeAudit()
            self.dispatcher = FakeDispatcher()

        def dispatch(self, cmd, payload):
            raise AssertionError("dispatch should not be called")

    handler = RequestHandler.__new__(RequestHandler)
    handler.server = FakeServer()
    handler.client_address = ("127.0.0.1", 5678)
    handler.rfile = BytesIO(bad_request)
    handler.wfile = BytesIO()

    handler.handle()

    responses = _decode_framed_messages(handler.wfile)
    assert responses[0]["ok"] is False
    assert responses[0]["error"]["type"] == ProtocolError.__name__
