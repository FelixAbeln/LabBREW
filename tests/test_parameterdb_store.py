from __future__ import annotations

from typing import Any

from Services.parameterDB.parameterdb_service.store import ParameterStore
from Services.parameterDB.parameterdb_service.plugin_api import ParameterBase


class FakeBroker:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def publish(self, event: dict[str, Any]) -> None:
        self.events.append(dict(event))


class FakeParameter(ParameterBase):
    parameter_type = "fake"

    def scan(self, ctx) -> None:
        return None


def test_store_add_set_update_and_remove_publish_events() -> None:
    broker = FakeBroker()
    store = ParameterStore(event_broker=broker)
    param = FakeParameter("reactor.temp", value=20.0, config={"units": "C"})

    store.add(param)
    store.set_value("reactor.temp", 25.0)
    store.update_config("reactor.temp", units="degC")
    store.update_metadata("reactor.temp", actor="pytest")
    removed = store.remove("reactor.temp")

    assert removed is True
    assert store.revision() == 5
    assert [event["event"] for event in broker.events] == [
        "parameter_added",
        "value_changed",
        "config_changed",
        "metadata_changed",
        "parameter_removed",
    ]
    assert broker.events[1]["source"] == "external"
    assert broker.events[2]["config"] == {"units": "degC"}
    assert broker.events[3]["metadata"] == {"actor": "pytest"}


def test_store_only_bumps_revision_when_value_changes() -> None:
    store = ParameterStore()
    store.add(FakeParameter("pump.speed", value=100.0))
    revision_after_add = store.revision()

    store.set_value("pump.speed", 100.0)

    assert store.revision() == revision_after_add
    assert store.snapshot() == {"pump.speed": 100.0}
    assert store.records()["pump.speed"]["value"] == 100.0


def test_store_get_record_returns_copy() -> None:
    store = ParameterStore()
    store.add(FakeParameter("ph.value", value=4.5, metadata={"source": "sensor"}))

    record = store.get_record("ph.value")
    record.metadata["source"] = "mutated"

    fresh_record = store.get_record("ph.value")
    assert fresh_record.metadata == {"source": "sensor"}


def test_store_remove_missing_parameter_returns_false() -> None:
    store = ParameterStore()

    assert store.remove("missing") is False
    assert store.revision() == 0