from __future__ import annotations

from Services.control_service.control.ownership import OwnershipManager


def test_request_release_and_snapshot_metadata() -> None:
    manager = OwnershipManager()

    assert manager.request(
        "reactor.temp.setpoint",
        "schedule",
        reason="schedule start",
        owner_source="schedule_service",
        rule_id="rule-1",
    ) is True
    assert manager.request("reactor.temp.setpoint", "operator") is False

    snapshot = manager.snapshot()
    assert snapshot["reactor.temp.setpoint"]["owner"] == "schedule"
    assert snapshot["reactor.temp.setpoint"]["reason"] == "schedule start"
    assert snapshot["reactor.temp.setpoint"]["owner_source"] == "schedule_service"
    assert snapshot["reactor.temp.setpoint"]["rule_id"] == "rule-1"
    assert isinstance(snapshot["reactor.temp.setpoint"]["time"], float)

    assert manager.release("reactor.temp.setpoint", "operator") is False
    assert manager.release("reactor.temp.setpoint", "schedule") is True
    assert manager.get_owner("reactor.temp.setpoint") is None
    assert manager.snapshot() == {}


def test_force_takeover_replaces_owner_and_snapshot_is_defensive_copy() -> None:
    manager = OwnershipManager()
    manager.request("pump.speed", "schedule")

    manager.force_takeover(
        "pump.speed",
        "operator",
        reason="manual override",
        owner_source="ui",
    )

    snapshot = manager.snapshot()
    snapshot["pump.speed"]["owner"] = "mutated"

    live_snapshot = manager.snapshot()
    assert manager.get_owner("pump.speed") == "operator"
    assert live_snapshot["pump.speed"]["owner"] == "operator"
    assert live_snapshot["pump.speed"]["reason"] == "manual override"
    assert live_snapshot["pump.speed"]["owner_source"] == "ui"