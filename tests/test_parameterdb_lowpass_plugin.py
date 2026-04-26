from __future__ import annotations

from types import SimpleNamespace

from Services.parameterDB.parameterdb_service.store import ParameterStore
from Services.parameterDB.plugins.lowpass.implementation import LowpassPlugin
from Services.parameterDB.plugins.static.implementation import StaticParameter


def _ctx(store: ParameterStore, *, dt: float):
    return SimpleNamespace(store=store, dt=dt)


def test_lowpass_plugin_filters_source_without_plugin_side_mirroring() -> None:
    store = ParameterStore()
    store.add(StaticParameter("signal", value=10.0))
    store.add(StaticParameter("signal.filtered", value=0.0))

    plugin = LowpassPlugin()
    param = plugin.create(
        "signal_lp",
        config={
            "source": "signal",
            "tau_s": 1.0,
            "output_params": ["signal.filtered"],
        },
        value=0.0,
    )

    param.scan(_ctx(store, dt=0.1))
    assert float(param.get_signal_value()) == 10.0

    store.set_value("signal", 20.0)
    param.scan(_ctx(store, dt=1.0))

    assert float(param.get_signal_value()) == 15.0
    assert float(store.get_value("signal.filtered")) == 0.0
    assert param.state["alpha"] == 0.5
    assert param.state["last_error"] == ""


def test_lowpass_plugin_dependencies_include_source_and_enable_param() -> None:
    plugin = LowpassPlugin()
    param = plugin.create(
        "signal_lp",
        config={
            "source": "signal",
            "enable_param": "filter.enable",
        },
    )

    assert param.dependencies() == ["signal", "filter.enable"]


def test_lowpass_plugin_disable_reenable_resets_to_current_input() -> None:
    store = ParameterStore()
    store.add(StaticParameter("signal", value=10.0))
    store.add(StaticParameter("filter.enable", value=True))

    plugin = LowpassPlugin()
    param = plugin.create(
        "signal_lp",
        config={"source": "signal", "enable_param": "filter.enable", "tau_s": 2.0},
        value=0.0,
    )

    param.scan(_ctx(store, dt=0.1))
    store.set_value("signal", 20.0)
    param.scan(_ctx(store, dt=1.0))
    assert float(param.get_signal_value()) > 10.0

    store.set_value("filter.enable", False)
    param.scan(_ctx(store, dt=1.0))
    assert param.state["enabled"] is False

    store.set_value("signal", 50.0)
    store.set_value("filter.enable", True)
    param.scan(_ctx(store, dt=0.1))

    assert float(param.get_signal_value()) == 50.0


def test_lowpass_plugin_non_numeric_source_sets_error_and_keeps_value() -> None:
    store = ParameterStore()
    store.add(StaticParameter("signal", value="bad"))

    plugin = LowpassPlugin()
    param = plugin.create("signal_lp", config={"source": "signal"}, value=7.0)

    param.scan(_ctx(store, dt=0.1))

    assert float(param.get_signal_value()) == 7.0
    assert "non-numeric source parameter" in param.state["last_error"]


def test_lowpass_plugin_default_config_and_schema_contract() -> None:
    plugin = LowpassPlugin()

    defaults = plugin.default_config()
    schema = plugin.schema()

    assert defaults == {
        "source": "",
        "enable_param": "",
        "tau_s": 1.0,
        "output_params": [],
    }
    assert schema["required"] == ["source"]
    assert schema["properties"]["output_params"]["type"] == ["array", "string"]
