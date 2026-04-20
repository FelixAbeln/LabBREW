from __future__ import annotations

from typing import Any

from ...parameterdb_service.plugin_api import ParameterBase, PluginSpec


class LowpassParameter(ParameterBase):
    parameter_type = "lowpass"
    display_name = "Lowpass"
    description = "Applies first-order lowpass filtering to a source parameter."

    def __init__(
        self,
        name: str,
        *,
        config: dict[str, Any] | None = None,
        value: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name, config=config, value=value, metadata=metadata)
        self._initialized = False

    def dependencies(self) -> list[str]:
        deps = [self.config.get("source"), self.config.get("enable_param")]
        return [str(dep) for dep in deps if dep]

    def scan(self, ctx) -> None:
        store = ctx.store
        source_name = self.config.get("source")
        enable_param = self.config.get("enable_param")

        if not source_name:
            self.state["last_error"] = "lowpass requires 'source'"
            return

        enabled = True
        if enable_param:
            enabled = bool(store.get_value(enable_param, True))
        self.state["enabled"] = bool(enabled)
        if not enabled:
            self._initialized = False
            self.state["last_error"] = ""
            return

        raw_value = store.get_value(source_name)
        if raw_value is None:
            self.state["last_error"] = f"missing source parameter '{source_name}'"
            return

        try:
            current_input = float(raw_value)
        except (TypeError, ValueError):
            self.state["last_error"] = f"non-numeric source parameter '{source_name}'"
            return

        try:
            tau_s = float(self.config.get("tau_s", 1.0))
        except (TypeError, ValueError):
            tau_s = 1.0
        if tau_s < 0.0:
            tau_s = 0.0

        try:
            dt = float(getattr(ctx, "dt", 0.0))
        except (TypeError, ValueError):
            dt = 0.0
        if dt < 0.0:
            dt = 0.0

        if not self._initialized:
            output = current_input
            alpha = 1.0
            self._initialized = True
        elif tau_s <= 0.0:
            output = current_input
            alpha = 1.0
        else:
            previous_output = self.value
            try:
                previous_value = float(previous_output)
            except (TypeError, ValueError):
                previous_value = current_input
            alpha = dt / (tau_s + dt) if dt > 0.0 else 0.0
            output = previous_value + (alpha * (current_input - previous_value))

        self.value = output

        self.state["source"] = str(source_name)
        self.state["input"] = current_input
        self.state["tau_s"] = tau_s
        self.state["dt"] = dt
        self.state["alpha"] = alpha
        self.state["last_error"] = ""


class LowpassPlugin(PluginSpec):
    parameter_type = "lowpass"
    display_name = "Lowpass"
    description = "First-order lowpass filter"

    def create(
        self, name: str, *, config=None, value=None, metadata=None
    ) -> ParameterBase:
        return LowpassParameter(name, config=config, value=value, metadata=metadata)

    def default_config(self) -> dict[str, Any]:
        return {
            "source": "",
            "enable_param": "",
            "tau_s": 1.0,
            "output_params": [],
        }

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "enable_param": {"type": "string"},
                "tau_s": {"type": "number"},
                "output_params": {"type": ["array", "string"]},
            },
            "required": ["source"],
        }


PLUGIN = LowpassPlugin()
