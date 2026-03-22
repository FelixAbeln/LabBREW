from __future__ import annotations

from typing import Any

from .validation import validate_subscribe


def register_streaming_handlers(server: Any) -> None:
    server.dispatcher.register_streaming("subscribe", server.api_subscribe)
