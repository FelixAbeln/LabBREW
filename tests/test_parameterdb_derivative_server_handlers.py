from __future__ import annotations

import pytest

from Services.parameterDB.parameterdb_service.engine import ScanEngine
from Services.parameterDB.parameterdb_service.event_broker import EventBroker
from Services.parameterDB.parameterdb_service.loader import PluginRegistry
from Services.parameterDB.parameterdb_service.server import SignalTCPServer
from Services.parameterDB.parameterdb_service.store import ParameterStore
from Services.parameterDB.plugins.derivative.implementation import DerivativePlugin
from Services.parameterDB.plugins.derivative.ui import get_ui_spec as get_derivative_ui_spec
from Services.parameterDB.plugins.static.implementation import StaticPlugin
from Services.parameterDB.plugins.static.ui import get_ui_spec as get_static_ui_spec
from test_parameterdb_server_handlers import FakeAudit


def _build_server() -> SignalTCPServer:
    registry = PluginRegistry()
    registry.register(StaticPlugin(), ui_spec=get_static_ui_spec())
    registry.register(DerivativePlugin(), ui_spec=get_derivative_ui_spec())

    server = SignalTCPServer.__new__(SignalTCPServer)
    server.engine = ScanEngine(period_s=0.01, store=ParameterStore())
    server.registry = registry
    server.event_broker = EventBroker()
    server.audit_log = FakeAudit()
    server.snapshot_manager = None
    return server


def test_api_derivative_continuous_mode_computes_rate_and_mirrors_output() -> None:
    server = _build_server()

    assert server.api_create_parameter({"name": "temp", "parameter_type": "static", "value": 10.0, "config": {}, "metadata": {}}) is True
    assert server.api_create_parameter({"name": "temp.rate", "parameter_type": "static", "value": 0.0, "config": {}, "metadata": {}}) is True
    assert server.api_create_parameter(
        {
            "name": "temp_deriv",
            "parameter_type": "derivative",
            "value": 0.0,
            "config": {
                "source": "temp",
                "mode": "continuous",
                "output_params": ["temp.rate"],
            },
            "metadata": {},
        }
    ) is True

    # First scan — no previous input, derivative = 0
    server.engine.scan_once(dt=1.0)
    assert server.api_get_value({"name": "temp_deriv"}) == 0.0

    # Change source: +5 over 1 s → derivative = 5.0 / 1.0 = 5.0
    assert server.api_set_value({"name": "temp", "value": 15.0}) is True
    server.engine.scan_once(dt=1.0)
    assert server.api_get_value({"name": "temp_deriv"}) == 5.0
    assert server.api_get_value({"name": "temp.rate"}) == 5.0

    records = server.api_describe({})
    state = records["temp_deriv"]["state"]
    assert state["output_targets"] == ["temp.rate"]
    assert state["last_error"] == ""
    assert state["mode"] == "continuous"
    assert state["source"] == "temp"


def test_api_derivative_window_mode_computes_rate_and_mirrors_output() -> None:
    server = _build_server()

    assert server.api_create_parameter({"name": "pressure", "parameter_type": "static", "value": 0.0, "config": {}, "metadata": {}}) is True
    assert server.api_create_parameter({"name": "pressure.rate", "parameter_type": "static", "value": 0.0, "config": {}, "metadata": {}}) is True
    assert server.api_create_parameter(
        {
            "name": "pressure_deriv",
            "parameter_type": "derivative",
            "value": 0.0,
            "config": {
                "source": "pressure",
                "mode": "window",
                "window_s": 2.0,
                "output_params": ["pressure.rate"],
            },
            "metadata": {},
        }
    ) is True

    # t=0: value=0
    server.engine.scan_once(dt=1.0)
    assert server.api_get_value({"name": "pressure_deriv"}) == 0.0

    # t=1: value=10 → only 1 sample in history, span=0, derivative=0
    assert server.api_set_value({"name": "pressure", "value": 10.0}) is True
    server.engine.scan_once(dt=1.0)

    # t=2: value=20 → oldest=0 at t=0, current=20 at t=2, span=2 → derivative=10.0
    assert server.api_set_value({"name": "pressure", "value": 20.0}) is True
    server.engine.scan_once(dt=1.0)
    result = server.api_get_value({"name": "pressure_deriv"})
    assert result == pytest.approx(10.0, abs=0.1)
    assert server.api_get_value({"name": "pressure.rate"}) == pytest.approx(10.0, abs=0.1)

    records = server.api_describe({})
    state = records["pressure_deriv"]["state"]
    assert state["output_targets"] == ["pressure.rate"]
    assert state["last_error"] == ""
    assert state["mode"] == "window"
