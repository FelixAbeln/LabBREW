from __future__ import annotations

from typing import Any

from ...parameterdb_service.plugin_api import ParameterBase, PluginSpec


class FollowParameter(ParameterBase):
    parameter_type = "follow"
    display_name = "Follow"
    description = "Mirrors a source parameter and can hold the last good value when the source becomes invalid."

    def _source_name(self) -> str:
        return str(self.config.get("source") or "").strip()

    def dependencies(self) -> list[str]:
        source_name = self._source_name()
        return [source_name] if source_name else []

    def allow_invalid_dependencies(self) -> bool:
        return True

    def scan(self, ctx) -> None:
        store = ctx.store
        source_name = self._source_name()
        if not source_name:
            self.state["last_error"] = "follow requires 'source'"
            return

        try:
            source_record = store.get_record(source_name)
            source_value = store.get_value(source_name)
        except KeyError:
            self.state["last_error"] = f"missing source parameter '{source_name}'"
            return

        source_state = dict(source_record.get("state") or {})
        source_invalid = source_state.get("parameter_valid") is False
        source_reasons = list(source_state.get("parameter_invalid_reasons") or [])
        latch_on_invalid = bool(self.config.get("latch_on_invalid", True))

        if source_invalid:
            self.state["source"] = source_name
            self.state["input"] = source_value
            self.state["source_invalid"] = True
            self.state["source_invalid_reasons"] = source_reasons
            if latch_on_invalid:
                self.state["latched"] = True
                self.state["last_error"] = ""
                return

            self.value = source_value
            self.state["latched"] = False
            self.state["last_error"] = ""
            return

        self.value = source_value
        self.state["source"] = source_name
        self.state["input"] = source_value
        self.state["source_invalid"] = False
        self.state["source_invalid_reasons"] = []
        self.state["latched"] = False
        self.state["last_error"] = ""


class FollowPlugin(PluginSpec):
    parameter_type = "follow"
    display_name = "Follow"
    description = "Mirror a source parameter and optionally latch the last good value while the source is invalid"

    def create(
        self, name: str, *, config=None, value=None, metadata=None
    ) -> ParameterBase:
        return FollowParameter(name, config=config, value=value, metadata=metadata)

    def default_config(self) -> dict[str, Any]:
        return {
            "source": "",
            "latch_on_invalid": True,
            "output_params": [],
        }

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "latch_on_invalid": {"type": "boolean"},
                "output_params": {"type": ["array", "string"]},
            },
            "required": ["source"],
        }


PLUGIN = FollowPlugin()