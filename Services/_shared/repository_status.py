from __future__ import annotations

import time
from typing import Any


class RepositoryStatusMixin:
    def __init__(self) -> None:
        self._last_save_ok: bool | None = None
        self._last_success_at: float | None = None
        self._last_error: str | None = None
        self._last_error_at: float | None = None

    def _record_success(self, *, save_ok: bool | None = None) -> None:
        self._last_success_at = time.time()
        if save_ok is not None:
            self._last_save_ok = save_ok
        self._last_error = None
        self._last_error_at = None

    def _record_failure(self, exc: Exception, *, save_ok: bool | None = None) -> None:
        if save_ok is not None:
            self._last_save_ok = save_ok
        self._last_error = str(exc)
        self._last_error_at = time.time()

    def _status_fields(self) -> dict[str, Any]:
        return {
            "available": self._last_error is None,
            "healthy": self._last_error is None,
            "last_save_ok": self._last_save_ok,
            "last_success_at": self._last_success_at,
            "last_error": self._last_error,
            "last_error_at": self._last_error_at,
        }