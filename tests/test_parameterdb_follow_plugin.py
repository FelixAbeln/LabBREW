from __future__ import annotations

from types import SimpleNamespace

from Services.parameterDB.parameterdb_service.engine import ScanEngine
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


def test_follow_plugin_still_runs_when_source_is_invalid_in_engine() -> None:
    store = ParameterStore()
    source = StaticParameter("source", value=1.111)
    store.add(source)

    plugin = FollowPlugin()
    param = plugin.create(
        "density.latched",
        config={"source": "source", "latch_on_invalid": True},
        value=0.0,
    )
    store.add(param)

    engine = ScanEngine(period_s=0.01, store=store)
    engine.scan_once(dt=0.1)

    source.set_value(0.0)
    source.state["parameter_valid"] = False
    source.state["parameter_invalid_reasons"] = ["plausibility"]

    engine.scan_once(dt=0.1)

    record = store.get_record("density.latched")
    assert float(record.signal_value) == 1.111
    assert record.state["source_invalid"] is True
    assert record.state["source_invalid_reasons"] == ["plausibility"]
    assert record.state["latched"] is True
    assert record.state["connected"] is True


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


def test_follow_plugin_dependencies_strip_source_name() -> None:
    plugin = FollowPlugin()
    param = plugin.create("density.latched", config={"source": "  brewcan.density.0  "})

    assert param.dependencies() == ["brewcan.density.0"]


def test_follow_plugin_updates_scan_graph_dependency_order() -> None:
    store = ParameterStore()
    store.add(StaticParameter("brewcan.density.0", value=1.05))

    plugin = FollowPlugin()
    follower = plugin.create(
        "brewcan.density.0.latched",
        config={"source": "brewcan.density.0"},
        value=0.0,
    )
    store.add(follower)

    engine = ScanEngine(period_s=0.01, store=store)
    graph = engine.graph_info()

    assert graph["dependencies"]["brewcan.density.0.latched"] == ["brewcan.density.0"]
    assert graph["scan_order"].index("brewcan.density.0") < graph["scan_order"].index(
        "brewcan.density.0.latched"
    )


def test_follow_plugin_graph_uses_stripped_source_name() -> None:
    store = ParameterStore()
    store.add(StaticParameter("brewcan.density.0", value=1.05))

    plugin = FollowPlugin()
    follower = plugin.create(
        "brewcan.density.0.latched",
        config={"source": "  brewcan.density.0  "},
        value=0.0,
    )
    store.add(follower)

    engine = ScanEngine(period_s=0.01, store=store)
    graph = engine.graph_info()

    assert graph["dependencies"]["brewcan.density.0.latched"] == ["brewcan.density.0"]


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