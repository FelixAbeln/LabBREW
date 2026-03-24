from __future__ import annotations

import os
import shutil
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ...parameterdb_core.client import SupportsSignalRequests
from ...parameterdb_sources.base import DataSourceBase, DataSourceSpec

try:
    from fmpy import extract, instantiate_fmu, read_model_description
    _HAS_FMPY = True
except Exception:
    extract = instantiate_fmu = read_model_description = None
    _HAS_FMPY = False


@dataclass(slots=True)
class TwinVariable:
    name: str
    var_type: str
    causality: str
    description: str = ''
    value_reference: Optional[int] = None


class DigitalTwinSource(DataSourceBase):
    source_type = "digital_twin"
    display_name = "Digital Twin FMU"
    description = "Loads an FMU, binds input variables to parameters, and mirrors FMU outputs back into parameters."

    def __init__(self, name: str, client: SupportsSignalRequests, *, config: dict[str, Any] | None = None) -> None:
        super().__init__(name, client, config=config)
        self.loaded_fmu_path: str = ''
        self.model_name: str = ''
        self.last_status_text: str = 'No FMU loaded'
        self._last_error: str = ''
        self.input_vars: list[TwinVariable] = []
        self.output_vars: list[TwinVariable] = []
        self._runtime_mode = 'none'
        self._unzipdir: Optional[str] = None
        self._model_description = None
        self._fmu = None
        self._sim_time = 0.0
        self._last_eval_monotonic: Optional[float] = None
        self._input_map: dict[str, TwinVariable] = {}
        self._output_map: dict[str, TwinVariable] = {}
        self._step_count = 0
        self._last_dt: Optional[float] = None
        self._last_step_wallclock: Optional[float] = None
        self._managed_output_targets: dict[str, str] = {}
        self._handled_reset_value: Any = None
        self._reset_count = 0
        self._last_reset_reason = ''

    @staticmethod
    def _normalize_fmu_path(path: str) -> str:
        path = str(path or '').strip()
        if not path:
            return ''
        try:
            return os.path.normcase(os.path.normpath(str(Path(path).expanduser().resolve(strict=False))))
        except Exception:
            return os.path.normcase(os.path.normpath(path))

    def _prefix(self) -> str:
        return str(self.config.get('parameter_prefix', self.name)).strip() or self.name

    def _status_param(self, key: str) -> str:
        explicit = self.config.get(f'{key}_param')
        if explicit:
            return str(explicit)
        return f'{self._prefix()}.{key}'

    def _set_status(self, key: str, value: Any) -> None:
        self.client.set_value(self._status_param(key), value)

    def _input_bindings(self) -> dict[str, str]:
        raw = self.config.get('input_bindings') or {}
        return dict(raw) if isinstance(raw, dict) else {}

    def _output_params(self) -> dict[str, str]:
        raw = self.config.get('output_params') or {}
        return dict(raw) if isinstance(raw, dict) else {}

    def _auto_manage_outputs(self) -> bool:
        return bool(self.config.get('auto_manage_outputs', True))

    def _managed_output_prefix(self) -> str:
        raw = str(self.config.get('managed_output_prefix', '') or '').strip()
        return raw or f'{self._prefix()}.outputs'

    @staticmethod
    def _sanitize_segment(name: str) -> str:
        clean = ''.join(ch if ch.isalnum() or ch == '_' else '_' for ch in str(name or '').strip())
        clean = clean.strip('_')
        return clean or 'output'

    def _managed_output_name(self, output_name: str) -> str:
        return f"{self._managed_output_prefix()}.{self._sanitize_segment(output_name)}"

    def _reset_param_name(self) -> str:
        explicit = str(self.config.get('reset_param', '') or '').strip()
        return explicit or f'{self._prefix()}.reset'

    def _desired_managed_outputs(self) -> dict[str, str]:
        if not self._auto_manage_outputs():
            return {}
        return {var.name: self._managed_output_name(var.name) for var in self.output_vars if str(var.name or '').strip()}

    def _publish_status(self, **extra: Any) -> None:
        payload = {
            'fmu_path': self.loaded_fmu_path or str(self.config.get('fmu_path', '') or ''),
            'model_name': self.model_name,
            'runtime_mode': self._runtime_mode,
            'last_status_text': self.last_status_text,
            'input_count': len(self.input_vars),
            'output_count': len(self.output_vars),
            'step_count': self._step_count,
            'sim_time_s': self._sim_time,
            'last_dt_s': self._last_dt,
            'last_step_age_s': (time.monotonic() - self._last_step_wallclock) if self._last_step_wallclock else None,
            'discovered_inputs': [self._variable_info(var) for var in self.input_vars],
            'discovered_outputs': [self._variable_info(var) for var in self.output_vars],
            'managed_output_targets': dict(self._managed_output_targets),
            'reset_param': self._reset_param_name(),
            'reset_count': self._reset_count,
            'last_reset_reason': self._last_reset_reason,
        }
        payload.update(extra)
        explicit_error = str(extra.get('last_error', '') or '').strip()
        if explicit_error:
            self._last_error = explicit_error
        self._set_status('status', dict(payload))
        self._set_status('connected', bool(self.loaded_fmu_path))
        self._set_status('last_error', self._last_error)
        self._set_status('last_sync', datetime.now(timezone.utc).isoformat())

    def _set_error(self, message: str) -> None:
        self._last_error = str(message)

    def _clear_error(self) -> None:
        self._last_error = ''

    @staticmethod
    def _variable_info(var: TwinVariable) -> dict[str, Any]:
        return {
            'name': var.name,
            'type': var.var_type,
            'causality': var.causality,
            'description': var.description,
            'value_reference': var.value_reference,
        }

    def _sync_managed_outputs(self, owned: dict[str, Any]) -> None:
        desired = self._desired_managed_outputs()
        self._managed_output_targets = dict(desired)
        for output_name, target in desired.items():
            self.ensure_parameter(target, 'static', value=None, metadata={**owned, 'role': 'twin_output', 'fmu_output': output_name, 'managed_output': True})
        prefix = self._managed_output_prefix().rstrip('.')
        if not prefix:
            return
        try:
            names = self.client.list_parameters()
        except Exception:
            return
        keep = set(desired.values())
        for name in names:
            if name in keep:
                continue
            if name == prefix or name.startswith(prefix + '.'):
                try:
                    self.client.delete_parameter(name)
                except Exception:
                    pass

    def ensure_parameters(self) -> None:
        owned = self.build_owned_metadata(device='digital_twin')
        self.ensure_parameter(self._status_param('connected'), 'static', value=False, metadata={**owned, 'role': 'status'})
        self.ensure_parameter(self._status_param('last_error'), 'static', value='', metadata={**owned, 'role': 'status'})
        self.ensure_parameter(self._status_param('last_sync'), 'static', value='', metadata={**owned, 'role': 'status'})
        self.ensure_parameter(self._status_param('status'), 'static', value={}, metadata={**owned, 'role': 'status'})
        self.ensure_parameter(self._reset_param_name(), 'static', value=False, metadata={**owned, 'role': 'control', 'control_action': 'reset_twin'})
        self._sync_managed_outputs(owned)
        for output_name, target in self._output_params().items():
            if not str(target).strip():
                continue
            self.ensure_parameter(str(target), 'static', value=None, metadata={**owned, 'role': 'twin_output', 'fmu_output': output_name})

    def _cleanup_runtime(self) -> None:
        try:
            if self._fmu is not None:
                try:
                    self._fmu.terminate()
                except Exception:
                    pass
                try:
                    self._fmu.freeInstance()
                except Exception:
                    pass
        finally:
            self._fmu = None
        if self._unzipdir:
            shutil.rmtree(self._unzipdir, ignore_errors=True)
            self._unzipdir = None
        self._model_description = None
        self._runtime_mode = 'none'
        self._sim_time = 0.0
        self._last_eval_monotonic = None
        self._input_map = {}
        self._output_map = {}
        self._step_count = 0
        self._last_dt = None
        self._last_step_wallclock = None

    def _parse_fmu_variables(self, path: Path) -> tuple[str, list[TwinVariable], list[TwinVariable]]:
        with zipfile.ZipFile(path, 'r') as zf:
            xml_bytes = zf.read('modelDescription.xml')
        root = ET.fromstring(xml_bytes)
        model_name = root.attrib.get('modelName') or path.stem
        model_vars = root.find('ModelVariables')
        inputs: list[TwinVariable] = []
        outputs: list[TwinVariable] = []
        if model_vars is None:
            return model_name, inputs, outputs
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
            vr = sv.attrib.get('valueReference')
            try:
                vr_i = int(vr) if vr is not None else None
            except Exception:
                vr_i = None
            var = TwinVariable(
                name=sv.attrib.get('name', ''),
                var_type=var_type,
                causality=causality,
                description=sv.attrib.get('description', '') or '',
                value_reference=vr_i,
            )
            (inputs if causality == 'input' else outputs).append(var)
        return model_name, inputs, outputs

    def _initialize_runtime(self, p: Path) -> None:
        self._cleanup_runtime()
        if not _HAS_FMPY:
            self._runtime_mode = 'metadata'
            self.last_status_text = f'FMU loaded: {p.name} (metadata only - install fmpy for runtime)'
            self._clear_error()
            return
        try:
            self._model_description = read_model_description(str(p))
            cs = getattr(self._model_description, 'coSimulation', None)
            if cs is None:
                self._runtime_mode = 'metadata'
                self.last_status_text = f'FMU loaded: {p.name} (no co-simulation runtime)'
                return
            tmpdir = tempfile.mkdtemp(prefix='parameterdb_fmu_')
            self._unzipdir = extract(str(p), unzipdir=tmpdir)
            self._fmu = instantiate_fmu(self._unzipdir, self._model_description, 'CoSimulation')
            self._fmu.setupExperiment(startTime=0.0)
            self._fmu.enterInitializationMode()
            self._fmu.exitInitializationMode()
            self._input_map = {v.name: v for v in self.input_vars if v.value_reference is not None}
            self._output_map = {v.name: v for v in self.output_vars if v.value_reference is not None}
            self._runtime_mode = 'runtime'
            self.last_status_text = f'Estimator running ({self.model_name})'
            self._clear_error()
        except Exception as exc:
            self._cleanup_runtime()
            self._runtime_mode = 'metadata'
            self.last_status_text = f'FMU loaded: {p.name} (metadata only, runtime error: {exc})'
            self._set_error(str(exc))

    def load_model(self, path: str) -> tuple[bool, str]:
        path = str(path or '').strip()
        normalized_path = self._normalize_fmu_path(path)
        self._cleanup_runtime()
        if not path:
            self.loaded_fmu_path = ''
            self.model_name = ''
            self.last_status_text = 'No FMU loaded'
            self._clear_error()
            self.input_vars = []
            self.output_vars = []
            return False, self.last_status_text
        p = Path(path)
        if not p.exists():
            self.loaded_fmu_path = ''
            self.model_name = ''
            self.input_vars = []
            self.output_vars = []
            self.last_status_text = f'FMU not found: {p.name}'
            self._set_error(self.last_status_text)
            return False, self.last_status_text
        if p.suffix.lower() != '.fmu':
            self.loaded_fmu_path = ''
            self.model_name = ''
            self.input_vars = []
            self.output_vars = []
            self.last_status_text = f'Not an FMU file: {p.name}'
            self._set_error(self.last_status_text)
            return False, self.last_status_text
        try:
            model_name, inputs, outputs = self._parse_fmu_variables(p)
        except Exception as exc:
            self.loaded_fmu_path = ''
            self.model_name = ''
            self.input_vars = []
            self.output_vars = []
            self.last_status_text = f'Failed to read FMU: {exc}'
            self._set_error(self.last_status_text)
            return False, self.last_status_text
        self.loaded_fmu_path = normalized_path
        self.model_name = model_name
        self.input_vars = inputs
        self.output_vars = outputs
        self._initialize_runtime(p)
        if self._runtime_mode != 'runtime' and 'metadata only' not in self.last_status_text.lower():
            self.last_status_text = f'FMU loaded: {p.name} ({len(inputs)} inputs, {len(outputs)} outputs)'
        if self._runtime_mode in {'runtime', 'metadata'} and not self._last_error:
            self._clear_error()
        return True, self.last_status_text

    def _coerce_input_value(self, binding: str | None) -> Optional[float]:
        if not binding:
            return None
        value = self.client.get_value(str(binding), None)
        if value is None:
            return None
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        try:
            return float(value)
        except Exception:
            return None

    def _placeholder_output(self, name: str, var_type: str, inputs: dict[str, Optional[float]]):
        low = name.lower()
        if var_type.lower() == 'boolean':
            if 'heat' in low:
                return bool(inputs.get('in_enable', 1.0) or 0.0) and bool(inputs.get('in_t_c', 0.0) < inputs.get('in_tsp_c', 0.0)) if inputs.get('in_t_c') is not None and inputs.get('in_tsp_c') is not None else bool(inputs.get('heat_cmd_in', 0.0) or 0.0)
            if 'cool' in low or 'pump' in low:
                return bool(inputs.get('in_enable', 1.0) or 0.0) and bool(inputs.get('in_t_c', 0.0) > inputs.get('in_tsp_c', 0.0)) if inputs.get('in_t_c') is not None and inputs.get('in_tsp_c') is not None else bool(inputs.get('cool_cmd_in', 0.0) or 0.0)
            return False
        if 'temp' in low:
            return inputs.get('in_t_c')
        if 'pressure' in low or 'psp' in low:
            return inputs.get('in_pressure_bar') or inputs.get('in_psp_bar')
        if 'gravity' in low or 'sg' in low:
            return inputs.get('in_gravity_sg')
        if 'level' in low:
            return inputs.get('in_level')
        return None

    def _set_runtime_inputs(self, inputs: dict[str, Optional[float]]) -> None:
        if self._fmu is None:
            return
        real_vrs, real_vals = [], []
        bool_vrs, bool_vals = [], []
        int_vrs, int_vals = [], []
        for name, value in inputs.items():
            if value is None:
                continue
            meta = self._input_map.get(name)
            if meta is None or meta.value_reference is None:
                continue
            t = (meta.var_type or '').lower()
            if t == 'boolean':
                bool_vrs.append(meta.value_reference)
                bool_vals.append(bool(value))
            elif t in {'integer', 'enumeration'}:
                int_vrs.append(meta.value_reference)
                int_vals.append(int(value))
            else:
                real_vrs.append(meta.value_reference)
                real_vals.append(float(value))
        if real_vrs:
            self._fmu.setReal(real_vrs, real_vals)
        if bool_vrs:
            try:
                self._fmu.setBoolean(bool_vrs, bool_vals)
            except Exception:
                self._fmu.setInteger(bool_vrs, [1 if v else 0 for v in bool_vals])
        if int_vrs:
            self._fmu.setInteger(int_vrs, int_vals)

    def _get_runtime_outputs(self) -> dict[str, Any]:
        outputs: dict[str, Any] = {}
        if self._fmu is None:
            return outputs
        for name, meta in self._output_map.items():
            if meta.value_reference is None:
                outputs[name] = None
                continue
            t = (meta.var_type or '').lower()
            try:
                if t == 'boolean':
                    try:
                        outputs[name] = bool(self._fmu.getBoolean([meta.value_reference])[0])
                    except Exception:
                        outputs[name] = bool(self._fmu.getInteger([meta.value_reference])[0])
                elif t in {'integer', 'enumeration'}:
                    outputs[name] = int(self._fmu.getInteger([meta.value_reference])[0])
                else:
                    outputs[name] = float(self._fmu.getReal([meta.value_reference])[0])
            except Exception:
                outputs[name] = None
        return outputs


    def _consume_reset_request(self) -> Optional[str]:
        param_name = self._reset_param_name()
        try:
            value = self.client.get_value(param_name, None)
        except Exception:
            return None
        if value in (None, False, 0, 0.0, '', '0', 'false', 'False', 'off', 'OFF', 'no', 'No'):
            return None
        if value == self._handled_reset_value:
            return None
        self._handled_reset_value = value
        try:
            self.client.set_value(param_name, False)
        except Exception:
            pass
        return f'reset requested via {param_name}'

    def _perform_reset(self, reason: str) -> None:
        self._cleanup_runtime()
        self._reset_count += 1
        self._last_reset_reason = reason
        self.last_status_text = f'Resetting twin ({reason})'
        self.load_model(str(self.config.get('fmu_path', '') or ''))

    def _publish_output_targets(self, outputs: dict[str, Any]) -> dict[str, Any]:
        written: dict[str, list[str]] = {}
        missing: dict[str, list[str]] = {}
        managed = self._desired_managed_outputs()
        explicit = self._output_params()
        owned = self.build_owned_metadata(device='digital_twin')
        for output_name in sorted(set(managed) | set(explicit)):
            targets: list[str] = []
            managed_target = str(managed.get(output_name, '') or '').strip()
            explicit_target = str(explicit.get(output_name, '') or '').strip()
            if managed_target:
                targets.append(managed_target)
            if explicit_target and explicit_target not in targets:
                targets.append(explicit_target)
            if not targets:
                continue
            if output_name not in outputs:
                missing[output_name] = targets
                continue
            for target_name in targets:
                # Output targets must remain auto-created even if the FMU was
                # loaded during this cycle after ensure_parameters() already ran.
                self.ensure_parameter(
                    target_name,
                    'static',
                    value=None,
                    metadata={
                        **owned,
                        'role': 'twin_output',
                        'fmu_output': output_name,
                        **({'managed_output': True} if target_name == managed_target else {}),
                    },
                )
                self.client.set_value(target_name, outputs[output_name])
            written[output_name] = targets
        return {'written': written, 'missing': missing}

    def _evaluate_once(self) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        reset_reason = self._consume_reset_request()
        if reset_reason:
            self._perform_reset(reset_reason)
        if self._normalize_fmu_path(self.config.get('fmu_path', '')) != self.loaded_fmu_path:
            self.load_model(str(self.config.get('fmu_path', '') or ''))
        input_bindings = self._input_bindings()
        inputs = {var.name: self._coerce_input_value(input_bindings.get(var.name)) for var in self.input_vars}
        missing_inputs = [var.name for var in self.input_vars if input_bindings.get(var.name) and inputs.get(var.name) is None]
        outputs: dict[str, Any] = {}

        enabled = bool(self.config.get('enabled', True))
        if not enabled:
            self.last_status_text = 'Disabled'
            return inputs, outputs, missing_inputs

        if self._runtime_mode == 'runtime' and self._fmu is not None and not missing_inputs:
            try:
                now = time.monotonic()
                dt = 0.1 if self._last_eval_monotonic is None else max(0.02, min(1.0, now - self._last_eval_monotonic))
                self._last_eval_monotonic = now
                self._set_runtime_inputs(inputs)
                self._fmu.doStep(currentCommunicationPoint=self._sim_time, communicationStepSize=dt)
                self._sim_time += dt
                self._step_count += 1
                self._last_dt = dt
                self._last_step_wallclock = now
                outputs = self._get_runtime_outputs()
                self.last_status_text = f'Estimator running ({self.model_name})'
                self._clear_error()
            except Exception as exc:
                self._cleanup_runtime()
                self._runtime_mode = 'metadata'
                self.last_status_text = f'FMU runtime failed; metadata only ({exc})'
                self._set_error(str(exc))

        if not outputs:
            if missing_inputs:
                preview = ', '.join(missing_inputs[:3])
                if len(missing_inputs) > 3:
                    preview += ', ...'
                self.last_status_text = f'FMU waiting for valid inputs ({preview})'
            elif enabled and not self.loaded_fmu_path:
                self.last_status_text = 'Enabled, waiting for FMU'
            outputs = {var.name: self._placeholder_output(var.name, var.var_type, inputs) for var in self.output_vars}
        return inputs, outputs, missing_inputs

    def run(self) -> None:
        interval = max(0.05, float(self.config.get('update_interval_s', 0.25)))
        reconnect_delay = max(interval, float(self.config.get('reconnect_delay_s', 2.0)))
        while not self.should_stop():
            try:
                self.ensure_parameters()
                inputs, outputs, missing_inputs = self._evaluate_once()
                publish_result = self._publish_output_targets(outputs)
                self._publish_status(inputs=inputs, outputs=outputs, missing_inputs=missing_inputs, output_targets=publish_result.get('written', {}), missing_output_targets=publish_result.get('missing', {}), reset_nonce=self.config.get('reset_nonce', 0), reset_param_value=self.client.get_value(self._reset_param_name(), None))
                if self.sleep(interval):
                    break
            except Exception as exc:
                self.last_status_text = f'Digital twin error: {exc}'
                self._set_error(str(exc))
                self._publish_status(inputs={}, outputs={}, missing_inputs=[], output_targets={}, missing_output_targets={})
                if self.sleep(reconnect_delay):
                    break
        self._cleanup_runtime()


class DigitalTwinSourceSpec(DataSourceSpec):
    source_type = 'digital_twin'
    display_name = 'Digital Twin FMU'
    description = 'Loads an FMU and binds discovered FMU inputs/outputs to parameters.'

    def create(self, name: str, client: SupportsSignalRequests, *, config: dict[str, Any] | None = None) -> DataSourceBase:
        return DigitalTwinSource(name, client, config=config)

    def default_config(self) -> dict[str, Any]:
        return {
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
        }


SOURCE = DigitalTwinSourceSpec()
