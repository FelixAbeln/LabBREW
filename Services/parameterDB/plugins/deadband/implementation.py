from __future__ import annotations

from typing import Any

from ...parameterdb_service.plugin_api import ParameterBase, PluginSpec


class DeadbandParameter(ParameterBase):
    parameter_type = "deadband"
    display_name = "Deadband"
    description = "Boolean hysteresis controller using other DB parameters as PV/SP."

    def dependencies(self) -> list[str]:
        deps = [
            self.config.get("pv"),
            self.config.get("sp"),
            self.config.get("enable_param"),
        ]
        return [str(d) for d in deps if d]

    def _offsets(self) -> tuple[float, float]:
        cfg = self.config
        legacy_deadband = abs(float(cfg.get("deadband", 0.0)))
        on_offset = abs(float(cfg.get("on_offset", legacy_deadband)))
        off_offset = abs(float(cfg.get("off_offset", legacy_deadband)))
        return on_offset, off_offset

    def scan(self, ctx) -> None:
        cfg = self.config
        store = ctx.store

        pv_name = cfg.get("pv")
        sp_name = cfg.get("sp")
        enable_param = cfg.get("enable_param")

        if not pv_name or not sp_name:
            self.state["last_error"] = "deadband requires 'pv' and 'sp'"
            return

        enabled = True
        if enable_param:
            enabled = bool(store.get_value(enable_param, True))
        self.state["enabled"] = bool(enabled)
        if not enabled:
            self.state.pop("last_error", None)
            return

        pv = float(store.get_value(pv_name, 0.0))
        sp = float(store.get_value(sp_name, 0.0))
        on_offset, off_offset = self._offsets()
        direction = str(cfg.get("direction", "below")).strip().lower()
        if direction not in {"below", "above"}:
            direction = "below"

        current = bool(self.value)

        if direction == "below":
            on_threshold = sp - on_offset
            off_threshold = sp - off_offset
            if pv <= on_threshold:
                output = True
            elif pv >= off_threshold:
                output = False
            else:
                output = current
        else:
            on_threshold = sp + on_offset
            off_threshold = sp + off_offset
            if pv >= on_threshold:
                output = True
            elif pv <= off_threshold:
                output = False
            else:
                output = current

        self.value = output
        self.state["pv"] = pv
        self.state["sp"] = sp
        self.state["on_offset"] = on_offset
        self.state["off_offset"] = off_offset
        self.state["on_threshold"] = on_threshold
        self.state["off_threshold"] = off_threshold
        self.state["direction"] = direction
        self.state.pop("last_error", None)


class DeadbandPlugin(PluginSpec):
    parameter_type = "deadband"
    display_name = "Deadband"
    description = "Boolean hysteresis controller"

    def create(
        self, name: str, *, config=None, value=None, metadata=None
    ) -> ParameterBase:
        return DeadbandParameter(name, config=config, value=value, metadata=metadata)

    def default_config(self) -> dict[str, Any]:
        return {
            "pv": "",
            "sp": "",
            "on_offset": 1.0,
            "off_offset": 1.0,
            "direction": "below",
            "enable_param": "",
            "output_params": [],
        }

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pv": {"type": "string"},
                "sp": {"type": "string"},
                "on_offset": {"type": "number"},
                "off_offset": {"type": "number"},
                "deadband": {"type": "number"},
                "direction": {"type": "string", "enum": ["below", "above"]},
                "enable_param": {"type": "string"},
                "output_params": {"type": ["array", "string"]},
            },
            "required": ["pv", "sp"],
        }


PLUGIN = DeadbandPlugin()
