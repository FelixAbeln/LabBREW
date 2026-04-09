from __future__ import annotations

from typing import Any


def register_graph_handlers(server: Any) -> None:
    server.dispatcher.register("graph_info", server.api_graph_info)
