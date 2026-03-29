from __future__ import annotations

from types import SimpleNamespace

import Services.schedule_service.runtime.core as core_module
from Services.schedule_service.models import ScheduleAction, ScheduleStep
from tests.test_schedule_runtime_behavior import FakeControlClient, FakeDataClient, _make_runtime



def test_start_run_guard_paths(tmp_path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())

    assert runtime.start_run() == {"ok": False, "message": "No schedule loaded"}

    runtime.load_schedule(
        {
            "id": "disabled",
            "name": "Disabled",
            "setup_steps": [{"id": "s1", "name": "S1", "enabled": False, "actions": []}],
            "plan_steps": [{"id": "p1", "name": "P1", "enabled": False, "actions": []}],
        }
    )
    assert runtime.start_run() == {"ok": False, "message": "No enabled steps"}

    runtime.load_schedule(
        {
            "id": "running",
            "name": "Running",
            "plan_steps": [{"id": "p1", "name": "P1", "actions": []}],
        }
    )
    assert runtime.start_run()["ok"] is True
    assert runtime.start_run() == {"ok": False, "message": "Already running"}


def test_get_and_clear_schedule_paths(tmp_path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())

    assert runtime.get_schedule() == {"ok": True, "schedule": None}

    runtime.load_schedule(
        {
            "id": "sched-1",
            "name": "Schedule 1",
            "plan_steps": [{"id": "p1", "name": "P1", "actions": []}],
        }
    )
    got = runtime.get_schedule()
    assert got["ok"] is True
    assert got["schedule"]["id"] == "sched-1"

    cleared = runtime.clear_schedule()
    assert cleared == {"ok": True}
    assert runtime.get_schedule() == {"ok": True, "schedule": None}


def test_start_run_setup_phase_and_release_manual_exception(tmp_path) -> None:
    control = FakeControlClient(values={})

    def _raise_release_manual(_targets=None):
        raise RuntimeError("control unavailable")

    control.release_manual = _raise_release_manual  # type: ignore[assignment]
    runtime = _make_runtime(tmp_path, control=control, data=FakeDataClient())
    runtime.load_schedule(
        {
            "id": "setup-first",
            "name": "Setup First",
            "setup_steps": [{"id": "s1", "name": "Setup 1", "actions": []}],
            "plan_steps": [{"id": "p1", "name": "Plan 1", "actions": []}],
        }
    )

    started = runtime.start_run()

    assert started["ok"] is True
    assert runtime.status()["phase"] == "setup"
    assert runtime.status()["current_step_name"] == "Setup 1"


def test_pause_run_success_path(tmp_path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())
    runtime.load_schedule(
        {
            "id": "pause-ok",
            "name": "Pause Ok",
            "plan_steps": [{"id": "p1", "name": "P1", "actions": []}],
        }
    )
    runtime.start_run()

    paused = runtime.pause_run()

    assert paused == {"ok": True}
    assert runtime.status()["state"] == "paused"
    assert runtime.status()["pause_reason"] == "manual"
    assert runtime.status()["wait_message"] == "Paused manually"



def test_pause_resume_next_previous_guard_paths(tmp_path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())

    assert runtime.pause_run() == {"ok": False, "message": "Run is not active"}
    assert runtime.resume_run() == {"ok": False, "message": "Run is not paused"}
    assert runtime.next_step() == {"ok": False, "message": "No schedule loaded"}
    assert runtime.previous_step() == {"ok": False, "message": "No schedule loaded"}

    runtime.load_schedule(
        {
            "id": "idle-nav",
            "name": "Idle Nav",
            "plan_steps": [{"id": "p1", "name": "P1", "actions": []}],
        }
    )
    assert runtime.next_step() == {"ok": False, "message": "Run is not active"}
    assert runtime.previous_step() == {"ok": False, "message": "Run is not active"}



def test_previous_step_no_previous_pauses_running_state(tmp_path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())
    runtime.load_schedule(
        {
            "id": "prev-none",
            "name": "Prev None",
            "setup_steps": [{"id": "s1", "name": "Setup 1", "actions": []}],
            "plan_steps": [{"id": "p1", "name": "Plan 1", "actions": []}],
        }
    )
    runtime.start_run()

    result = runtime.previous_step()

    assert result == {"ok": False, "message": "No previous step"}
    assert runtime.status()["state"] == "paused"
    assert runtime.status()["pause_reason"] == "Manual step back"



def test_resume_run_missing_schedule_and_pending_exit_message(tmp_path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())
    runtime._status.state = "paused"
    runtime.repository.clear()

    assert runtime.resume_run() == {"ok": False, "message": "No schedule loaded"}

    runtime.load_schedule(
        {
            "id": "resume-exit",
            "name": "Resume Exit",
            "plan_steps": [{"id": "p1", "name": "P1", "actions": []}],
        }
    )
    runtime.start_run()
    runtime._status.state = "paused"
    runtime._status.pause_reason = "manual"
    runtime._step_runtime.pending_exit_loadsteps = {"ls_a", "ls_b"}
    runtime._auto_start_measurement_locked = lambda _schedule: None

    resumed = runtime.resume_run()

    assert resumed == {"ok": True}
    assert runtime.status()["state"] == "running"
    assert "Waiting for loadstep completion" in runtime.status()["wait_message"]



def test_tick_non_running_and_missing_schedule_paths(tmp_path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())
    runtime._persist_locked = lambda: (_ for _ in ()).throw(AssertionError("should not persist"))
    runtime._tick()  # idle should short-circuit

    runtime._status.state = "running"
    persisted = {"called": False}
    runtime._persist_locked = lambda: persisted.update(called=True)
    runtime.repository.clear()

    runtime._tick()

    assert runtime.status()["state"] == "faulted"
    assert runtime.status()["wait_message"] == "Schedule missing"
    assert persisted["called"] is True



def test_tick_out_of_range_advances_phase_or_completes(tmp_path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())
    runtime.load_schedule(
        {
            "id": "advance-range",
            "name": "Advance Range",
            "plan_steps": [{"id": "p1", "name": "P1", "actions": []}],
        }
    )
    runtime._status.state = "running"
    runtime._phase = "plan"
    runtime._step_index = 99

    calls = {"advance": 0, "persist": 0}
    runtime._advance_phase_or_complete_locked = lambda _schedule: calls.update(advance=calls["advance"] + 1)
    runtime._persist_locked = lambda: calls.update(persist=calls["persist"] + 1)

    runtime._tick()

    assert calls == {"advance": 1, "persist": 1}



def test_tick_wait_not_matched_persists_state(tmp_path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={"x": 1.0}), data=FakeDataClient())
    runtime.load_schedule(
        {
            "id": "wait-false",
            "name": "Wait False",
            "plan_steps": [{"id": "p1", "name": "P1", "actions": [], "wait": {"kind": "elapsed", "duration_s": 100}}],
        }
    )
    runtime._status.state = "running"
    runtime._phase = "plan"
    runtime._step_index = 0
    runtime._step_runtime.actions_applied = True
    runtime._step_runtime.wait_state = object()

    runtime.wait_engine = SimpleNamespace(
        evaluate=lambda *_args, **_kwargs: SimpleNamespace(matched=False, message="still waiting", next_state="next")
    )
    runtime._ownership_lost = lambda _step: False

    persisted = {"count": 0}
    runtime._persist_locked = lambda: persisted.update(count=persisted["count"] + 1)

    runtime._tick()

    assert runtime.status()["wait_message"] == "still waiting"
    assert runtime._step_runtime.wait_state == "next"
    assert persisted["count"] == 1



def test_loop_fault_branch_and_thread_lifecycle_paths(monkeypatch, tmp_path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())
    runtime._status.state = "running"

    runtime._tick = lambda: (_ for _ in ()).throw(RuntimeError("boom"))

    def _sleep(_seconds):
        runtime._stop_event.set()

    monkeypatch.setattr(core_module.time, "sleep", _sleep)

    runtime._loop()

    assert runtime.status()["state"] == "faulted"
    assert "Fault: boom" in runtime.status()["wait_message"]
    assert any("Fault: boom" in item for item in runtime.status()["event_log"])

    class DummyThread:
        def __init__(self, target=None, daemon=False, name=None):
            self.target = target
            self.daemon = daemon
            self.name = name
            self.started = False
            self.joined = False
            self._alive = True

        def start(self):
            self.started = True

        def is_alive(self):
            return self._alive

        def join(self, timeout=None):
            self.joined = True

    monkeypatch.setattr(core_module.threading, "Thread", DummyThread)

    runtime2 = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())
    runtime2.start_background()
    assert runtime2._thread is not None
    assert runtime2._thread.started is True

    # Calling start_background again while thread is alive should no-op.
    existing_thread = runtime2._thread
    runtime2.start_background()
    assert runtime2._thread is existing_thread

    runtime2.shutdown()
    assert runtime2._thread.joined is True


def test_resume_run_release_manual_exception_is_non_fatal(tmp_path) -> None:
    control = FakeControlClient(values={})

    def _raise_release_manual(_targets=None):
        raise RuntimeError("control unavailable")

    control.release_manual = _raise_release_manual  # type: ignore[assignment]
    runtime = _make_runtime(tmp_path, control=control, data=FakeDataClient())
    runtime.load_schedule(
        {
            "id": "resume-exception",
            "name": "Resume Exception",
            "plan_steps": [{"id": "p1", "name": "P1", "actions": []}],
        }
    )
    runtime.start_run()
    runtime._status.state = "paused"
    runtime._status.pause_reason = "manual"
    runtime._auto_start_measurement_locked = lambda _schedule: None

    resumed = runtime.resume_run()

    assert resumed == {"ok": True}
    assert runtime.status()["state"] == "running"


def test_ownership_lost_with_non_dict_ownership_meta(tmp_path) -> None:
    control = FakeControlClient(values={"x": 1.0})
    runtime = _make_runtime(tmp_path, control=control, data=FakeDataClient())

    step = ScheduleStep(id="s1", name="S1", actions=[ScheduleAction(kind="write", target="x", owner="schedule_service")])
    runtime._status.owned_targets = ["x"]
    runtime._owned_target_owners = {"x": "schedule_service"}

    # ownership() returns non-dict meta for x; this forces current_owner=None path.
    runtime.control.ownership = lambda: {"x": "not-a-dict"}  # type: ignore[assignment]

    assert runtime._ownership_lost(step) is True


def test_reclaim_step_ownership_request_control_and_fail_fast(tmp_path) -> None:
    control = FakeControlClient(values={"a": 1.0, "b": 2.0, "c": 3.0})
    runtime = _make_runtime(tmp_path, control=control, data=FakeDataClient())

    step = ScheduleStep(
        id="s1",
        name="Reclaim",
        actions=[
            ScheduleAction(kind="request_control", target="a", owner="schedule_service"),
            ScheduleAction(kind="write", target="b", value=4.0, owner="schedule_service"),
            ScheduleAction(kind="ramp", target="c", value=6.0, duration_s=2.0, owner="schedule_service"),
        ],
    )

    # Force write failure so reclaim exits early before ramp action.
    def fail_write(target, value, owner):
        return {"ok": False, "target": target, "owner": owner, "reason": "simulated write failure"}

    control.write = fail_write  # type: ignore[assignment]

    result = runtime._reclaim_step_ownership_locked(step)

    assert result["ok"] is False
    # request_control branch should have succeeded and been remembered before failure.
    assert runtime._owned_target_owners.get("a") == "schedule_service"
    # write failed, so b/c are not remembered.
    assert "b" not in runtime._owned_target_owners
    assert "c" not in runtime._owned_target_owners


def test_reclaim_step_ownership_ramp_success_path(tmp_path) -> None:
    control = FakeControlClient(values={"c": 3.0})
    runtime = _make_runtime(tmp_path, control=control, data=FakeDataClient())

    step = ScheduleStep(
        id="s1",
        name="Ramp Reclaim",
        actions=[ScheduleAction(kind="ramp", target="c", value=9.0, duration_s=3.0, owner="schedule_service")],
    )

    result = runtime._reclaim_step_ownership_locked(step)

    assert result["ok"] is True
    assert runtime._owned_target_owners.get("c") == "schedule_service"


def test_ownership_new_guards_for_unowned_targets_missing_target_and_discard_paths(tmp_path) -> None:
    control = FakeControlClient(values={"x": 1.0})
    runtime = _make_runtime(tmp_path, control=control, data=FakeDataClient())

    # _ownership_lost line 24: owned target guard continue
    step = ScheduleStep(id="s1", name="S1", actions=[ScheduleAction(kind="write", target="x", owner="schedule_service")])
    runtime._status.owned_targets = []
    runtime._owned_target_owners = {}
    assert runtime._ownership_lost(step) is False

    # _reclaim_step_ownership_locked lines 38/40: skip unsupported action then fail on missing target
    bad_step = ScheduleStep(
        id="s2",
        name="Bad",
        actions=[
            ScheduleAction(kind="take_loadstep", target=None),
            ScheduleAction(kind="write", target=None, owner="schedule_service"),
        ],
    )
    result = runtime._reclaim_step_ownership_locked(bad_step)
    assert result["ok"] is False
    assert "missing target" in str(result["error"])

    # _remove_owned_targets_for_step_locked and _discard_owned_target_locked lines 77-79, 86-87
    runtime._owned_target_owners = {"x": "schedule_service", "y": "schedule_service"}
    runtime._refresh_owned_targets_locked()
    remove_step = ScheduleStep(
        id="s3",
        name="Remove",
        actions=[ScheduleAction(kind="write", target="x"), ScheduleAction(kind="write", target=None)],
    )
    runtime._remove_owned_targets_for_step_locked(remove_step)
    assert runtime._owned_target_owners == {"y": "schedule_service"}
    assert runtime.status()["owned_targets"] == ["y"]

    runtime._discard_owned_target_locked("missing")
    assert runtime._owned_target_owners == {"y": "schedule_service"}


def test_ownership_lost_ignores_non_mapping_meta_and_release_cleans_up(tmp_path) -> None:
    control = FakeControlClient(values={"x": 1.0})
    runtime = _make_runtime(tmp_path, control=control, data=FakeDataClient())

    ignored_step = ScheduleStep(id="s4-ignore", name="Ignore", actions=[ScheduleAction(kind="take_loadstep", target=None)])
    assert runtime._ownership_lost(ignored_step) is False

    step = ScheduleStep(id="s4", name="S4", actions=[ScheduleAction(kind="write", target="x", owner="schedule_service")])
    runtime._status.owned_targets = ["x"]
    runtime._owned_target_owners = {"x": "schedule_service"}
    control.owners["x"] = "schedule_service"
    control.ownership = lambda: {"x": "not-a-dict"}  # type: ignore[assignment]

    assert runtime._ownership_lost(step) is True

    runtime._release_owned_targets_locked("stop run")

    assert runtime._owned_target_owners == {}
    assert runtime.status()["owned_targets"] == []
    assert any("released ownership for x" in entry for entry in runtime.status()["event_log"])


def test_move_previous_crosses_from_plan_to_setup(tmp_path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())
    runtime.load_schedule(
        {
            "id": "cross-prev",
            "name": "Cross Prev",
            "setup_steps": [
                {"id": "s1", "name": "S1", "enabled": True, "actions": []},
                {"id": "s2", "name": "S2", "enabled": False, "actions": []},
            ],
            "plan_steps": [{"id": "p1", "name": "P1", "enabled": True, "actions": []}],
        }
    )

    schedule = runtime.repository.get_current()
    assert schedule is not None
    runtime._phase = "plan"
    runtime._step_index = 0

    moved = runtime._move_previous_locked(schedule)

    assert moved is True
    assert runtime._phase == "setup"
    assert runtime._step_index == 0


def test_move_previous_cross_phase_with_last_enabled_setup_step(tmp_path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())
    runtime.load_schedule(
        {
            "id": "cross-prev-last",
            "name": "Cross Prev Last",
            "setup_steps": [
                {"id": "s1", "name": "Setup 1", "enabled": False, "actions": []},
                {"id": "s2", "name": "Setup 2", "enabled": True, "actions": []},
            ],
            "plan_steps": [{"id": "p1", "name": "Plan 1", "enabled": True, "actions": []}],
        }
    )

    schedule = runtime.repository.get_current()
    assert schedule is not None
    runtime._phase = "plan"
    runtime._step_index = 0

    assert runtime._move_previous_locked(schedule) is True
    assert runtime._phase == "setup"
    assert runtime._step_index == 1
    assert runtime.status()["current_step_name"] == "Setup 2"


def test_move_previous_cross_phase_branch_with_stubbed_helpers(tmp_path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())
    runtime._phase = "plan"
    runtime._step_index = 0

    class Step:
        def __init__(self, enabled: bool):
            self.enabled = enabled

    schedule = SimpleNamespace(
        setup_steps=[Step(False), Step(True)],
        plan_steps=[Step(True)],
    )
    activated: list[str] = []
    runtime._phase_steps = lambda _schedule: schedule.plan_steps
    runtime._enabled_steps = lambda steps: [step for step in steps if step.enabled]
    runtime._activate_step_locked = lambda: activated.append("yes")
    runtime._append_event = lambda _text: None

    assert runtime._move_previous_locked(schedule) is True
    assert runtime._phase == "setup"
    assert runtime._step_index == 1
    assert activated == ["yes"]
