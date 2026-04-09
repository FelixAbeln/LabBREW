from __future__ import annotations

import pytest

from Services.parameterDB.parameterdb_core.errors import CommandError, ValidationError
from Services.parameterDB.parameterdb_service.api import register_all_handlers
from Services.parameterDB.parameterdb_service.api.dispatcher import CommandDispatcher
from Services.parameterDB.parameterdb_service.api.handlers_general import (
    _cmd_ping,
    register_general_handlers,
)
from Services.parameterDB.parameterdb_service.api.handlers_graph import (
    register_graph_handlers,
)
from Services.parameterDB.parameterdb_service.api.handlers_parameters import (
    register_parameter_handlers,
)
from Services.parameterDB.parameterdb_service.api.handlers_plugins import (
    register_plugin_handlers,
)
from Services.parameterDB.parameterdb_service.api.handlers_streaming import (
    register_streaming_handlers,
)


class StubServer:
    def __init__(self) -> None:
        self.dispatcher = CommandDispatcher()

    def api_stats(self, payload):
        return {"handler": "stats", "payload": payload}

    def api_snapshot(self, payload):
        return {"handler": "snapshot", "payload": payload}

    def api_export_snapshot(self, payload):
        return {"handler": "export_snapshot", "payload": payload}

    def api_import_snapshot(self, payload):
        return {"handler": "import_snapshot", "payload": payload}

    def api_describe(self, payload):
        return {"handler": "describe", "payload": payload}

    def api_list_parameters(self, payload):
        return {"handler": "list_parameters", "payload": payload}

    def api_graph_info(self, payload):
        return {"handler": "graph_info", "payload": payload}

    def api_create_parameter(self, payload):
        return {"handler": "create_parameter", "payload": payload}

    def api_delete_parameter(self, payload):
        return {"handler": "delete_parameter", "payload": payload}

    def api_get_value(self, payload):
        return {"handler": "get_value", "payload": payload}

    def api_set_value(self, payload):
        return {"handler": "set_value", "payload": payload}

    def api_update_config(self, payload):
        return {"handler": "update_config", "payload": payload}

    def api_update_metadata(self, payload):
        return {"handler": "update_metadata", "payload": payload}

    def api_list_parameter_types(self, payload):
        return {"handler": "list_parameter_types", "payload": payload}

    def api_list_parameter_type_ui(self, payload):
        return {"handler": "list_parameter_type_ui", "payload": payload}

    def api_get_parameter_type_ui(self, payload):
        return {"handler": "get_parameter_type_ui", "payload": payload}

    def api_load_parameter_type_folder(self, payload):
        return {"handler": "load_parameter_type_folder", "payload": payload}

    def api_subscribe(self, _request_handler, *, req_id, payload):
        return {"handler": "subscribe", "req_id": req_id, "payload": payload}



def test_dispatcher_register_dispatch_and_streaming_lookup() -> None:
    dispatcher = CommandDispatcher()

    dispatcher.register("echo", lambda payload: {"ok": True, "payload": payload})
    dispatcher.register_streaming("subscribe", lambda *_args, **_kwargs: None)

    result = dispatcher.dispatch("echo", {"x": 1})

    assert result == {"ok": True, "payload": {"x": 1}}
    assert dispatcher.get_streaming_handler("subscribe") is not None
    assert dispatcher.get_streaming_handler("missing") is None
    assert dispatcher.list_commands() == ["echo", "subscribe"]



def test_dispatcher_rejects_invalid_commands_and_unknown_dispatch() -> None:
    dispatcher = CommandDispatcher()

    with pytest.raises(ValueError):
        dispatcher.register("", lambda _payload: None)

    with pytest.raises(ValueError):
        dispatcher.register_streaming("   ", lambda *_args, **_kwargs: None)

    with pytest.raises(CommandError):
        dispatcher.dispatch("does_not_exist", {})



def test_cmd_ping_requires_object_payload() -> None:
    assert _cmd_ping({}) == "pong"

    with pytest.raises(ValidationError):
        _cmd_ping([])  # type: ignore[arg-type]



def test_register_general_handlers_wires_expected_commands() -> None:
    server = StubServer()

    register_general_handlers(server)

    assert server.dispatcher.dispatch("ping", {}) == "pong"
    assert server.dispatcher.dispatch("stats", {})["handler"] == "stats"
    assert server.dispatcher.dispatch("snapshot", {})["handler"] == "snapshot"
    assert server.dispatcher.dispatch("export_snapshot", {})["handler"] == "export_snapshot"
    assert server.dispatcher.dispatch("import_snapshot", {"snapshot": {}})["handler"] == "import_snapshot"
    assert server.dispatcher.dispatch("describe", {})["handler"] == "describe"
    assert server.dispatcher.dispatch("list_parameters", {})["handler"] == "list_parameters"



def test_register_parameter_handlers_wires_all_parameter_commands() -> None:
    server = StubServer()

    register_parameter_handlers(server)

    for cmd in [
        "create_parameter",
        "delete_parameter",
        "get_value",
        "set_value",
        "update_config",
        "update_metadata",
    ]:
        result = server.dispatcher.dispatch(cmd, {"k": "v"})
        assert result["handler"] == cmd
        assert result["payload"] == {"k": "v"}



def test_register_graph_and_plugin_handlers_wires_commands() -> None:
    server = StubServer()

    register_graph_handlers(server)
    register_plugin_handlers(server)

    assert server.dispatcher.dispatch("graph_info", {})["handler"] == "graph_info"
    assert server.dispatcher.dispatch("list_parameter_types", {})["handler"] == "list_parameter_types"
    assert server.dispatcher.dispatch("list_parameter_type_ui", {})["handler"] == "list_parameter_type_ui"
    assert server.dispatcher.dispatch("get_parameter_type_ui", {})["handler"] == "get_parameter_type_ui"
    assert server.dispatcher.dispatch("load_parameter_type_folder", {})["handler"] == "load_parameter_type_folder"



def test_register_streaming_handlers_and_register_all_handlers() -> None:
    server = StubServer()

    register_streaming_handlers(server)
    streaming_handler = server.dispatcher.get_streaming_handler("subscribe")
    assert callable(streaming_handler)

    server_all = StubServer()
    register_all_handlers(server_all)

    commands = server_all.dispatcher.list_commands()
    assert "ping" in commands
    assert "stats" in commands
    assert "graph_info" in commands
    assert "create_parameter" in commands
    assert "export_snapshot" in commands
    assert "import_snapshot" in commands
    assert "list_parameter_types" in commands
    assert "subscribe" in commands
