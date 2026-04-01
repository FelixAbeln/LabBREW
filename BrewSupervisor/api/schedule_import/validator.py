from __future__ import annotations

from typing import Any

VALID_ACTION_KINDS = {'request_control', 'write', 'ramp', 'release_control', 'global_measurement', 'take_loadstep'}
VALID_WAIT_KINDS = {None, 'elapsed', 'condition', 'all_of', 'any_of', 'rising', 'falling', 'pulse'}
VALID_OPERATORS = {'==', '!=', '>', '>=', '<', '<='}


def _add_issue(
    issues: list[dict[str, Any]],
    *,
    level: str,
    code: str,
    path: str,
    message: str,
    **extra: Any,
) -> None:
    issue = {
        'level': level,
        'code': code,
        'path': path,
        'message': message,
    }
    issue.update(extra)
    issues.append(issue)


def _require_parameter(
    *,
    parameter: str,
    path: str,
    source: str,
    available_parameters: set[str] | None,
    issues: list[dict[str, Any]],
) -> None:
    if available_parameters is None:
        return
    if parameter in available_parameters:
        return
    _add_issue(
        issues,
        level='error',
        code='UNKNOWN_PARAMETER',
        path=path,
        message=f"Unknown parameter '{parameter}' referenced in {source}",
        parameter=parameter,
        source=source,
    )


def _validate_action(
    action: dict[str, Any],
    prefix: str,
    issues: list[dict[str, Any]],
    *,
    available_parameters: set[str] | None,
    default_loadstep_duration_seconds: float | None,
) -> None:
    kind = action.get('kind')
    if kind not in VALID_ACTION_KINDS:
        _add_issue(
            issues,
            level='error',
            code='INVALID_ACTION_KIND',
            path=prefix,
            message=f"{prefix}: invalid action kind '{kind}'",
            kind=kind,
        )
        return

    if kind in {'request_control', 'write', 'ramp', 'release_control'} and not action.get('target'):
        _add_issue(
            issues,
            level='error',
            code='MISSING_ACTION_TARGET',
            path=prefix,
            message=f"{prefix}: target is required for action kind '{kind}'",
            kind=kind,
        )

    if kind in {'request_control', 'write', 'ramp', 'release_control'} and action.get('target'):
        _require_parameter(
            parameter=str(action.get('target')),
            path=f'{prefix}.target',
            source=f'action.{kind}',
            available_parameters=available_parameters,
            issues=issues,
        )

    if kind == 'write' and action.get('value') is None:
        _add_issue(
            issues,
            level='error',
            code='MISSING_WRITE_VALUE',
            path=f'{prefix}.value',
            message=f"{prefix}: value is required for write",
        )

    if kind == 'ramp':
        if action.get('value') is None:
            _add_issue(
                issues,
                level='error',
                code='MISSING_RAMP_VALUE',
                path=f'{prefix}.value',
                message=f"{prefix}: value is required for ramp",
            )
        if action.get('duration_s') in (None, ''):
            _add_issue(
                issues,
                level='error',
                code='MISSING_RAMP_DURATION',
                path=f'{prefix}.duration_s',
                message=f"{prefix}: duration_s is required for ramp",
            )

    if kind == 'global_measurement':
        mode = str(action.get('value') or (action.get('params') or {}).get('mode') or 'start').strip().lower()
        if mode not in {'start', 'setup_start', 'stop'}:
            _add_issue(
                issues,
                level='error',
                code='INVALID_GLOBAL_MEASUREMENT_MODE',
                path=f'{prefix}.value',
                message=f"{prefix}: global_measurement mode must be one of ['start', 'setup_start', 'stop']",
                mode=mode,
            )

        params = action.get('params') if isinstance(action.get('params'), dict) else {}
        listed = params.get('parameters')
        if isinstance(listed, list):
            for idx, param in enumerate(listed):
                _require_parameter(
                    parameter=str(param),
                    path=f'{prefix}.params.parameters[{idx}]',
                    source='global_measurement.parameters',
                    available_parameters=available_parameters,
                    issues=issues,
                )

    if kind == 'take_loadstep':
        params = action.get('params') if isinstance(action.get('params'), dict) else {}
        duration_value = action.get('duration_s')
        if duration_value in (None, ''):
            duration_value = params.get('duration_seconds')
        if duration_value in (None, ''):
            duration_value = default_loadstep_duration_seconds
        if duration_value in (None, ''):
            _add_issue(
                issues,
                level='error',
                code='MISSING_LOADSTEP_DURATION',
                path=prefix,
                message=f"{prefix}: duration_s (or params.duration_seconds, or measurement_config.loadstep_duration_seconds) is required for take_loadstep",
            )
        else:
            try:
                if float(duration_value) <= 0:
                    raise ValueError('non-positive duration')
            except (TypeError, ValueError):
                _add_issue(
                    issues,
                    level='error',
                    code='INVALID_LOADSTEP_DURATION',
                    path=f'{prefix}.duration_s',
                    message=f"{prefix}: loadstep duration must be a positive number",
                )

        trigger_wait = params.get('trigger_wait')
        if trigger_wait is not None:
            if isinstance(trigger_wait, dict):
                _validate_wait(
                    trigger_wait,
                    f'{prefix}.params.trigger_wait',
                    issues,
                    available_parameters=available_parameters,
                )
            else:
                _add_issue(
                    issues,
                    level='error',
                    code='INVALID_LOADSTEP_TRIGGER',
                    path=f'{prefix}.params.trigger_wait',
                    message=f"{prefix}: params.trigger_wait must be a wait expression object",
                )

        listed = params.get('parameters')
        if isinstance(listed, list):
            for idx, param in enumerate(listed):
                _require_parameter(
                    parameter=str(param),
                    path=f'{prefix}.params.parameters[{idx}]',
                    source='take_loadstep.parameters',
                    available_parameters=available_parameters,
                    issues=issues,
                )


def _validate_wait(
    wait: dict[str, Any] | None,
    prefix: str,
    issues: list[dict[str, Any]],
    *,
    available_parameters: set[str] | None,
) -> None:
    if wait is None:
        return

    kind = wait.get('kind')
    if kind not in VALID_WAIT_KINDS:
        _add_issue(
            issues,
            level='error',
            code='INVALID_WAIT_KIND',
            path=prefix,
            message=f"{prefix}: invalid wait kind '{kind}'",
            kind=kind,
        )
        return

    if kind == 'elapsed':
        if wait.get('duration_s') in (None, ''):
            _add_issue(
                issues,
                level='error',
                code='MISSING_ELAPSED_DURATION',
                path=f'{prefix}.duration_s',
                message=f"{prefix}: duration_s is required for elapsed wait",
            )
        return

    if kind == 'condition':
        cond = wait.get('condition') or {}
        if not cond.get('source'):
            _add_issue(
                issues,
                level='error',
                code='MISSING_CONDITION_SOURCE',
                path=f'{prefix}.condition.source',
                message=f"{prefix}.condition: source is required",
            )
        if cond.get('operator') not in VALID_OPERATORS:
            _add_issue(
                issues,
                level='error',
                code='INVALID_CONDITION_OPERATOR',
                path=f'{prefix}.condition.operator',
                message=f"{prefix}.condition: operator must be one of {sorted(VALID_OPERATORS)}",
                operator=cond.get('operator'),
            )
        if cond.get('threshold') in (None, ''):
            _add_issue(
                issues,
                level='error',
                code='MISSING_CONDITION_THRESHOLD',
                path=f'{prefix}.condition.threshold',
                message=f"{prefix}.condition: threshold is required",
            )
        source = cond.get('source')
        if source:
            _require_parameter(
                parameter=str(source),
                path=f'{prefix}.condition.source',
                source='wait.condition.source',
                available_parameters=available_parameters,
                issues=issues,
            )
        if cond.get('for_s') not in (None, ''):
            try:
                float(cond.get('for_s'))
            except (TypeError, ValueError):
                _add_issue(
                    issues,
                    level='error',
                    code='INVALID_CONDITION_FOR_SECONDS',
                    path=f'{prefix}.condition.for_s',
                    message=f"{prefix}.condition: for_s must be numeric",
                )
        return

    if kind in {'rising', 'falling', 'pulse'}:
        child = wait.get('child')
        if not isinstance(child, dict):
            _add_issue(
                issues,
                level='error',
                code='MISSING_WAIT_CHILD',
                path=f'{prefix}.child',
                message=f"{prefix}: {kind} requires a child wait expression",
                kind=kind,
            )
            return

        if kind == 'pulse':
            hold_s = wait.get('hold_s')
            if hold_s in (None, ''):
                _add_issue(
                    issues,
                    level='error',
                    code='MISSING_PULSE_HOLD_SECONDS',
                    path=f'{prefix}.hold_s',
                    message=f"{prefix}: pulse requires hold_s in seconds",
                )
            else:
                try:
                    if float(hold_s) < 0:
                        raise ValueError('negative hold_s')
                except (TypeError, ValueError):
                    _add_issue(
                        issues,
                        level='error',
                        code='INVALID_PULSE_HOLD_SECONDS',
                        path=f'{prefix}.hold_s',
                        message=f"{prefix}: pulse hold_s must be a non-negative number",
                    )

        _validate_wait(
            child,
            f"{prefix}.child",
            issues,
            available_parameters=available_parameters,
        )
        return

    children = wait.get('children')
    if not isinstance(children, list) or not children:
        _add_issue(
            issues,
            level='error',
            code='MISSING_WAIT_CHILDREN',
            path=f'{prefix}.children',
            message=f"{prefix}: {kind} requires at least one child wait",
            kind=kind,
        )
        return
    for index, child in enumerate(children):
        _validate_wait(
            child,
            f"{prefix}.children[{index}]",
            issues,
            available_parameters=available_parameters,
        )


def _validate_step(
    step: dict[str, Any],
    phase: str,
    index: int,
    issues: list[dict[str, Any]],
    *,
    available_parameters: set[str] | None,
    default_loadstep_duration_seconds: float | None,
) -> None:
    prefix = f"{phase}[{index}]"
    if not step.get('id'):
        _add_issue(
            issues,
            level='error',
            code='MISSING_STEP_ID',
            path=f'{prefix}.id',
            message=f"{prefix}: step id is required",
        )
    if not step.get('name'):
        _add_issue(
            issues,
            level='error',
            code='MISSING_STEP_NAME',
            path=f'{prefix}.name',
            message=f"{prefix}: step name is required",
        )

    actions = step.get('actions', [])
    if not isinstance(actions, list):
        _add_issue(
            issues,
            level='error',
            code='INVALID_ACTIONS_TYPE',
            path=f'{prefix}.actions',
            message=f"{prefix}: actions must be a list",
        )
    else:
        for action_index, action in enumerate(actions):
            _validate_action(
                action,
                f"{prefix}.actions[{action_index}]",
                issues,
                available_parameters=available_parameters,
                default_loadstep_duration_seconds=default_loadstep_duration_seconds,
            )

    if not actions:
        _add_issue(
            issues,
            level='warning',
            code='STEP_HAS_NO_ACTIONS',
            path=f'{prefix}.actions',
            message=f"{prefix}: step has no actions",
        )

    _validate_wait(
        step.get('wait'),
        f"{prefix}.wait",
        issues,
        available_parameters=available_parameters,
    )


def _validate_measurement_config(
    payload: dict[str, Any],
    issues: list[dict[str, Any]],
    *,
    available_parameters: set[str] | None,
) -> None:
    measurement = payload.get('measurement_config')
    if not isinstance(measurement, dict):
        return
    params = measurement.get('parameters')
    if not isinstance(params, list):
        return
    for idx, name in enumerate(params):
        _require_parameter(
            parameter=str(name),
            path=f'measurement_config.parameters[{idx}]',
            source='measurement_config.parameters',
            available_parameters=available_parameters,
            issues=issues,
        )

    loadstep_default = measurement.get('loadstep_duration_seconds')
    if loadstep_default not in (None, ''):
        try:
            if float(loadstep_default) <= 0:
                raise ValueError('non-positive default')
        except (TypeError, ValueError):
            _add_issue(
                issues,
                level='error',
                code='INVALID_LOADSTEP_DEFAULT_DURATION',
                path='measurement_config.loadstep_duration_seconds',
                message='measurement_config.loadstep_duration_seconds must be a positive number',
            )


def validate_schedule_payload(
    payload: dict[str, Any],
    *,
    available_parameters: set[str] | None = None,
    extra_parameter_references: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    measurement_cfg = payload.get('measurement_config') if isinstance(payload.get('measurement_config'), dict) else {}
    default_loadstep_duration_seconds = measurement_cfg.get('loadstep_duration_seconds')

    if not payload.get('id'):
        _add_issue(
            issues,
            level='error',
            code='MISSING_SCHEDULE_ID',
            path='id',
            message='schedule id is required',
        )
    if not payload.get('name'):
        _add_issue(
            issues,
            level='error',
            code='MISSING_SCHEDULE_NAME',
            path='name',
            message='schedule name is required',
        )

    _validate_measurement_config(
        payload,
        issues,
        available_parameters=available_parameters,
    )

    for phase in ('setup_steps', 'plan_steps'):
        steps = payload.get(phase)
        if steps is None:
            _add_issue(
                issues,
                level='error',
                code='MISSING_PHASE',
                path=phase,
                message=f'{phase} is required',
            )
            continue
        if not isinstance(steps, list):
            _add_issue(
                issues,
                level='error',
                code='INVALID_PHASE_TYPE',
                path=phase,
                message=f'{phase} must be a list',
            )
            continue
        for index, step in enumerate(steps):
            _validate_step(
                step,
                phase,
                index,
                issues,
                available_parameters=available_parameters,
                default_loadstep_duration_seconds=default_loadstep_duration_seconds,
            )

    for item in extra_parameter_references or []:
        parameter = str(item.get('parameter') or '').strip()
        if not parameter:
            continue
        _require_parameter(
            parameter=parameter,
            path=str(item.get('path') or 'schedule_import'),
            source=str(item.get('source') or 'workbook_reference'),
            available_parameters=available_parameters,
            issues=issues,
        )

    errors = [item['message'] for item in issues if item.get('level') == 'error']
    warnings = [item['message'] for item in issues if item.get('level') == 'warning']
    error_codes = sorted({str(item.get('code')) for item in issues if item.get('level') == 'error'})
    warning_codes = sorted({str(item.get('code')) for item in issues if item.get('level') == 'warning'})

    return {
        'valid': not errors,
        'errors': errors,
        'warnings': warnings,
        'error_codes': error_codes,
        'warning_codes': warning_codes,
        'issues': issues,
    }