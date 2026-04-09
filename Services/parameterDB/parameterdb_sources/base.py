from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Event
from typing import Any

from ..parameterdb_core.client import SupportsSignalRequests


class DataSourceBase(ABC):
    source_type = "base"
    display_name = "Base Data Source"
    description = "Base external data source"

    def __init__(
        self,
        name: str,
        client: SupportsSignalRequests,
        *,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.client = client
        self.config = dict(config or {})
        self._stop_event = Event()

    def stop(self) -> None:
        self._stop_event.set()

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def sleep(self, seconds: float) -> bool:
        return self._stop_event.wait(seconds)

    def build_owned_metadata(self, **extra: Any) -> dict[str, Any]:
        data = {
            "owner": self.name,
            "source_type": self.source_type,
            "created_by": "data_source",
        }
        data.update(extra)
        return data

    def ensure_parameter(
        self,
        name: str,
        parameter_type: str = "static",
        *,
        value: Any = None,
        config: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        config_payload = config or {}
        metadata_payload = metadata or self.build_owned_metadata()
        try:
            self.client.create_parameter(
                name,
                parameter_type,
                value=value,
                config=config_payload,
                metadata=metadata_payload,
            )
        except Exception:
                # Existing parameters still need datasource ownership/config
                # metadata repaired so UI features can discover published params
                # and source-generated controls.
            try:
                if config_payload:
                    self.client.update_config(name, **config_payload)
                if metadata_payload:
                    self.client.update_metadata(name, **metadata_payload)
            except Exception:
                    # Parameter already exists or service unavailable;
                    # keep startup tolerant.
                pass

    @abstractmethod
    def ensure_parameters(self) -> None:
        """Create or verify the parameters managed by this source."""

    def start(self) -> None:
        self.ensure_parameters()

    @abstractmethod
    def run(self) -> None:
        """Main loop for the source. Should return when should_stop() becomes True."""


class DataSourceSpec(ABC):
    source_type = "base"
    display_name = "Base Data Source"
    description = "Base external data source"

    @abstractmethod
    def create(
        self,
        name: str,
        client: SupportsSignalRequests,
        *,
        config: dict[str, Any] | None = None,
    ) -> DataSourceBase:
        raise NotImplementedError

    def default_config(self) -> dict[str, Any]:
        return {}
