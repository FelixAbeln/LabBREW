from __future__ import annotations

from io import BytesIO
from typing import Any

from openpyxl import load_workbook


def _cell_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _cell_bool(value: Any, default: bool = True) -> bool:
    if value is None or value == '':
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {'1', 'true', 'yes', 'y'}:
        return True
    if text in {'0', 'false', 'no', 'n'}:
        return False
    return default


def _cell_float(value: Any) -> float | None:
    if value is None or value == '':
        return None
    return float(value)


def _read_meta_sheet(wb) -> dict[str, str]:
    if 'meta' not in wb.sheetnames:
        raise ValueError("Workbook must contain a 'meta' sheet")
    ws = wb['meta']
    meta: dict[str, str] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        key, value = row[:2]
        if key is None:
            continue
        meta[str(key).strip()] = '' if value is None else str(value).strip()
    return meta


def _read_steps_sheet(wb, sheet_name: str) -> list[dict[str, Any]]:
    if sheet_name not in wb.sheetnames:
        return []
    ws = wb[sheet_name]
    headers = [str(v).strip() if v is not None else '' for v in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    rows: list[dict[str, Any]] = []
    for values in ws.iter_rows(min_row=2, values_only=True):
        row = {headers[i]: values[i] for i in range(min(len(headers), len(values)))}
        if not any(v is not None and str(v).strip() != '' for v in row.values()):
            continue
        rows.append(row)
    return rows


def _split_top_level(text: str, delimiter: str = ';') -> list[str]:
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


def _normalize_number(value_text: str) -> Any:
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


def _parse_actions(cell_value: Any) -> list[dict[str, Any]]:
    text = _cell_str(cell_value)
    if not text:
        return []

    actions: list[dict[str, Any]] = []
    for token in _split_top_level(text, ';'):
        parts = [part.strip() for part in token.split(':')]
        if len(parts) not in {2, 3}:
            raise ValueError(f"Invalid action syntax '{token}'. Use target:value[:ramp_seconds]")
        target = parts[0]
        value = _normalize_number(parts[1])
        if len(parts) == 2:
            actions.append({
                'kind': 'write',
                'target': target,
                'value': value,
                'duration_s': None,
                'owner': None,
                'params': {},
            })
        else:
            actions.append({
                'kind': 'ramp',
                'target': target,
                'value': value,
                'duration_s': float(parts[2]),
                'owner': None,
                'params': {},
            })
    return actions


def _parse_condition(expr: str) -> dict[str, Any]:
    parts = [part.strip() for part in expr.split(':')]
    if len(parts) not in {4, 5} or parts[0] != 'cond':
        raise ValueError(
            f"Invalid condition syntax '{expr}'. Use cond:source:operator:threshold[:for_seconds]"
        )
    condition = {
        'source': parts[1],
        'operator': parts[2],
        'threshold': _normalize_number(parts[3]),
    }
    if len(parts) == 5 and parts[4] != '':
        condition['for_s'] = float(parts[4])
    return {'kind': 'condition', 'condition': condition}


def _parse_elapsed(expr: str) -> dict[str, Any]:
    parts = [part.strip() for part in expr.split(':')]
    if len(parts) != 2 or parts[0] != 'elapsed':
        raise ValueError(f"Invalid elapsed syntax '{expr}'. Use elapsed:seconds")
    return {'kind': 'elapsed', 'duration_s': float(parts[1])}


def _parse_wait_expr(expr: str) -> dict[str, Any]:
    expr = expr.strip()
    if not expr:
        return None

    if expr.startswith('all(') and expr.endswith(')'):
        inner = expr[4:-1].strip()
        return {
            'kind': 'all_of',
            'children': [_parse_wait_expr(part) for part in _split_top_level(inner, ';')],
        }

    if expr.startswith('any(') and expr.endswith(')'):
        inner = expr[4:-1].strip()
        return {
            'kind': 'any_of',
            'children': [_parse_wait_expr(part) for part in _split_top_level(inner, ';')],
        }

    if expr.startswith('elapsed:'):
        return _parse_elapsed(expr)

    if expr.startswith('cond:'):
        return _parse_condition(expr)

    raise ValueError(
        f"Invalid wait syntax '{expr}'. Use elapsed:..., cond:..., all(...), or any(...)"
    )


def _build_step(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': _cell_str(row.get('step_id')),
        'name': _cell_str(row.get('name')),
        'actions': _parse_actions(row.get('actions')),
        'wait': _parse_wait_expr(_cell_str(row.get('wait')) or ''),
        'enabled': _cell_bool(row.get('enabled'), True),
    }


def parse_schedule_workbook(file_bytes: bytes, filename: str = 'schedule.xlsx') -> dict[str, Any]:
    wb = load_workbook(BytesIO(file_bytes), data_only=True)
    meta = _read_meta_sheet(wb)
    setup_rows = _read_steps_sheet(wb, 'setup_steps')
    plan_rows = _read_steps_sheet(wb, 'plan_steps')

    return {
        'id': meta.get('id') or filename.rsplit('.', 1)[0],
        'name': meta.get('name') or meta.get('id') or filename,
        'setup_steps': [_build_step(row) for row in setup_rows],
        'plan_steps': [_build_step(row) for row in plan_rows],
    }