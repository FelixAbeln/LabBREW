from __future__ import annotations

from typing import Any

from ...parameterdb_service.plugin_api import ParameterBase, PluginSpec


class StaticParameter(ParameterBase):
    parameter_type = "static"
    display_name = "Static"
    description = "Retained value set by other apps or operators."

    def __init__(
        self,
        name: str,
        *,
        config: dict[str, Any] | None = None,
        value: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name, config=config, value=value, metadata=metadata)

    def scan(self, ctx) -> None:
        # Passive parameter: just keeps its value until changed.
        pass


class StaticPlugin(PluginSpec):
    parameter_type = "static"
    display_name = "Static"
    description = "Retained parameter value"

    def create(self, name: str, *, config=None, value=None, metadata=None) -> ParameterBase:
        return StaticParameter(name, config=config, value=value, metadata=metadata)

    def default_config(self) -> dict[str, Any]:
        return {}

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {}
        }


PLUGIN = StaticPlugin()