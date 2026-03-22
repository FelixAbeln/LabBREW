from __future__ import annotations

from pathlib import Path
from typing import Any

from .validation import validate_empty_ok, validate_get_parameter_type_ui, validate_load_parameter_type_folder


def register_plugin_handlers(server: Any) -> None:
    d = server.dispatcher
    d.register("list_parameter_types", server.api_list_parameter_types)
    d.register("list_parameter_type_ui", server.api_list_parameter_type_ui)
    d.register("get_parameter_type_ui", server.api_get_parameter_type_ui)
    d.register("load_parameter_type_folder", server.api_load_parameter_type_folder)
