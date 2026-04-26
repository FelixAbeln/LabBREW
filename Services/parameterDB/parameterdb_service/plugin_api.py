from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .engine import ScanContext
    from .store import ParameterStore


@dataclass(slots=True)
class ParameterRecord:
    name: str
    parameter_type: str
    config: dict[str, Any] = field(default_factory=dict)
    value: Any = None          # post-pipeline value (what operators and consumers see)
    signal_value: Any = None   # raw plugin output before pipeline transforms
    state: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# Sentinel used in _pipeline_value to indicate that the scan engine has not
# yet processed this parameter.  get_value() falls back to the raw signal
# when this sentinel is present, ensuring the value is always immediately
# readable after a write without bypassing the pipeline.
_PIPELINE_PENDING: object = object()


class ParameterBase(ABC):
    parameter_type = "base"
    display_name = "Base Parameter"
    description = "Base parameter"

    def __init__(
        self,
        name: str,
        *,
        config: dict[str, Any] | None = None,
        value: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.config = dict(config or {})
        # self.value holds the raw signal: what the plugin writes during scan().
        # Plugins continue to write self.value directly or via set_value().
        self.value = value
        # self._pipeline_value holds the post-pipeline output.
        # Set to _PIPELINE_PENDING until the engine processes this parameter.
        # get_value() falls back to the raw signal while pending, so writes
        # are immediately readable without the engine pre-writing the pipeline.
        self._pipeline_value: Any = _PIPELINE_PENDING
        # Monotonic timestamp of the last set_value() call.
        # Used by the engine for datasource silence detection (stale_timeout_s).
        self._last_signal_time: float = time.monotonic()
        self.state: dict[str, Any] = {}
        self.metadata = dict(metadata or {})

    def on_added(self, _store: ParameterStore) -> None:
        return None

    def on_removed(self, _store: ParameterStore) -> None:
        return None

    def set_value(self, value: Any) -> None:
        """Write the raw signal value.  Called by plugins during scan().
        Resets the pipeline to pending so get_value() falls back to this
        signal until the engine applies its pipeline stage."""
        self.value = value
        self._pipeline_value = _PIPELINE_PENDING
        self._last_signal_time = time.monotonic()

    def get_signal_age_s(self) -> float:
        """Return seconds since the last set_value() call (monotonic clock)."""
        return time.monotonic() - self._last_signal_time

    def set_pipeline_value(self, value: Any) -> None:
        """Write the post-pipeline value.  Called exclusively by the scan engine
        after calibration, transducer, and mirror stages have been applied."""
        self._pipeline_value = value

    def get_value(self) -> Any:
        """Return the post-pipeline value — what operators and downstream
        parameters see.  Falls back to the raw signal when the scan engine
        has not yet processed this parameter (pipeline pending)."""
        pv = self._pipeline_value
        return self.value if pv is _PIPELINE_PENDING else pv

    def get_signal_value(self) -> Any:
        """Return the raw signal value written by the plugin during scan()."""
        return self.value

    def dependencies(self) -> list[str]:
        """Parameters this object reads from during scan()."""
        return []

    def write_targets(self) -> list[str]:
        """Parameters this object may write to during scan()."""
        return []

    @abstractmethod
    def scan(self, ctx: ScanContext) -> None:
        raise NotImplementedError

    def update_config(self, **changes: Any) -> None:
        self.config.update(changes)

    def to_record(self) -> ParameterRecord:
        pv = self._pipeline_value
        return ParameterRecord(
            name=self.name,
            parameter_type=self.parameter_type,
            config=dict(self.config),
            value=self.value if pv is _PIPELINE_PENDING else pv,
            signal_value=self.value,
            state=dict(self.state),
            metadata=dict(self.metadata),
        )


class PluginSpec(ABC):
    parameter_type = "base"
    display_name = "Base Parameter"
    description = "Base plugin"

    @abstractmethod
    def create(
        self,
        name: str,
        *,
        config: dict[str, Any] | None = None,
        value: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> ParameterBase:
        raise NotImplementedError

    def default_config(self) -> dict[str, Any]:
        return {}

    def schema(self) -> dict[str, Any]:
        return {}
