from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from .models import OperatorMetadata


class OperatorPlugin(Protocol):
    metadata: OperatorMetadata

    def evaluate(self, value: Any, params: dict[str, Any]) -> bool:
        ...


@dataclass(slots=True)
class OperatorRegistry:
    _operators: dict[str, OperatorPlugin]

    def __init__(self) -> None:
        self._operators = {}

    def register(self, plugin: OperatorPlugin) -> None:
        name = plugin.metadata.name.strip()
        if not name:
            raise ValueError('Operator name cannot be empty')
        if name in self._operators:
            raise ValueError(f'Operator already registered: {name}')
        self._operators[name] = plugin

    def register_many(self, plugins: Iterable[OperatorPlugin]) -> None:
        for plugin in plugins:
            self.register(plugin)

    def get(self, name: str) -> OperatorPlugin:
        try:
            return self._operators[name]
        except KeyError as exc:
            raise KeyError(f'Unknown operator: {name}') from exc

    def evaluate(self, name: str, value: Any, params: dict[str, Any] | None = None) -> bool:
        return self.get(name).evaluate(value, params or {})

    def list_metadata(self) -> list[OperatorMetadata]:
        return sorted((plugin.metadata for plugin in self._operators.values()), key=lambda item: item.name)
