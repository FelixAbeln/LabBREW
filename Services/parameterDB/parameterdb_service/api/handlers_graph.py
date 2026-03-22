from __future__ import annotations

from typing import Any

from .validation import validate_empty_ok


def register_graph_handlers(server: Any) -> None:
    server.dispatcher.register("graph_info", server.api_graph_info)
