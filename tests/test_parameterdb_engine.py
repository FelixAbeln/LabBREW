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

    def scan(self, ctx) -> None:
        if self._raise_error:
            raise RuntimeError("scan failed")
        if self._scan_value is not None:
            self.set_value(self._scan_value)


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