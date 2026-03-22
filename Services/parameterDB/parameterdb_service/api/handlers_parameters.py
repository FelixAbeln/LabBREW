from __future__ import annotations

from typing import Any


def register_parameter_handlers(server: Any) -> None:
    d = server.dispatcher
    d.register("create_parameter", server.api_create_parameter)
    d.register("delete_parameter", server.api_delete_parameter)
    d.register("get_value", server.api_get_value)
    d.register("set_value", server.api_set_value)
    d.register("update_config", server.api_update_config)
    d.register("update_metadata", server.api_update_metadata)
