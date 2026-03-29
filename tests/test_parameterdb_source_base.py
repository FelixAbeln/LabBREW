from __future__ import annotations

import pytest

from Services.parameterDB.parameterdb_sources.base import DataSourceBase, DataSourceSpec


class _FakeClient:
    def create_parameter(self, *args, **kwargs):
        return None


class _ConcreteSource(DataSourceBase):
    source_type = "concrete"

    def ensure_parameters(self) -> None:
        return None

    def run(self) -> None:
        return None


class _ViaSuperSpec(DataSourceSpec):
    source_type = "super"

    def create(self, name: str, client, *, config=None):
        return super().create(name, client, config=config)


def test_datasource_spec_default_config_and_super_create_not_implemented() -> None:
    assert _ViaSuperSpec().default_config() == {}

    with pytest.raises(NotImplementedError):
        _ViaSuperSpec().create("x", _FakeClient())