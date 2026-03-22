from __future__ import annotations

import os
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _normalize_fmu_path(path: str) -> str:
    path = str(path or '').strip()
    if not path:
        return ''
    try:
        return os.path.normcase(os.path.normpath(str(Path(path).expanduser().resolve(strict=False))))
    except Exception:
        return os.path.normcase(os.path.normpath(path))


def _parse_fmu(path: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], str | None]:
    raw_path = str(path or '').strip()
    if not raw_path:
        return '', [], [], 'Choose an FMU path first.'
    p = Path(raw_path)
    if not p.exists():
        return '', [], [], f'FMU not found: {p}'
    if p.suffix.lower() != '.fmu':
        return '', [], [], f'Not an FMU file: {p.name}'
    try:
        with zipfile.ZipFile(p, 'r') as zf:
            xml_bytes = zf.read('modelDescription.xml')
        root = ET.fromstring(xml_bytes)
    except Exception as exc:
        return '', [], [], f'Failed to read FMU: {exc}'
    model_name = root.attrib.get('modelName') or p.stem
    model_vars = root.find('ModelVariables')
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    if model_vars is None:
        return model_name, inputs, outputs, None
    for sv in model_vars:
        causality = (sv.attrib.get('causality') or '').strip()
        if causality not in {'input', 'output'}:
            continue
        var_type = 'Unknown'
        if len(sv):
            tag = sv[0].tag
            if '}' in tag:
                tag = tag.rsplit('}', 1)[1]
            var_type = tag
        item = {
            'name': sv.attrib.get('name', ''),
            'type': var_type,
            'description': sv.attrib.get('description', '') or '',
        }
        (inputs if causality == 'input' else outputs).append(item)
    return model_name, inputs, outputs, None


def _build_dynamic_sections(config: dict[str, Any]) -> list[dict[str, Any]]:
    model_name, inputs, outputs, error = _parse_fmu(config.get('fmu_path', ''))
    input_bindings = dict(config.get('input_bindings') or {}) if isinstance(config.get('input_bindings'), dict) else {}
    output_params = dict(config.get('output_params') or {}) if isinstance(config.get('output_params'), dict) else {}
    summary = {
        'normalized_fmu_path': _normalize_fmu_path(config.get('fmu_path', '')),
        'model_name': model_name,
        'input_count': len(inputs),
        'output_count': len(outputs),
        'error': error,
        'inputs': inputs,
        'outputs': outputs,
    }
    sections = [
        {
            'title': 'Discovered FMU',
            'fields': [
                {'key': 'config.discovered_fmu', 'label': 'FMU Summary', 'type': 'json', 'readonly': True, 'help': 'Auto-generated from the current FMU path when the edit form is opened.'},
            ],
        }
    ]
    if inputs:
        sections.append({
            'title': 'Input Bindings',
            'fields': [
                {
                    'key': f'config.input_bindings.{item["name"]}',
                    'label': f'{item["name"]} ({item["type"]})',
                    'type': 'parameter_ref',
                    'required': False,
                    'help': item.get('description') or 'Parameter to feed this FMU input.',
                }
                for item in inputs
            ],
        })
    else:
        sections.append({
            'title': 'Input Bindings',
            'fields': [
                {'key': 'config.input_bindings', 'label': 'Input Bindings', 'type': 'json', 'required': False, 'help': error or 'No input variables were discovered from this FMU.'},
            ],
        })
    if outputs:
        sections.append({
            'title': 'Output Targets',
            'fields': [
                {
                    'key': f'config.output_params.{item["name"]}',
                    'label': f'{item["name"]} ({item["type"]})',
                    'type': 'parameter_ref',
                    'required': False,
                    'help': item.get('description') or 'Optional extra mirror target for this FMU output. The twin can also manage its own output parameters automatically.',
                }
                for item in outputs
            ],
        })
    else:
        sections.append({
            'title': 'Output Targets',
            'fields': [
                {'key': 'config.output_params', 'label': 'Output Targets', 'type': 'json', 'required': False, 'help': error or 'No output variables were discovered from this FMU.'},
            ],
        })
    if 'discovered_fmu' not in config:
        config['discovered_fmu'] = summary
    else:
        config['discovered_fmu'] = summary
    for name, target in input_bindings.items():
        config.setdefault('input_bindings', {})[name] = target
    for name, target in output_params.items():
        config.setdefault('output_params', {})[name] = target
    return sections


def get_ui_spec(record: dict[str, Any] | None = None, mode: str | None = None) -> dict:
    record = dict(record or {})
    config = dict(record.get('config') or {})
    edit_sections = [
        {
            'title': 'Identity',
            'fields': [
                {'key': 'name', 'label': 'Source Name', 'type': 'string', 'required': True},
                {'key': 'config.parameter_prefix', 'label': 'Parameter Prefix', 'type': 'string', 'required': True},
            ],
        },
        {
            'title': 'FMU',
            'fields': [
                {'key': 'config.fmu_path', 'label': 'FMU Path', 'type': 'string', 'required': True, 'help': 'Pick the FMU first. The edit form will discover its inputs and outputs from modelDescription.xml.'},
                {'key': 'config.enabled', 'label': 'Enabled', 'type': 'bool', 'required': False},
                {'key': 'config.update_interval_s', 'label': 'Scan Interval (s)', 'type': 'float', 'required': True},
                {'key': 'config.reconnect_delay_s', 'label': 'Retry Delay (s)', 'type': 'float', 'required': True},
            ],
        },
        {
            'title': 'Outputs',
            'fields': [
                {'key': 'config.auto_manage_outputs', 'label': 'Auto-manage discovered outputs', 'type': 'bool', 'required': False, 'help': 'Create one parameter per discovered FMU output and remove stale managed outputs when the FMU changes.'},
                {'key': 'config.managed_output_prefix', 'label': 'Managed Output Prefix', 'type': 'string', 'required': False, 'help': 'Defaults to <parameter_prefix>.outputs.'},
                {'key': 'config.reset_nonce', 'label': 'Reset Token', 'type': 'int', 'required': False, 'help': 'Bump this number and save to force a reinitialize/restart of the twin from the admin UI.'},
                {'key': 'config.reset_param', 'label': 'Reset Parameter', 'type': 'string', 'required': False, 'help': 'Optional parameter name that can be pulsed/set by automation. The twin resets itself when this parameter becomes truthy, then clears it back to false.'},
            ],
        },
    ]
    if mode == 'edit' or record:
        edit_sections.extend(_build_dynamic_sections(config))
        record['config'] = config

    return {
        'source_type': 'digital_twin',
        'display_name': 'Digital Twin FMU',
        'description': 'Creates a digital twin data source from an FMU. Create with just the FMU path, then edit to bind discovered inputs and outputs. Discovered outputs can also be auto-created by the twin itself.',
        'create': {
            'required': ['name', 'config.fmu_path'],
            'defaults': {
                'config': {
                    'fmu_path': '',
                    'enabled': True,
                    'update_interval_s': 0.25,
                    'reconnect_delay_s': 2.0,
                    'parameter_prefix': 'twin',
                    'input_bindings': {},
                    'output_params': {},
                    'auto_manage_outputs': True,
                    'managed_output_prefix': '',
                    'reset_nonce': 0,
                    'reset_param': '',
                    'discovered_fmu': {},
                }
            },
            'sections': [
                {
                    'title': 'Identity',
                    'fields': [
                        {'key': 'name', 'label': 'Source Name', 'type': 'string', 'required': True},
                        {'key': 'config.parameter_prefix', 'label': 'Parameter Prefix', 'type': 'string', 'required': True},
                    ],
                },
                {
                    'title': 'FMU',
                    'fields': [
                        {'key': 'config.fmu_path', 'label': 'FMU Path', 'type': 'string', 'required': True},
                        {'key': 'config.enabled', 'label': 'Enabled', 'type': 'bool', 'required': False},
                        {'key': 'config.update_interval_s', 'label': 'Scan Interval (s)', 'type': 'float', 'required': True},
                        {'key': 'config.reconnect_delay_s', 'label': 'Retry Delay (s)', 'type': 'float', 'required': True},
                    ],
                },
            ],
        },
        'edit': {
            'defaults': {'config': config},
            'sections': edit_sections,
        },
    }
