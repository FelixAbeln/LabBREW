from __future__ import annotations

from typing import Any

from ...parameterdb_service.plugin_api import ParameterBase, PluginSpec


class DerivativeParameter(ParameterBase):
    parameter_type = "derivative"
    display_name = "Derivative"
    description = "Computes rate-of-change from a source parameter."

    def __init__(
        self,
        name: str,
        *,
        config: dict[str, Any] | None = None,
        value: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name, config=config, value=value, metadata=metadata)
        self._previous_input: float | None = None
        self._elapsed_since_change_s: float = 0.0
        self._elapsed_total_s: float = 0.0
        self._history: list[tuple[float, float]] = []

    def dependencies(self) -> list[str]:
        deps = [
            self.config.get("source"),
            self.config.get("enable_param"),
        ]
        return [str(dep) for dep in deps if dep]

    def _mode(self) -> str:
        mode = (
            str(self.config.get("mode", "continuous") or "continuous").strip().lower()
        )
        if mode not in {"continuous", "window"}:
            return "continuous"
        return mode

    def _window_s(self) -> float:
        try:
            window_s = float(self.config.get("window_s", 2.0))
        except (TypeError, ValueError):
            window_s = 2.0
        return max(0.0, window_s)

    def _reset_runtime_state(self) -> None:
        self._previous_input = None
        self._elapsed_since_change_s = 0.0
        self._elapsed_total_s = 0.0
        self._history = []

    def scan(self, ctx) -> None:
        store = ctx.store
        source_name = self.config.get("source")
        enable_param = self.config.get("enable_param")

        if not source_name:
            self.state["last_error"] = "derivative requires 'source'"
            return

        enabled = True
        if enable_param:
            enabled = bool(store.get_value(enable_param, True))
        self.state["enabled"] = bool(enabled)
        if not enabled:
            self._reset_runtime_state()
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
            scale = float(self.config.get("scale", 1.0))
        except (TypeError, ValueError):
            scale = 1.0

        try:
            min_dt = float(self.config.get("min_dt", 1e-6))
        except (TypeError, ValueError):
            min_dt = 1e-6
        if min_dt <= 0.0:
            min_dt = 1e-6

        try:
            dt = float(getattr(ctx, "dt", 0.0))
        except (TypeError, ValueError):
            dt = 0.0
        step_dt = dt if dt > min_dt else min_dt

        mode = self._mode()
        window_s = self._window_s()

        if mode == "window":
            self._elapsed_total_s += step_dt
            now_s = self._elapsed_total_s
            self._history.append((now_s, current_input))

            if window_s > 0.0:
                cutoff_s = now_s - window_s
                while len(self._history) >= 2 and self._history[1][0] <= cutoff_s:
                    self._history.pop(0)
            else:
                self._history = [self._history[-1]]

            oldest_time_s, oldest_value = self._history[0]
            delta = current_input - oldest_value
            span_s = now_s - oldest_time_s
            effective_dt = span_s if span_s > min_dt else min_dt
            derivative = delta / effective_dt if span_s > 0.0 else 0.0
            output = derivative * scale
            self._previous_input = current_input
            self._elapsed_since_change_s = 0.0
            self.state["updated_on_change"] = abs(delta) > 0.0
            self.state["history_sample_count"] = len(self._history)
            self.state["history_span_s"] = span_s
        else:
            if self._previous_input is None:
                delta = 0.0
                effective_dt = step_dt
                derivative = 0.0
                output = derivative * scale
                self._elapsed_since_change_s = 0.0
                self._history = []
                self.state["history_sample_count"] = 0
                self.state["history_span_s"] = 0.0
            else:
                delta = current_input - self._previous_input
                self._elapsed_since_change_s += step_dt

                if abs(delta) > 0.0:
                    effective_dt = (
                        self._elapsed_since_change_s
                        if self._elapsed_since_change_s > min_dt
                        else min_dt
                    )
                    derivative = delta / effective_dt
                    output = derivative * scale
                    self._previous_input = current_input
                    self._elapsed_since_change_s = 0.0
                    self.state["updated_on_change"] = True
                else:
                    effective_dt = self._elapsed_since_change_s
                    # Reuse the previously computed unscaled derivative and apply the
                    # current scale so scaling behaves consistently even when input
                    # does not change or when scale is modified at runtime.
                    derivative = self.state.get("raw_derivative", 0.0)
                    output = derivative * scale
                    self.state["updated_on_change"] = False
                self.state["history_sample_count"] = 0
                self.state["history_span_s"] = 0.0

        self.value = output
        if self._previous_input is None:
            self._previous_input = current_input

        self.state["mode"] = mode
        self.state["window_s"] = window_s
        self.state["source"] = str(source_name)
        self.state["input"] = current_input
        self.state["delta"] = delta
        self.state["raw_derivative"] = derivative
        self.state["scale"] = scale
        self.state["dt"] = dt
        self.state["effective_dt"] = effective_dt
        self.state["elapsed_since_change_s"] = self._elapsed_since_change_s
        self.state["last_error"] = ""


class DerivativePlugin(PluginSpec):
    parameter_type = "derivative"
    display_name = "Derivative"
    description = "Rate-of-change evaluator"

    def create(
        self, name: str, *, config=None, value=None, metadata=None
    ) -> ParameterBase:
        return DerivativeParameter(name, config=config, value=value, metadata=metadata)

    def default_config(self) -> dict[str, Any]:
        return {
            "source": "",
            "enable_param": "",
            "mode": "continuous",
            "window_s": 2.0,
            "scale": 1.0,
            "min_dt": 1e-6,
            "output_params": [],
        }

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "enable_param": {"type": "string"},
                "mode": {"type": "string", "enum": ["continuous", "window"]},
                "window_s": {"type": "number"},
                "scale": {"type": "number"},
                "min_dt": {"type": "number"},
                "output_params": {"type": ["array", "string"]},
            },
            "required": ["source"],
        }


PLUGIN = DerivativePlugin()
