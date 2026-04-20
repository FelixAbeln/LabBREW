from __future__ import annotations

from typing import Any

from Services.parameterDB.parameterdb_service.engine import ScanEngine
from Services.parameterDB.parameterdb_service.plugin_api import ParameterBase
from Services.parameterDB.parameterdb_service.store import ParameterStore


class FakeBroker:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def publish(self, event: dict[str, Any]) -> None:
        self.events.append(dict(event))


class FakeParameter(ParameterBase):
    parameter_type = "fake"

    def __init__(
        self,
        name: str,
        *,
        value: Any = None,
        deps: list[str] | None = None,
        targets: list[str] | None = None,
        scan_value: Any = None,
        raise_error: bool = False,
    ) -> None:
        super().__init__(name, value=value)
        self._deps = list(deps or [])
        self._targets = list(targets or [])
        self._scan_value = scan_value
        self._raise_error = raise_error

    def dependencies(self) -> list[str]:
        return list(self._deps)

    def write_targets(self) -> list[str]:
        return list(self._targets)

    def scan(self, _ctx) -> None:
        if self._raise_error:
            raise RuntimeError("scan failed")
        if self._scan_value is not None:
            self.set_value(self._scan_value)


class StatefulParameter(FakeParameter):
    def __init__(self, name: str, *, initial_state: dict[str, Any] | None = None, **kwargs) -> None:
        super().__init__(name, **kwargs)
        if initial_state:
            self.state.update(initial_state)


class SequenceParameter(FakeParameter):
    def __init__(self, name: str, *, scan_values: list[Any], value: Any = None, **kwargs) -> None:
        super().__init__(name, value=value, **kwargs)
        self._scan_values = list(scan_values)

    def scan(self, _ctx) -> None:
        if self._scan_values:
            self.set_value(self._scan_values.pop(0))


def test_scan_engine_graph_orders_dependencies_and_reports_conflicts() -> None:
    store = ParameterStore()
    store.add(FakeParameter("source"))
    store.add(FakeParameter("derived", deps=["source"]))
    store.add(FakeParameter("writer_a", targets=["shared.target"]))
    store.add(FakeParameter("writer_b", targets=["shared.target"]))

    engine = ScanEngine(period_s=0.01, store=store)
    graph = engine.graph_info()

    assert graph["scan_order"].index("source") < graph["scan_order"].index("derived")
    assert graph["dependencies"]["derived"] == ["source"]
    assert any("multiple writers for 'shared.target'" in warning for warning in graph["warnings"])


def test_scan_engine_cycle_warning_falls_back_to_stable_order() -> None:
    store = ParameterStore()
    store.add(FakeParameter("a", deps=["b"]))
    store.add(FakeParameter("b", deps=["a"]))

    engine = ScanEngine(period_s=0.01, store=store)
    graph = engine.graph_info()

    assert graph["scan_order"] == ["a", "b"]
    assert any("dependency cycle detected" in warning for warning in graph["warnings"])


def test_scan_once_updates_value_state_and_publishes_scan_events() -> None:
    broker = FakeBroker()
    store = ParameterStore(event_broker=broker)
    store.add(FakeParameter("temp", value=10.0, scan_value=12.5))

    engine = ScanEngine(period_s=0.01, store=store)
    engine.scan_once(dt=0.1)

    record = store.get_record("temp")
    assert record.value == 12.5
    assert record.state["connected"] is True
    assert "last_sync" in record.state
    assert any(event["event"] == "value_changed" and event.get("source") == "scan" for event in broker.events)
    assert any(event["event"] == "state_changed" for event in broker.events)


def test_scan_engine_records_scan_errors_as_disconnected_state() -> None:
    store = ParameterStore()
    store.add(FakeParameter("temp", raise_error=True))

    engine = ScanEngine(period_s=0.01, store=store)
    engine.scan_once(dt=0.1)

    record = store.get_record("temp")
    assert record.state["connected"] is False
    assert record.state["last_error"] == "scan failed"


def test_scan_engine_init_and_desired_period_variants() -> None:
    engine = ScanEngine(period_s=0.01, mode="invalid", target_utilization=5.0, min_period_s=-1.0, max_period_s=0.001)

    assert engine.mode == "fixed"
    assert engine.target_utilization == 0.95
    assert engine.min_period_s == 0.0
    assert engine.max_period_s == 0.001

    adaptive = ScanEngine(period_s=0.01, mode="adaptive", target_utilization=0.5, min_period_s=0.002, max_period_s=0.05)
    assert adaptive._desired_period_s(0.01) == 0.02
    assert adaptive._desired_period_s(1.0) == 0.05
    adaptive.target_utilization = 0.0
    assert adaptive._desired_period_s(0.01) == 0.01


def test_scan_engine_graph_caches_revision_and_filters_self_edges() -> None:
    store = ParameterStore()
    store.add(FakeParameter("alpha", deps=["", "alpha", "missing"], targets=["", "alpha", "target.x"]))
    store.add(FakeParameter("beta", deps=["alpha"], targets=["target.x"]))

    engine = ScanEngine(period_s=0.01, store=store)
    first = engine.graph_info()
    cached_revision = engine._cached_store_revision

    assert first["dependencies"]["alpha"] == ["missing"]
    assert first["write_targets"]["alpha"] == ["target.x"]
    assert any("dependency 'missing' does not exist" in warning for warning in first["warnings"])
    assert any("multiple writers for 'target.x'" in warning for warning in first["warnings"])

    engine._graph_warnings.append("cached-marker")
    second = engine.graph_info()
    assert second["warnings"][-1] == "cached-marker"
    assert engine._cached_store_revision == cached_revision


def test_scan_once_handles_missing_param_disabled_and_stale_error_state(monkeypatch) -> None:
    store = ParameterStore()
    disabled = StatefulParameter("disabled", initial_state={"enabled": False, "last_error": ""})
    stale_error = StatefulParameter("stale", initial_state={"last_error": "keep-me"})
    store.add(disabled)
    store.add(stale_error)

    engine = ScanEngine(period_s=0.01, store=store)
    monkeypatch.setattr(engine, "get_scan_order", lambda: ["missing", "disabled", "stale"])
    monkeypatch.setattr(engine, "_rebuild_graph_if_needed", lambda: None)

    original_get = store._get_runtime_param

    def selective_get(name: str):
        if name == "missing":
            raise KeyError(name)
        return original_get(name)

    monkeypatch.setattr(store, "_get_runtime_param", selective_get)

    engine.scan_once(dt=0.1)

    disabled_record = store.get_record("disabled")
    assert disabled_record.state["connected"] is False
    assert disabled_record.state["last_error"] == ""

    stale_record = store.get_record("stale")
    # Stale pre-existing errors are cleared before scan to allow recovery.
    assert stale_record.state["connected"] is True
    assert stale_record.state["last_error"] == ""


def test_scan_once_updates_average_duration_after_first_cycle(monkeypatch) -> None:
    store = ParameterStore()
    store.add(FakeParameter("temp", value=1.0))
    engine = ScanEngine(period_s=0.01, store=store)

    perf_values = iter([10.0, 10.2, 20.0, 20.4])
    monkeypatch.setattr("Services.parameterDB.parameterdb_service.engine.time.perf_counter", lambda: next(perf_values))
    monkeypatch.setattr("Services.parameterDB.parameterdb_service.engine.time.time", lambda: 100.0)

    engine.scan_once(dt=0.1)
    first_avg = engine._avg_scan_duration_s
    engine.scan_once(dt=0.1)

    assert round(first_avg, 6) == 0.2
    assert round(engine._avg_scan_duration_s, 6) == 0.22


def test_scan_engine_run_loop_start_stop_and_stats(monkeypatch) -> None:
    store = ParameterStore()
    store.add(FakeParameter("temp", value=1.0))
    engine = ScanEngine(period_s=0.01, store=store, mode="adaptive", target_utilization=0.5)

    perf_values = iter([10.0, 10.1, 10.15, 10.3])
    monkeypatch.setattr("Services.parameterDB.parameterdb_service.engine.time.perf_counter", lambda: next(perf_values))

    calls: list[float] = []

    def fake_scan_once(dt: float) -> None:
        calls.append(dt)
        with engine._state_lock:
            engine._running = False

    sleep_calls: list[float] = []
    monkeypatch.setattr(engine, "scan_once", fake_scan_once)
    monkeypatch.setattr("Services.parameterDB.parameterdb_service.engine.time.sleep", lambda seconds: sleep_calls.append(seconds))

    engine._running = True
    engine._run_loop()

    assert len(calls) == 1
    assert engine._last_effective_period_s == 0.05
    assert engine._last_sleep_s == 0.0
    assert engine._overrun_count == 1
    assert sleep_calls == [0.0]

    class FakeThread:
        def __init__(self, target=None, name: str = "", daemon: bool = False) -> None:
            self.target = target
            self.name = name
            self.daemon = daemon
            self.started = False
            self.joined = False

        def start(self) -> None:
            self.started = True

        def join(self, timeout: float | None = None) -> None:
            _ = timeout
            self.joined = True

    monkeypatch.setattr("Services.parameterDB.parameterdb_service.engine.threading.Thread", FakeThread)

    lifecycle = ScanEngine(period_s=0.01, store=store)
    lifecycle.start()
    first_thread = lifecycle._thread
    assert isinstance(first_thread, FakeThread)
    assert first_thread.started is True

    lifecycle.start()
    assert lifecycle._thread is first_thread

    lifecycle.stop()
    assert first_thread.joined is True
    assert lifecycle._thread is None

    with lifecycle._state_lock:
        lifecycle._running = True
        lifecycle._cycle_count = 3
        lifecycle._last_scan_started_at = 12.0
        lifecycle._last_scan_duration_s = 0.2
        lifecycle._avg_scan_duration_s = 0.1
        lifecycle._last_sleep_s = 0.05
        lifecycle._last_effective_period_s = 0.25
        lifecycle._overrun_count = 4

    stats = lifecycle.stats()
    assert stats["estimated_cycle_rate_hz"] == 4.0
    assert stats["estimated_utilization"] == 0.4
    assert stats["parameter_count"] == 1


def test_scan_engine_stats_none_when_effective_period_is_zero() -> None:
    engine = ScanEngine(period_s=0.0)
    with engine._state_lock:
        engine._last_effective_period_s = 0.0
        engine._avg_scan_duration_s = 1.0

    stats = engine.stats()
    assert stats["estimated_cycle_rate_hz"] is None
    assert stats["estimated_utilization"] is None


def test_scan_engine_desired_period_fixed_mode_returns_configured_period() -> None:
    engine = ScanEngine(period_s=0.02, mode="fixed", min_period_s=0.001)
    assert engine._desired_period_s(10.0) == 0.02


def test_scan_engine_run_loop_exits_immediately_when_not_running() -> None:
    engine = ScanEngine(period_s=0.01)
    engine._running = False
    engine._run_loop()


def test_scan_engine_database_pipeline_applies_calibration_and_mirror() -> None:
    store = ParameterStore()
    mirror = FakeParameter("mirror.target", value=0.0)
    calc = FakeParameter(
        "calc",
        value=1.0,
        scan_value=3.0,
    )
    calc.update_config(
        calibration_equation="2*x + 5",
        mirror_to=["mirror.target"],
    )
    store.add(mirror)
    store.add(calc)

    engine = ScanEngine(period_s=0.01, store=store)
    engine.scan_once(dt=0.1)

    calc_record = store.get_record("calc")
    assert calc_record.value == 11.0
    assert calc_record.state["calibration_output"] == 11.0
    assert calc_record.state["output_targets"] == ["mirror.target"]
    assert store.get_value("mirror.target") == 11.0


def test_scan_engine_database_pipeline_skips_on_plugin_error() -> None:
    store = ParameterStore()
    target = FakeParameter("target", value=9.0)
    bad = StatefulParameter(
        "bad",
        value=3.0,
        raise_error=True,
    )
    bad.update_config(mirror_to=["target"], calibration_equation="2*x")
    store.add(target)
    store.add(bad)

    engine = ScanEngine(period_s=0.01, store=store)
    engine.scan_once(dt=0.1)

    assert store.get_value("target") == 9.0
    assert store.get_record("bad").state["last_error"] == "scan failed"
