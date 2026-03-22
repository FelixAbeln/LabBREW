from __future__ import annotations

import threading
from typing import Any

from .models import StepAction

try:
    from ...parameterDB.parameterdb_core.client import SignalSession
except Exception:  # pragma: no cover
    SignalSession = None  # type: ignore


class SignalStoreBackend:
    """Thin adapter around SignalStore / ParameterDB.

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

    def apply_action(self, action: StepAction, *, stepped_value: Any | None = None) -> bool:
        value = action.value if stepped_value is None else stepped_value
        return self.set_value(action.target_key, value)

    def snapshot(self, names: list[str]) -> dict[str, Any]:
        return {name: self.get_value(name) for name in names}
