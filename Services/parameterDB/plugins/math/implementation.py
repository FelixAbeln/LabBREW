from __future__ import annotations

import ast
import math
import re
from typing import Any

from ...parameterdb_service.plugin_api import ParameterBase, PluginSpec


_ALLOWED_BINARY_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}

_ALLOWED_UNARY_OPS = {
    ast.UAdd: lambda a: +a,
    ast.USub: lambda a: -a,
}

_ALLOWED_FUNCTIONS: dict[str, Any] = {
    "abs": abs,
    "max": max,
    "min": min,
    "pow": pow,
    "round": round,
    "ceil": math.ceil,
    "floor": math.floor,
    "sqrt": math.sqrt,
    "exp": math.exp,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
}

_ALLOWED_CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
}


class _ExpressionSymbolCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: list[str] = []
        self.function_names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        self.names.append(node.id)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if isinstance(node.func, ast.Name):
            self.function_names.add(node.func.id)
        self.generic_visit(node)


class MathParameter(ParameterBase):
    parameter_type = "math"
    display_name = "Math"
    description = "Evaluates a symbolic equation from other DB parameters. Output can also be mirrored to other parameters."

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
        self._cached_tree: ast.Expression | None = None
        self._cached_symbols: list[str] = []
        self._cached_alias_to_symbol: dict[str, str] = {}
        self._cached_error: str | None = None

    def _rewrite_dotted_symbols(self, equation: str) -> tuple[str, dict[str, str]]:
        alias_to_symbol: dict[str, str] = {}
        symbol_to_alias: dict[str, str] = {}
        dotted_symbol_pattern = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+\b")

        def _replace(match: re.Match[str]) -> str:
            symbol = match.group(0)
            existing = symbol_to_alias.get(symbol)
            if existing is not None:
                return existing
            alias = f"__p{len(symbol_to_alias)}"
            symbol_to_alias[symbol] = alias
            alias_to_symbol[alias] = symbol
            return alias

        rewritten = dotted_symbol_pattern.sub(_replace, equation)
        return rewritten, alias_to_symbol

    def _output_targets(self) -> list[str]:
        raw = self.config.get("output_params") or []
        if isinstance(raw, str):
            raw = [raw]
        result: list[str] = []
        if isinstance(raw, list):
            for item in raw:
                if not item:
                    continue
                name = str(item).strip()
                if name and name != self.name:
                    result.append(name)
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

    def _compile_equation(self) -> None:
        equation = str(self.config.get("equation", "") or "").strip()
        if equation == self._cached_equation:
            return

        self._cached_equation = equation
        self._cached_tree = None
        self._cached_symbols = []
        self._cached_alias_to_symbol = {}
        self._cached_error = None

        if not equation:
            self._cached_error = "math requires non-empty 'equation'"
            return

        rewritten_equation, alias_to_symbol = self._rewrite_dotted_symbols(equation)

        try:
            tree = ast.parse(rewritten_equation, mode="eval")
        except SyntaxError as exc:
            self._cached_error = f"invalid equation syntax: {exc.msg}"
            return

        collector = _ExpressionSymbolCollector()
        collector.visit(tree)
        symbols: list[str] = []
        for name in collector.names:
            if name in collector.function_names or name in _ALLOWED_CONSTANTS:
                continue
            symbols.append(alias_to_symbol.get(name, name))

        self._cached_tree = tree
        self._cached_symbols = list(dict.fromkeys(symbols))
        self._cached_alias_to_symbol = alias_to_symbol

    def dependencies(self) -> list[str]:
        self._compile_equation()
        deps: list[str] = []
        enable_param = self.config.get("enable_param")
        if enable_param:
            deps.append(str(enable_param))
        deps.extend(self._cached_symbols)
        return [name for name in list(dict.fromkeys(deps)) if name and name != self.name]

    def _eval_expr(self, node: ast.AST, values: dict[str, float]) -> float:
        if isinstance(node, ast.Expression):
            return self._eval_expr(node.body, values)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, bool)):
                return float(node.value)
            raise ValueError(f"unsupported constant type: {type(node.value).__name__}")
        if isinstance(node, ast.Name):
            if node.id in values:
                return float(values[node.id])
            if node.id in _ALLOWED_CONSTANTS:
                return float(_ALLOWED_CONSTANTS[node.id])
            raise ValueError(f"unknown symbol '{node.id}'")
        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            op = _ALLOWED_BINARY_OPS.get(op_type)
            if op is None:
                raise ValueError(f"unsupported operator: {op_type.__name__}")
            return float(op(self._eval_expr(node.left, values), self._eval_expr(node.right, values)))
        if isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            op = _ALLOWED_UNARY_OPS.get(op_type)
            if op is None:
                raise ValueError(f"unsupported unary operator: {op_type.__name__}")
            return float(op(self._eval_expr(node.operand, values)))
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("only direct function names are allowed")
            func = _ALLOWED_FUNCTIONS.get(node.func.id)
            if func is None:
                raise ValueError(f"unsupported function '{node.func.id}'")
            if node.keywords:
                raise ValueError("keyword arguments are not supported")
            args = [self._eval_expr(arg, values) for arg in node.args]
            return float(func(*args))
        raise ValueError(f"unsupported expression node: {type(node).__name__}")

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

        assert self._cached_tree is not None

        values: dict[str, float] = {}
        missing: list[str] = []
        bad_values: list[str] = []
        ast_names = [
            name for name in self._cached_alias_to_symbol.keys()
        ] + [
            symbol for symbol in self._cached_symbols if symbol not in self._cached_alias_to_symbol.values()
        ]

        for name in ast_names:
            source_symbol = self._cached_alias_to_symbol.get(name, name)
            if not store.exists(source_symbol):
                missing.append(source_symbol)
                continue
            raw_value = store.get_value(source_symbol)
            try:
                values[name] = float(raw_value)
            except (TypeError, ValueError):
                bad_values.append(source_symbol)

        if missing:
            self.state["last_error"] = "missing parameters in equation: " + ", ".join(missing)
            return
        if bad_values:
            self.state["last_error"] = "non-numeric parameters in equation: " + ", ".join(bad_values)
            return

        try:
            result = self._eval_expr(self._cached_tree, values)
        except Exception as exc:
            self.state["last_error"] = f"equation evaluation failed: {exc}"
            return

        self.value = result
        self._write_output_targets(store, result)
        self.state["equation"] = self._cached_equation
        self.state["symbols"] = list(self._cached_symbols)
        self.state.pop("last_error", None)


class MathPlugin(PluginSpec):
    parameter_type = "math"
    display_name = "Math"
    description = "Symbolic equation evaluator"

    def create(self, name: str, *, config=None, value=None, metadata=None) -> ParameterBase:
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