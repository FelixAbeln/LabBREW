from __future__ import annotations

import ast
import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any

ALLOWED_BINARY_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}

ALLOWED_UNARY_OPS = {
    ast.UAdd: lambda a: +a,
    ast.USub: lambda a: -a,
}

ALLOWED_FUNCTIONS: dict[str, Any] = {
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

ALLOWED_CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
}


class _ExpressionSymbolCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: list[str] = []
        self.function_names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        self.names.append(node.id)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self.function_names.add(node.func.id)
        self.generic_visit(node)


@dataclass(slots=True)
class CompiledExpression:
    expression: str
    tree: ast.Expression
    symbols: list[str]
    alias_to_symbol: dict[str, str]


def _rewrite_dotted_symbols(equation: str) -> tuple[str, dict[str, str]]:
    alias_to_symbol: dict[str, str] = {}
    symbol_to_alias: dict[str, str] = {}
    dotted_symbol_pattern = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+\b")
    used_identifiers = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", equation))

    def _new_alias(symbol: str) -> str:
        digest = hashlib.sha1(symbol.encode("utf-8")).hexdigest()[:12]
        base = f"__lb_dsym_{digest}"
        alias = base
        index = 1
        while alias in used_identifiers or alias in alias_to_symbol:
            alias = f"{base}_{index}"
            index += 1
        used_identifiers.add(alias)
        return alias

    def _replace(match: re.Match[str]) -> str:
        symbol = match.group(0)
        existing = symbol_to_alias.get(symbol)
        if existing is not None:
            return existing
        alias = _new_alias(symbol)
        symbol_to_alias[symbol] = alias
        alias_to_symbol[alias] = symbol
        return alias

    rewritten = dotted_symbol_pattern.sub(_replace, equation)
    return rewritten, alias_to_symbol


def compile_expression(expression: str, *, required: bool = True) -> CompiledExpression:
    text = str(expression or "").strip()
    if not text:
        if required:
            raise ValueError("equation requires non-empty expression")
        return CompiledExpression(
            expression="",
            tree=ast.Expression(body=ast.Constant(value=None)),
            symbols=[],
            alias_to_symbol={},
        )

    rewritten_expression, alias_to_symbol = _rewrite_dotted_symbols(text)
    try:
        tree = ast.parse(rewritten_expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid equation syntax: {exc.msg}") from exc

    collector = _ExpressionSymbolCollector()
    collector.visit(tree)
    symbols: list[str] = []
    for name in collector.names:
        if name in collector.function_names or name in ALLOWED_CONSTANTS:
            continue
        symbols.append(alias_to_symbol.get(name, name))

    return CompiledExpression(
        expression=text,
        tree=tree,
        symbols=list(dict.fromkeys(symbols)),
        alias_to_symbol=alias_to_symbol,
    )


def expression_symbol_names(compiled: CompiledExpression) -> list[str]:
    return [name for name in compiled.alias_to_symbol] + [
        symbol
        for symbol in compiled.symbols
        if symbol not in compiled.alias_to_symbol.values()
    ]


def evaluate_expression(node: ast.AST, values: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return evaluate_expression(node.body, values)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, bool)):
            return float(node.value)
        raise ValueError(f"unsupported constant type: {type(node.value).__name__}")
    if isinstance(node, ast.Name):
        if node.id in values:
            return float(values[node.id])
        if node.id in ALLOWED_CONSTANTS:
            return float(ALLOWED_CONSTANTS[node.id])
        raise ValueError(f"unknown symbol '{node.id}'")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        op = ALLOWED_BINARY_OPS.get(op_type)
        if op is None:
            raise ValueError(f"unsupported operator: {op_type.__name__}")
        return float(
            op(
                evaluate_expression(node.left, values),
                evaluate_expression(node.right, values),
            )
        )
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        op = ALLOWED_UNARY_OPS.get(op_type)
        if op is None:
            raise ValueError(f"unsupported unary operator: {op_type.__name__}")
        return float(op(evaluate_expression(node.operand, values)))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("only direct function names are allowed")
        func = ALLOWED_FUNCTIONS.get(node.func.id)
        if func is None:
            raise ValueError(f"unsupported function '{node.func.id}'")
        if node.keywords:
            raise ValueError("keyword arguments are not supported")
        args = [evaluate_expression(arg, values) for arg in node.args]
        return float(func(*args))
    raise ValueError(f"unsupported expression node: {type(node).__name__}")