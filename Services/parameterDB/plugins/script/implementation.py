from __future__ import annotations

from typing import Any

from ...parameterdb_service.plugin_api import ParameterBase, PluginSpec


class ScriptParameter(ParameterBase):
    parameter_type = "script"
    display_name = "Script"
    description = "Evaluates a Python expression each scan."

    def __init__(
        self,
        name: str,
        *,
        config: dict[str, Any] | None = None,
        value: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name, config=config, value=value, metadata=metadata)

    def dependencies(self) -> list[str]:
        deps = self.config.get("depends_on", [])
        if isinstance(deps, str):
            deps = [deps]
        return [str(d) for d in deps if d]

    def scan(self, ctx) -> None:
        expr = self.config.get("expr", "")

        local_ctx = {
            "store": ctx.store,
            "value": self.value,
            "dt": ctx.dt,
            "now": ctx.now,
            "cycle": ctx.cycle_count,
        }

        try:
            result = eval(expr, {}, local_ctx)
            self.value = result
            self.state.pop("last_error", None)
        except Exception as exc:
            self.state["last_error"] = str(exc)


class ScriptPlugin(PluginSpec):
    parameter_type = "script"
    display_name = "Script"
    description = "Python expression parameter"

    def create(self, name: str, *, config=None, value=None, metadata=None) -> ParameterBase:
        return ScriptParameter(name, config=config, value=value, metadata=metadata)

    def default_config(self) -> dict[str, Any]:
        return {"expr": "value", "depends_on": []}

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "expr": {"type": "string"},
                "depends_on": {"type": ["array", "string"]}
            }
        }


PLUGIN = ScriptPlugin()