from __future__ import annotations

from typing import Any

VALID_ACTION_KINDS = {'request_control', 'write', 'ramp', 'release_control'}
VALID_WAIT_KINDS = {None, 'elapsed', 'condition', 'all_of', 'any_of'}
VALID_OPERATORS = {'==', '!=', '>', '>=', '<', '<='}


def _validate_action(action: dict[str, Any], prefix: str, errors: list[str]) -> None:
    kind = action.get('kind')
    if kind not in VALID_ACTION_KINDS:
        errors.append(f"{prefix}: invalid action kind '{kind}'")
        return

    if kind in {'request_control', 'write', 'ramp', 'release_control'} and not action.get('target'):
        errors.append(f"{prefix}: target is required for action kind '{kind}'")

    if kind == 'write' and action.get('value') is None:
        errors.append(f"{prefix}: value is required for write")

    if kind == 'ramp':
        if action.get('value') is None:
            errors.append(f"{prefix}: value is required for ramp")
        if action.get('duration_s') in (None, ''):
            errors.append(f"{prefix}: duration_s is required for ramp")


def _validate_wait(wait: dict[str, Any] | None, prefix: str, errors: list[str]) -> None:
    if wait is None:
        return

    kind = wait.get('kind')
    if kind not in VALID_WAIT_KINDS:
        errors.append(f"{prefix}: invalid wait kind '{kind}'")
        return

    if kind == 'elapsed':
        if wait.get('duration_s') in (None, ''):
            errors.append(f"{prefix}: duration_s is required for elapsed wait")
        return

    if kind == 'condition':
        cond = wait.get('condition') or {}
        if not cond.get('source'):
            errors.append(f"{prefix}.condition: source is required")
        if cond.get('operator') not in VALID_OPERATORS:
            errors.append(f"{prefix}.condition: operator must be one of {sorted(VALID_OPERATORS)}")
        if cond.get('threshold') in (None, ''):
            errors.append(f"{prefix}.condition: threshold is required")
        if cond.get('for_s') not in (None, ''):
            try:
                float(cond.get('for_s'))
            except (TypeError, ValueError):
                errors.append(f"{prefix}.condition: for_s must be numeric")
        return

    children = wait.get('children')
    if not isinstance(children, list) or not children:
        errors.append(f"{prefix}: {kind} requires at least one child wait")
        return
    for index, child in enumerate(children):
        _validate_wait(child, f"{prefix}.children[{index}]", errors)


def _validate_step(step: dict[str, Any], phase: str, index: int, errors: list[str], warnings: list[str]) -> None:
    prefix = f"{phase}[{index}]"
    if not step.get('id'):
        errors.append(f"{prefix}: step id is required")
    if not step.get('name'):
        errors.append(f"{prefix}: step name is required")

    actions = step.get('actions', [])
    if not isinstance(actions, list):
        errors.append(f"{prefix}: actions must be a list")
    else:
        for action_index, action in enumerate(actions):
            _validate_action(action, f"{prefix}.actions[{action_index}]", errors)

    if not actions:
        warnings.append(f"{prefix}: step has no actions")

    _validate_wait(step.get('wait'), f"{prefix}.wait", errors)


def validate_schedule_payload(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not payload.get('id'):
        errors.append('schedule id is required')
    if not payload.get('name'):
        errors.append('schedule name is required')

    for phase in ('setup_steps', 'plan_steps'):
        steps = payload.get(phase)
        if steps is None:
            errors.append(f'{phase} is required')
            continue
        if not isinstance(steps, list):
            errors.append(f'{phase} must be a list')
            continue
        for index, step in enumerate(steps):
            _validate_step(step, phase, index, errors, warnings)

    return {
        'valid': not errors,
        'errors': errors,
        'warnings': warnings,
    }