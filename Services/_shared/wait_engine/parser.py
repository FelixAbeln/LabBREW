from __future__ import annotations

from typing import Any


def split_top_level(text: str, delimiter: str = ';') -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in text:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth = max(depth - 1, 0)
        if ch == delimiter and depth == 0:
            piece = ''.join(current).strip()
            if piece:
                parts.append(piece)
            current = []
        else:
            current.append(ch)
    tail = ''.join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def normalize_scalar(value_text: str) -> Any:
    text = value_text.strip()
    lowered = text.lower()
    if lowered in {'true', 'false'}:
        return lowered == 'true'
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer():
        return int(number)
    return number


def parse_condition_expr(expr: str) -> dict[str, Any]:
    parts = [part.strip() for part in expr.split(':')]
    if len(parts) not in {4, 5} or parts[0] != 'cond':
        raise ValueError(
            f"Invalid condition syntax '{expr}'. Use cond:source:operator:threshold[:for_seconds]"
        )
    condition = {
        'source': parts[1],
        'operator': parts[2],
        'threshold': normalize_scalar(parts[3]),
    }
    if len(parts) == 5 and parts[4] != '':
        condition['for_s'] = float(parts[4])
    return {'kind': 'condition', 'condition': condition}


def parse_elapsed_expr(expr: str) -> dict[str, Any]:
    parts = [part.strip() for part in expr.split(':')]
    if len(parts) != 2 or parts[0] != 'elapsed':
        raise ValueError(f"Invalid elapsed syntax '{expr}'. Use elapsed:seconds")
    return {'kind': 'elapsed', 'duration_s': float(parts[1])}


def parse_wait_expr_string(expr: str) -> dict[str, Any] | None:
    expr = str(expr or '').strip()
    if not expr:
        return None

    if expr.startswith('all(') and expr.endswith(')'):
        inner = expr[4:-1].strip()
        return {
            'kind': 'all_of',
            'children': [parse_wait_expr_string(part) for part in split_top_level(inner, ';')],
        }

    if expr.startswith('any(') and expr.endswith(')'):
        inner = expr[4:-1].strip()
        return {
            'kind': 'any_of',
            'children': [parse_wait_expr_string(part) for part in split_top_level(inner, ';')],
        }

    if expr.startswith('elapsed:'):
        return parse_elapsed_expr(expr)

    if expr.startswith('cond:'):
        return parse_condition_expr(expr)

    raise ValueError(
        f"Invalid wait syntax '{expr}'. Use elapsed:..., cond:..., all(...), or any(...)"
    )