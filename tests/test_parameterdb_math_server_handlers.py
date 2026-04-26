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
    state = records["density_math"]["state"]
    assert state["parameter_valid"] is False
    assert state["parameter_invalid_reasons"] == ["dependency"]
    assert state["dependency_invalid_parameters"] == ["density"]
    assert state["last_error"] == ""


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
    state = records["brewcan.temperature.0"]["state"]
    assert state["parameter_valid"] is False
    assert state["parameter_invalid_reasons"] == ["dependency"]
    assert state["dependency_invalid_parameters"] == ["missing_param"]
    assert state["last_error"] == ""
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
                "equation": "0.6*x",
                "input_unit": "V",
                "output_unit": "bar",
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

    # calibration: 5 + 1 = 6V; transducer equation: 0.6 * 6 = 3.6bar
    assert records["sensor.volt"]["value"] == pytest.approx(3.6, abs=1e-9)
    assert state.get("transducer_id") == "volt_to_pressure"
    assert state.get("transducer_input") == 6.0
    assert state.get("transducer_output") == pytest.approx(3.6, abs=1e-9)
    assert state.get("transducer_equation") == "0.6*x"
    assert state.get("transducer_symbols") == ["x"]
    assert state.get("transducer_input_unit") == "V"
    assert state.get("transducer_output_unit") == "bar"


def test_transducer_pipeline_supports_equation_mode_after_calibration() -> None:
    server = _build_server_with_math()

    created = server.api_create_transducer(
        {
            "transducer": {
                "name": "eq_quad",
                "equation": "x**2 + 1",
                "input_unit": "V",
                "output_unit": "kPa",
                "description": "quadratic fit",
            }
        }
    )
    assert created["name"] == "eq_quad"
    assert created["equation"] == "x**2 + 1"

    assert server.api_create_parameter(
        {
            "name": "sensor.eq",
            "parameter_type": "static",
            "value": 2.0,
            "config": {
                "calibration_equation": "x + 1",
                "transducer_id": "eq_quad",
            },
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)
    records = server.api_describe({})
    state = records["sensor.eq"]["state"]

    # calibration: 2 + 1 = 3; transducer equation: 3**2 + 1 = 10
    assert records["sensor.eq"]["value"] == pytest.approx(10.0, abs=1e-9)
    assert state.get("transducer_equation") == "x**2 + 1"
    assert state.get("transducer_symbols") == ["x"]
    assert state.get("transducer_input") == pytest.approx(3.0, abs=1e-9)
    assert state.get("transducer_output") == pytest.approx(10.0, abs=1e-9)


def test_transducer_pipeline_additive_mapping_does_not_accumulate_between_scans() -> None:
    server = _build_server_with_math()

    server.api_create_transducer(
        {
            "transducer": {
                "name": "wide_gain",
                "equation": "10*x",
                "input_unit": "V",
                "output_unit": "u",
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


def test_transducer_pipeline_reapplies_from_manual_raw_write_not_cached_output() -> None:
    server = _build_server_with_math()

    server.api_create_transducer(
        {
            "transducer": {
                "name": "gain10",
                "equation": "10*x",
                "input_unit": "V",
                "output_unit": "u",
            }
        }
    )

    assert server.api_create_parameter(
        {
            "name": "sensor.raw",
            "parameter_type": "static",
            "value": 1.0,
            "config": {
                "transducer_id": "gain10",
            },
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)
    assert server.api_get_value({"name": "sensor.raw"}) == pytest.approx(10.0, abs=1e-9)

    # Manual writes are raw inputs; next scan should map from 10.0 -> 100.0.
    assert server.api_set_value({"name": "sensor.raw", "value": 10.0}) is True
    server.engine.scan_once(dt=0.1)
    assert server.api_get_value({"name": "sensor.raw"}) == pytest.approx(100.0, abs=1e-9)


def test_pipeline_calibration_plus_transducer_does_not_accumulate_between_scans() -> None:
    server = _build_server_with_math()

    server.api_create_transducer(
        {
            "transducer": {
                "name": "combo_gain",
                "equation": "10*x",
                "input_unit": "V",
                "output_unit": "u",
            }
        }
    )

    assert server.api_create_parameter(
        {
            "name": "sensor.combo",
            "parameter_type": "static",
            "value": 1.0,
            "config": {
                "calibration_equation": "x + 1",
                "transducer_id": "combo_gain",
            },
            "metadata": {},
        }
    ) is True

    # First scan: (1 + 1) -> 2, then transducer equation 10*2 = 20.
    server.engine.scan_once(dt=0.1)
    assert server.api_get_value({"name": "sensor.combo"}) == pytest.approx(20.0, abs=1e-9)

    # Second scan without fresh raw input should remain stable at 20 (no re-application drift).
    server.engine.scan_once(dt=0.1)
    assert server.api_get_value({"name": "sensor.combo"}) == pytest.approx(20.0, abs=1e-9)

    # Fresh raw input should still apply exactly once.
    assert server.api_set_value({"name": "sensor.combo", "value": 2.0}) is True
    server.engine.scan_once(dt=0.1)
    # (2 + 1) -> 3, then 10*3 = 30.
    assert server.api_get_value({"name": "sensor.combo"}) == pytest.approx(30.0, abs=1e-9)


def test_pipeline_marks_transducer_limit_invalid_independently() -> None:
    server = _build_server_with_math()

    server.api_create_transducer(
        {
            "transducer": {
                "name": "gain2",
                "equation": "2*x",
                "min_limit": 0.0,
                "max_limit": 9.0,
                "input_unit": "V",
                "output_unit": "bar",
            }
        }
    )

    assert server.api_create_parameter(
        {
            "name": "sensor.pressure",
            "parameter_type": "static",
            "value": 5.0,
            "config": {
                "calibration_equation": "x",
                "transducer_id": "gain2",
                "channel_min": 0.0,
                "channel_max": 10.0,
            },
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)
    record = server.api_describe({})["sensor.pressure"]
    state = record["state"]

    # Channel is valid (5V), transducer output is invalid (10bar > 9bar).
    assert state.get("channel_limit_in_range") is True
    assert state.get("transducer_limit_in_range") is False
    assert "transducer_limit_violation" in state
    assert state.get("parameter_valid") is False
    assert state.get("parameter_invalid_reasons") == ["transducer"]

    server.api_update_transducer(
        {
            "name": "gain2",
            "transducer": {
                "equation": "2*x",
                "min_limit": None,
                "max_limit": None,
                "input_unit": "V",
                "output_unit": "bar",
            },
        }
    )

    server.engine.scan_once(dt=0.1)
    recovered = server.api_describe({})["sensor.pressure"]
    recovered_state = recovered["state"]
    assert recovered_state.get("transducer_limit_in_range") is True
    assert "transducer_limit_violation" not in recovered_state
    assert recovered_state.get("parameter_valid") is True
    assert "parameter_invalid_reasons" not in recovered_state


def test_pipeline_marks_channel_limit_invalid_independently() -> None:
    server = _build_server_with_math()

    server.api_create_transducer(
        {
            "transducer": {
                "name": "gain_half",
                "equation": "0.5*x",
                "min_limit": 0.0,
                "max_limit": 10.0,
                "input_unit": "V",
                "output_unit": "bar",
            }
        }
    )

    assert server.api_create_parameter(
        {
            "name": "sensor.channel",
            "parameter_type": "static",
            "value": 11.0,
            "config": {
                "calibration_equation": "x",
                "transducer_id": "gain_half",
                "channel_min": 0.0,
                "channel_max": 10.0,
            },
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)
    record = server.api_describe({})["sensor.channel"]
    state = record["state"]

    # Channel is invalid (11V > 10V), transducer output is valid (5.5bar).
    assert state.get("channel_limit_in_range") is False
    assert "channel_limit_violation" in state
    assert state.get("transducer_limit_in_range") is True
    assert "transducer_limit_violation" not in state
    assert state.get("parameter_valid") is False
    assert state.get("parameter_invalid_reasons") == ["channel"]


def test_pipeline_failure_clears_stale_pipeline_state_details() -> None:
    server = _build_server_with_math()

    assert server.api_create_parameter(
        {
            "name": "src.temp",
            "parameter_type": "static",
            "value": 10.0,
            "config": {
                "calibration_equation": "x + 5",
            },
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)
    first = server.api_describe({})["src.temp"]
    assert first["state"].get("calibration_input") == 10.0
    assert first["state"].get("calibration_output") == 15.0

    assert (
        server.api_update_config(
            {
                "name": "src.temp",
                "changes": {
                    "calibration_equation": "x + missing_param",
                },
            }
        )
        is True
    )
    server.engine.scan_once(dt=0.1)
    second = server.api_describe({})["src.temp"]

    assert second["state"]["parameter_valid"] is False
    assert second["state"]["parameter_invalid_reasons"] == ["dependency"]
    assert second["state"]["dependency_invalid_parameters"] == ["missing_param"]
    assert second["state"]["last_error"] == ""
    assert "calibration_input" not in second["state"]
    assert "calibration_output" not in second["state"]


def test_api_set_value_clears_prior_pipeline_runtime_state_until_next_scan() -> None:
    server = _build_server_with_math()

    assert server.api_create_parameter(
        {
            "name": "src.temp",
            "parameter_type": "static",
            "value": 10.0,
            "config": {
                "calibration_equation": "x + 5",
            },
            "metadata": {},
        }
    ) is True

    server.engine.scan_once(dt=0.1)
    scanned = server.api_describe({})["src.temp"]
    assert scanned["value"] == 15.0
    assert scanned["signal_value"] == 10.0
    assert scanned["state"].get("calibration_output") == 15.0

    publish_broker = EventBroker()
    server.engine.store.attach_event_broker(publish_broker)
    _token, events, _size = publish_broker.subscribe(names=["src.temp"])
    assert server.api_set_value({"name": "src.temp", "value": 40.0}) is True
    emitted = [events.get_nowait(), events.get_nowait()]
    state_event = next(item for item in emitted if item["event"] == "state_changed")
    assert state_event["name"] == "src.temp"
    assert state_event["state"]["signal_value"] == 40.0

    pending = server.api_describe({})["src.temp"]

    # Pipeline is pending after external signal write, so value falls back to raw.
    assert pending["value"] == 40.0
    assert pending["signal_value"] == 40.0
    assert "calibration_input" not in pending["state"]
    assert "calibration_output" not in pending["state"]
    assert "parameter_valid" not in pending["state"]
    assert "parameter_invalid_reasons" not in pending["state"]


def test_transducer_crud_handlers() -> None:
    server = _build_server_with_math()

    server.api_create_transducer(
        {
            "transducer": {
                "name": "t1",
                "equation": "2*x + 4",
                "input_unit": "V",
                "output_unit": "mA",
            }
        }
    )

    updated = server.api_update_transducer(
        {
            "name": "t1",
            "transducer": {
                "equation": "2*x + 6",
                "description": "updated",
            },
        }
    )
    assert updated["equation"] == "2*x + 6"
    assert updated["description"] == "updated"

    listed = server.api_list_transducers({})
    assert len(listed) == 1
    assert listed[0]["name"] == "t1"
    assert listed[0]["equation"] == "2*x + 6"

    assert server.api_delete_transducer({"name": "t1"}) is True
    assert server.api_list_transducers({}) == []
