from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..parameterdb_core.expression import (
    CompiledExpression,
    compile_expression,
    evaluate_expression,
    expression_symbol_names,
)
from .store import ParameterStore
from .transducers import PostgresTransducerCatalog, TransducerCatalog

UTC = timezone.utc
_PIPELINE_INVALID_REASONS = frozenset({"channel", "transducer"})
_MIRROR_STALE_REASON = "mirror_source_invalid"
_DATASOURCE_SILENT_REASON = "datasource_silent"
# Reasons that represent amber/stale state rather than true invalidity.
# A dependency whose only invalid reasons are in this set propagates stale, not invalid.
_STALE_REASONS = frozenset({_MIRROR_STALE_REASON, _DATASOURCE_SILENT_REASON, "dependency_stale"})


@dataclass(slots=True)
class ScanContext:
    now: float
    dt: float
    cycle_count: int
    store: ParameterStore


class ScanEngine:
    def __init__(
        self,
        period_s: float,
        store: ParameterStore | None = None,
        transducers: TransducerCatalog | PostgresTransducerCatalog | None = None,
        *,
        mode: str = "fixed",
        target_utilization: float = 0.7,
        min_period_s: float = 0.002,
        max_period_s: float = 0.05,
    ) -> None:
        self.period_s = max(0.0, float(period_s))
        self.mode = str(mode or "fixed").strip().lower()
        if self.mode not in {"fixed", "adaptive"}:
            self.mode = "fixed"
        self.target_utilization = min(0.95, max(0.05, float(target_utilization)))
        self.min_period_s = max(0.0, float(min_period_s))
        self.max_period_s = max(self.min_period_s, float(max_period_s))
        self.store = store or ParameterStore()
        self.transducers = transducers or TransducerCatalog(path=None)
        self._running = False
        self._thread: threading.Thread | None = None
        self._cycle_count = 0
        self._last_scan_started_at: float | None = None
        self._last_scan_duration_s = 0.0
        self._avg_scan_duration_s = 0.0
        self._last_sleep_s = 0.0
        self._last_effective_period_s = self.period_s
        self._overrun_count = 0
        self._graph_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._cached_store_revision = -1
        self._scan_order: list[str] = []
        self._graph_warnings: list[str] = []
        self._dependency_map: dict[str, list[str]] = {}
        self._write_target_map: dict[str, list[str]] = {}
        self._pipeline_cache_lock = threading.RLock()
        # Caches for compiled expression objects only — not for parameter values.
        # The signal-layer design makes value-level caching unnecessary.
        self._calibration_cache: dict[str, CompiledExpression | None] = {}
        self._transducer_expr_cache: dict[str, tuple[str, CompiledExpression]] = {}

    def _mark_mirror_targets_stale(self, source_name: str, config: dict) -> None:
        """Mark mirror targets as stale when their source param is invalid/skipped."""
        for target in self._database_mirror_targets(source_name, config):
            try:
                t = self.store._get_runtime_param(target)
            except KeyError:
                continue
            old_reasons = list(t.state.get("parameter_invalid_reasons") or [])
            new_reasons = list(old_reasons)
            if _MIRROR_STALE_REASON not in new_reasons:
                new_reasons.append(_MIRROR_STALE_REASON)

            changed = (
                old_reasons != new_reasons
                or t.state.get("parameter_valid") is not False
                or t.state.get("mirror_source") != source_name
            )
            if not changed:
                continue

            t.state["parameter_invalid_reasons"] = new_reasons
            t.state["parameter_valid"] = False
            t.state["mirror_source"] = source_name
            self.store.publish_scan_state(target, dict(t.state))

    def _clear_mirror_targets_stale(self, source_name: str, config: dict) -> None:
        """Clear the stale marker from mirror targets when source recovers."""
        for target in self._database_mirror_targets(source_name, config):
            try:
                t = self.store._get_runtime_param(target)
            except KeyError:
                continue
            if t.state.get("mirror_source") != source_name:
                continue
            old_reasons = list(t.state.get("parameter_invalid_reasons") or [])
            new_reasons = [r for r in old_reasons if r != _MIRROR_STALE_REASON]
            changed = old_reasons != new_reasons or "mirror_source" in t.state
            if not changed:
                continue

            if not new_reasons:
                t.state.pop("parameter_invalid_reasons", None)
                t.state.pop("parameter_valid", None)
            else:
                t.state["parameter_invalid_reasons"] = new_reasons
            t.state.pop("mirror_source", None)
            self.store.publish_scan_state(target, dict(t.state))

    def _clear_database_pipeline_state(self, param) -> None:
        for key in (
            "calibration_equation",
            "calibration_symbols",
            "calibration_input",
            "calibration_output",
            "transducer_id",
            "transducer_equation",
            "transducer_symbols",
            "transducer_input",
            "transducer_output",
            "transducer_input_unit",
            "transducer_output_unit",
            "channel_limit_min",
            "channel_limit_max",
            "channel_limit_in_range",
            "channel_limit_violation",
            "transducer_limit_min",
            "transducer_limit_max",
            "transducer_limit_in_range",
            "transducer_limit_violation",
            "parameter_valid",
            "parameter_invalid_reasons",
            "output_targets",
            "missing_output_targets",
            "timeshift",
            "timeshift_buffer_length",
        ):
            param.state.pop(key, None)

    def _prune_runtime_caches(self, names: set[str]) -> None:
        """Prune stale compiled-expression caches for removed parameters.

        _calibration_cache is keyed by parameter name — prune when a parameter
        is removed.  _transducer_expr_cache is keyed by transducer ID (not
        parameter name) and must NOT be pruned here.
        """
        with self._pipeline_cache_lock:
            stale = [name for name in self._calibration_cache if name not in names]
            for name in stale:
                self._calibration_cache.pop(name, None)

    def _database_mirror_targets(self, param_name: str, config: dict[str, Any]) -> list[str]:
        def _normalize_targets(raw_value: Any) -> list[str]:
            if isinstance(raw_value, str):
                raw_value = [raw_value]
            if not isinstance(raw_value, list):
                return []
            targets: list[str] = []
            for item in raw_value:
                target = str(item or "").strip()
                if target and target != param_name:
                    targets.append(target)
            return list(dict.fromkeys(targets))

        mirror_to_present = "mirror_to" in config
        if mirror_to_present:
            return _normalize_targets(config.get("mirror_to"))
        return _normalize_targets(config.get("output_params"))

    def _database_calibration_compiled(self, param_name: str, config: dict[str, Any]) -> CompiledExpression | None:
        equation = str(config.get("calibration_equation") or "").strip()
        if not equation:
            with self._pipeline_cache_lock:
                self._calibration_cache[param_name] = None
            return None
        with self._pipeline_cache_lock:
            cached = self._calibration_cache.get(param_name)
        if cached is not None and cached.expression == equation:
            return cached
        compiled = compile_expression(equation, required=True)
        with self._pipeline_cache_lock:
            self._calibration_cache[param_name] = compiled
        return compiled

    def _database_dependencies(self, param_name: str, config: dict[str, Any]) -> tuple[list[str], str | None]:
        try:
            compiled = self._database_calibration_compiled(param_name, config)
        except Exception as exc:
            return [], str(exc)
        if compiled is None:
            return [], None
        deps = [
            symbol
            for symbol in compiled.symbols
            if symbol and symbol not in {param_name, "x", "value"}
        ]
        return list(dict.fromkeys(deps)), None

    def _apply_calibration_equation(
        self,
        *,
        param_name: str,
        config: dict[str, Any],
        base_value: Any,
    ) -> tuple[Any, dict[str, Any] | None]:
        equation = str(config.get("calibration_equation") or "").strip()
        if not equation:
            return base_value, None
        try:
            x_value = float(base_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "calibration equation requires numeric parameter value"
            ) from exc

        compiled = self._database_calibration_compiled(param_name, config)
        if compiled is None:
            return base_value, None

        values: dict[str, float] = {
            "x": x_value,
            "value": x_value,
        }
        missing: list[str] = []
        non_numeric: list[str] = []
        for name in expression_symbol_names(compiled):
            source_symbol = compiled.alias_to_symbol.get(name, name)
            if source_symbol in {"x", "value"}:
                continue
            if not self.store.exists(source_symbol):
                missing.append(source_symbol)
                continue
            raw_value = self.store.get_value(source_symbol)
            try:
                values[name] = float(raw_value)
            except (TypeError, ValueError):
                non_numeric.append(source_symbol)

        if missing:
            raise ValueError(
                "missing parameters in calibration equation: " + ", ".join(missing)
            )
        if non_numeric:
            raise ValueError(
                "non-numeric parameters in calibration equation: "
                + ", ".join(non_numeric)
            )

        try:
            calibrated = evaluate_expression(compiled.tree, values)
        except Exception as exc:
            raise ValueError(f"calibration equation failed: {exc}") from exc

        return calibrated, {
            "calibration_equation": equation,
            "calibration_symbols": list(compiled.symbols),
            "calibration_input": x_value,
            "calibration_output": calibrated,
        }

    def _apply_mirror_to_targets(self, *, name: str, config: dict[str, Any], value: Any) -> dict[str, Any] | None:
        targets = self._database_mirror_targets(name, config)
        if not targets:
            return None
        written: list[str] = []
        missing: list[str] = []
        for target in targets:
            try:
                self.store.set_value(target, value, source="scan")
            except KeyError:
                missing.append(target)
                continue
            written.append(target)
        # Source is healthy and writing — clear any stale marker set in prior cycles.
        self._clear_mirror_targets_stale(name, config)
        state: dict[str, Any] = {"output_targets": written}
        if missing:
            state["missing_output_targets"] = missing
        return state

    def _optional_limit(self, config: dict[str, Any], key: str) -> float | None:
        raw = config.get(key)
        if raw is None:
            return None
        if isinstance(raw, str) and not raw.strip():
            return None
        if isinstance(raw, bool):
            raise ValueError(f"{key} must be a finite number")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a finite number") from exc
        if not math.isfinite(value):
            raise ValueError(f"{key} must be a finite number")
        return value

    def _evaluate_stage_limits(
        self,
        *,
        stage: str,
        value: float,
        min_limit: float | None,
        max_limit: float | None,
    ) -> tuple[dict[str, Any], bool, str | None]:
        prefix = f"{stage}_limit"
        state: dict[str, Any] = {
            f"{prefix}_min": min_limit,
            f"{prefix}_max": max_limit,
        }
        if min_limit is None and max_limit is None:
            state[f"{prefix}_in_range"] = True
            return state, True, None

        in_range = True
        if min_limit is not None and value < min_limit:
            in_range = False
        if max_limit is not None and value > max_limit:
            in_range = False

        state[f"{prefix}_in_range"] = in_range
        if not in_range:
            state[f"{prefix}_violation"] = (
                f"{stage} value {value} outside configured range "
                f"[{min_limit if min_limit is not None else '-inf'}, {max_limit if max_limit is not None else 'inf'}]"
            )
            return state, False, stage
        return state, True, None

    def _apply_transducer_mapping(
        self,
        *,
        param_name: str,
        config: dict[str, Any],
        base_value: Any,
    ) -> tuple[Any, dict[str, Any] | None]:
        transducer_id = str(config.get("transducer_id") or "").strip()
        if not transducer_id:
            return base_value, None

        transducer = self.transducers.get(transducer_id)
        if transducer is None:
            raise ValueError(f"unknown transducer '{transducer_id}'")

        try:
            x_value = float(base_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "transducer mapping requires numeric parameter value"
            ) from exc

        equation = str(transducer.get("equation") or "").strip()
        if not equation:
            raise ValueError(f"transducer '{transducer_id}' requires a non-empty equation")

        try:
            with self._pipeline_cache_lock:
                cached = self._transducer_expr_cache.get(transducer_id)
                if cached is not None and cached[0] == equation:
                    compiled = cached[1]
                else:
                    compiled = compile_expression(equation, required=True)
                    self._transducer_expr_cache[transducer_id] = (equation, compiled)
            mapped = evaluate_expression(
                compiled.tree,
                {
                    "x": x_value,
                    "value": x_value,
                },
            )
        except Exception as exc:
            raise ValueError(f"transducer equation failed: {exc}") from exc

        state: dict[str, Any] = {
            "transducer_id": transducer_id,
            "transducer_equation": equation,
            "transducer_symbols": list(compiled.symbols),
            "transducer_input": x_value,
            "transducer_output": mapped,
            "transducer_input_unit": str(transducer.get("input_unit") or ""),
            "transducer_output_unit": str(transducer.get("output_unit") or ""),
            "transducer_limit_min": transducer.get("min_limit"),
            "transducer_limit_max": transducer.get("max_limit"),
        }
        return mapped, state

    def _apply_database_pipeline(self, param_name: str, param) -> str | None:
        """Apply calibration → transducer → mirror pipeline stages.

        Always reads the raw signal value written by the plugin (get_signal_value),
        applies all transforms deterministically, then writes the result via
        set_pipeline_value.  No value-level caching is used — the signal layer makes
        that unnecessary and keeps the pipeline fully deterministic every cycle.
        """
        config = dict(param.config)
        # Always start from the raw signal written by the plugin this cycle.
        signal = param.get_signal_value()
        equation = str(config.get("calibration_equation") or "").strip()
        transducer_id = str(config.get("transducer_id") or "").strip()

        # Clear prior-cycle pipeline details so failed attempts cannot leak stale state.
        self._clear_database_pipeline_state(param)

        try:
            calibrated, calibration_state = self._apply_calibration_equation(
                param_name=param_name,
                config=config,
                base_value=signal,
            )
        except Exception as exc:
            return str(exc)

        try:
            channel_min = self._optional_limit(config, "channel_min")
            channel_max = self._optional_limit(config, "channel_max")
        except Exception as exc:
            return str(exc)

        if channel_min is not None and channel_max is not None and channel_min > channel_max:
            return "channel_min must be <= channel_max"
        channel_reason: str | None = None
        if channel_min is None and channel_max is None:
            channel_limit_state = {
                "channel_limit_min": None,
                "channel_limit_max": None,
                "channel_limit_in_range": True,
            }
        else:
            try:
                calibrated_float = float(calibrated)
            except (TypeError, ValueError) as exc:
                return f"calibrated value must be numeric for limit checks: {exc}"

            channel_limit_state, _channel_ok, channel_reason = self._evaluate_stage_limits(
                stage="channel",
                value=calibrated_float,
                min_limit=channel_min,
                max_limit=channel_max,
            )

        try:
            transformed, transducer_state = self._apply_transducer_mapping(
                param_name=param_name,
                config=config,
                base_value=calibrated,
            )
        except Exception as exc:
            return str(exc)

        transducer_min: float | None = None
        transducer_max: float | None = None
        if transducer_state:
            transducer_min = self._optional_limit(transducer_state, "transducer_limit_min")
            transducer_max = self._optional_limit(transducer_state, "transducer_limit_max")

        transducer_limits_apply = bool(transducer_id)
        transducer_limit_state: dict[str, Any]
        transducer_reason: str | None = None
        if transducer_limits_apply and (transducer_min is not None or transducer_max is not None):
            try:
                transformed_float = float(transformed)
            except (TypeError, ValueError) as exc:
                return f"transformed value must be numeric for limit checks: {exc}"
            transducer_limit_state, _transducer_ok, transducer_reason = self._evaluate_stage_limits(
                stage="transducer",
                value=transformed_float,
                min_limit=transducer_min,
                max_limit=transducer_max,
            )
        else:
            transducer_limit_state = {
                "transducer_limit_min": transducer_min,
                "transducer_limit_max": transducer_max,
                "transducer_limit_in_range": True,
            }

        # Commit the pipeline output.  The signal (param.value) is unchanged.
        param.set_pipeline_value(transformed)

        if calibration_state:
            param.state.update(calibration_state)
        else:
            param.state.pop("calibration_equation", None)
            param.state.pop("calibration_symbols", None)
            param.state.pop("calibration_input", None)
            param.state.pop("calibration_output", None)

        if transducer_state:
            param.state.update(transducer_state)
        else:
            param.state.pop("transducer_id", None)
            param.state.pop("transducer_equation", None)
            param.state.pop("transducer_symbols", None)
            param.state.pop("transducer_input", None)
            param.state.pop("transducer_output", None)
            param.state.pop("transducer_input_unit", None)
            param.state.pop("transducer_output_unit", None)

        param.state.update(channel_limit_state)
        if "channel_limit_violation" not in channel_limit_state:
            param.state.pop("channel_limit_violation", None)

        param.state.update(transducer_limit_state)
        if "transducer_limit_violation" not in transducer_limit_state:
            param.state.pop("transducer_limit_violation", None)

        invalid_reasons: list[str] = []
        if channel_reason:
            invalid_reasons.append(channel_reason)
        if transducer_reason:
            invalid_reasons.append(transducer_reason)
        param.state["parameter_valid"] = not bool(invalid_reasons)
        if invalid_reasons:
            param.state["parameter_invalid_reasons"] = invalid_reasons
        else:
            param.state.pop("parameter_invalid_reasons", None)

        mirror_state = self._apply_mirror_to_targets(
            name=param_name,
            config=config,
            value=transformed,
        )
        if mirror_state:
            param.state.update(mirror_state)
            if "missing_output_targets" not in mirror_state:
                param.state.pop("missing_output_targets", None)
        else:
            param.state.pop("output_targets", None)
            param.state.pop("missing_output_targets", None)

        return None

    def _desired_period_s(self, elapsed_s: float) -> float:
        if self.mode == "adaptive":
            adaptive_period = (
                elapsed_s / self.target_utilization
                if self.target_utilization > 0
                else elapsed_s
            )
            return max(self.min_period_s, min(self.max_period_s, adaptive_period))
        return max(self.min_period_s, self.period_s)

    def _rebuild_graph_if_needed(self) -> None:
        rev = self.store.revision()
        with self._graph_lock:
            if rev == self._cached_store_revision:
                return
            params = self.store._iter_runtime_params()
            names = {p.name for p in params}
            self._prune_runtime_caches(names)
            param_map = {p.name: p for p in params}
            dependency_map: dict[str, list[str]] = {}
            write_target_map: dict[str, list[str]] = {}
            warnings: list[str] = []
            graph: dict[str, set[str]] = {name: set() for name in names}
            indegree: dict[str, int] = {name: 0 for name in names}
            writers: dict[str, list[str]] = defaultdict(list)

            for name, p in param_map.items():
                deps: list[str] = []
                for dep in p.dependencies():
                    if not dep or dep == name:
                        continue
                    deps.append(dep)
                    if dep in names:
                        graph[dep].add(name)
                        indegree[name] += 1
                    else:
                        warnings.append(f"{name}: dependency '{dep}' does not exist")

                db_deps, db_dep_error = self._database_dependencies(name, p.config)
                if db_dep_error:
                    warnings.append(f"{name}: invalid calibration equation: {db_dep_error}")
                for dep in db_deps:
                    if not dep or dep == name:
                        continue
                    deps.append(dep)
                    if dep in names:
                        graph[dep].add(name)
                        indegree[name] += 1
                    else:
                        warnings.append(f"{name}: dependency '{dep}' does not exist")
                dependency_map[name] = deps

                targets: list[str] = []
                seen_targets: set[str] = set()
                for target in p.write_targets():
                    if not target or target == name:
                        continue
                    if target in seen_targets:
                        continue
                    seen_targets.add(target)
                    targets.append(target)
                    if name not in writers[target]:
                        writers[target].append(name)

                for target in self._database_mirror_targets(name, p.config):
                    if not target or target == name:
                        continue
                    if target in seen_targets:
                        continue
                    seen_targets.add(target)
                    targets.append(target)
                    if name not in writers[target]:
                        writers[target].append(name)
                write_target_map[name] = targets

            for target, source_names in sorted(writers.items()):
                if len(source_names) > 1:
                    warnings.append(
                        f"multiple writers for '{target}': "
                        f"{', '.join(sorted(source_names))}"
                    )

            q = deque(sorted([name for name, deg in indegree.items() if deg == 0]))
            ordered: list[str] = []
            while q:
                name = q.popleft()
                ordered.append(name)
                for child in sorted(graph[name]):
                    indegree[child] -= 1
                    if indegree[child] == 0:
                        q.append(child)

            if len(ordered) != len(names):
                cyclic = sorted(name for name, deg in indegree.items() if deg > 0)
                warnings.append(
                    "dependency cycle detected; falling back to stable order for: "
                    + ", ".join(cyclic)
                )
                remaining = [p.name for p in params if p.name not in ordered]
                ordered.extend(remaining)

            self._scan_order = ordered
            self._graph_warnings = warnings
            self._dependency_map = dependency_map
            self._write_target_map = write_target_map
            self._cached_store_revision = rev

    def _dependency_status(self, param_name: str) -> tuple[list[str], list[str], list[str]]:
        with self._graph_lock:
            deps = list(self._dependency_map.get(param_name, ()))
        missing: list[str] = []
        invalid: list[str] = []
        stale: list[str] = []
        for dep in deps:
            try:
                dep_param = self.store._get_runtime_param(dep)
            except KeyError:
                missing.append(dep)
                continue
            if dep_param.state.get("parameter_valid") is False:
                reasons = set(dep_param.state.get("parameter_invalid_reasons") or [])
                if reasons and reasons.issubset(_STALE_REASONS):
                    stale.append(dep)
                else:
                    invalid.append(dep)
        return missing, invalid, stale

    def get_scan_order(self) -> list[str]:
        self._rebuild_graph_if_needed()
        with self._graph_lock:
            return list(self._scan_order)

    def graph_info(self) -> dict[str, Any]:
        self._rebuild_graph_if_needed()
        with self._graph_lock:
            return {
                "store_revision": self._cached_store_revision,
                "scan_order": list(self._scan_order),
                "dependencies": {k: list(v) for k, v in self._dependency_map.items()},
                "write_targets": {
                    k: list(v) for k, v in self._write_target_map.items()
                },
                "warnings": list(self._graph_warnings),
            }

    def scan_once(self, dt: float) -> None:
        started = time.perf_counter()
        now = time.time()
        with self._state_lock:
            self._last_scan_started_at = now
            cycle_count = self._cycle_count
        ctx = ScanContext(now=now, dt=dt, cycle_count=cycle_count, store=self.store)
        self._rebuild_graph_if_needed()

        scan_order = self.get_scan_order()
        for name in scan_order:
            try:
                param = self.store._get_runtime_param(name)
            except KeyError:
                continue
            old_value = param.get_value()

            force_invalid = bool(param.config.get("force_invalid", False))
            force_invalid_reason = str(param.config.get("force_invalid_reason") or "").strip()
            if force_invalid:
                self._clear_database_pipeline_state(param)
                param.state["parameter_force_invalid"] = True
                if force_invalid_reason:
                    param.state["parameter_force_invalid_reason"] = force_invalid_reason
                else:
                    param.state.pop("parameter_force_invalid_reason", None)
                param.state["parameter_valid"] = False
                param.state["parameter_invalid_reasons"] = ["manual"]
                param.state["last_error"] = ""
                param.state["connected"] = False
                new_value = param.get_value()
                param.state["signal_value"] = param.get_signal_value()
                self._mark_mirror_targets_stale(name, dict(param.config))
                self.store.publish_scan_value_if_changed(param.name, old_value, new_value)
                self.store.publish_scan_state(param.name, dict(param.state))
                continue

            param.state.pop("parameter_force_invalid", None)
            param.state.pop("parameter_force_invalid_reason", None)

            # Allow recovery after force_invalid is turned off.
            # The forced-invalid branch marks state as manual invalid and skips scan;
            # if we do not clear that marker here, the parameter can remain stuck.
            if (
                param.state.get("parameter_valid") is False
                and param.state.get("parameter_invalid_reasons") == ["manual"]
            ):
                param.state.pop("parameter_valid", None)
                param.state.pop("parameter_invalid_reasons", None)

            missing_dependencies, invalid_dependencies, stale_dependencies = self._dependency_status(name)
            if missing_dependencies or invalid_dependencies:
                self._clear_database_pipeline_state(param)
                dependency_failures = list(
                    dict.fromkeys([*missing_dependencies, *invalid_dependencies])
                )
                param.state["parameter_valid"] = False
                param.state["parameter_invalid_reasons"] = ["dependency"]
                param.state["dependency_invalid_parameters"] = dependency_failures
                param.state.pop("dependency_stale_parameters", None)
                param.state["last_error"] = ""
                param.state["connected"] = False
                new_value = param.get_value()
                param.state["signal_value"] = param.get_signal_value()
                self._mark_mirror_targets_stale(name, dict(param.config))
                self.store.publish_scan_value_if_changed(param.name, old_value, new_value)
                self.store.publish_scan_state(param.name, dict(param.state))
                continue

            if stale_dependencies:
                self._clear_database_pipeline_state(param)
                param.state["parameter_valid"] = False
                param.state["parameter_invalid_reasons"] = ["dependency_stale"]
                param.state["dependency_stale_parameters"] = stale_dependencies
                param.state.pop("dependency_invalid_parameters", None)
                param.state["last_error"] = ""
                param.state["connected"] = False
                new_value = param.get_value()
                param.state["signal_value"] = param.get_signal_value()
                self._mark_mirror_targets_stale(name, dict(param.config))
                self.store.publish_scan_value_if_changed(param.name, old_value, new_value)
                self.store.publish_scan_state(param.name, dict(param.state))
                continue

            if param.state.get("parameter_invalid_reasons") in (["dependency"], ["dependency_stale"]):
                param.state.pop("parameter_valid", None)
                param.state.pop("parameter_invalid_reasons", None)
            param.state.pop("dependency_invalid_parameters", None)
            param.state.pop("dependency_stale_parameters", None)

            invalid_reasons = param.state.get("parameter_invalid_reasons") or []
            _recoverable_reasons = _PIPELINE_INVALID_REASONS.union(_STALE_REASONS)
            is_recoverable_invalid_only = bool(invalid_reasons) and set(invalid_reasons).issubset(_recoverable_reasons)
            if param.state.get("parameter_valid") is False and invalid_reasons and not is_recoverable_invalid_only:
                # Skip evaluation when a parameter is already marked invalid by datasource/runtime.
                param.state["last_error"] = ""
                param.state["connected"] = False
                new_value = param.get_value()
                param.state["signal_value"] = param.get_signal_value()
                self._mark_mirror_targets_stale(name, dict(param.config))
                self.store.publish_scan_value_if_changed(param.name, old_value, new_value)
                self.store.publish_scan_state(param.name, dict(param.state))
                continue

            if is_recoverable_invalid_only:
                param.state.pop("parameter_valid", None)
                param.state.pop("parameter_invalid_reasons", None)

            # Parse datasource silence timeout once; evaluate freshness after scan()
            # so polling-style plugins can refresh signal and recover in the same cycle.
            datasource_stale_timeout_s: float | None = None
            _stale_cfg = param.config.get("stale_timeout_s")
            if _stale_cfg is not None:
                try:
                    _stale_timeout = float(_stale_cfg)
                except (TypeError, ValueError):
                    _stale_timeout = None
                if _stale_timeout is not None and _stale_timeout > 0:
                    datasource_stale_timeout_s = _stale_timeout

            # Reset previous-cycle error so scan/pipeline can recover when config is fixed.
            param.state.pop("last_error", None)
            try:
                param.scan(ctx)
            except Exception as exc:
                param.state["last_error"] = str(exc)
                param.state["connected"] = False
            else:
                if datasource_stale_timeout_s is not None:
                    signal_age = param.get_signal_age_s()
                    reasons = list(param.state.get("parameter_invalid_reasons") or [])
                    if signal_age > datasource_stale_timeout_s:
                        # Freshly scanned but still stale: keep pipeline output pending and
                        # mark amber stale until a new signal write arrives.
                        self._clear_database_pipeline_state(param)
                        reasons = [r for r in reasons if r != _DATASOURCE_SILENT_REASON]
                        reasons.append(_DATASOURCE_SILENT_REASON)
                        param.state["parameter_valid"] = False
                        param.state["parameter_invalid_reasons"] = reasons
                        self._mark_mirror_targets_stale(name, dict(param.config))
                    elif _DATASOURCE_SILENT_REASON in reasons:
                        reasons = [r for r in reasons if r != _DATASOURCE_SILENT_REASON]
                        if not reasons:
                            param.state.pop("parameter_invalid_reasons", None)
                            if param.state.get("parameter_valid") is False:
                                param.state.pop("parameter_valid", None)
                        else:
                            param.state["parameter_invalid_reasons"] = reasons

                plugin_marked_invalid = param.state.get("parameter_valid") is False and bool(param.state.get("parameter_invalid_reasons"))
                pre_pipeline_error = str(param.state.get("last_error", "") or "").strip()
                if plugin_marked_invalid:
                    # Datasource/plugin can mark a parameter invalid for this cycle.
                    pass
                elif not pre_pipeline_error:
                    pipeline_error = self._apply_database_pipeline(name, param)
                    if pipeline_error:
                        param.state["last_error"] = pipeline_error

            new_value = param.get_value()
            error_text = str(param.state.get("last_error", "") or "").strip()
            parameter_invalid = param.state.get("parameter_valid") is False
            if error_text:
                param.state["connected"] = False
            elif param.state.get("enabled") is False:
                param.state["last_error"] = ""
                param.state["connected"] = False
            elif parameter_invalid:
                invalid_reasons = set(param.state.get("parameter_invalid_reasons") or [])
                param.state["last_error"] = ""
                param.state["connected"] = not bool(invalid_reasons) or not invalid_reasons.issubset(_STALE_REASONS)
                param.state["last_sync"] = datetime.fromtimestamp(
                    now, tz=UTC
                ).isoformat()
            else:
                param.state["last_error"] = ""
                param.state["connected"] = True
                param.state["last_sync"] = datetime.fromtimestamp(
                    now, tz=UTC
                ).isoformat()
            param.state["signal_value"] = param.get_signal_value()
            self.store.publish_scan_value_if_changed(param.name, old_value, new_value)
            self.store.publish_scan_state(param.name, dict(param.state))

        duration = time.perf_counter() - started
        with self._state_lock:
            self._cycle_count += 1
            self._last_scan_duration_s = duration
            if self._avg_scan_duration_s <= 0.0:
                self._avg_scan_duration_s = duration
            else:
                self._avg_scan_duration_s = (self._avg_scan_duration_s * 0.9) + (
                    duration * 0.1
                )

    def _run_loop(self) -> None:
        last = time.perf_counter()
        while True:
            with self._state_lock:
                if not self._running:
                    break
            start = time.perf_counter()
            dt = start - last
            last = start
            self.scan_once(dt)
            elapsed = time.perf_counter() - start
            desired_period_s = self._desired_period_s(elapsed)
            sleep_s = max(0.0, desired_period_s - elapsed)
            with self._state_lock:
                self._last_effective_period_s = desired_period_s
                self._last_sleep_s = sleep_s
                if sleep_s <= 0.0:
                    self._overrun_count += 1
            time.sleep(sleep_s)

    def start(self) -> None:
        with self._state_lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._run_loop, name="ParameterScanEngine", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        thread: threading.Thread | None
        with self._state_lock:
            self._running = False
            thread = self._thread
            self._thread = None
        if thread is not None:
            thread.join(timeout=2.0)

    def stats(self) -> dict[str, Any]:
        graph = self.graph_info()
        with self._state_lock:
            running = self._running
            cycle_count = self._cycle_count
            last_scan_started_at = self._last_scan_started_at
            last_scan_duration_s = self._last_scan_duration_s
            avg_scan_duration_s = self._avg_scan_duration_s
            last_sleep_s = self._last_sleep_s
            last_effective_period_s = self._last_effective_period_s
            overrun_count = self._overrun_count
        return {
            "running": running,
            "period_s": self.period_s,
            "mode": self.mode,
            "target_utilization": self.target_utilization,
            "min_period_s": self.min_period_s,
            "max_period_s": self.max_period_s,
            "cycle_count": cycle_count,
            "last_scan_started_at": last_scan_started_at,
            "last_scan_duration_s": last_scan_duration_s,
            "avg_scan_duration_s": avg_scan_duration_s,
            "last_sleep_s": last_sleep_s,
            "last_effective_period_s": last_effective_period_s,
            "estimated_cycle_rate_hz": (1.0 / last_effective_period_s)
            if last_effective_period_s > 0
            else None,
            "estimated_utilization": (avg_scan_duration_s / last_effective_period_s)
            if last_effective_period_s > 0
            else None,
            "overrun_count": overrun_count,
            "parameter_count": len(self.store.list_names()),
            "store_revision": graph["store_revision"],
            "graph_warning_count": len(graph["warnings"]),
            "scan_order": graph["scan_order"],
        }
