from __future__ import annotations

from statistics import median
from typing import Any

from ...parameterdb_service.plugin_api import ParameterBase, PluginSpec


class MedianParameter(ParameterBase):
    parameter_type = "median"
    display_name = "Median"
    description = "Applies a rolling median filter to a source parameter. Output can also be mirrored to other parameters."

    def __init__(
        self,
        name: str,
        *,
        config: dict[str, Any] | None = None,
        value: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name, config=config, value=value, metadata=metadata)
        self._samples: list[float] = []

    def _output_targets(self) -> list[str]:
        raw = self.config.get("output_params") or []
        if isinstance(raw, str):
            raw = [raw]
        result: list[str] = []
        if isinstance(raw, list):
            for item in raw:
                if not item:
                    continue
                target = str(item).strip()
                if target and target != self.name:
                    result.append(target)
        return list(dict.fromkeys(result))

    def write_targets(self) -> list[str]:
        return self._output_targets()

    def _write_output_targets(self, store, value: float) -> None:
        written: list[str] = []
        missing: list[str] = []
        for target in self._output_targets():
            if not store.exists(target):
                missing.append(target)
                continue
            store.set_value(target, value)
            written.append(target)
        self.state["output_targets"] = written
        if missing:
            self.state["missing_output_targets"] = missing
        else:
            self.state.pop("missing_output_targets", None)

    def dependencies(self) -> list[str]:
        deps = [self.config.get("source"), self.config.get("enable_param")]
        return [str(dep) for dep in deps if dep]

    def _window_size(self) -> int:
        try:
            window = int(self.config.get("window", 5))
        except (TypeError, ValueError):
            window = 5
        return max(1, window)

    def scan(self, ctx) -> None:
        store = ctx.store
        source_name = self.config.get("source")
        enable_param = self.config.get("enable_param")

        if not source_name:
            self.state["last_error"] = "median requires 'source'"
            return

        enabled = True
        if enable_param:
            enabled = bool(store.get_value(enable_param, True))
        self.state["enabled"] = bool(enabled)
        if not enabled:
            self._samples = []
            self.state["sample_count"] = 0
            self.state["samples"] = []
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

        window = self._window_size()
        self._samples.append(current_input)
        if len(self._samples) > window:
            self._samples = self._samples[-window:]

        output = float(median(self._samples))
        self.value = output
        self._write_output_targets(store, output)

        self.state["source"] = str(source_name)
        self.state["input"] = current_input
        self.state["window"] = window
        self.state["sample_count"] = len(self._samples)
        self.state["samples"] = list(self._samples)
        self.state["last_error"] = ""


class MedianPlugin(PluginSpec):
    parameter_type = "median"
    display_name = "Median"
    description = "Rolling median filter"

    def create(self, name: str, *, config=None, value=None, metadata=None) -> ParameterBase:
        return MedianParameter(name, config=config, value=value, metadata=metadata)

    def default_config(self) -> dict[str, Any]:
        return {
            "source": "",
            "enable_param": "",
            "window": 5,
            "output_params": [],
        }

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "enable_param": {"type": "string"},
                "window": {"type": "integer"},
                "output_params": {"type": ["array", "string"]},
            },
            "required": ["source"],
        }


PLUGIN = MedianPlugin()
