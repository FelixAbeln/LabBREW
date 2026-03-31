from __future__ import annotations

import json
import time
from typing import Any

from ...._shared.operator_engine.evaluator import ConditionEngine
from ...._shared.operator_engine.loader import load_registry
from ...._shared.operator_engine.models import AtomicCondition, CompositeCondition, ConditionNode
from ...._shared.wait_engine.evaluator import WaitEngine, parse_condition_node, parse_wait_spec
from ...._shared.wait_engine.models import WaitContext, WaitSpec, WaitState
from ...._shared.wait_engine.parser import parse_wait_expr_string
from ...parameterdb_service.plugin_api import ParameterBase, PluginSpec


_CONDITION_ENGINE = ConditionEngine(load_registry())
_WAIT_ENGINE = WaitEngine(_CONDITION_ENGINE)


def _condition_fingerprint(payload: Any) -> str:
    try:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return repr(payload)


def _collect_condition_sources(node: ConditionNode) -> list[str]:
    if isinstance(node, AtomicCondition):
        return [node.source]

    sources: list[str] = []
    for child in node.children:
        sources.extend(_collect_condition_sources(child))
    return sources


def _collect_wait_sources(spec: WaitSpec | None) -> list[str]:
    if spec is None:
        return []
    if spec.kind == "condition":
        condition = spec.condition
        if isinstance(condition, dict):
            node = parse_condition_node(condition)
        else:
            node = condition
        return _collect_condition_sources(node)
    if spec.kind in {"all_of", "any_of"}:
        sources: list[str] = []
        for child in spec.children:
            sources.extend(_collect_wait_sources(child))
        return sources
    return []


def _condition_kind(node: ConditionNode | None) -> str:
    if node is None:
        return ""
    if isinstance(node, AtomicCondition):
        return "atomic"
    return str(node.kind)


def _wait_kind(spec: WaitSpec | None) -> str:
    return "none" if spec is None else str(spec.kind)


class ConditionParameter(ParameterBase):
    parameter_type = "condition"
    display_name = "Condition"
    description = "Evaluates the shared condition syntax and stores the boolean result."

    def __init__(
        self,
        name: str,
        *,
        config: dict[str, Any] | None = None,
        value: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name, config=config, value=value, metadata=metadata)
        self._cached_condition_key = ""
        self._cached_condition: ConditionNode | None = None
        self._cached_wait_spec: WaitSpec | None = None
        self._cached_sources: list[str] = []
        self._cached_error: str | None = None
        self._wait_state = WaitState()
        self._logic_started_monotonic: float | None = None
        self._last_enabled = True

    def _raw_logic(self) -> Any:
        if "expression" in self.config and str(self.config.get("expression") or "").strip():
            return self.config.get("expression")
        return self.config.get("condition")

    def _normalize_wait_payload(self, raw_logic: Any) -> tuple[WaitSpec | None, ConditionNode | None]:
        if isinstance(raw_logic, str):
            parsed_payload = parse_wait_expr_string(raw_logic)
            parsed_wait_spec = parse_wait_spec(parsed_payload)
            parsed_condition = None
            if isinstance(parsed_payload, dict) and parsed_payload.get("kind") == "condition":
                parsed_condition = parse_condition_node(parsed_payload.get("condition") or {})
            return parsed_wait_spec, parsed_condition

        if isinstance(raw_logic, dict):
            if "kind" in raw_logic:
                parsed_wait_spec = parse_wait_spec(raw_logic)
                parsed_condition = None
                if str(raw_logic.get("kind")) == "condition" and isinstance(raw_logic.get("condition"), dict):
                    parsed_condition = parse_condition_node(raw_logic.get("condition") or {})
                return parsed_wait_spec, parsed_condition

            parsed_condition = parse_condition_node(raw_logic)
            wait_payload = {"kind": "condition", "condition": raw_logic}
            return parse_wait_spec(wait_payload), parsed_condition

        if raw_logic in (None, ""):
            raise ValueError("condition requires non-empty logic")

        raise ValueError("condition requires 'condition' to be an object or a DSL string")

    def _compile_condition(self) -> None:
        raw_logic = self._raw_logic()
        cache_key = _condition_fingerprint(raw_logic)
        if cache_key == self._cached_condition_key:
            return

        self._cached_condition_key = cache_key
        self._cached_condition = None
        self._cached_wait_spec = None
        self._cached_sources = []
        self._cached_error = None
        self._wait_state = WaitState()
        self._logic_started_monotonic = None

        try:
            parsed_wait_spec, parsed_condition = self._normalize_wait_payload(raw_logic)
        except Exception as exc:
            self._cached_error = f"invalid condition logic: {exc}"
            return

        self._cached_wait_spec = parsed_wait_spec
        self._cached_condition = parsed_condition
        self._cached_sources = list(dict.fromkeys(_collect_wait_sources(parsed_wait_spec)))

    def dependencies(self) -> list[str]:
        self._compile_condition()
        deps: list[str] = []
        enable_param = self.config.get("enable_param")
        if enable_param:
            deps.append(str(enable_param))
        deps.extend(self._cached_sources)
        return [name for name in list(dict.fromkeys(deps)) if name and name != self.name]

    def scan(self, ctx) -> None:
        store = ctx.store
        enable_param = self.config.get("enable_param")

        enabled = True
        if enable_param:
            enabled = bool(store.get_value(enable_param, True))
        self.state["enabled"] = bool(enabled)
        if not enabled:
            self._wait_state = WaitState()
            self._logic_started_monotonic = None
            self._last_enabled = False
            self.state["last_error"] = ""
            return

        if not self._last_enabled:
            self._wait_state = WaitState()
            self._logic_started_monotonic = None
        self._last_enabled = True

        self._compile_condition()
        if self._cached_error:
            self.state["last_error"] = self._cached_error
            return

        # If compiling the condition did not produce a valid wait spec,
        # treat this as a recoverable configuration error instead of
        # raising an AssertionError.
        if self._cached_wait_spec is None:
            self.state["last_error"] = "invalid or empty wait configuration"
            return

        now_monotonic = time.monotonic()
        if self._logic_started_monotonic is None:
            self._logic_started_monotonic = now_monotonic
        values = store.snapshot()
        values.pop(self.name, None)

        try:
            result = _WAIT_ENGINE.evaluate(
                self._cached_wait_spec,
                context=WaitContext(
                    now_monotonic=now_monotonic,
                    step_started_monotonic=self._logic_started_monotonic,
                    values=values,
                ),
                previous_state=self._wait_state,
            )
        except Exception as exc:
            self.state["last_error"] = f"condition evaluation failed: {exc}"
            return

        self._wait_state = result.next_state
        self.state["expression"] = self._raw_logic()
        self.state["condition"] = self.config.get("condition")
        self.state["logic_kind"] = _wait_kind(self._cached_wait_spec)
        self.state["condition_kind"] = _condition_kind(self._cached_condition)
        self.state["sources"] = list(self._cached_sources)
        self.state["matched"] = bool(result.matched)
        self.state["message"] = result.message
        self.state["observed_values"] = dict(result.observed_values)
        self.state["elapsed_s"] = max(0.0, now_monotonic - self._logic_started_monotonic)

        required_for_s = 0.0
        if isinstance(self._cached_condition, (AtomicCondition, CompositeCondition)):
            required_for_s = float(getattr(self._cached_condition, "for_s", 0.0) or 0.0)
        elif self._cached_wait_spec.kind == "elapsed":
            required_for_s = float(self._cached_wait_spec.duration_s or 0.0)
        self.state["required_for_s"] = required_for_s

        if isinstance(self._cached_condition, AtomicCondition):
            self.state["source"] = self._cached_condition.source
            self.state["operator"] = self._cached_condition.operator
            self.state["params"] = dict(self._cached_condition.params)
        else:
            self.state.pop("source", None)
            self.state.pop("operator", None)
            self.state.pop("params", None)

        missing_sources = sorted(
            source for source in self._cached_sources
            if values.get(source) is None
        )
        if missing_sources:
            if "Missing value for " in result.message:
                self.state["last_error"] = result.message
            else:
                self.state["last_error"] = "Missing value for " + ", ".join(missing_sources)
        else:
            self.value = bool(result.matched)
            self.state["last_error"] = ""


class ConditionPlugin(PluginSpec):
    parameter_type = "condition"
    display_name = "Condition"
    description = "Boolean condition evaluator"

    def create(self, name: str, *, config=None, value=None, metadata=None) -> ParameterBase:
        return ConditionParameter(name, config=config, value=value, metadata=metadata)

    def default_config(self) -> dict[str, Any]:
        return {
            "condition": "",
            "enable_param": "",
        }

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "condition": {"type": ["object", "string"]},
                "expression": {"type": "string"},
                "enable_param": {"type": "string"},
            },
            "required": ["condition"],
        }


PLUGIN = ConditionPlugin()