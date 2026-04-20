from __future__ import annotations

import contextlib
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
_DB_PIPELINE_APPLIED_FLAG = "__db_pipeline_applied"


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
        self._calibration_cache: dict[str, CompiledExpression | None] = {}
        self._calibration_input_cache: dict[str, Any] = {}
        self._calibration_output_cache: dict[str, Any] = {}
        self._transducer_input_cache: dict[str, Any] = {}
        self._transducer_output_cache: dict[str, Any] = {}

    def _clear_database_pipeline_state(self, param) -> None:
        for key in (
            "calibration_equation",
            "calibration_symbols",
            "calibration_input",
            "calibration_output",
            "transducer_id",
            "transducer_input",
            "transducer_output",
            "transducer_input_unit",
            "transducer_output_unit",
            "output_targets",
            "missing_output_targets",
            "timeshift",
            "timeshift_buffer_length",
            _DB_PIPELINE_APPLIED_FLAG,
        ):
            param.state.pop(key, None)

    def invalidate_database_pipeline_runtime(self, param_name: str) -> None:
        """Invalidate per-parameter pipeline caches after manual/external writes."""
        self._calibration_input_cache.pop(param_name, None)
        self._calibration_output_cache.pop(param_name, None)
        self._transducer_input_cache.pop(param_name, None)
        self._transducer_output_cache.pop(param_name, None)
        with contextlib.suppress(Exception):
            param = self.store._get_runtime_param(param_name)
            self._clear_database_pipeline_state(param)

    def _prune_runtime_caches(self, names: set[str]) -> None:
        for cache in (
            self._calibration_cache,
            self._calibration_input_cache,
            self._calibration_output_cache,
            self._transducer_input_cache,
            self._transducer_output_cache,
        ):
            stale = [name for name in cache if name not in names]
            for name in stale:
                cache.pop(name, None)

    def _resolve_calibration_input(
        self,
        param_name: str,
        current_value: Any,
        *,
        allow_cached_input: bool,
    ) -> Any:
        """Return stable calibration input to avoid repeated accumulation.

        For passive parameters (e.g. static values updated externally), scan() may
        leave the previously calibrated value untouched. If we calibrate that value
        again every cycle, equations like `x + offset` drift upward forever.

        Rule:
        - If current value still equals our last calibrated output, reuse the last
          raw input value.
        - Otherwise treat current value as fresh raw input.
        """
        if (
            allow_cached_input
            and param_name in self._calibration_input_cache
            and param_name in self._calibration_output_cache
            and current_value == self._calibration_output_cache[param_name]
        ):
            return self._calibration_input_cache[param_name]
        self._calibration_input_cache[param_name] = current_value
        return current_value

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

        targets = _normalize_targets(config.get("mirror_to"))
        if not targets:
            targets = _normalize_targets(config.get("output_params"))
        return targets
    def _resolve_transducer_input(
        self,
        param_name: str,
        current_value: Any,
        *,
        allow_cached_input: bool,
    ) -> Any:
        """Return stable transducer input to avoid repeated remapping drift.

        For passive parameters, stored value can already be previous mapped output.
        Re-mapping that output as raw input causes runaway growth when clamp is off.

        Reuse cached pre-transducer input only when the previous cycle applied the
        pipeline and the current value still equals last mapped output.
        """
        if (
            allow_cached_input
            and param_name in self._transducer_input_cache
            and param_name in self._transducer_output_cache
            and current_value == self._transducer_output_cache[param_name]
        ):
            return self._transducer_input_cache[param_name]
        self._transducer_input_cache[param_name] = current_value
        return current_value

    def _database_calibration_compiled(self, param_name: str, config: dict[str, Any]) -> CompiledExpression | None:
        equation = str(config.get("calibration_equation") or "").strip()
        if not equation:
            self._calibration_cache[param_name] = None
            return None
        cached = self._calibration_cache.get(param_name)
        if cached is not None and cached.expression == equation:
            return cached
        compiled = compile_expression(equation, required=True)
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
            if not self.store.exists(target):
                missing.append(target)
                continue
            self.store.set_value(target, value, source="scan")
            written.append(target)
        state: dict[str, Any] = {"output_targets": written}
        if missing:
            state["missing_output_targets"] = missing
        return state

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

        input_min = float(transducer["input_min"])
        input_max = float(transducer["input_max"])
        output_min = float(transducer["output_min"])
        output_max = float(transducer["output_max"])

        if input_min == input_max:
            raise ValueError(
                f"transducer '{transducer_id}' has invalid input range"
            )

        ratio = (x_value - input_min) / (input_max - input_min)
        mapped = output_min + ratio * (output_max - output_min)

        if bool(transducer.get("clamp", True)):
            low = min(output_min, output_max)
            high = max(output_min, output_max)
            mapped = max(low, min(high, mapped))

        return mapped, {
            "transducer_id": transducer_id,
            "transducer_input": x_value,
            "transducer_output": mapped,
            "transducer_input_unit": str(transducer.get("input_unit") or ""),
            "transducer_output_unit": str(transducer.get("output_unit") or ""),
        }

    def _apply_database_pipeline(self, param_name: str, param, now: float) -> str | None:
        config = dict(param.config)
        value = param.get_value()
        equation = str(config.get("calibration_equation") or "").strip()
        transducer_id = str(config.get("transducer_id") or "").strip()
        allow_cached_input = bool(param.state.get(_DB_PIPELINE_APPLIED_FLAG))

        # Clear prior-cycle pipeline details so failed attempts cannot leak stale state.
        self._clear_database_pipeline_state(param)

        base_value = value
        if equation:
            base_value = self._resolve_calibration_input(
                param_name,
                value,
                allow_cached_input=allow_cached_input,
            )

        try:
            calibrated, calibration_state = self._apply_calibration_equation(
                param_name=param_name,
                config=config,
                base_value=base_value,
            )
        except Exception as exc:
            self.invalidate_database_pipeline_runtime(param_name)
            return str(exc)

        pre_transducer_value = calibrated
        if transducer_id:
            pre_transducer_value = self._resolve_transducer_input(
                param_name,
                calibrated,
                allow_cached_input=allow_cached_input,
            )

        try:
            transformed, transducer_state = self._apply_transducer_mapping(
                param_name=param_name,
                config=config,
                base_value=pre_transducer_value,
            )
        except Exception as exc:
            self.invalidate_database_pipeline_runtime(param_name)
            return str(exc)

        param.set_value(transformed)
        if equation:
            self._calibration_output_cache[param_name] = transformed
        else:
            self._calibration_input_cache.pop(param_name, None)
            self._calibration_output_cache.pop(param_name, None)

        if transducer_id:
            self._transducer_output_cache[param_name] = transformed
        else:
            self._transducer_input_cache.pop(param_name, None)
            self._transducer_output_cache.pop(param_name, None)

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
            param.state.pop("transducer_input", None)
            param.state.pop("transducer_output", None)
            param.state.pop("transducer_input_unit", None)
            param.state.pop("transducer_output_unit", None)

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

        if equation or transducer_id:
            param.state[_DB_PIPELINE_APPLIED_FLAG] = True

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
                for target in p.write_targets():
                    if not target or target == name:
                        continue
                    targets.append(target)
                    writers[target].append(name)

                for target in self._database_mirror_targets(name, p.config):
                    if not target or target == name:
                        continue
                    targets.append(target)
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
            # Reset previous-cycle error so scan/pipeline can recover when config is fixed.
            param.state.pop("last_error", None)
            try:
                param.scan(ctx)
            except Exception as exc:
                self.invalidate_database_pipeline_runtime(name)
                param.state["last_error"] = str(exc)
                param.state["connected"] = False
            else:
                pre_pipeline_error = str(param.state.get("last_error", "") or "").strip()
                if not pre_pipeline_error:
                    pipeline_error = self._apply_database_pipeline(name, param, now)
                    if pipeline_error:
                        param.state["last_error"] = pipeline_error
                else:
                    self.invalidate_database_pipeline_runtime(name)
            new_value = param.get_value()
            error_text = str(param.state.get("last_error", "") or "").strip()
            if error_text:
                param.state["connected"] = False
            elif param.state.get("enabled") is False:
                param.state["last_error"] = ""
                param.state["connected"] = False
            else:
                param.state["last_error"] = ""
                param.state["connected"] = True
                param.state["last_sync"] = datetime.fromtimestamp(
                    now, tz=UTC
                ).isoformat()
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
