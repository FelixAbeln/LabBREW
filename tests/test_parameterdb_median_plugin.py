from __future__ import annotations

from types import SimpleNamespace

from Services.parameterDB.parameterdb_service.store import ParameterStore
from Services.parameterDB.plugins.median.implementation import MedianPlugin
from Services.parameterDB.plugins.static.implementation import StaticParameter


def _ctx(store: ParameterStore, *, dt: float = 0.1):
    return SimpleNamespace(store=store, dt=dt)


def test_median_plugin_filters_without_plugin_side_mirroring() -> None:
    store = ParameterStore()
    store.add(StaticParameter("signal", value=10.0))
    store.add(StaticParameter("signal.med", value=0.0))

    plugin = MedianPlugin()
    param = plugin.create(
        "signal_med",
        config={
            "source": "signal",
            "window": 3,
            "output_params": ["signal.med"],
        },
        value=0.0,
    )

    param.scan(_ctx(store))
    assert float(param.get_value()) == 10.0

    store.set_value("signal", 100.0)
    param.scan(_ctx(store))
    assert float(param.get_value()) == 55.0

    store.set_value("signal", 12.0)
    param.scan(_ctx(store))
    assert float(param.get_value()) == 12.0
    assert float(store.get_value("signal.med")) == 0.0
    assert param.state["samples"] == [10.0, 100.0, 12.0]
    assert param.state["last_error"] == ""


def test_median_plugin_dependencies_include_source_and_enable_param() -> None:
    plugin = MedianPlugin()
    param = plugin.create(
        "signal_med",
        config={
            "source": "signal",
            "enable_param": "filter.enable",
        },
    )

    assert param.dependencies() == ["signal", "filter.enable"]


def test_median_plugin_disable_reenable_resets_window() -> None:
    store = ParameterStore()
    store.add(StaticParameter("signal", value=10.0))
    store.add(StaticParameter("filter.enable", value=True))

    plugin = MedianPlugin()
    param = plugin.create(
        "signal_med",
        config={"source": "signal", "enable_param": "filter.enable", "window": 5},
        value=0.0,
    )

    param.scan(_ctx(store))
    store.set_value("signal", 100.0)
    param.scan(_ctx(store))
    assert float(param.get_value()) == 55.0

    store.set_value("filter.enable", False)
    param.scan(_ctx(store))
    assert param.state["enabled"] is False

    store.set_value("signal", 7.0)
    store.set_value("filter.enable", True)
    param.scan(_ctx(store))

    assert float(param.get_value()) == 7.0
    assert param.state["samples"] == [7.0]


def test_median_plugin_non_numeric_source_sets_error_and_keeps_value() -> None:
    store = ParameterStore()
    store.add(StaticParameter("signal", value="bad"))

    plugin = MedianPlugin()
    param = plugin.create("signal_med", config={"source": "signal"}, value=7.0)

    param.scan(_ctx(store))

    assert float(param.get_value()) == 7.0
    assert "non-numeric source parameter" in param.state["last_error"]


def test_median_plugin_default_config_and_schema_contract() -> None:
    plugin = MedianPlugin()

    defaults = plugin.default_config()
    schema = plugin.schema()

    assert defaults == {
        "source": "",
        "enable_param": "",
        "window": 5,
        "output_params": [],
    }
    assert schema["required"] == ["source"]
    assert schema["properties"]["output_params"]["type"] == ["array", "string"]
