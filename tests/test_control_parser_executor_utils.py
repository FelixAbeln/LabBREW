from __future__ import annotations

import pytest

from Services.control_service.control.executor import execute_action, read_value, set_value_checked
from Services.control_service.control.utils import get_targets
from Services.control_service.rules.parser import parse_condition


class DummyBackend:
    def __init__(self, values: dict[str, object] | None = None, *, write_ok: bool = True) -> None:
        self.values = dict(values or {})
        self.write_ok = write_ok

    def set_value(self, target: str, value: object) -> bool:
        self.values[target] = value
        return self.write_ok

    def get_value(self, target: str, default=None):
        return self.values.get(target, default)


class DummyOwnership:
    def __init__(self, owners: dict[str, str] | None = None) -> None:
        self.owners = dict(owners or {})

    def get_owner(self, target: str) -> str | None:
        return self.owners.get(target)

    def request(self, target: str, owner: str) -> bool:
        self.owners[target] = owner
        return True


def test_parse_condition_atomic_and_composites() -> None:
    atomic = parse_condition({"source": "temp", "operator": ">", "params": {"threshold": 20}}, path="rule:r1")
    all_node = parse_condition({"all": [{"source": "temp", "operator": ">", "params": {"threshold": 20}}]})
    any_node = parse_condition({"any": [{"source": "temp", "operator": "<", "params": {"threshold": 5}}]})
    not_node = parse_condition({"not": {"source": "alarm", "operator": "==", "params": {"threshold": True}}})

    assert atomic.source == "temp"
    assert atomic.node_id == "rule:r1"
    assert all_node.kind == "all"
    assert any_node.kind == "any"
    assert not_node.kind == "not"
    assert len(not_node.children) == 1


def test_parse_condition_validation_errors() -> None:
    with pytest.raises(ValueError):
        parse_condition("bad")

    with pytest.raises(ValueError):
        parse_condition({"unknown": True})


def test_get_targets_prefers_targets_list_and_filters_empty_values() -> None:
    assert get_targets({"targets": ["a", None, "", "b"]}) == ["a", "b"]
    assert get_targets({"target": "solo"}) == ["solo"]
    assert get_targets({"target": ""}) == []


def test_set_value_checked_blocks_conflicting_owner() -> None:
    backend = DummyBackend(values={"temp": 20.0})
    ownership = DummyOwnership(owners={"temp": "schedule"})

    result = set_value_checked(backend, ownership, "temp", 30.0, "operator")

    assert result["ok"] is False
    assert result["blocked"] is True
    assert result["current_owner"] == "schedule"
    assert backend.values["temp"] == 20.0


def test_set_value_checked_writes_and_tracks_owner() -> None:
    backend = DummyBackend(values={"temp": 20.0})
    ownership = DummyOwnership()

    result = set_value_checked(backend, ownership, "temp", 31.0, "schedule")

    assert result["ok"] is True
    assert result["blocked"] is False
    assert result["current_owner"] == "schedule"
    assert backend.values["temp"] == 31.0


def test_set_value_checked_handles_backend_write_failure() -> None:
    backend = DummyBackend(values={"temp": 20.0}, write_ok=False)
    ownership = DummyOwnership()

    result = set_value_checked(backend, ownership, "temp", 31.0, "schedule")

    assert result["ok"] is False
    assert result["written"] is False
    assert result["blocked"] is False


def test_read_value_returns_default_when_missing() -> None:
    backend = DummyBackend(values={"temp": 22.0})

    result = read_value(backend, "missing", default=123)

    assert result == {"ok": True, "target": "missing", "value": 123}


def test_execute_action_set_and_error_paths() -> None:
    backend = DummyBackend(values={"a": 1, "b": 2})

    missing_target = execute_action(backend, {"type": "set", "value": 9})
    missing_value = execute_action(backend, {"type": "set", "targets": ["a", "b"]})
    set_result = execute_action(backend, {"type": "set", "targets": ["a", "b"], "value": 9})
    unsupported = execute_action(backend, {"type": "noop", "target": "a"})

    assert missing_target == {"ok": False, "written": False, "reason": "missing target(s)"}
    assert missing_value == {
        "ok": False,
        "written": False,
        "reason": "missing value",
        "targets": ["a", "b"],
    }
    assert set_result["ok"] is True
    assert set_result["written"] == {"a": True, "b": True}
    assert set_result["value"] == 9
    assert backend.values["a"] == 9
    assert backend.values["b"] == 9
    assert unsupported == {
        "ok": False,
        "written": False,
        "reason": "unsupported action type: noop",
        "targets": ["a"],
    }