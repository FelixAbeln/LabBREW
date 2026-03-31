from __future__ import annotations

import Services.parameterDB.plugins.condition.implementation as condition_module
from Services.parameterDB.parameterdb_service.engine import ScanEngine
from Services.parameterDB.parameterdb_service.event_broker import EventBroker
from Services.parameterDB.parameterdb_service.loader import PluginRegistry
from Services.parameterDB.parameterdb_service.server import SignalTCPServer
from Services.parameterDB.parameterdb_service.store import ParameterStore
from Services.parameterDB.plugins.condition.implementation import ConditionPlugin
from Services.parameterDB.plugins.condition.ui import get_ui_spec as get_condition_ui_spec
from Services.parameterDB.plugins.static.implementation import StaticPlugin
from Services.parameterDB.plugins.static.ui import get_ui_spec as get_static_ui_spec
from test_parameterdb_server_handlers import FakeAudit


def _build_server_with_condition() -> SignalTCPServer:
    registry = PluginRegistry()
    registry.register(StaticPlugin(), ui_spec=get_static_ui_spec())
    registry.register(ConditionPlugin(), ui_spec=get_condition_ui_spec())

    server = SignalTCPServer.__new__(SignalTCPServer)
    server.engine = ScanEngine(period_s=0.01, store=ParameterStore())
    server.registry = registry
    server.event_broker = EventBroker()
    server.audit_log = FakeAudit()
    server.snapshot_manager = None
    return server


def test_api_condition_parameter_evaluates_boolean_result() -> None:
    server = _build_server_with_condition()

    assert server.api_create_parameter({"name": "reactor.temp", "parameter_type": "static", "value": 68.0, "config": {}, "metadata": {}}) is True
    assert server.api_create_parameter(
        {
            "name": "reactor.hot",
            "parameter_type": "condition",
            "value": False,
            "config": {"condition": "cond:reactor.temp:>=:65"},
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)

    assert server.api_get_value({"name": "reactor.hot"}) is True
    records = server.api_describe({})
    assert records["reactor.hot"]["state"]["logic_kind"] == "condition"
    assert records["reactor.hot"]["state"]["condition_kind"] == "atomic"
    assert records["reactor.hot"]["state"]["source"] == "reactor.temp"
    assert records["reactor.hot"]["state"]["sources"] == ["reactor.temp"]
    assert records["reactor.hot"]["state"]["last_error"] == ""


def test_api_condition_parameter_reports_missing_source() -> None:
    server = _build_server_with_condition()

    assert server.api_create_parameter(
        {
            "name": "reactor.ready",
            "parameter_type": "condition",
            "value": True,
            "config": {"condition": "cond:missing.signal:==:1"},
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)

    assert server.api_get_value({"name": "reactor.ready"}) is True
    records = server.api_describe({})
    assert records["reactor.ready"]["state"]["last_error"] == "Missing value for missing.signal"


def test_api_condition_parameter_honors_hold_time(monkeypatch) -> None:
    now = {"t": 100.0}
    monkeypatch.setattr(condition_module.time, "monotonic", lambda: now["t"])

    server = _build_server_with_condition()

    assert server.api_create_parameter({"name": "reactor.temp", "parameter_type": "static", "value": 68.0, "config": {}, "metadata": {}}) is True
    assert server.api_create_parameter(
        {
            "name": "reactor.hot",
            "parameter_type": "condition",
            "value": False,
            "config": {"condition": "cond:reactor.temp:>=:65:2"},
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)
    assert server.api_get_value({"name": "reactor.hot"}) is False

    now["t"] = 102.1
    server.engine.scan_once(dt=0.1)

    assert server.api_get_value({"name": "reactor.hot"}) is True
    records = server.api_describe({})
    assert records["reactor.hot"]["state"]["required_for_s"] == 2.0