from __future__ import annotations

import threading
from typing import Any


try:
    from ...parameterDB.parameterdb_core.client import SignalSession, SupportsSignalRequests
except Exception:  # pragma: no cover
    SignalSession = None  # type: ignore


class SignalStoreBackend:
    """Thin adapter around arameterDB.

    The runtime sends exact backend parameter names. No UI-side business logic,
    no hidden controller remapping.
    """

    def __init__(self, *, host: str = "127.0.0.1", port: int = 8765, timeout: float = 2.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._lock = threading.RLock()
        self._client = SignalSession(host=host, port=port, timeout=timeout) if SignalSession is not None else None

    def connected(self) -> bool:
        try:
            return bool(self._client and self._client.ping())
        except Exception:
            return False

    def ping(self) -> str:
        if self._client is None:
            return "parameterdb_core not importable"
        return str(self._client.ping())

    def ensure(self, name: str, value: Any) -> bool:
        if self._client is None:
            return False
        try:
            with self._lock:
                result = self._client.set_value(name, value)
            return True if result is None else bool(result)
        except Exception:
            return False

    def ensure_parameter(
        self,
        name: str,
        parameter_type: str = "static",
        *,
        value: Any = None,
        config: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._client.create_parameter(
                name,
                parameter_type,
                value=value,
                config=config or {},
                metadata=metadata or {},
            )
        except Exception:
            # Parameter already exists or service unavailable; keep it tolerant.
            pass

    def get_value(self, name: str, default: Any = None) -> Any:
        if self._client is None:
            return default
        try:
            with self._lock:
                return self._client.get_value(name, default)
        except Exception:
            return default

    def set_value(self, name: str, value: Any) -> bool:
        if self._client is None:
            return False
        try:
            with self._lock:
                result = self._client.set_value(name, value)
            return True if result is None else bool(result)
        except Exception:
            return False

    def snapshot(self, names: list[str]) -> dict[str, Any]:
        return {name: self.get_value(name) for name in names}

    def full_snapshot(self) -> dict[str, Any]:
        if self._client is None:
            return {}
        try:
            with self._lock:
                return dict(self._client.snapshot())
        except Exception:
            return {}

    def describe(self) -> dict[str, Any]:
        if self._client is None:
            return {}
        try:
            with self._lock:
                return dict(self._client.describe())
        except Exception:
            return {}
