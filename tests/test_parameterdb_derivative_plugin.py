from __future__ import annotations

from types import SimpleNamespace

from Services.parameterDB.parameterdb_service.store import ParameterStore
from Services.parameterDB.plugins.derivative.implementation import DerivativePlugin
from Services.parameterDB.plugins.static.implementation import StaticParameter


def _ctx(store: ParameterStore, *, dt: float):
    return SimpleNamespace(store=store, dt=dt)


def test_derivative_plugin_evaluates_rate_and_mirrors_output() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.temp", value=10.0))
    store.add(StaticParameter("reactor.temp_rate", value=0.0))

    plugin = DerivativePlugin()
    param = plugin.create(
        "d_temp",
        config={
            "source": "reactor.temp",
            "output_params": ["reactor.temp_rate"],
        },
        value=0.0,
    )

    param.scan(_ctx(store, dt=1.0))
    assert float(param.get_value()) == 0.0

    store.set_value("reactor.temp", 13.0)
    param.scan(_ctx(store, dt=2.0))

    assert float(param.get_value()) == 1.5
    assert float(store.get_value("reactor.temp_rate")) == 1.5
    assert param.state["source"] == "reactor.temp"
    assert param.state["delta"] == 3.0
    assert param.state["raw_derivative"] == 1.5
    assert param.state["output_targets"] == ["reactor.temp_rate"]
    assert param.state["updated_on_change"] is True
    assert param.state["mode"] == "continuous"
    assert param.state["last_error"] == ""


def test_derivative_plugin_holds_last_output_between_source_updates() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.temp", value=10.0))

    plugin = DerivativePlugin()
    param = plugin.create("d_temp", config={"source": "reactor.temp"}, value=0.0)

    param.scan(_ctx(store, dt=1.0))
    store.set_value("reactor.temp", 12.0)
    param.scan(_ctx(store, dt=2.0))
    assert float(param.get_value()) == 1.0

    # No new source change: keep last slope output instead of dropping to 0 immediately.
    param.scan(_ctx(store, dt=0.5))
    assert float(param.get_value()) == 1.0
    assert param.state["updated_on_change"] is False


def test_derivative_plugin_window_mode_uses_trailing_time_window() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.temp", value=10.0))

    plugin = DerivativePlugin()
    param = plugin.create(
        "d_temp",
        config={
            "source": "reactor.temp",
            "mode": "window",
            "window_s": 2.0,
        },
        value=0.0,
    )

    param.scan(_ctx(store, dt=1.0))
    assert float(param.get_value()) == 0.0

    store.set_value("reactor.temp", 12.0)
    param.scan(_ctx(store, dt=1.0))
    assert float(param.get_value()) == 2.0
    assert param.state["mode"] == "window"
    assert param.state["window_s"] == 2.0

    store.set_value("reactor.temp", 16.0)
    param.scan(_ctx(store, dt=1.0))
    assert float(param.get_value()) == 3.0
    assert param.state["history_sample_count"] >= 2
    assert param.state["history_span_s"] == 2.0


def test_derivative_plugin_dependencies_include_source_and_enable_param() -> None:
    plugin = DerivativePlugin()
    param = plugin.create(
        "d_temp",
        config={
            "source": "reactor.temp",
            "enable_param": "logic.enable",
        },
    )

    assert param.dependencies() == ["reactor.temp", "logic.enable"]


def test_derivative_plugin_non_numeric_source_sets_error_and_keeps_value() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.temp", value="bad"))

    plugin = DerivativePlugin()
    param = plugin.create("d_temp", config={"source": "reactor.temp"}, value=7.0)

    param.scan(_ctx(store, dt=1.0))

    assert float(param.get_value()) == 7.0
    assert "non-numeric source parameter" in param.state["last_error"]


def test_derivative_plugin_reenable_resets_baseline() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.temp", value=10.0))
    store.add(StaticParameter("logic.enable", value=True))

    plugin = DerivativePlugin()
    param = plugin.create(
        "d_temp",
        config={
            "source": "reactor.temp",
            "enable_param": "logic.enable",
        },
        value=0.0,
    )

    param.scan(_ctx(store, dt=1.0))
    store.set_value("reactor.temp", 20.0)
    param.scan(_ctx(store, dt=1.0))
    assert float(param.get_value()) == 10.0

    store.set_value("logic.enable", False)
    param.scan(_ctx(store, dt=1.0))
    assert param.state["enabled"] is False

    store.set_value("reactor.temp", 30.0)
    store.set_value("logic.enable", True)
    param.scan(_ctx(store, dt=1.0))

    assert param.state["enabled"] is True
    assert float(param.get_value()) == 0.0


def test_derivative_plugin_default_config_and_schema_contract() -> None:
    plugin = DerivativePlugin()

    defaults = plugin.default_config()
    schema = plugin.schema()

    assert defaults == {
        "source": "",
        "enable_param": "",
        "mode": "continuous",
        "window_s": 2.0,
        "scale": 1.0,
        "min_dt": 1e-6,
        "output_params": [],
    }
    assert schema["required"] == ["source"]
    assert schema["properties"]["mode"]["enum"] == ["continuous", "window"]
    assert schema["properties"]["output_params"]["type"] == ["array", "string"]
