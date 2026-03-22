from __future__ import annotations

from typing import Any

from .validation import validate_empty_ok


def register_general_handlers(server: Any) -> None:
    d = server.dispatcher
    d.register("ping", _cmd_ping)
    d.register("stats", server.api_stats)
    d.register("snapshot", server.api_snapshot)
    d.register("describe", server.api_describe)
    d.register("list_parameters", server.api_list_parameters)



def _cmd_ping(payload: dict[str, Any]) -> str:
    validate_empty_ok(payload)
    return "pong"
