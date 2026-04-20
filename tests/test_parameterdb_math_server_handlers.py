from __future__ import annotations

import pytest
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


def test_db_pipeline_recovers_after_calibration_error_and_applies_mirror() -> None:
    server = _build_server_with_math()

    assert server.api_create_parameter(
        {
            "name": "brewcan.temperature.0",
            "parameter_type": "static",
            "value": 20.5,
            "config": {},
            "metadata": {},
        }
    ) is True
    assert server.api_create_parameter(
        {
            "name": "brewcan.temperature.comp",
            "parameter_type": "static",
            "value": 0.0,
            "config": {},
            "metadata": {},
        }
    ) is True

    # First set an invalid equation to produce a pipeline error.
    assert (
        server.api_update_config(
            {
                "name": "brewcan.temperature.0",
                "changes": {
                    "calibration_equation": "x + missing_param",
                    "mirror_to": ["brewcan.temperature.comp"],
                },
            }
        )
        is True
    )
    server.engine.scan_once(dt=0.1)
    records = server.api_describe({})
    assert "missing parameters in calibration equation" in records["brewcan.temperature.0"]["state"]["last_error"]
    assert server.api_get_value({"name": "brewcan.temperature.comp"}) == 0.0

    # Fix equation; pipeline should recover on the next scan and apply both
    # calibration and mirror writes.
    assert (
        server.api_update_config(
            {
                "name": "brewcan.temperature.0",
                "changes": {
                    "calibration_equation": "x + 100000",
                    "mirror_to": ["brewcan.temperature.comp"],
                },
            }
        )
        is True
    )
    server.engine.scan_once(dt=0.1)

    assert server.api_get_value({"name": "brewcan.temperature.0"}) == 100020.5
    assert server.api_get_value({"name": "brewcan.temperature.comp"}) == 100020.5
    records = server.api_describe({})
    assert records["brewcan.temperature.0"]["state"]["last_error"] == ""


def test_db_pipeline_additive_calibration_does_not_accumulate_between_scans() -> None:
    server = _build_server_with_math()

    assert server.api_create_parameter(
        {
            "name": "src.temp",
            "parameter_type": "static",
            "value": 30.0,
            "config": {},
            "metadata": {},
        }
    ) is True
    assert server.api_create_parameter(
        {
            "name": "dst.temp",
            "parameter_type": "static",
            "value": 0.0,
            "config": {},
            "metadata": {},
        }
    ) is True

    assert (
        server.api_update_config(
            {
                "name": "src.temp",
                "changes": {
                    "calibration_equation": "x + 15",
                    "mirror_to": ["dst.temp"],
                },
            }
        )
        is True
    )

    # First scan applies offset once.
    server.engine.scan_once(dt=0.1)
    assert server.api_get_value({"name": "src.temp"}) == 45.0
    assert server.api_get_value({"name": "dst.temp"}) == 45.0

    # Second scan without new raw update should remain stable (no accumulation).
    server.engine.scan_once(dt=0.1)
    assert server.api_get_value({"name": "src.temp"}) == 45.0
    assert server.api_get_value({"name": "dst.temp"}) == 45.0

    # External source update should apply offset to the new raw value.
    assert server.api_set_value({"name": "src.temp", "value": 40.0}) is True
    server.engine.scan_once(dt=0.1)
    assert server.api_get_value({"name": "src.temp"}) == 55.0
    assert server.api_get_value({"name": "dst.temp"}) == 55.0


def test_db_pipeline_clears_missing_output_targets_after_target_created() -> None:
    server = _build_server_with_math()

    assert server.api_create_parameter(
        {
            "name": "src.temp",
            "parameter_type": "static",
            "value": 10.0,
            "config": {},
            "metadata": {},
        }
    ) is True

    assert (
        server.api_update_config(
            {
                "name": "src.temp",
                "changes": {
                    "mirror_to": ["dst.temp"],
                },
            }
        )
        is True
    )

    # First scan: target is missing.
    server.engine.scan_once(dt=0.1)
    records = server.api_describe({})
    state = records["src.temp"]["state"]
    assert state.get("output_targets") == []
    assert state.get("missing_output_targets") == ["dst.temp"]

    # Add target and scan again: missing list should be cleared.
    assert server.api_create_parameter(
        {
            "name": "dst.temp",
            "parameter_type": "static",
            "value": 0.0,
            "config": {},
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)
    records = server.api_describe({})
    state = records["src.temp"]["state"]
    assert state.get("output_targets") == ["dst.temp"]
    assert "missing_output_targets" not in state


def test_transducer_pipeline_maps_value_after_calibration() -> None:
    server = _build_server_with_math()

    created = server.api_create_transducer(
        {
            "transducer": {
                "name": "volt_to_pressure",
                "input_min": 0.0,
                "input_max": 10.0,
                "output_min": 0.0,
                "output_max": 6.0,
                "input_unit": "V",
                "output_unit": "bar",
                "clamp": True,
            }
        }
    )
    assert created["name"] == "volt_to_pressure"

    assert server.api_create_parameter(
        {
            "name": "sensor.volt",
            "parameter_type": "static",
            "value": 5.0,
            "config": {
                "calibration_equation": "x + 1",
                "transducer_id": "volt_to_pressure",
            },
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)
    records = server.api_describe({})
    state = records["sensor.volt"]["state"]

    # calibration: 5 + 1 = 6V; transducer: 6/10 * 6bar = 3.6bar
    assert records["sensor.volt"]["value"] == pytest.approx(3.6, abs=1e-9)
    assert state.get("transducer_id") == "volt_to_pressure"
    assert state.get("transducer_input") == 6.0
    assert state.get("transducer_output") == pytest.approx(3.6, abs=1e-9)
    assert state.get("transducer_input_unit") == "V"
    assert state.get("transducer_output_unit") == "bar"


def test_transducer_pipeline_additive_mapping_does_not_accumulate_between_scans() -> None:
    server = _build_server_with_math()

    server.api_create_transducer(
        {
            "transducer": {
                "name": "wide_gain",
                "input_min": 0.0,
                "input_max": 10.0,
                "output_min": 0.0,
                "output_max": 100.0,
                "input_unit": "V",
                "output_unit": "u",
                "clamp": False,
            }
        }
    )

    assert server.api_create_parameter(
        {
            "name": "sensor.raw",
            "parameter_type": "static",
            "value": 1.0,
            "config": {
                "transducer_id": "wide_gain",
            },
            "metadata": {},
        }
    ) is True

    # First scan maps 1.0 -> 10.0
    server.engine.scan_once(dt=0.1)
    assert server.api_get_value({"name": "sensor.raw"}) == pytest.approx(10.0, abs=1e-9)

    # Second scan must stay stable (must NOT remap 10.0 -> 100.0).
    server.engine.scan_once(dt=0.1)
    assert server.api_get_value({"name": "sensor.raw"}) == pytest.approx(10.0, abs=1e-9)

    # Fresh external raw update should map once from new raw input.
    assert server.api_set_value({"name": "sensor.raw", "value": 2.0}) is True
    server.engine.scan_once(dt=0.1)
    assert server.api_get_value({"name": "sensor.raw"}) == pytest.approx(20.0, abs=1e-9)


def test_transducer_crud_handlers() -> None:
    server = _build_server_with_math()

    server.api_create_transducer(
        {
            "transducer": {
                "name": "t1",
                "input_min": 0,
                "input_max": 10,
                "output_min": 4,
                "output_max": 20,
                "input_unit": "V",
                "output_unit": "mA",
                "clamp": True,
            }
        }
    )

    updated = server.api_update_transducer(
        {
            "name": "t1",
            "transducer": {
                "output_max": 24,
                "description": "updated",
            },
        }
    )
    assert updated["output_max"] == 24.0
    assert updated["description"] == "updated"

    listed = server.api_list_transducers({})
    assert len(listed) == 1
    assert listed[0]["name"] == "t1"

    assert server.api_delete_transducer({"name": "t1"}) is True
    assert server.api_list_transducers({}) == []
