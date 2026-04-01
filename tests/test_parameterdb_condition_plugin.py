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


def test_condition_plugin_dependencies_include_sources_under_event_wrappers() -> None:
    plugin = ConditionPlugin()
    param = plugin.create(
        "edge_ready",
        config={
            "condition": "rising(any(cond:temp:>=:20;cond:pressure:>:1.5))",
        },
    )

    assert param.dependencies() == ["temp", "pressure"]


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


def test_condition_plugin_rising_and_falling_event_dsl(monkeypatch) -> None:
    now = {"t": 10.0}
    monkeypatch.setattr(condition_module.time, "monotonic", lambda: now["t"])

    store = ParameterStore()
    store.add(StaticParameter("signal", value=0))

    plugin = ConditionPlugin()

    rising_param = plugin.create(
        "sig_rise",
        config={"condition": "rising(cond:signal:==:1)"},
        value=False,
    )
    falling_param = plugin.create(
        "sig_fall",
        config={"condition": "falling(cond:signal:==:1)"},
        value=False,
    )

    rising_param.scan(_ctx(store))
    falling_param.scan(_ctx(store))
    assert rising_param.get_value() is False
    assert falling_param.get_value() is False

    store.set_value("signal", 1)
    now["t"] = 11.0
    rising_param.scan(_ctx(store))
    falling_param.scan(_ctx(store))
    assert rising_param.get_value() is True
    assert falling_param.get_value() is False

    now["t"] = 12.0
    rising_param.scan(_ctx(store))
    falling_param.scan(_ctx(store))
    assert rising_param.get_value() is False
    assert falling_param.get_value() is False

    store.set_value("signal", 0)
    now["t"] = 13.0
    rising_param.scan(_ctx(store))
    falling_param.scan(_ctx(store))
    assert rising_param.get_value() is False
    assert falling_param.get_value() is True


def test_condition_plugin_pulse_event_dsl_holds_for_window(monkeypatch) -> None:
    now = {"t": 100.0}
    monkeypatch.setattr(condition_module.time, "monotonic", lambda: now["t"])

    store = ParameterStore()
    store.add(StaticParameter("signal", value=0))

    plugin = ConditionPlugin()
    param = plugin.create(
        "sig_pulse",
        config={"condition": "pulse(cond:signal:==:1;2)"},
        value=False,
    )

    param.scan(_ctx(store))
    assert param.get_value() is False

    store.set_value("signal", 1)
    now["t"] = 101.0
    param.scan(_ctx(store))
    assert param.get_value() is True

    now["t"] = 102.5
    param.scan(_ctx(store))
    assert param.get_value() is True

    now["t"] = 103.2
    param.scan(_ctx(store))
    assert param.get_value() is False


def test_condition_plugin_elapsed_timer_resets_after_re_enable(monkeypatch) -> None:
    now = {"t": 100.0}
    monkeypatch.setattr(condition_module.time, "monotonic", lambda: now["t"])

    store = ParameterStore()
    store.add(StaticParameter("logic.enable", value=True))

    plugin = ConditionPlugin()
    param = plugin.create(
        "ready",
        config={
            "condition": "elapsed:10",
            "enable_param": "logic.enable",
        },
        value=False,
    )

    param.scan(_ctx(store))
    assert param.get_value() is False

    now["t"] = 109.0
    param.scan(_ctx(store))
    assert param.get_value() is False

    store.set_value("logic.enable", False)
    now["t"] = 109.1
    param.scan(_ctx(store))
    assert param.state["enabled"] is False

    store.set_value("logic.enable", True)
    now["t"] = 115.0
    param.scan(_ctx(store))
    assert param.state["enabled"] is True
    assert param.get_value() is False

    now["t"] = 125.2
    param.scan(_ctx(store))
    assert param.get_value() is True
    assert param.state["matched"] is True


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