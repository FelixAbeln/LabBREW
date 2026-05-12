from __future__ import annotations

from types import SimpleNamespace

from Services.parameterDB.parameterdb_service.store import ParameterStore
from Services.parameterDB.plugins.follow.implementation import FollowPlugin
from Services.parameterDB.plugins.static.implementation import StaticParameter


def _ctx(store: ParameterStore):
    return SimpleNamespace(store=store, dt=0.1)


def test_follow_plugin_mirrors_valid_source_value() -> None:
    store = ParameterStore()
    store.add(StaticParameter("source", value=1.234))

    plugin = FollowPlugin()
    param = plugin.create("density.latched", config={"source": "source"}, value=0.0)

    param.scan(_ctx(store))

    assert float(param.get_signal_value()) == 1.234
    assert param.state["source_invalid"] is False
    assert param.state["latched"] is False


def test_follow_plugin_latches_last_good_value_when_source_is_invalid() -> None:
    store = ParameterStore()
    source = StaticParameter("source", value=1.111)
    store.add(source)

    plugin = FollowPlugin()
    param = plugin.create("density.latched", config={"source": "source", "latch_on_invalid": True}, value=0.0)

    param.scan(_ctx(store))
    assert float(param.get_signal_value()) == 1.111

    source.set_value(9.999)
    source.state["parameter_valid"] = False
    source.state["parameter_invalid_reasons"] = ["plausibility"]

    param.scan(_ctx(store))

    assert float(param.get_signal_value()) == 1.111
    assert param.state["source_invalid"] is True
    assert param.state["source_invalid_reasons"] == ["plausibility"]
    assert param.state["latched"] is True


def test_follow_plugin_can_pass_through_invalid_source_when_latch_disabled() -> None:
    store = ParameterStore()
    source = StaticParameter("source", value=1.111)
    store.add(source)

    plugin = FollowPlugin()
    param = plugin.create("density.latched", config={"source": "source", "latch_on_invalid": False}, value=0.0)

    param.scan(_ctx(store))
    source.set_value(0.0)
    source.state["parameter_valid"] = False
    source.state["parameter_invalid_reasons"] = ["plausibility"]

    param.scan(_ctx(store))

    assert float(param.get_signal_value()) == 0.0
    assert param.state["latched"] is False


def test_follow_plugin_dependencies_include_source() -> None:
    plugin = FollowPlugin()
    param = plugin.create("density.latched", config={"source": "brewcan.density.0"})

    assert param.dependencies() == ["brewcan.density.0"]


def test_follow_plugin_default_config_and_schema_contract() -> None:
    plugin = FollowPlugin()

    defaults = plugin.default_config()
    schema = plugin.schema()

    assert defaults == {
        "source": "",
        "latch_on_invalid": True,
        "output_params": [],
    }
    assert schema["required"] == ["source"]
    assert schema["properties"]["latch_on_invalid"]["type"] == "boolean"