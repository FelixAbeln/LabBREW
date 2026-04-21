from __future__ import annotations

from types import SimpleNamespace

from Services.parameterDB.parameterdb_service.store import ParameterStore
from Services.parameterDB.plugins.moving_average.implementation import (
    MovingAveragePlugin,
)
from Services.parameterDB.plugins.static.implementation import StaticParameter


def _ctx(store: ParameterStore, *, dt: float = 0.1):
    return SimpleNamespace(store=store, dt=dt)


def test_moving_average_plugin_filters_without_plugin_side_mirroring() -> None:
    store = ParameterStore()
    store.add(StaticParameter("signal", value=10.0))
    store.add(StaticParameter("signal.avg", value=0.0))

    plugin = MovingAveragePlugin()
    param = plugin.create(
        "signal_ma",
        config={
            "source": "signal",
            "window": 3,
            "output_params": ["signal.avg"],
        },
        value=0.0,
    )

    param.scan(_ctx(store))
    assert float(param.get_value()) == 10.0

    store.set_value("signal", 20.0)
    param.scan(_ctx(store))
    assert float(param.get_value()) == 15.0

    store.set_value("signal", 40.0)
    param.scan(_ctx(store))
    assert float(param.get_value()) == 70.0 / 3.0
    assert float(store.get_value("signal.avg")) == 0.0
    assert param.state["samples"] == [10.0, 20.0, 40.0]
    assert param.state["last_error"] == ""


def test_moving_average_plugin_dependencies_include_source_and_enable_param() -> None:
    plugin = MovingAveragePlugin()
    param = plugin.create(
        "signal_ma",
        config={
            "source": "signal",
            "enable_param": "filter.enable",
        },
    )

    assert param.dependencies() == ["signal", "filter.enable"]


def test_moving_average_plugin_disable_reenable_resets_window() -> None:
    store = ParameterStore()
    store.add(StaticParameter("signal", value=10.0))
    store.add(StaticParameter("filter.enable", value=True))

    plugin = MovingAveragePlugin()
    param = plugin.create(
        "signal_ma",
        config={"source": "signal", "enable_param": "filter.enable", "window": 3},
        value=0.0,
    )

    param.scan(_ctx(store))
    store.set_value("signal", 20.0)
    param.scan(_ctx(store))
    assert float(param.get_value()) == 15.0

    store.set_value("filter.enable", False)
    param.scan(_ctx(store))
    assert param.state["enabled"] is False

    store.set_value("signal", 100.0)
    store.set_value("filter.enable", True)
    param.scan(_ctx(store))

    assert float(param.get_value()) == 100.0
    assert param.state["samples"] == [100.0]


def test_moving_average_plugin_non_numeric_source_sets_error_and_keeps_value() -> None:
    store = ParameterStore()
    store.add(StaticParameter("signal", value="bad"))

    plugin = MovingAveragePlugin()
    param = plugin.create("signal_ma", config={"source": "signal"}, value=7.0)

    param.scan(_ctx(store))

    assert float(param.get_value()) == 7.0
    assert "non-numeric source parameter" in param.state["last_error"]


def test_moving_average_plugin_default_config_and_schema_contract() -> None:
    plugin = MovingAveragePlugin()

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
