from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from typing import Any

import pytest
import requests

from Services.parameterDB.parameterdb_core.client import SignalClient


class IntegrationApi:
    def __init__(self, *, base_url: str, timeout_s: float = 6.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def get(self, path: str) -> dict[str, Any]:
        response = requests.get(f"{self.base_url}{path}", timeout=self.timeout_s)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        response = requests.post(f"{self.base_url}{path}", json=(payload or {}), timeout=self.timeout_s)
        response.raise_for_status()
        return response.json()

    def put(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.put(f"{self.base_url}{path}", json=payload, timeout=self.timeout_s)
        response.raise_for_status()
        return response.json()

    def delete(self, path: str) -> dict[str, Any]:
        response = requests.delete(f"{self.base_url}{path}", timeout=self.timeout_s)
        response.raise_for_status()
        return response.json()


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def skip_if_unreachable(url: str, path: str) -> None:
    try:
        response = requests.get(f"{url.rstrip('/')}{path}", timeout=2.0)
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover - depends on local services
        pytest.skip(f"Service not reachable: {url}{path} ({exc})")


def skip_if_parameterdb_unreachable(host: str = "127.0.0.1", port: int = 8765) -> None:
    try:
        with SignalClient(host, port, timeout=2.0).session() as session:
            session.ping()
    except Exception as exc:  # pragma: no cover - depends on local services
        pytest.skip(f"ParameterDB not reachable on {host}:{port} ({exc})")


@contextmanager
def managed_test_parameters(
    parameters: list[dict[str, Any]],
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> Iterator[list[str]]:
    created: list[str] = []

    with SignalClient(host, port, timeout=3.0).session() as session:
        for parameter in parameters:
            name = str(parameter["name"])
            parameter_type = str(parameter.get("parameter_type", "static"))
            value = parameter.get("value")
            config = dict(parameter.get("config") or {})
            metadata = dict(parameter.get("metadata") or {})

            with suppress(Exception):
                session.delete_parameter(name)

            session.create_parameter(
                name,
                parameter_type,
                value=value,
                config=config,
                metadata=metadata,
            )
            created.append(name)

        try:
            yield created
        finally:
            for name in reversed(created):
                with suppress(Exception):
                    session.delete_parameter(name)


def wait_until(
    predicate: Callable[[], Any],
    *,
    timeout_s: float,
    label: str,
    sleep_s: float = 0.2,
) -> Any:
    deadline = time.time() + timeout_s
    last_value: Any = None

    while time.time() < deadline:
        last_value = predicate()
        if last_value:
            return last_value
        time.sleep(sleep_s)

    raise AssertionError(f"Timeout waiting for {label}. Last value: {last_value}")
