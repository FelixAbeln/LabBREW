from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from typing import Any, Protocol

from .protocol import (
    encode_message,
    make_request,
    read_message,
    validate_response_envelope,
)


class SupportsSignalRequests(Protocol):
    def ping(self) -> str: ...
    def stats(self) -> dict[str, Any]: ...
    def graph_info(self) -> dict[str, Any]: ...
    def snapshot(self) -> dict[str, Any]: ...
    def export_snapshot(self) -> dict[str, Any]: ...
    def import_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        replace_existing: bool = True,
        save_to_disk: bool = True,
    ) -> dict[str, Any]: ...
    def describe(self) -> dict[str, Any]: ...
    def list_parameters(self) -> list[str]: ...
    def list_parameter_types(self) -> dict[str, Any]: ...
    def list_parameter_type_ui(self) -> dict[str, Any]: ...
    def get_parameter_type_ui(self, parameter_type: str) -> dict[str, Any]: ...
    def create_parameter(
        self,
        name: str,
        parameter_type: str,
        *,
        value: Any = None,
        config: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool: ...
    def delete_parameter(self, name: str) -> bool: ...
    def get_value(self, name: str, default: Any = None) -> Any: ...
    def set_value(self, name: str, value: Any) -> bool: ...
    def update_config(self, name: str, **changes: Any) -> bool: ...
    def update_metadata(self, name: str, **changes: Any) -> bool: ...
    def load_parameter_type_folder(self, folder: str) -> str: ...
    def subscribe(
        self,
        names: list[str] | None = None,
        send_initial: bool = True,
        max_queue: int = 1000,
    ) -> Subscription: ...


class Subscription:
    def __init__(
        self,
        host: str,
        port: int,
        timeout: float,
        names: list[str] | None = None,
        send_initial: bool = True,
        max_queue: int = 1000,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.names = names or []
        self.send_initial = send_initial
        self.max_queue = max(1, int(max_queue))
        self.sock: socket.socket | None = None
        self.file = None
        self.subscription_info: dict[str, Any] | None = None

    def __enter__(self) -> Subscription:
        self.sock = socket.create_connection(
            (self.host, self.port), timeout=self.timeout
        )
        self.file = self.sock.makefile("rb")
        self.sock.sendall(
            encode_message(
                make_request(
                    "subscribe",
                    {
                        "names": self.names,
                        "send_initial": self.send_initial,
                        "max_queue": self.max_queue,
                    },
                )
            )
        )
        ack = read_message(self.file)
        if ack is None:
            raise RuntimeError("No subscribe response from server")
        ok, _req_id, result, error = validate_response_envelope(ack)
        if not ok:
            raise RuntimeError((error or {}).get("message", "Subscribe failed"))
        self.subscription_info = (
            result if isinstance(result, dict) else {"status": result}
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self.file:
                self.file.close()
        finally:
            if self.sock:
                self.sock.close()
        self.file = None
        self.sock = None

    def __iter__(self) -> Iterator[dict[str, Any]]:
        while True:
            if self.file is None:
                break
            msg = read_message(self.file)
            if msg is None:
                break
            yield msg


class _BaseClient:
    def __init__(
        self, host: str = "127.0.0.1", port: int = 8765, timeout: float = 2.0
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def _request(self, cmd: str, payload: dict[str, Any] | None = None) -> Any:
        raise NotImplementedError

    def subscribe(
        self,
        names: list[str] | None = None,
        send_initial: bool = True,
        max_queue: int = 1000,
    ) -> Subscription:
        return Subscription(
            self.host,
            self.port,
            self.timeout,
            names=names,
            send_initial=send_initial,
            max_queue=max_queue,
        )

    def ping(self) -> str:
        return self._request("ping")

    def stats(self) -> dict[str, Any]:
        return self._request("stats")

    def graph_info(self) -> dict[str, Any]:
        return self._request("graph_info")

    def snapshot(self) -> dict[str, Any]:
        return self._request("snapshot")

    def export_snapshot(self) -> dict[str, Any]:
        return self._request("export_snapshot")

    def import_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        replace_existing: bool = True,
        save_to_disk: bool = True,
    ) -> dict[str, Any]:
        return self._request(
            "import_snapshot",
            {
                "snapshot": snapshot,
                "replace_existing": replace_existing,
                "save_to_disk": save_to_disk,
            },
        )

    def describe(self) -> dict[str, Any]:
        return self._request("describe")

    def list_parameters(self) -> list[str]:
        return self._request("list_parameters")

    def list_parameter_types(self) -> dict[str, Any]:
        return self._request("list_parameter_types")

    def list_parameter_type_ui(self) -> dict[str, Any]:
        return self._request("list_parameter_type_ui")

    def get_parameter_type_ui(self, parameter_type: str) -> dict[str, Any]:
        return self._request(
            "get_parameter_type_ui", {"parameter_type": parameter_type}
        )

    def list_source_types_ui(self) -> dict[str, Any]:
        return self._request("list_source_types_ui")

    def get_source_type_ui(
        self, source_type: str, *, name: str | None = None, mode: str | None = None
    ) -> dict[str, Any]:
        payload = {"source_type": source_type}
        if name:
            payload["name"] = name
        if mode:
            payload["mode"] = mode
        return self._request("get_source_type_ui", payload)

    def list_sources(self) -> dict[str, Any]:
        return self._request("list_sources")

    def create_source(
        self, name: str, source_type: str, *, config: dict[str, Any] | None = None
    ) -> bool:
        return self._request(
            "create_source",
            {"name": name, "source_type": source_type, "config": config or {}},
        )

    def update_source(self, name: str, *, config: dict[str, Any] | None = None) -> bool:
        return self._request("update_source", {"name": name, "config": config or {}})

    def delete_source(self, name: str) -> bool:
        return self._request("delete_source", {"name": name})

    def create_parameter(
        self,
        name: str,
        parameter_type: str,
        *,
        value: Any = None,
        config: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        return self._request(
            "create_parameter",
            {
                "name": name,
                "parameter_type": parameter_type,
                "value": value,
                "config": config or {},
                "metadata": metadata or {},
            },
        )

    def delete_parameter(self, name: str) -> bool:
        return self._request("delete_parameter", {"name": name})

    def get_value(self, name: str, default: Any = None) -> Any:
        return self._request("get_value", {"name": name, "default": default})

    def set_value(self, name: str, value: Any) -> bool:
        return self._request("set_value", {"name": name, "value": value})

    def update_config(self, name: str, **changes: Any) -> bool:
        return self._request("update_config", {"name": name, "changes": changes})

    def update_metadata(self, name: str, **changes: Any) -> bool:
        return self._request("update_metadata", {"name": name, "changes": changes})

    def load_parameter_type_folder(self, folder: str) -> str:
        return self._request("load_parameter_type_folder", {"folder": folder})


class SignalSession(_BaseClient):
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        timeout: float = 2.0,
        reconnect_attempts: int = 1,
    ) -> None:
        super().__init__(host, port, timeout)
        self.sock: socket.socket | None = None
        self.file = None
        self._lock = threading.RLock()
        self.reconnect_attempts = max(0, int(reconnect_attempts))

    def connect(self) -> SignalSession:
        with self._lock:
            if self.sock is None:
                self.sock = socket.create_connection(
                    (self.host, self.port), timeout=self.timeout
                )
                self.file = self.sock.makefile("rb")
        return self

    def close(self) -> None:
        with self._lock:
            try:
                if self.file is not None:
                    self.file.close()
            finally:
                if self.sock is not None:
                    self.sock.close()
            self.file = None
            self.sock = None

    def __enter__(self) -> SignalSession:
        return self.connect()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _request_once(self, req: dict[str, Any]) -> Any:
        self.connect()
        assert self.sock is not None
        assert self.file is not None
        self.sock.sendall(encode_message(req))
        resp = read_message(self.file)
        if resp is None:
            raise ConnectionError("No response from server")
        ok, _req_id, result, error = validate_response_envelope(resp)
        if not ok:
            if error is None:
                raise RuntimeError("Unknown server error")
            raise RuntimeError(
                f"{error.get('type', 'Error')}: {error.get('message', 'Unknown error')}"
            )
        return result

    def _request(self, cmd: str, payload: dict[str, Any] | None = None) -> Any:
        req = make_request(cmd, payload or {})
        attempts = self.reconnect_attempts + 1
        last_exc: Exception | None = None
        with self._lock:
            for attempt in range(attempts):
                try:
                    return self._request_once(req)
                except (OSError, EOFError, ConnectionError) as exc:
                    last_exc = exc
                    self.close()
                    if attempt + 1 >= attempts:
                        break
            if last_exc is not None:
                raise RuntimeError(
                    f"Request failed after reconnect attempt: {last_exc}"
                ) from last_exc
            raise RuntimeError("Request failed")


class SignalClient(_BaseClient):
    def _request(self, cmd: str, payload: dict[str, Any] | None = None) -> Any:
        req = make_request(cmd, payload or {})
        with socket.create_connection(
            (self.host, self.port), timeout=self.timeout
        ) as sock:
            sock.sendall(encode_message(req))
            resp = read_message(sock.makefile("rb"))
            if resp is None:
                raise RuntimeError("No response from server")
        ok, _req_id, result, error = validate_response_envelope(resp)
        if not ok:
            if error is None:
                raise RuntimeError("Unknown server error")
            raise RuntimeError(
                f"{error.get('type', 'Error')}: {error.get('message', 'Unknown error')}"
            )
        return result

    def session(self, reconnect_attempts: int = 1) -> SignalSession:
        return SignalSession(
            self.host, self.port, self.timeout, reconnect_attempts=reconnect_attempts
        )
