from __future__ import annotations

from Services.parameterDB.parameterdb_service.engine import ScanEngine
from Services.parameterDB.parameterdb_service.event_broker import EventBroker
from Services.parameterDB.parameterdb_service.loader import PluginRegistry
from Services.parameterDB.parameterdb_service.server import SignalTCPServer
from Services.parameterDB.parameterdb_service.store import ParameterStore
from Services.parameterDB.plugins.lowpass.implementation import LowpassPlugin
from Services.parameterDB.plugins.lowpass.ui import get_ui_spec as get_lowpass_ui_spec
from Services.parameterDB.plugins.static.implementation import StaticPlugin
from Services.parameterDB.plugins.static.ui import get_ui_spec as get_static_ui_spec
from test_parameterdb_server_handlers import FakeAudit


def _build_server_with_lowpass() -> SignalTCPServer:
    registry = PluginRegistry()
    registry.register(StaticPlugin(), ui_spec=get_static_ui_spec())
    registry.register(LowpassPlugin(), ui_spec=get_lowpass_ui_spec())

    server = SignalTCPServer.__new__(SignalTCPServer)
    server.engine = ScanEngine(period_s=0.01, store=ParameterStore())
    server.registry = registry
    server.event_broker = EventBroker()
    server.audit_log = FakeAudit()
    server.snapshot_manager = None
    return server


def test_api_lowpass_parameter_filters_and_mirrors_output() -> None:
    server = _build_server_with_lowpass()

    assert server.api_create_parameter({"name": "signal", "parameter_type": "static", "value": 10.0, "config": {}, "metadata": {}}) is True
    assert server.api_create_parameter({"name": "signal.filtered", "parameter_type": "static", "value": 0.0, "config": {}, "metadata": {}}) is True
    assert server.api_create_parameter(
        {
            "name": "signal_lp",
            "parameter_type": "lowpass",
            "value": 0.0,
            "config": {
                "source": "signal",
                "tau_s": 1.0,
                "output_params": ["signal.filtered"],
            },
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)
    assert server.api_get_value({"name": "signal_lp"}) == 10.0

    assert server.api_set_value({"name": "signal", "value": 20.0}) is True
    server.engine.scan_once(dt=1.0)

    assert server.api_get_value({"name": "signal_lp"}) == 15.0
    assert server.api_get_value({"name": "signal.filtered"}) == 15.0

    records = server.api_describe({})
    lowpass = records["signal_lp"]
    assert lowpass["state"]["source"] == "signal"
    assert lowpass["state"]["alpha"] == 0.5
    assert lowpass["state"]["output_targets"] == ["signal.filtered"]
    assert lowpass["state"]["last_error"] == ""


def test_api_lowpass_parameter_missing_source_sets_error_and_keeps_output() -> None:
    server = _build_server_with_lowpass()

    assert server.api_create_parameter(
        {
            "name": "signal_lp",
            "parameter_type": "lowpass",
            "value": 3.0,
            "config": {
                "source": "signal",
                "tau_s": 1.0,
            },
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)

    assert server.api_get_value({"name": "signal_lp"}) == 3.0
    records = server.api_describe({})
    assert "missing source parameter" in records["signal_lp"]["state"]["last_error"]