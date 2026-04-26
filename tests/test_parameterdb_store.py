from __future__ import annotations

from typing import Any

import pytest

from Services.parameterDB.parameterdb_service.plugin_api import ParameterBase
from Services.parameterDB.parameterdb_service.store import ParameterStore


class FakeBroker:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def publish(self, event: dict[str, Any]) -> None:
        self.events.append(dict(event))


class FakeParameter(ParameterBase):
    parameter_type = "fake"

    def scan(self, _ctx) -> None:
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


def test_store_external_set_value_bumps_revision_even_if_value_is_unchanged() -> None:
    """The default external set_value path bumps the revision even when the
    assigned value is unchanged; scan-originated updates are handled separately."""
    store = ParameterStore()
    store.add(FakeParameter("pump.speed", value=100.0))
    revision_after_add = store.revision()

    store.set_value("pump.speed", 100.0)

    assert store.revision() > revision_after_add
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


def test_store_helpers_and_runtime_paths() -> None:
    store = ParameterStore()
    broker = FakeBroker()
    store.attach_event_broker(broker)

    alpha = FakeParameter("alpha", value=1)
    beta = FakeParameter("beta", value=2)
    store.add(alpha)
    store.add(beta)

    assert store.exists("alpha") is True
    assert store.exists("missing") is False
    assert store.get_value("alpha") == 1
    assert store.get_value("missing", default=99) == 99
    assert store.list_names() == ["alpha", "beta"]

    runtime_alpha = store._get_runtime_param("alpha")
    assert runtime_alpha is alpha
    assert set(param.name for param in store._iter_runtime_params()) == {"alpha", "beta"}

    removed = store._remove_runtime_param("alpha")
    assert removed is alpha
    assert store._remove_runtime_param("alpha") is None

    assert any(event["event"] == "parameter_removed" and event["name"] == "alpha" for event in broker.events)

    with pytest.raises(KeyError, match="Unknown parameter 'missing'"):
        store._get_runtime_param("missing")


def test_store_duplicate_and_get_record_error_scan_publish_paths() -> None:
    broker = FakeBroker()
    store = ParameterStore(event_broker=broker)
    param = FakeParameter("scan.value", value=5)

    store.add(param)

    with pytest.raises(ValueError, match="already exists"):
        store.add(FakeParameter("scan.value", value=7))

    with pytest.raises(KeyError, match="Unknown parameter 'missing'"):
        store.get_record("missing")

    rev_before = store.revision()
    store.publish_scan_value_if_changed("scan.value", old=10, new=10)
    assert store.revision() == rev_before

    store.publish_scan_value_if_changed("scan.value", old=10, new=11)
    assert store.revision() == rev_before + 1
    assert broker.events[-1]["event"] == "value_changed"
    assert broker.events[-1]["source"] == "scan"

    store.publish_scan_state("scan.value", {"ok": True})
    assert broker.events[-1] == {
        "event": "state_changed",
        "name": "scan.value",
        "state": {"ok": True},
    }
