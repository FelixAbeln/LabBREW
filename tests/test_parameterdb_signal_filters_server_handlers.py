from __future__ import annotations

from Services.parameterDB.parameterdb_service.engine import ScanEngine
from Services.parameterDB.parameterdb_service.event_broker import EventBroker
from Services.parameterDB.parameterdb_service.loader import PluginRegistry
from Services.parameterDB.parameterdb_service.server import SignalTCPServer
from Services.parameterDB.parameterdb_service.store import ParameterStore
from Services.parameterDB.plugins.median.implementation import MedianPlugin
from Services.parameterDB.plugins.median.ui import get_ui_spec as get_median_ui_spec
from Services.parameterDB.plugins.moving_average.implementation import MovingAveragePlugin
from Services.parameterDB.plugins.moving_average.ui import get_ui_spec as get_moving_average_ui_spec
from Services.parameterDB.plugins.static.implementation import StaticPlugin
from Services.parameterDB.plugins.static.ui import get_ui_spec as get_static_ui_spec
from test_parameterdb_server_handlers import FakeAudit


def _build_server_with_signal_filters() -> SignalTCPServer:
    registry = PluginRegistry()
    registry.register(StaticPlugin(), ui_spec=get_static_ui_spec())
    registry.register(MovingAveragePlugin(), ui_spec=get_moving_average_ui_spec())
    registry.register(MedianPlugin(), ui_spec=get_median_ui_spec())

    server = SignalTCPServer.__new__(SignalTCPServer)
    server.engine = ScanEngine(period_s=0.01, store=ParameterStore())
    server.registry = registry
    server.event_broker = EventBroker()
    server.audit_log = FakeAudit()
    server.snapshot_manager = None
    return server


def test_api_moving_average_parameter_filters_and_mirrors_output() -> None:
    server = _build_server_with_signal_filters()

    assert server.api_create_parameter({"name": "signal", "parameter_type": "static", "value": 10.0, "config": {}, "metadata": {}}) is True
    assert server.api_create_parameter({"name": "signal.avg", "parameter_type": "static", "value": 0.0, "config": {}, "metadata": {}}) is True
    assert server.api_create_parameter(
        {
            "name": "signal_ma",
            "parameter_type": "moving_average",
            "value": 0.0,
            "config": {"source": "signal", "window": 3, "output_params": ["signal.avg"]},
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)
    assert server.api_get_value({"name": "signal_ma"}) == 10.0

    assert server.api_set_value({"name": "signal", "value": 20.0}) is True
    server.engine.scan_once(dt=0.1)

    assert server.api_get_value({"name": "signal_ma"}) == 15.0
    assert server.api_get_value({"name": "signal.avg"}) == 15.0
    records = server.api_describe({})
    assert records["signal_ma"]["state"]["output_targets"] == ["signal.avg"]
    assert records["signal_ma"]["state"]["last_error"] == ""


def test_api_median_parameter_filters_and_mirrors_output() -> None:
    server = _build_server_with_signal_filters()

    assert server.api_create_parameter({"name": "signal", "parameter_type": "static", "value": 10.0, "config": {}, "metadata": {}}) is True
    assert server.api_create_parameter({"name": "signal.med", "parameter_type": "static", "value": 0.0, "config": {}, "metadata": {}}) is True
    assert server.api_create_parameter(
        {
            "name": "signal_med",
            "parameter_type": "median",
            "value": 0.0,
            "config": {"source": "signal", "window": 3, "output_params": ["signal.med"]},
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)
    assert server.api_get_value({"name": "signal_med"}) == 10.0

    assert server.api_set_value({"name": "signal", "value": 100.0}) is True
    server.engine.scan_once(dt=0.1)
    assert server.api_get_value({"name": "signal_med"}) == 55.0

    assert server.api_set_value({"name": "signal", "value": 12.0}) is True
    server.engine.scan_once(dt=0.1)

    assert server.api_get_value({"name": "signal_med"}) == 12.0
    assert server.api_get_value({"name": "signal.med"}) == 12.0
    records = server.api_describe({})
    assert records["signal_med"]["state"]["output_targets"] == ["signal.med"]
    assert records["signal_med"]["state"]["last_error"] == ""
