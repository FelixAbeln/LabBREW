from __future__ import annotations

from pathlib import Path

from tests.test_schedule_runtime_behavior import FakeControlClient, FakeDataClient, _make_runtime


def test_schedule_runtime_moves_from_setup_to_plan(tmp_path: Path) -> None:
    runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=FakeDataClient(),
    )
    runtime.load_schedule(
        {
            "id": "setup-to-plan",
            "name": "Setup To Plan",
            "setup_steps": [{"id": "setup-1", "name": "Prime", "actions": [], "wait": {"kind": "none"}}],
            "plan_steps": [{"id": "plan-1", "name": "Run", "actions": [], "wait": {"kind": "elapsed", "duration_s": 5}}],
        }
    )

    runtime.start_run()
    runtime._tick()

    status = runtime.status()
    assert status["state"] == "running"
    assert status["phase"] == "plan"
    assert status["current_step_name"] == "Run"
    assert any("Entered plan phase" in entry for entry in status["event_log"])


def test_previous_step_crosses_from_plan_back_to_setup(tmp_path: Path) -> None:
    runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=FakeDataClient(),
    )
    runtime.load_schedule(
        {
            "id": "previous-step",
            "name": "Previous Step",
            "setup_steps": [{"id": "setup-1", "name": "Setup", "actions": [], "wait": {"kind": "elapsed", "duration_s": 5}}],
            "plan_steps": [{"id": "plan-1", "name": "Plan", "actions": [], "wait": {"kind": "elapsed", "duration_s": 5}}],
        }
    )

    runtime.start_run()
    assert runtime.next_step()["ok"] is True
    assert runtime.previous_step()["ok"] is True

    status = runtime.status()
    assert status["state"] == "paused"
    assert status["phase"] == "setup"
    assert status["current_step_name"] == "Setup"
    assert status["pause_reason"] is None


def test_schedule_runtime_pauses_when_target_ownership_is_lost(tmp_path: Path) -> None:
    control = FakeControlClient(values={"reactor.temp": 20.0})
    data = FakeDataClient(recording=True, session_name="existing")
    runtime = _make_runtime(tmp_path, control=control, data=data)
    runtime.load_schedule(
        {
            "id": "ownership-loss",
            "name": "Ownership Loss",
            "plan_steps": [
                {
                    "id": "plan-1",
                    "name": "Write",
                    "actions": [{"kind": "write", "target": "reactor.temp", "value": 30.0, "owner": "schedule_service"}],
                    "wait": {"kind": "elapsed", "duration_s": 60},
                }
            ],
        }
    )

    runtime.start_run()
    runtime._tick()
    control.owners["reactor.temp"] = "operator"
    runtime._tick()

    status = runtime.status()
    assert status["state"] == "paused"
    assert status["pause_reason"] == "ownership_lost"
    assert status["owned_targets"] == []
    assert status["wait_message"] == "Ownership lost; paused"


def test_resume_after_manual_override_reclaims_control_for_active_step(tmp_path: Path) -> None:
    control = FakeControlClient(values={"reactor.temp": 20.0})
    data = FakeDataClient(recording=True, session_name="existing")
    runtime = _make_runtime(tmp_path, control=control, data=data)
    runtime.load_schedule(
        {
            "id": "resume-reclaim",
            "name": "Resume Reclaim",
            "plan_steps": [
                {
                    "id": "plan-1",
                    "name": "Hold Setpoint",
                    "actions": [{"kind": "write", "target": "reactor.temp", "value": 30.0, "owner": "schedule_service"}],
                    "wait": {"kind": "elapsed", "duration_s": 60},
                }
            ],
        }
    )

    runtime.start_run()
    runtime._tick()
    control.owners["reactor.temp"] = "operator"
    control.values["reactor.temp"] = 25.0
    runtime._tick()

    paused = runtime.status()
    assert paused["state"] == "paused"
    assert paused["pause_reason"] == "ownership_lost"

    resumed = runtime.resume_run()
    assert resumed["ok"] is True

    status = runtime.status()
    assert status["state"] == "running"
    assert status["pause_reason"] is None
    assert status["owned_targets"] == ["reactor.temp"]
    assert control.manual_release_calls[-1] is None
    assert control.owners["reactor.temp"] == "schedule_service"
    assert control.values["reactor.temp"] == 30.0


def test_schedule_runtime_skips_before_next_loadstep_when_step_has_no_wait(tmp_path: Path) -> None:
    control = FakeControlClient(values={"reactor.temp": 20.0})
    data = FakeDataClient(recording=True, session_name="existing")
    runtime = _make_runtime(tmp_path, control=control, data=data)
    runtime.load_schedule(
        {
            "id": "skip-exit-loadstep",
            "name": "Skip Exit Loadstep",
            "plan_steps": [
                {
                    "id": "plan-1",
                    "name": "No Wait",
                    "actions": [
                        {
                            "kind": "take_loadstep",
                            "params": {"timing": "before_next", "loadstep_name": "ls_exit", "duration_seconds": 1},
                        }
                    ],
                    "wait": {"kind": "none"},
                }
            ],
        }
    )

    runtime.start_run()
    runtime._tick()

    status = runtime.status()
    assert status["state"] == "completed"
    assert data.loadstep_calls == []
    assert any("Skipped exit loadstep" in entry for entry in status["event_log"])


def test_schedule_runtime_tracks_multiple_owned_targets_in_one_step(tmp_path: Path) -> None:
    control = FakeControlClient(values={"reactor.temp": 20.0, "pump.speed": 100.0})
    data = FakeDataClient(recording=True, session_name="existing")
    runtime = _make_runtime(tmp_path, control=control, data=data)
    runtime.load_schedule(
        {
            "id": "multi-owned",
            "name": "Multi Owned Targets",
            "plan_steps": [
                {
                    "id": "plan-1",
                    "name": "Write Two Targets",
                    "actions": [
                        {"kind": "write", "target": "reactor.temp", "value": 31.0, "owner": "schedule_service"},
                        {"kind": "write", "target": "pump.speed", "value": 120.0, "owner": "schedule_service"},
                    ],
                    "wait": {"kind": "elapsed", "duration_s": 60},
                }
            ],
        }
    )

    runtime.start_run()
    runtime._tick()

    status = runtime.status()
    assert status["state"] == "running"
    assert sorted(status["owned_targets"]) == ["pump.speed", "reactor.temp"]
    assert control.owners["reactor.temp"] == "schedule_service"
    assert control.owners["pump.speed"] == "schedule_service"

    runtime.stop_run()
    assert control.owners["reactor.temp"] is None
    assert control.owners["pump.speed"] is None


def test_resume_fails_when_non_manual_owner_still_holds_target(tmp_path: Path) -> None:
    control = FakeControlClient(values={"reactor.temp": 20.0})
    data = FakeDataClient(recording=True, session_name="existing")
    runtime = _make_runtime(tmp_path, control=control, data=data)
    runtime.load_schedule(
        {
            "id": "failed-reclaim",
            "name": "Failed Reclaim",
            "plan_steps": [
                {
                    "id": "plan-1",
                    "name": "Write",
                    "actions": [{"kind": "write", "target": "reactor.temp", "value": 30.0, "owner": "schedule_service"}],
                    "wait": {"kind": "elapsed", "duration_s": 60},
                }
            ],
        }
    )

    runtime.start_run()
    runtime._tick()
    control.owners["reactor.temp"] = "operator"
    runtime._tick()

    assert runtime.status()["pause_reason"] == "ownership_lost"

    # A non-manual owner takes the target before resume; release-manual should not clear this owner.
    control.owners["reactor.temp"] = "safety"
    resumed = runtime.resume_run()

    assert resumed["ok"] is False
    assert resumed["message"] == "Could not reclaim control for active step"
    assert resumed["details"]["ok"] is False
    assert resumed["details"]["current_owner"] == "safety"
    assert runtime.status()["state"] == "paused"