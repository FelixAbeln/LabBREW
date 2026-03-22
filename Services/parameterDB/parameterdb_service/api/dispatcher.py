from __future__ import annotations

from typing import Any, Callable

from ...parameterdb_core.errors import CommandError


Handler = Callable[[dict[str, Any]], Any]
StreamingHandler = Callable[..., None]


class CommandDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}
        self._streaming_handlers: dict[str, StreamingHandler] = {}

    def register(self, cmd: str, handler: Handler) -> None:
        if not isinstance(cmd, str) or not cmd.strip():
            raise ValueError("Command must be a non-empty string")
        self._handlers[cmd] = handler

    def register_streaming(self, cmd: str, handler: StreamingHandler) -> None:
        if not isinstance(cmd, str) or not cmd.strip():
            raise ValueError("Command must be a non-empty string")
        self._streaming_handlers[cmd] = handler

    def dispatch(self, cmd: str, payload: dict[str, Any]) -> Any:
        handler = self._handlers.get(cmd)
        if handler is None:
            raise CommandError(f"Unknown command: {cmd}")
        return handler(payload)

    def get_streaming_handler(self, cmd: str) -> StreamingHandler | None:
        return self._streaming_handlers.get(cmd)

    def list_commands(self) -> list[str]:
        return sorted(set(self._handlers) | set(self._streaming_handlers))
