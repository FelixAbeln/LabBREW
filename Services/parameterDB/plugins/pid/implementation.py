from __future__ import annotations

from typing import Any

from ...parameterdb_service.plugin_api import ParameterBase, PluginSpec


class PIDParameter(ParameterBase):
    parameter_type = "pid"
    display_name = "PID"
    description = "PID controller using other DB parameters as PV/SP."

    def __init__(
        self,
        name: str,
        *,
        config: dict[str, Any] | None = None,
        value: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name, config=config, value=value, metadata=metadata)
        self.state.setdefault("integral", 0.0)
        self.state.setdefault("prev_error", 0.0)

    def dependencies(self) -> list[str]:
        deps = [
            self.config.get("pv"),
            self.config.get("sp"),
            self.config.get("enable_param"),
            self.config.get("mode_param"),
            self.config.get("manual_out_param"),
        ]
        return [str(d) for d in deps if d]

    def scan(self, ctx) -> None:
        cfg = self.config
        store = ctx.store

        pv_name = cfg.get("pv")
        sp_name = cfg.get("sp")
        enable_param = cfg.get("enable_param")
        mode_param = cfg.get("mode_param")
        manual_out_param = cfg.get("manual_out_param")

        if not pv_name or not sp_name:
            self.state["last_error"] = "pid requires 'pv' and 'sp'"
            return

        enabled = True
        if enable_param:
            enabled = bool(store.get_value(enable_param, True))
        self.state["enabled"] = enabled
        if not enabled:
            return

        mode = "auto"
        if mode_param:
            mode = str(store.get_value(mode_param, "auto")).lower()
        if mode not in ("auto", "manual"):
            mode = "auto"

        pv = float(store.get_value(pv_name, 0.0))
        sp = float(store.get_value(sp_name, 0.0))
        kp = float(cfg.get("kp", 1.0))
        ki = float(cfg.get("ki", 0.0))
        kd = float(cfg.get("kd", 0.0))
        out_min = float(cfg.get("out_min", 0.0))
        out_max = float(cfg.get("out_max", 100.0))
        bias = float(cfg.get("bias", 0.0))

        if mode == "manual":
            if manual_out_param:
                manual_out = float(
                    store.get_value(
                        manual_out_param, self.value if self.value is not None else 0.0
                    )
                )
            else:
                manual_out = float(
                    cfg.get("manual_out", self.value if self.value is not None else 0.0)
                )
            self.value = manual_out
            self.state["mode"] = "manual"
            self.state["pv"] = pv
            self.state["sp"] = sp
            self.state.pop("last_error", None)
            return

        error = sp - pv
        integral = float(self.state.get("integral", 0.0)) + error * ctx.dt
        prev_error = float(self.state.get("prev_error", 0.0))
        derivative = (error - prev_error) / ctx.dt if ctx.dt > 0 else 0.0

        out = bias + (kp * error) + (ki * integral) + (kd * derivative)
        out = max(out_min, min(out_max, out))

        if out != out_min and out != out_max:
            self.state["integral"] = integral

        self.state["prev_error"] = error
        self.state["mode"] = "auto"
        self.state["pv"] = pv
        self.state["sp"] = sp
        self.state["error"] = error
        self.state.pop("last_error", None)
        self.value = out


class PIDPlugin(PluginSpec):
    parameter_type = "pid"
    display_name = "PID"
    description = "PID controller"

    def create(
        self, name: str, *, config=None, value=None, metadata=None
    ) -> ParameterBase:
        return PIDParameter(name, config=config, value=value, metadata=metadata)

    def default_config(self) -> dict[str, Any]:
        return {
            "pv": "",
            "sp": "",
            "enable_param": "",
            "mode_param": "",
            "manual_out_param": "",
            "kp": 1.0,
            "ki": 0.0,
            "kd": 0.0,
            "bias": 0.0,
            "out_min": 0.0,
            "out_max": 100.0,
            "manual_out": 0.0,
            "output_params": [],
        }

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pv": {"type": "string"},
                "sp": {"type": "string"},
                "enable_param": {"type": "string"},
                "mode_param": {"type": "string"},
                "manual_out_param": {"type": "string"},
                "kp": {"type": "number"},
                "ki": {"type": "number"},
                "kd": {"type": "number"},
                "bias": {"type": "number"},
                "out_min": {"type": "number"},
                "out_max": {"type": "number"},
                "manual_out": {"type": "number"},
                "output_params": {"type": ["array", "string"]},
            },
            "required": ["pv", "sp"],
        }


PLUGIN = PIDPlugin()
