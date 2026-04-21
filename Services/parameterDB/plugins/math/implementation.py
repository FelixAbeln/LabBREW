from __future__ import annotations

from typing import Any

from ...parameterdb_core.expression import (
    CompiledExpression,
    compile_expression,
    evaluate_expression,
    expression_symbol_names,
)
from ...parameterdb_service.plugin_api import ParameterBase, PluginSpec


class MathParameter(ParameterBase):
    parameter_type = "math"
    display_name = "Math"
    description = (
        "Evaluates a symbolic equation from other DB parameters. "
        "Output can also be mirrored to other parameters."
    )

    def __init__(
        self,
        name: str,
        *,
        config: dict[str, Any] | None = None,
        value: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name, config=config, value=value, metadata=metadata)
        self._cached_equation: str = ""
        self._cached_compiled: CompiledExpression | None = None
        self._cached_symbols: list[str] = []
        self._cached_error: str | None = None

    def _compile_equation(self) -> None:
        equation = str(self.config.get("equation", "") or "").strip()
        if equation == self._cached_equation:
            return

        self._cached_equation = equation
        self._cached_compiled = None
        self._cached_symbols = []
        self._cached_error = None

        try:
            compiled = compile_expression(equation, required=True)
        except ValueError as exc:
            self._cached_error = str(exc).replace(
                "equation requires non-empty expression",
                "math requires non-empty 'equation'",
            )
            return

        self._cached_compiled = compiled
        self._cached_symbols = list(compiled.symbols)

    def dependencies(self) -> list[str]:
        self._compile_equation()
        deps: list[str] = []
        enable_param = self.config.get("enable_param")
        if enable_param:
            deps.append(str(enable_param))
        deps.extend(self._cached_symbols)
        return [
            name for name in list(dict.fromkeys(deps)) if name and name != self.name
        ]

    def scan(self, ctx) -> None:
        store = ctx.store
        enable_param = self.config.get("enable_param")

        enabled = True
        if enable_param:
            enabled = bool(store.get_value(enable_param, True))
        self.state["enabled"] = bool(enabled)
        if not enabled:
            self.state.pop("last_error", None)
            return

        self._compile_equation()
        if self._cached_error:
            self.state["last_error"] = self._cached_error
            return

        if self._cached_compiled is None:
            self.state["last_error"] = "math equation compilation failed"
            return

        values: dict[str, float] = {}
        missing: list[str] = []
        bad_values: list[str] = []
        ast_names = expression_symbol_names(self._cached_compiled)

        for name in ast_names:
            source_symbol = self._cached_compiled.alias_to_symbol.get(name, name)
            if not store.exists(source_symbol):
                missing.append(source_symbol)
                continue
            raw_value = store.get_value(source_symbol)
            try:
                values[name] = float(raw_value)
            except (TypeError, ValueError):
                bad_values.append(source_symbol)

        if missing:
            self.state["last_error"] = "missing parameters in equation: " + ", ".join(
                missing
            )
            return
        if bad_values:
            self.state["last_error"] = (
                "non-numeric parameters in equation: " + ", ".join(bad_values)
            )
            return

        try:
            result = evaluate_expression(self._cached_compiled.tree, values)
        except Exception as exc:
            self.state["last_error"] = f"equation evaluation failed: {exc}"
            return

        self.value = result
        self.state["equation"] = self._cached_equation
        self.state["symbols"] = list(self._cached_symbols)
        self.state.pop("last_error", None)


class MathPlugin(PluginSpec):
    parameter_type = "math"
    display_name = "Math"
    description = "Symbolic equation evaluator"

    def create(
        self, name: str, *, config=None, value=None, metadata=None
    ) -> ParameterBase:
        return MathParameter(name, config=config, value=value, metadata=metadata)

    def default_config(self) -> dict[str, Any]:
        return {
            "equation": "",
            "enable_param": "",
            "output_params": [],
        }

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "equation": {"type": "string"},
                "enable_param": {"type": "string"},
                "output_params": {"type": ["array", "string"]},
            },
            "required": ["equation"],
        }


PLUGIN = MathPlugin()
