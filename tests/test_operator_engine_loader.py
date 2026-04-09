from __future__ import annotations

from types import SimpleNamespace

import pytest

import Services._shared.operator_engine.loader as loader_module
from Services._shared.operator_engine.models import OperatorMetadata
from Services._shared.operator_engine.registry import OperatorRegistry


class _Plugin:
    metadata = OperatorMetadata(name="test", label="Test", description="desc")

    def evaluate(self, _value, _params):
        return True


def test_load_registry_requires_package_context(monkeypatch) -> None:
    monkeypatch.setattr(loader_module, "__package__", "")

    with pytest.raises(RuntimeError, match="Cannot resolve plugin package"):
        loader_module.load_registry()


def test_load_from_module_registers_discovered_operator_instance() -> None:
    registry = OperatorRegistry()
    module = SimpleNamespace(PLUGIN=_Plugin)

    loader_module._load_from_module(module, registry)

    assert registry.get("test").metadata.name == "test"
