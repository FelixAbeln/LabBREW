from __future__ import annotations

from types import SimpleNamespace

import Services.parameterDB.plugins.condition.implementation as condition_module
from Services.parameterDB.plugins.condition.implementation import ConditionPlugin
from Services.parameterDB.plugins.static.implementation import StaticParameter
from Services.parameterDB.parameterdb_service.store import ParameterStore


def _ctx(store: ParameterStore):
    return SimpleNamespace(store=store, dt=0.1)


def test_condition_plugin_evaluates_rule_style_condition_to_boolean() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.temp", value=72.0))

    plugin = ConditionPlugin()
    param = plugin.create(
        "reactor.hot",
        config={
            "condition": "cond:reactor.temp:>=:70",
        },
        value=False,
    )

    param.scan(_ctx(store))

    assert param.get_value() is True
    assert param.state["logic_kind"] == "condition"
    assert param.state["condition_kind"] == "atomic"
    assert param.state["source"] == "reactor.temp"
    assert param.state["operator"] == ">="
    assert param.state["params"] == {"threshold": 70.0}
    assert param.state["sources"] == ["reactor.temp"]
    assert param.state["matched"] is True
    assert param.state["last_error"] == ""


def test_condition_plugin_dependencies_include_enable_param_and_nested_sources() -> None:
    plugin = ConditionPlugin()
    param = plugin.create(
        "ready",
        config={
            "enable_param": "conditions_enabled",
            "condition": "all(cond:temp:>=:20;any(cond:pressure:>:1.5;cond:flow:==:1))",
        },
    )

    assert param.dependencies() == ["conditions_enabled", "temp", "pressure", "flow"]


def test_condition_plugin_sets_missing_value_error_and_keeps_existing_value() -> None:
    plugin = ConditionPlugin()
    param = plugin.create(
        "ready",
        config={"condition": "cond:missing.input:==:1"},
        value=True,
    )

    param.scan(_ctx(ParameterStore()))

    assert param.get_value() is True
    assert param.state["matched"] is False
    assert param.state["last_error"] == "Missing value for missing.input"


def test_condition_plugin_composite_missing_value_keeps_previous_output() -> None:
    store = ParameterStore()
    store.add(StaticParameter("temp", value=20.0))

    plugin = ConditionPlugin()
    param = plugin.create(
        "ready",
        config={
            "condition": "all(cond:temp:>=:10;cond:missing.signal:==:1)",
        },
        value=True,
    )

    param.scan(_ctx(store))

    assert param.get_value() is True
    assert param.state["matched"] is False
    assert "Missing value for" in param.state["last_error"]


def test_condition_plugin_honors_for_s_hold_time(monkeypatch) -> None:
    now = {"t": 100.0}
    monkeypatch.setattr(condition_module.time, "monotonic", lambda: now["t"])

    store = ParameterStore()
    store.add(StaticParameter("reactor.temp", value=12.0))

    plugin = ConditionPlugin()
    param = plugin.create(
        "reactor.hot",
        config={"condition": "cond:reactor.temp:>=:10:2"},
        value=False,
    )

    param.scan(_ctx(store))
    assert param.get_value() is False
    assert param.state["matched"] is False

    now["t"] = 102.2
    param.scan(_ctx(store))

    assert param.get_value() is True
    assert param.state["matched"] is True
    assert param.state["required_for_s"] == 2.0


def test_condition_plugin_elapsed_and_condition_dsl_honors_both_parts(monkeypatch) -> None:
    now = {"t": 10.0}
    monkeypatch.setattr(condition_module.time, "monotonic", lambda: now["t"])

    store = ParameterStore()
    store.add(StaticParameter("brewcan.density.0", value=1.011))

    plugin = ConditionPlugin()
    param = plugin.create(
        "ready",
        config={
            "condition": "all(elapsed:900;cond:brewcan.density.0:<=:1.012:120)",
        },
        value=False,
    )

    param.scan(_ctx(store))
    assert param.get_value() is False
    assert param.state["logic_kind"] == "all_of"
    assert param.state["sources"] == ["brewcan.density.0"]
    assert param.state["matched"] is False

    now["t"] = 909.0
    param.scan(_ctx(store))

    assert param.get_value() is False
    assert param.state["matched"] is False

    now["t"] = 1030.0
    param.scan(_ctx(store))

    assert param.get_value() is True
    assert param.state["matched"] is True
    assert param.state["elapsed_s"] >= 1020.0


def test_condition_plugin_default_config_and_schema_contract() -> None:
    plugin = ConditionPlugin()

    defaults = plugin.default_config()
    schema = plugin.schema()

    assert defaults == {"condition": "", "enable_param": ""}
    assert schema["required"] == ["condition"]
    assert schema["properties"]["condition"]["type"] == ["object", "string"]


def test_condition_plugin_reports_invalid_condition_config() -> None:
    plugin = ConditionPlugin()
    param = plugin.create("bad", config={"condition": "temp >= 10"}, value=False)

    param.scan(_ctx(ParameterStore()))

    assert param.get_value() is False
    assert "Invalid wait syntax" in param.state["last_error"]


def test_condition_plugin_legacy_dict_condition_still_works() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.temp", value=72.0))

    plugin = ConditionPlugin()
    param = plugin.create(
        "reactor.hot",
        config={
            "condition": {
                "source": "reactor.temp",
                "operator": ">=",
                "params": {"threshold": 70.0},
            },
        },
        value=False,
    )

    param.scan(_ctx(store))

    assert param.get_value() is True
    assert param.state["logic_kind"] == "condition"
    assert param.state["condition_kind"] == "atomic"