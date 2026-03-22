from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ParameterRecord:
    name: str
    parameter_type: str
    config: dict[str, Any] = field(default_factory=dict)
    value: Any = None
    state: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class ParameterBase(ABC):
    parameter_type = 'base'
    display_name = 'Base Parameter'
    description = 'Base parameter'

    def __init__(self, name: str, *, config: dict[str, Any] | None = None, value: Any = None, metadata: dict[str, Any] | None = None) -> None:
        self.name = name
        self.config = dict(config or {})
        self.value = value
        self.state: dict[str, Any] = {}
        self.metadata = dict(metadata or {})

    def on_added(self, store: 'ParameterStore') -> None:
        pass

    def on_removed(self, store: 'ParameterStore') -> None:
        pass

    def set_value(self, value: Any) -> None:
        self.value = value

    def get_value(self) -> Any:
        return self.value

    def dependencies(self) -> list[str]:
        """Parameters this object reads from during scan()."""
        return []

    def write_targets(self) -> list[str]:
        """Parameters this object may write to during scan()."""
        return []

    @abstractmethod
    def scan(self, ctx: 'ScanContext') -> None:
        raise NotImplementedError

    def update_config(self, **changes: Any) -> None:
        self.config.update(changes)

    def to_record(self) -> ParameterRecord:
        return ParameterRecord(
            name=self.name,
            parameter_type=self.parameter_type,
            config=dict(self.config),
            value=self.value,
            state=dict(self.state),
            metadata=dict(self.metadata),
        )


class PluginSpec(ABC):
    parameter_type = 'base'
    display_name = 'Base Parameter'
    description = 'Base plugin'

    @abstractmethod
    def create(self, name: str, *, config: dict[str, Any] | None = None, value: Any = None, metadata: dict[str, Any] | None = None) -> ParameterBase:
        raise NotImplementedError

    def default_config(self) -> dict[str, Any]:
        return {}

    def schema(self) -> dict[str, Any]:
        return {}
