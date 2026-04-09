from __future__ import annotations

from io import BytesIO
from typing import Any

import Services.parameterDB.parameterdb_service.server as server_module
from Services.parameterDB.parameterdb_core.errors import ProtocolError
from Services.parameterDB.parameterdb_core.protocol import (
    decode_message_bytes,
    encode_message,
    make_request,
)
from Services.parameterDB.parameterdb_service.engine import ScanEngine
from Services.parameterDB.parameterdb_service.event_broker import EventBroker
from Services.parameterDB.parameterdb_service.plugin_api import (
    ParameterBase,
    PluginSpec,
)
from Services.parameterDB.parameterdb_service.server import (
    RequestHandler,
    SignalTCPServer,
)
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

    def on_added(self, _store: ParameterStore) -> None:
        self.added = True

    def on_removed(self, _store: ParameterStore) -> None:
        self.removed = True

    def scan(self, _ctx) -> None:
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


class FakeSnapshotManager:
    def __init__(self) -> None:
        self.saved_force_flags: list[bool] = []

    def save_now(self, *, force: bool = False) -> bool:
        self.saved_force_flags.append(force)
        return True

    def stats(self) -> dict[str, Any]:
        return {"enabled": True, "path": "snapshot.json"}


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
    server.snapshot_manager = FakeSnapshotManager()
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

    def _fake_load(_folder, registry):
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

    def _subscribe(_names, max_queue=1000):
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

        def dispatch(self, _cmd, _payload):
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

        def dispatch(self, _cmd, _payload):
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


def test_request_handler_success_response_and_streaming_handler_path() -> None:
    normal_request = encode_message(make_request("snapshot", payload={}, req_id="r1"))

    class NormalServer:
        def __init__(self):
            self.audit_log = FakeAudit()
            self.dispatcher = FakeDispatcher()

        def dispatch(self, cmd, payload):
            assert cmd == "snapshot"
            assert payload == {}
            return {"ok": "value"}

    normal_handler = RequestHandler.__new__(RequestHandler)
    normal_handler.server = NormalServer()
    normal_handler.client_address = ("127.0.0.1", 9999)
    normal_handler.rfile = BytesIO(normal_request)
    normal_handler.wfile = BytesIO()

    normal_handler.handle()

    responses = _decode_framed_messages(normal_handler.wfile)
    assert responses == [{"v": 1, "req_id": "r1", "ok": True, "result": {"ok": "value"}, "error": None}]

    streamed: dict[str, Any] = {}

    def streaming_handler(handler, *, req_id, payload):
        streamed["req_id"] = req_id
        streamed["payload"] = payload
        handler.wfile.write(encode_message({"event": "streamed"}))

    stream_request = encode_message(make_request("subscribe", payload={"names": []}, req_id="r2"))

    class StreamingServer:
        def __init__(self):
            self.audit_log = FakeAudit()
            self.dispatcher = FakeDispatcher(streaming_handler=streaming_handler)

        def dispatch(self, _cmd, _payload):
            raise AssertionError("dispatch should not be called for streaming handler")

    streaming = RequestHandler.__new__(RequestHandler)
    streaming.server = StreamingServer()
    streaming.client_address = ("127.0.0.1", 1000)
    streaming.rfile = BytesIO(stream_request)
    streaming.wfile = BytesIO()

    streaming.handle()

    assert streamed == {"req_id": "r2", "payload": {"names": []}}
    assert _decode_framed_messages(streaming.wfile) == [{"event": "streamed"}]


def test_signal_tcp_server_constructor_wires_dispatcher_and_audit(monkeypatch) -> None:
    init_args: dict[str, Any] = {}
    registered: list[SignalTCPServer] = []

    def fake_tcp_init(_self, addr, handler_cls):
        init_args["addr"] = addr
        init_args["handler_cls"] = handler_cls

    class FakeAuditLogger:
        def __init__(self, path: str, enabled: bool):
            self.path = path
            self.enabled = enabled

    class FakeCommandDispatcher:
        def dispatch(self, cmd: str, payload: dict[str, Any]) -> dict[str, Any]:
            return {"cmd": cmd, "payload": payload}

    def fake_register(server: SignalTCPServer) -> None:
        registered.append(server)

    monkeypatch.setattr(server_module.socketserver.ThreadingTCPServer, "__init__", fake_tcp_init)
    monkeypatch.setattr(server_module, "AuditLogger", FakeAuditLogger)
    monkeypatch.setattr(server_module, "CommandDispatcher", FakeCommandDispatcher)
    monkeypatch.setattr(server_module, "register_all_handlers", fake_register)

    engine = ScanEngine(period_s=0.01, store=ParameterStore())
    registry = FakeRegistry()
    broker = FakeBroker()

    server = SignalTCPServer("127.0.0.1", 4321, engine, registry, broker)

    assert init_args == {"addr": ("127.0.0.1", 4321), "handler_cls": RequestHandler}
    assert server.engine is engine
    assert server.registry is registry
    assert server.event_broker is broker
    assert isinstance(server.audit_log, FakeAuditLogger)
    assert isinstance(server.dispatcher, FakeCommandDispatcher)
    assert registered == [server]
    assert server.dispatch("cmd", {"x": 1}) == {"cmd": "cmd", "payload": {"x": 1}}


def test_signal_tcp_server_dispatch_and_general_read_handlers() -> None:
    server = _build_server()
    server.engine.store.add(FakeParam("alpha", value=3, metadata={"m": 1}))

    server.dispatcher = type("Dispatch", (), {"dispatch": lambda _self, cmd, payload: {"cmd": cmd, "payload": payload}})()

    assert server.dispatch("hello", {"x": 1}) == {"cmd": "hello", "payload": {"x": 1}}
    assert server.api_snapshot({}) == {"alpha": 3}
    described = server.api_describe({})
    assert "alpha" in described
    assert server.api_list_parameters({}) == ["alpha"]
    graph = server.api_graph_info({})
    assert "scan_order" in graph
    assert server.api_get_value({"name": "alpha", "default": 9}) == 3


def test_signal_tcp_server_mutation_handlers_and_audit_logging(monkeypatch) -> None:
    _ = monkeypatch
    server = _build_server()
    server.engine.store.add(FakeParam("alpha", value=1, config={"unit": "C"}, metadata={"owner": "x"}))

    server.audit_log.audit_external_writes = True
    assert server.api_set_value({"name": "alpha", "value": 8}) is True
    assert server.engine.store.get_value("alpha") == 8
    assert any(entry.get("action") == "value_written" for entry in server.audit_log.entries)

    assert server.api_update_config({"name": "alpha", "changes": {"unit": "degC", "hz": 2}}) is True
    assert server.api_update_metadata({"name": "alpha", "changes": {"owner": "pytest"}}) is True
    assert any(entry.get("action") == "config_updated" and entry.get("changed_keys") == ["hz", "unit"] for entry in server.audit_log.entries)
    assert any(entry.get("action") == "metadata_updated" and entry.get("changed_keys") == ["owner"] for entry in server.audit_log.entries)

    assert server.api_delete_parameter({"name": "missing"}) is True


def test_signal_tcp_server_snapshot_export_and_import_handlers() -> None:
    server = _build_server()
    server.engine.store.add(FakeParam("alpha", value=1, metadata={"m": 1}))

    exported = server.api_export_snapshot({})
    assert exported["snapshot"]["format_version"] == 1
    assert exported["snapshot"]["parameters"]["alpha"]["value"] == 1
    assert exported["snapshot_stats"]["path"] == "snapshot.json"

    imported = server.api_import_snapshot({
        "snapshot": {
            "format_version": 1,
            "parameters": {
                "beta": {
                    "parameter_type": "fake",
                    "value": 5,
                    "config": {"unit": "C"},
                    "state": {"ready": True},
                    "metadata": {"owner": "import"},
                }
            },
        },
        "replace_existing": True,
        "save_to_disk": True,
    })

    assert imported["ok"] is True
    assert imported["removed_count"] == 1
    assert imported["restored_count"] == 1
    assert server.engine.store.get_value("alpha", default="missing") == "missing"
    assert server.engine.store.get_value("beta") == 5
    assert server.snapshot_manager.saved_force_flags == [True]
    assert any(entry.get("action") == "snapshot_imported" for entry in server.audit_log.entries)


def test_signal_tcp_server_snapshot_handlers_without_snapshot_manager() -> None:
    server = _build_server()
    server.snapshot_manager = None

    exported = server.api_export_snapshot({})
    imported = server.api_import_snapshot({
        "snapshot": {
            "format_version": 1,
            "parameters": {
                "gamma": {
                    "parameter_type": "fake",
                    "value": 9,
                    "config": {},
                    "metadata": {},
                }
            },
        },
        "replace_existing": False,
        "save_to_disk": True,
    })

    assert exported["snapshot_stats"] is None
    assert imported["snapshot_stats"] is None
    assert imported["restored_count"] == 1
    assert server.engine.store.get_value("gamma") == 9


def test_signal_tcp_server_snapshot_import_restarts_running_engine() -> None:
    server = _build_server()
    lifecycle_calls: list[str] = []

    server.engine.stats = lambda: {"running": True}  # type: ignore[method-assign]
    server.engine.stop = lambda: lifecycle_calls.append("stop")  # type: ignore[method-assign]
    server.engine.start = lambda: lifecycle_calls.append("start")  # type: ignore[method-assign]

    imported = server.api_import_snapshot({
        "snapshot": {
            "format_version": 1,
            "parameters": {
                "delta": {
                    "parameter_type": "fake",
                    "value": 11,
                    "config": {},
                    "metadata": {},
                }
            },
        },
        "replace_existing": False,
        "save_to_disk": False,
    })

    assert imported["restored_count"] == 1
    assert lifecycle_calls == ["stop", "start"]


def test_api_subscribe_filters_initial_and_stream_events() -> None:
    server = _build_server()
    server.engine.store.add(FakeParam("a", value=1))
    server.engine.store.add(FakeParam("b", value=2))

    def _subscribe(_names, max_queue=1000):
        return "token-2", FakeQueue([
            {"event": "value_changed", "name": "b", "value": 99},
            {"event": "subscription_overflow", "dropped": 3},
        ]), max_queue

    server.event_broker.subscribe = _subscribe  # type: ignore[assignment]

    class FakeRequestHandler:
        def __init__(self):
            self.wfile = BytesIO()

    handler = FakeRequestHandler()
    server.api_subscribe(handler, req_id="req-2", payload={"names": ["a"], "send_initial": True, "max_queue": 5})  # type: ignore[arg-type]

    messages = _decode_framed_messages(handler.wfile)
    assert messages[0]["result"]["subscription_id"] == "token-2"
    assert any(item.get("event") == "parameter_snapshot" and item.get("name") == "a" for item in messages)
    assert not any(item.get("event") == "parameter_snapshot" and item.get("name") == "b" for item in messages)
    assert any(item.get("event") == "subscription_overflow" for item in messages)
    assert not any(item.get("event") == "value_changed" and item.get("name") == "b" for item in messages)
