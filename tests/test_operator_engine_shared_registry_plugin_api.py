from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from Services._shared.operator_engine.models import OperatorMetadata
from Services._shared.operator_engine.plugins.shared import as_float, loosely_equal
from Services._shared.operator_engine.registry import OperatorRegistry
from Services.parameterDB.parameterdb_service.plugin_api import ParameterBase, PluginSpec


@dataclass
class _Op:
    metadata: OperatorMetadata

    def evaluate(self, value: Any, params: dict[str, Any]) -> bool:
        threshold = params.get("threshold", 0)
        return float(value) >= float(threshold)


class _ConcreteParameter(ParameterBase):
    parameter_type = "concrete"

    def scan(self, _ctx) -> None:
        return None


class _ScanViaSuperParameter(ParameterBase):
    parameter_type = "super"

    def scan(self, ctx) -> None:
        super().scan(ctx)


class _ViaSuperPluginSpec(PluginSpec):
    parameter_type = "super"

    def create(self, name: str, *, config=None, value=None, metadata=None):
        return super().create(name, config=config, value=value, metadata=metadata)


def test_shared_helpers_cover_bool_numeric_and_fallback_paths() -> None:
    assert as_float(True) == 1.0
    assert as_float(False) == 0.0
    assert as_float("2.5") == 2.5

    assert loosely_equal(True, 1) is True
    assert loosely_equal(False, 1) is False
    assert loosely_equal("3", 3.0) is True

    class _NeverFloat:
        def __float__(self):
            raise TypeError("no float")

        def __eq__(self, other):
            return isinstance(other, _NeverFloat)

    assert loosely_equal(_NeverFloat(), _NeverFloat()) is True


def test_operator_registry_rejects_empty_duplicate_and_unknown() -> None:
    registry = OperatorRegistry()
    empty_name = _Op(OperatorMetadata(name="", label="", description=""))
    with pytest.raises(ValueError, match="cannot be empty"):
        registry.register(empty_name)

    gt = _Op(OperatorMetadata(name=">=", label=">=", description="gte"))
    registry.register(gt)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(gt)
    with pytest.raises(KeyError, match="Unknown operator"):
        registry.get("missing")


def test_plugin_api_default_hooks_and_abstract_super_paths() -> None:
    param = _ConcreteParameter("alpha", value=1)
    param.on_added(None)  # type: ignore[arg-type]
    param.on_removed(None)  # type: ignore[arg-type]
    assert param.dependencies() == []
    assert param.write_targets() == []

    with pytest.raises(NotImplementedError):
        _ScanViaSuperParameter("beta").scan(None)

    with pytest.raises(NotImplementedError):
        _ViaSuperPluginSpec().create("x")