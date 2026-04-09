from __future__ import annotations

from typing import Any


def register_streaming_handlers(server: Any) -> None:
    server.dispatcher.register_streaming("subscribe", server.api_subscribe)
