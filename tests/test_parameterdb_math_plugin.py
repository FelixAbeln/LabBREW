from __future__ import annotations

from types import SimpleNamespace

from Services.parameterDB.plugins.math.implementation import MathPlugin
from Services.parameterDB.plugins.static.implementation import StaticParameter
from Services.parameterDB.parameterdb_service.store import ParameterStore


def _ctx(store: ParameterStore):
    return SimpleNamespace(store=store, dt=0.1)


def test_math_plugin_evaluates_equation_and_mirrors_output() -> None:
    store = ParameterStore()
    store.add(StaticParameter("density", value=1.234))
    store.add(StaticParameter("linked_density", value=0.0))

    plugin = MathPlugin()
    param = plugin.create(
        "density_math",
        config={
            "equation": "density * 2 / 2",
            "output_params": ["linked_density"],
        },
        value=0.0,
    )

    param.scan(_ctx(store))

    assert float(param.get_value()) == 1.234
    assert float(store.get_value("linked_density")) == 1.234
    assert param.state["symbols"] == ["density"]
    assert param.state["output_targets"] == ["linked_density"]
    assert "last_error" not in param.state


def test_math_plugin_dependencies_include_equation_symbols_and_enable_param() -> None:
    plugin = MathPlugin()
    param = plugin.create(
        "calc",
        config={
            "equation": "max(density, temp) + calc",
            "enable_param": "math_enabled",
        },
    )

    deps = param.dependencies()

    assert deps == ["math_enabled", "density", "temp"]


def test_math_plugin_sets_error_when_symbol_missing_and_keeps_existing_outputs() -> None:
    store = ParameterStore()
    store.add(StaticParameter("mirror", value=7.0))

    plugin = MathPlugin()
    param = plugin.create(
        "calc",
        config={
            "equation": "missing_density * 2",
            "output_params": ["mirror"],
        },
        value=5.0,
    )

    param.scan(_ctx(store))

    assert float(param.get_value()) == 5.0
    assert float(store.get_value("mirror")) == 7.0
    assert "missing parameters in equation" in str(param.state.get("last_error", ""))


def test_math_plugin_sets_error_for_invalid_equation_syntax() -> None:
    plugin = MathPlugin()
    param = plugin.create("calc", config={"equation": "density * (2 +"}, value=1.0)

    param.scan(_ctx(ParameterStore()))

    assert float(param.get_value()) == 1.0
    assert "invalid equation syntax" in str(param.state.get("last_error", ""))


def test_math_plugin_default_config_and_schema_contract() -> None:
    plugin = MathPlugin()

    defaults = plugin.default_config()
    schema = plugin.schema()

    assert defaults["equation"] == ""
    assert defaults["output_params"] == []
    assert "equation" in schema["required"]
    assert schema["properties"]["output_params"]["type"] == ["array", "string"]


def test_math_plugin_supports_dotted_parameter_names() -> None:
    store = ParameterStore()
    store.add(StaticParameter("brewcan.density.0", value=1.056))

    plugin = MathPlugin()
    param = plugin.create(
        "calc",
        config={
            "equation": "brewcan.density.0 * 2 / 2",
        },
        value=0.0,
    )

    param.scan(_ctx(store))

    assert float(param.get_value()) == 1.056
    assert param.state["symbols"] == ["brewcan.density.0"]
    assert "last_error" not in param.state


def test_math_plugin_dotted_alias_does_not_collide_with_user_identifier() -> None:
    store = ParameterStore()
    store.add(StaticParameter("__p0", value=100.0))
    store.add(StaticParameter("brewcan.density.0", value=1.05))

    plugin = MathPlugin()
    param = plugin.create(
        "calc",
        config={
            "equation": "__p0 + brewcan.density.0",
        },
        value=0.0,
    )

    param.scan(_ctx(store))

    assert float(param.get_value()) == 101.05
    assert param.dependencies() == ["__p0", "brewcan.density.0"]
    assert "last_error" not in param.state