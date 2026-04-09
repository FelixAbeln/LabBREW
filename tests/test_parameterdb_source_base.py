from __future__ import annotations

import pytest

from Services.parameterDB.parameterdb_sources.base import DataSourceBase, DataSourceSpec


class _FakeClient:
    def __init__(self, *, create_error: Exception | None = None) -> None:
        self.create_error = create_error
        self.create_calls = []
        self.config_updates = []
        self.metadata_updates = []

    def create_parameter(self, *args, **kwargs):
        self.create_calls.append((args, kwargs))
        if self.create_error is not None:
            raise self.create_error
        return

    def update_config(self, name: str, **changes):
        self.config_updates.append((name, changes))
        return True

    def update_metadata(self, name: str, **changes):
        self.metadata_updates.append((name, changes))
        return True


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


def test_ensure_parameter_repairs_existing_parameter_metadata_and_config() -> None:
    client = _FakeClient(create_error=RuntimeError("already exists"))
    source = _ConcreteSource("brewtools", client, config={})

    source.ensure_parameter(
        "brewcan.pressure.1.calibrate",
        "static",
        value=False,
        config={"ui_group": "brewtools"},
        metadata={
            "owner": "brewtools",
            "created_by": "data_source",
            "source_type": "brewtools_kvaser",
            "role": "command",
            "widget_hint": "button",
        },
    )

    assert len(client.create_calls) == 1
    assert client.config_updates == [
        ("brewcan.pressure.1.calibrate", {"ui_group": "brewtools"}),
    ]
    assert client.metadata_updates == [
        (
            "brewcan.pressure.1.calibrate",
            {
                "owner": "brewtools",
                "created_by": "data_source",
                "source_type": "brewtools_kvaser",
                "role": "command",
                "widget_hint": "button",
            },
        ),
    ]
