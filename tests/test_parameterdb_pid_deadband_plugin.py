from __future__ import annotations

from types import SimpleNamespace

from Services.parameterDB.parameterdb_service.store import ParameterStore
from Services.parameterDB.plugins.deadband.implementation import DeadbandPlugin
from Services.parameterDB.plugins.pid.implementation import PIDPlugin
from Services.parameterDB.plugins.static.implementation import StaticParameter


def _ctx(store: ParameterStore, *, dt: float = 0.1):
    return SimpleNamespace(store=store, dt=dt)


def _make_pid(_store, extra_config=None):
    plugin = PIDPlugin()
    cfg = {
        "pv": "reactor.pv",
        "sp": "reactor.sp",
        "enable_param": "reactor.enable",
        "kp": 2.0,
    }
    if extra_config:
        cfg.update(extra_config)
    return plugin.create("reactor.pid", config=cfg, value=0.0)


def _make_dbc(store, extra_config=None):
    plugin = DeadbandPlugin()
    cfg = {
        "pv": "reactor.pv",
        "sp": "reactor.sp",
        "enable_param": "reactor.enable",
        "on_offset": 1.0,
        "off_offset": 0.5,
        "direction": "below",
    }
    if extra_config:
        cfg.update(extra_config)
    return plugin.create("reactor.dbc", config=cfg, value=False)


def test_pid_plugin_config_contract_exposes_disabled_value() -> None:
    plugin = PIDPlugin()

    cfg = plugin.default_config()
    assert "disabled_value" in cfg
    assert cfg["disabled_value"] is None

    schema = plugin.schema()
    disabled_value = schema["properties"]["disabled_value"]
    assert "anyOf" in disabled_value
    options = disabled_value["anyOf"]
    assert {"type": "number"} in options
    assert {"type": "null"} in options
    assert any(
        isinstance(option, dict)
        and option.get("type") == "string"
        and "anyOf" in option
        for option in options
    )


def test_deadband_plugin_config_contract_exposes_disabled_value() -> None:
    plugin = DeadbandPlugin()

    cfg = plugin.default_config()
    assert "disabled_value" in cfg
    assert cfg["disabled_value"] is None

    schema = plugin.schema()
    disabled_value = schema["properties"]["disabled_value"]
    assert "anyOf" in disabled_value
    options = disabled_value["anyOf"]
    assert {"type": ["boolean", "null"]} in options
    token_option = next(
        option
        for option in options
        if isinstance(option, dict) and option.get("type") == "string"
    )
    assert token_option.get("enum") == [
        "",
        "true",
        "false",
        "hold",
        "force_off",
        "force_on",
    ]


def test_pid_disable_no_disabled_value_latches_output() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.pv", value=10.0))
    store.add(StaticParameter("reactor.sp", value=20.0))
    store.add(StaticParameter("reactor.enable", value=True))

    param = _make_pid(store)
    param.scan(_ctx(store, dt=1.0))
    last_output = float(param.get_signal_value())
    assert last_output == 20.0

    store.set_value("reactor.enable", False)
    param.scan(_ctx(store, dt=1.0))

    assert param.state["enabled"] is False
    assert float(param.get_signal_value()) == last_output  # latched


def test_pid_disable_with_disabled_value_drives_that_value() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.pv", value=10.0))
    store.add(StaticParameter("reactor.sp", value=20.0))
    store.add(StaticParameter("reactor.enable", value=True))

    param = _make_pid(store, {"disabled_value": 0.0})
    param.scan(_ctx(store, dt=1.0))
    assert float(param.get_signal_value()) == 20.0

    store.set_value("reactor.enable", False)
    param.scan(_ctx(store, dt=1.0))

    assert param.state["enabled"] is False
    assert float(param.get_signal_value()) == 0.0


def test_pid_disable_with_invalid_disabled_value_keeps_latched() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.pv", value=10.0))
    store.add(StaticParameter("reactor.sp", value=20.0))
    store.add(StaticParameter("reactor.enable", value=True))

    param = _make_pid(store, {"disabled_value": "banana"})
    param.scan(_ctx(store, dt=1.0))
    assert float(param.get_signal_value()) == 20.0

    store.set_value("reactor.enable", False)
    param.scan(_ctx(store, dt=1.0))

    assert param.state["enabled"] is False
    assert float(param.get_signal_value()) == 20.0
    assert "disabled_value" in str(param.state.get("last_error", ""))


def test_deadband_disable_no_disabled_value_latches_output() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.pv", value=8.0))
    store.add(StaticParameter("reactor.sp", value=10.0))
    store.add(StaticParameter("reactor.enable", value=True))

    param = _make_dbc(store)
    param.scan(_ctx(store))
    assert param.get_signal_value() is True  # pv below sp-on_offset → on

    store.set_value("reactor.enable", False)
    param.scan(_ctx(store))

    assert param.state["enabled"] is False
    assert param.get_signal_value() is True  # latched at True


def test_deadband_disable_with_disabled_value_drives_that_value() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.pv", value=8.0))
    store.add(StaticParameter("reactor.sp", value=10.0))
    store.add(StaticParameter("reactor.enable", value=True))

    param = _make_dbc(store, {"disabled_value": False})
    param.scan(_ctx(store))
    assert param.get_signal_value() is True

    store.set_value("reactor.enable", False)
    param.scan(_ctx(store))

    assert param.state["enabled"] is False
    assert param.get_signal_value() is False


def test_pid_disable_with_string_disabled_value_hold_latches_output() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.pv", value=10.0))
    store.add(StaticParameter("reactor.sp", value=20.0))
    store.add(StaticParameter("reactor.enable", value=True))

    param = _make_pid(store, {"disabled_value": ""})
    param.scan(_ctx(store, dt=1.0))
    last_output = float(param.get_signal_value())
    assert last_output == 20.0

    store.set_value("reactor.enable", False)
    param.scan(_ctx(store, dt=1.0))

    assert param.state["enabled"] is False
    assert float(param.get_signal_value()) == last_output


def test_pid_disable_with_string_disabled_value_false_drives_zero() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.pv", value=10.0))
    store.add(StaticParameter("reactor.sp", value=20.0))
    store.add(StaticParameter("reactor.enable", value=True))

    param = _make_pid(store, {"disabled_value": "false"})
    param.scan(_ctx(store, dt=1.0))
    assert float(param.get_signal_value()) == 20.0

    store.set_value("reactor.enable", False)
    param.scan(_ctx(store, dt=1.0))

    assert param.state["enabled"] is False
    assert float(param.get_signal_value()) == 0.0


def test_pid_disable_with_string_disabled_value_true_drives_one() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.pv", value=10.0))
    store.add(StaticParameter("reactor.sp", value=20.0))
    store.add(StaticParameter("reactor.enable", value=True))

    param = _make_pid(store, {"disabled_value": "true"})
    param.scan(_ctx(store, dt=1.0))
    assert float(param.get_signal_value()) == 20.0

    store.set_value("reactor.enable", False)
    param.scan(_ctx(store, dt=1.0))

    assert param.state["enabled"] is False
    assert float(param.get_signal_value()) == 1.0


def test_deadband_disable_with_string_disabled_value_hold_latches_output() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.pv", value=8.0))
    store.add(StaticParameter("reactor.sp", value=10.0))
    store.add(StaticParameter("reactor.enable", value=True))

    param = _make_dbc(store, {"disabled_value": ""})
    param.scan(_ctx(store))
    assert param.get_signal_value() is True

    store.set_value("reactor.enable", False)
    param.scan(_ctx(store))

    assert param.state["enabled"] is False
    assert param.get_signal_value() is True


def test_deadband_disable_with_string_disabled_value_false_drives_false() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.pv", value=8.0))
    store.add(StaticParameter("reactor.sp", value=10.0))
    store.add(StaticParameter("reactor.enable", value=True))

    param = _make_dbc(store, {"disabled_value": "false"})
    param.scan(_ctx(store))
    assert param.get_signal_value() is True

    store.set_value("reactor.enable", False)
    param.scan(_ctx(store))

    assert param.state["enabled"] is False
    assert param.get_signal_value() is False


def test_deadband_disable_with_string_disabled_value_true_drives_true() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.pv", value=12.0))
    store.add(StaticParameter("reactor.sp", value=10.0))
    store.add(StaticParameter("reactor.enable", value=True))

    param = _make_dbc(store, {"disabled_value": "true"})
    param.scan(_ctx(store))
    assert param.get_signal_value() is False

    store.set_value("reactor.enable", False)
    param.scan(_ctx(store))

    assert param.state["enabled"] is False
    assert param.get_signal_value() is True


def test_deadband_disable_with_invalid_string_disabled_value_latches() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.pv", value=8.0))
    store.add(StaticParameter("reactor.sp", value=10.0))
    store.add(StaticParameter("reactor.enable", value=True))

    param = _make_dbc(store, {"disabled_value": "banana"})
    param.scan(_ctx(store))
    assert param.get_signal_value() is True

    store.set_value("reactor.enable", False)
    param.scan(_ctx(store))

    assert param.state["enabled"] is False
    assert param.get_signal_value() is True
    assert "disabled_value" in str(param.state.get("last_error", ""))


def test_deadband_disable_with_hold_token_latches_output() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.pv", value=8.0))
    store.add(StaticParameter("reactor.sp", value=10.0))
    store.add(StaticParameter("reactor.enable", value=True))

    param = _make_dbc(store, {"disabled_value": "hold"})
    param.scan(_ctx(store))
    assert param.get_signal_value() is True

    store.set_value("reactor.enable", False)
    param.scan(_ctx(store))

    assert param.state["enabled"] is False
    assert param.get_signal_value() is True


def test_deadband_disable_with_force_on_token_drives_true() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.pv", value=12.0))
    store.add(StaticParameter("reactor.sp", value=10.0))
    store.add(StaticParameter("reactor.enable", value=True))

    param = _make_dbc(store, {"disabled_value": "force_on"})
    param.scan(_ctx(store))
    assert param.get_signal_value() is False

    store.set_value("reactor.enable", False)
    param.scan(_ctx(store))

    assert param.state["enabled"] is False
    assert param.get_signal_value() is True


def test_deadband_disable_with_force_off_token_drives_false() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.pv", value=8.0))
    store.add(StaticParameter("reactor.sp", value=10.0))
    store.add(StaticParameter("reactor.enable", value=True))

    # Mixed case and padding verify token normalization path.
    param = _make_dbc(store, {"disabled_value": "  FoRcE_OfF  "})
    param.scan(_ctx(store))
    assert param.get_signal_value() is True

    store.set_value("reactor.enable", False)
    param.scan(_ctx(store))

    assert param.state["enabled"] is False
    assert param.get_signal_value() is False
