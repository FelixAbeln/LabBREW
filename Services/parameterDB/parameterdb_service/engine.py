from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from .store import ParameterStore


@dataclass(slots=True)
class ScanContext:
    now: float
    dt: float
    cycle_count: int
    store: ParameterStore


class ScanEngine:
    def __init__(self, period_s: float, store: ParameterStore | None = None) -> None:
        self.period_s = period_s
        self.store = store or ParameterStore()
        self._running = False
        self._thread: threading.Thread | None = None
        self._cycle_count = 0
        self._last_scan_started_at: float | None = None
        self._last_scan_duration_s = 0.0
        self._graph_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._cached_store_revision = -1
        self._scan_order: list[str] = []
        self._graph_warnings: list[str] = []
        self._dependency_map: dict[str, list[str]] = {}
        self._write_target_map: dict[str, list[str]] = {}

    def _rebuild_graph_if_needed(self) -> None:
        rev = self.store.revision()
        with self._graph_lock:
            if rev == self._cached_store_revision:
                return
            params = self.store._iter_runtime_params()
            names = {p.name for p in params}
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
                dependency_map[name] = deps

                targets: list[str] = []
                for target in p.write_targets():
                    if not target or target == name:
                        continue
                    targets.append(target)
                    writers[target].append(name)
                write_target_map[name] = targets

            for target, source_names in sorted(writers.items()):
                if len(source_names) > 1:
                    warnings.append(
                        f"multiple writers for '{target}': {', '.join(sorted(source_names))}"
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
                    "dependency cycle detected; falling back to stable order for: " + ", ".join(cyclic)
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
                "write_targets": {k: list(v) for k, v in self._write_target_map.items()},
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
            try:
                param.scan(ctx)
            except Exception as exc:
                param.state["last_error"] = str(exc)
            new_value = param.get_value()
            self.store.publish_scan_value_if_changed(param.name, old_value, new_value)
            self.store.publish_scan_state(param.name, dict(param.state))

        duration = time.perf_counter() - started
        with self._state_lock:
            self._cycle_count += 1
            self._last_scan_duration_s = duration

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
            time.sleep(max(0.0, self.period_s - elapsed))

    def start(self) -> None:
        with self._state_lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, name="ParameterScanEngine", daemon=True)
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
        return {
            "running": running,
            "period_s": self.period_s,
            "cycle_count": cycle_count,
            "last_scan_started_at": last_scan_started_at,
            "last_scan_duration_s": last_scan_duration_s,
            "parameter_count": len(self.store.list_names()),
            "store_revision": graph["store_revision"],
            "graph_warning_count": len(graph["warnings"]),
            "scan_order": graph["scan_order"],
        }
