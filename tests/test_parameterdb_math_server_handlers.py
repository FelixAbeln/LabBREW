from __future__ import annotations

from test_parameterdb_server_handlers import FakeAudit

from Services.parameterDB.parameterdb_service.engine import ScanEngine
from Services.parameterDB.parameterdb_service.event_broker import EventBroker
from Services.parameterDB.parameterdb_service.loader import PluginRegistry
from Services.parameterDB.parameterdb_service.server import SignalTCPServer
from Services.parameterDB.parameterdb_service.store import ParameterStore
from Services.parameterDB.plugins.math.implementation import MathPlugin
from Services.parameterDB.plugins.math.ui import get_ui_spec as get_math_ui_spec
from Services.parameterDB.plugins.static.implementation import StaticPlugin
from Services.parameterDB.plugins.static.ui import get_ui_spec as get_static_ui_spec


def _build_server_with_math() -> SignalTCPServer:
    registry = PluginRegistry()
    registry.register(StaticPlugin(), ui_spec=get_static_ui_spec())
    registry.register(MathPlugin(), ui_spec=get_math_ui_spec())

    server = SignalTCPServer.__new__(SignalTCPServer)
    server.engine = ScanEngine(period_s=0.01, store=ParameterStore())
    server.registry = registry
    server.event_broker = EventBroker()
    server.audit_log = FakeAudit()
    server.snapshot_manager = None
    return server


def test_api_math_parameter_evaluates_and_mirrors_to_output_params() -> None:
    server = _build_server_with_math()

    assert server.api_create_parameter({"name": "density", "parameter_type": "static", "value": 4.5, "config": {}, "metadata": {}}) is True
    assert server.api_create_parameter({"name": "linked_density", "parameter_type": "static", "value": 0.0, "config": {}, "metadata": {}}) is True
    assert server.api_create_parameter(
        {
            "name": "density_math",
            "parameter_type": "math",
            "value": 0.0,
            "config": {
                "equation": "density * 2 / 2",
                "output_params": ["linked_density"],
            },
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)

    assert server.api_get_value({"name": "density_math"}) == 4.5
    assert server.api_get_value({"name": "linked_density"}) == 4.5

    records = server.api_describe({})
    density_math = records["density_math"]
    assert density_math["state"]["symbols"] == ["density"]
    assert density_math["state"]["output_targets"] == ["linked_density"]
    assert density_math["state"]["last_error"] == ""


def test_api_math_parameter_missing_symbol_sets_error_and_keeps_output() -> None:
    server = _build_server_with_math()

    assert server.api_create_parameter({"name": "linked_density", "parameter_type": "static", "value": 9.0, "config": {}, "metadata": {}}) is True
    assert server.api_create_parameter(
        {
            "name": "density_math",
            "parameter_type": "math",
            "value": 3.0,
            "config": {
                "equation": "density * 2",
                "output_params": ["linked_density"],
            },
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)

    assert server.api_get_value({"name": "density_math"}) == 3.0
    assert server.api_get_value({"name": "linked_density"}) == 9.0

    records = server.api_describe({})
    error_text = records["density_math"]["state"]["last_error"]
    assert "missing parameters in equation" in error_text


def test_api_math_parameter_supports_dotted_parameter_names() -> None:
    server = _build_server_with_math()

    assert server.api_create_parameter({"name": "brewcan.density.0", "parameter_type": "static", "value": 1.061, "config": {}, "metadata": {}}) is True
    assert server.api_create_parameter(
        {
            "name": "density_math",
            "parameter_type": "math",
            "value": 0.0,
            "config": {
                "equation": "brewcan.density.0 * 2 / 2",
            },
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)

    assert server.api_get_value({"name": "density_math"}) == 1.061
    records = server.api_describe({})
    assert records["density_math"]["state"]["symbols"] == ["brewcan.density.0"]
    assert records["density_math"]["state"]["last_error"] == ""
