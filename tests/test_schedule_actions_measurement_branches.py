from __future__ import annotations

from pathlib import Path

import pytest

from Services.schedule_service.models import ScheduleAction, ScheduleDefinition, ScheduleStep
from tests.test_schedule_runtime_behavior import FakeControlClient, FakeDataClient, _make_runtime


class SetupFailDataClient(FakeDataClient):
    def setup_measurement(self, **kwargs):  # type: ignore[override]
        self.setup_calls.append(kwargs)
        return {"ok": False, "error": "setup failed"}


class StartFailDataClient(FakeDataClient):
    def measure_start(self):  # type: ignore[override]
        self.start_calls += 1
        return {"ok": False, "error": "start failed"}


class StatusErrorDataClient(FakeDataClient):
    def status(self):  # type: ignore[override]
        raise RuntimeError("status unavailable")


class NamelessLoadstepDataClient(FakeDataClient):
    def take_loadstep(self, **kwargs):  # type: ignore[override]
        self.loadstep_calls.append(kwargs)
        return {"ok": True}


class StopFailDataClient(FakeDataClient):
    def measure_stop(self):  # type: ignore[override]
        self.stop_calls += 1
        self.recording = False
        return {"ok": False, "error": "stop failed"}


class FailedExitLoadstepDataClient(FakeDataClient):
    def take_loadstep(self, **kwargs):  # type: ignore[override]
        self.loadstep_calls.append(kwargs)
        return {"ok": False, "error": "loadstep failed"}


class StatusPayloadDataClient(FakeDataClient):
    def __init__(self, payload: dict) -> None:
        super().__init__(recording=True)
        self._payload = payload

    def status(self):  # type: ignore[override]
        return dict(self._payload)



def test_apply_actions_request_write_release_and_take_loadstep_on_enter(tmp_path: Path) -> None:
    runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=FakeDataClient(recording=True, session_name="existing"),
    )
    step = ScheduleStep(
        id="s1",
        name="Actions",
        actions=[
            ScheduleAction(kind="request_control", target="reactor.temp", owner="schedule_service"),
            ScheduleAction(kind="write", target="reactor.temp", value=25.0, owner="schedule_service"),
            ScheduleAction(kind="release_control", target="reactor.temp", owner="schedule_service"),
            ScheduleAction(
                kind="take_loadstep",
                duration_s=3.0,
                params={"timing": "on_enter", "loadstep_name": "ls1", "parameters": ["reactor.temp"]},
            ),
        ],
        wait={"kind": "elapsed", "duration_s": 1},
    )

    runtime._apply_actions_locked(step)

    assert runtime.status()["last_action_result"]["ok"] is True
    assert runtime.control.owners["reactor.temp"] is None
    assert runtime.data.loadstep_calls[0]["loadstep_name"] == "ls1"



def test_apply_actions_global_measurement_modes_and_invalid_mode(tmp_path: Path) -> None:
    runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=FakeDataClient(recording=False),
    )
    step = ScheduleStep(
        id="s1",
        name="Measurement",
        actions=[
            ScheduleAction(kind="global_measurement", value="start", params={"parameters": ["reactor.temp"], "session_name": "m1"}),
            ScheduleAction(kind="global_measurement", value="stop"),
        ],
    )

    runtime._apply_actions_locked(step)

    assert runtime.data.setup_calls[0]["session_name"] == "m1"
    assert runtime.data.start_calls == 1
    assert runtime.data.stop_calls == 1

    bad_step = ScheduleStep(id="s2", name="Bad", actions=[ScheduleAction(kind="global_measurement", value="invalid")])
    with pytest.raises(ValueError):
        runtime._apply_actions_locked(bad_step)



def test_apply_actions_raises_when_control_action_fails(tmp_path: Path) -> None:
    control = FakeControlClient(values={"reactor.temp": 20.0}, owners={"reactor.temp": "operator"})
    runtime = _make_runtime(tmp_path, control=control, data=FakeDataClient(recording=True))
    step = ScheduleStep(
        id="s1",
        name="Conflict",
        actions=[ScheduleAction(kind="write", target="reactor.temp", value=30.0, owner="schedule_service")],
    )

    with pytest.raises(RuntimeError):
        runtime._apply_actions_locked(step)


def test_apply_actions_ramp_and_unsupported_kind_paths(tmp_path: Path) -> None:
    runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=FakeDataClient(recording=True),
    )
    ramp_step = ScheduleStep(
        id="s-ramp",
        name="Ramp",
        actions=[ScheduleAction(kind="ramp", target="reactor.temp", value=26.5, duration_s=12.0)],
    )
    runtime._apply_actions_locked(ramp_step)
    assert runtime.control.values["reactor.temp"] == 26.5
    assert runtime.control.owners["reactor.temp"] == runtime.owner

    bad_step = ScheduleStep(id="s-bad", name="Bad", actions=[ScheduleAction(kind="unsupported_action")])
    with pytest.raises(ValueError):
        runtime._apply_actions_locked(bad_step)



def test_run_exit_actions_waits_then_completes_when_loadstep_finishes(tmp_path: Path) -> None:
    data = FakeDataClient(recording=True, session_name="active")
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={"reactor.temp": 20.0}), data=data)
    step = ScheduleStep(
        id="s1",
        name="ExitLoadstep",
        actions=[ScheduleAction(kind="take_loadstep", params={"timing": "before_next", "loadstep_name": "ls_exit"})],
        wait={"kind": "elapsed", "duration_s": 1},
    )

    first = runtime._run_exit_actions_locked(step)
    assert first is False
    assert "Waiting for loadstep completion" in runtime.status()["wait_message"]

    second = runtime._run_exit_actions_locked(step)
    assert second is False

    data.complete_active_loadsteps()
    done = runtime._run_exit_actions_locked(step)
    assert done is True
    assert runtime._step_runtime.pending_exit_loadsteps == set()



def test_run_exit_actions_with_nameless_loadstep_returns_ready(tmp_path: Path) -> None:
    data = NamelessLoadstepDataClient(recording=True)
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={"reactor.temp": 20.0}), data=data)
    step = ScheduleStep(
        id="s1",
        name="ExitNameless",
        actions=[ScheduleAction(kind="take_loadstep", params={"timing": "before_next"})],
        wait={"kind": "elapsed", "duration_s": 1},
    )

    assert runtime._run_exit_actions_locked(step) is True


def test_run_exit_actions_raises_when_exit_loadstep_fails(tmp_path: Path) -> None:
    data = FailedExitLoadstepDataClient(recording=True)
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={"reactor.temp": 20.0}), data=data)
    step = ScheduleStep(
        id="s1",
        name="ExitFails",
        actions=[ScheduleAction(kind="take_loadstep", params={"timing": "before_next", "loadstep_name": "ls_bad"})],
        wait={"kind": "elapsed", "duration_s": 1},
    )

    with pytest.raises(RuntimeError):
        runtime._run_exit_actions_locked(step)


def test_run_exit_actions_wait_message_formatting_edge_paths(tmp_path: Path) -> None:
    payload = {
        "backend_connected": True,
        "recording": True,
        "config": None,
        "active_loadstep_names": [],
        "completed_loadsteps": [],
        "active_loadsteps": [
            "not-a-dict",
            {"name": "", "remaining_seconds": 10},
            {"name": "other", "remaining_seconds": 10},
            {"name": "ls_pending", "remaining_seconds": None},
        ],
    }
    runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=StatusPayloadDataClient(payload),
    )
    runtime._step_runtime.pending_exit_loadsteps = {"ls_pending"}
    step = ScheduleStep(
        id="s1",
        name="Fmt",
        actions=[ScheduleAction(kind="take_loadstep", params={"timing": "before_next", "loadstep_name": "ls_pending"})],
        wait={"kind": "elapsed", "duration_s": 1},
    )

    done = runtime._run_exit_actions_locked(step)
    assert done is False
    assert "ls_pending" in runtime.status()["wait_message"]


def test_run_exit_actions_wait_message_fallback_and_bad_remaining(tmp_path: Path) -> None:
    bad_remaining_payload = {
        "backend_connected": True,
        "recording": True,
        "config": None,
        "active_loadstep_names": ["ls_pending"],
        "completed_loadsteps": [],
        "active_loadsteps": [{"name": "ls_pending", "remaining_seconds": object()}],
    }
    runtime_bad = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=StatusPayloadDataClient(bad_remaining_payload),
    )
    runtime_bad._step_runtime.pending_exit_loadsteps = {"ls_pending"}
    bad_step = ScheduleStep(
        id="s1",
        name="BadRemain",
        actions=[ScheduleAction(kind="take_loadstep", params={"timing": "before_next", "loadstep_name": "ls_pending"})],
        wait={"kind": "elapsed", "duration_s": 1},
    )
    assert runtime_bad._run_exit_actions_locked(bad_step) is False
    assert runtime_bad.status()["wait_message"].endswith("ls_pending")

    fallback_payload = {
        "backend_connected": True,
        "recording": True,
        "config": None,
        "active_loadstep_names": [],
        "completed_loadsteps": [],
        "active_loadsteps": [{"name": "other", "remaining_seconds": 3}],
    }
    runtime_fallback = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=StatusPayloadDataClient(fallback_payload),
    )
    runtime_fallback._step_runtime.pending_exit_loadsteps = {"ls_missing"}
    fallback_step = ScheduleStep(
        id="s1",
        name="Fallback",
        actions=[ScheduleAction(kind="take_loadstep", params={"timing": "before_next", "loadstep_name": "ls_missing"})],
        wait={"kind": "elapsed", "duration_s": 1},
    )
    assert runtime_fallback._run_exit_actions_locked(fallback_step) is False
    assert runtime_fallback.status()["wait_message"].endswith("ls_missing")



def test_auto_start_measurement_handles_status_error_and_no_parameters(tmp_path: Path) -> None:
    status_error_runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=StatusErrorDataClient(),
    )
    schedule = ScheduleDefinition(id="s1", name="S1")

    status_error_runtime._auto_start_measurement_locked(schedule)
    assert any("status unavailable" in entry for entry in status_error_runtime.status()["event_log"])

    no_params_runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={}),
        data=FakeDataClient(recording=False),
    )
    no_params_runtime._auto_start_measurement_locked(schedule)
    assert any("no parameters configured or available" in entry for entry in no_params_runtime.status()["event_log"])



def test_auto_start_measurement_logs_setup_or_start_failures(tmp_path: Path) -> None:
    setup_fail_runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=SetupFailDataClient(recording=False),
    )
    schedule = ScheduleDefinition(id="s2", name="S2")
    setup_fail_runtime._auto_start_measurement_locked(schedule)
    assert any("setup failed" in entry for entry in setup_fail_runtime.status()["event_log"])

    start_fail_runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=StartFailDataClient(recording=False),
    )
    start_fail_runtime._auto_start_measurement_locked(schedule)
    assert any("start failed" in entry for entry in start_fail_runtime.status()["event_log"])



def test_start_global_measurement_requires_parameters_or_snapshot(tmp_path: Path) -> None:
    runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={}),
        data=FakeDataClient(recording=False),
    )
    action = ScheduleAction(kind="global_measurement", params={})
    step = ScheduleStep(id="s1", name="Step")

    with pytest.raises(RuntimeError):
        runtime._start_global_measurement(action, step)


def test_start_global_measurement_idempotent_when_already_recording(tmp_path: Path) -> None:
    runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=FakeDataClient(recording=True),
    )
    action = ScheduleAction(kind="global_measurement", params={"parameters": ["reactor.temp"]})
    step = ScheduleStep(id="s1", name="Step")

    result = runtime._start_global_measurement(action, step)
    assert result["ok"] is True
    assert "already recording" in result["message"]


def test_start_global_measurement_raises_on_setup_or_start_failure(tmp_path: Path) -> None:
    action = ScheduleAction(kind="global_measurement", params={"parameters": ["reactor.temp"]})
    step = ScheduleStep(id="s1", name="Step")

    setup_fail_runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=SetupFailDataClient(recording=False),
    )
    with pytest.raises(RuntimeError):
        setup_fail_runtime._start_global_measurement(action, step)

    start_fail_runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=StartFailDataClient(recording=False),
    )
    with pytest.raises(RuntimeError):
        start_fail_runtime._start_global_measurement(action, step)


def test_stop_global_measurement_idempotent_when_already_stopped(tmp_path: Path) -> None:
    runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=FakeDataClient(recording=False),
    )

    result = runtime._stop_global_measurement()
    assert result["ok"] is True
    assert "already stopped" in result["message"]



def test_ensure_measurement_running_returns_false_without_schedule(tmp_path: Path) -> None:
    runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=FakeDataClient(recording=False),
    )

    assert runtime._ensure_measurement_running_locked() is False
    assert any("no schedule loaded" in entry for entry in runtime.status()["event_log"])


def test_ensure_measurement_running_auto_starts_when_schedule_exists(tmp_path: Path) -> None:
    runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=FakeDataClient(recording=False),
    )
    runtime.load_schedule(
        {
            "id": "s1",
            "name": "AutoStart",
            "measurement_config": {"parameters": ["reactor.temp"], "output_dir": str(tmp_path)},
            "plan_steps": [],
        }
    )

    assert runtime._ensure_measurement_running_locked() is True
    assert runtime.data.start_calls == 1


def test_take_data_loadstep_raises_when_measurement_unavailable(tmp_path: Path) -> None:
    runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=FakeDataClient(recording=False),
    )
    runtime._ensure_measurement_running_locked = lambda: False  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        runtime._take_data_loadstep(ScheduleAction(kind="take_loadstep"), ScheduleStep(id="s1", name="S"))


def test_atomic_write_text_file_cleans_temp_file_on_replace_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=FakeDataClient(recording=False),
    )
    output_path = tmp_path / "output.txt"

    def _raise_replace(*_args, **_kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr("Services.schedule_service.runtime.measurement.os.replace", _raise_replace)

    with pytest.raises(OSError):
        runtime._atomic_write_text_file(str(output_path), "content")

    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_text_file_ignores_unlink_oserror_on_replace_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=FakeDataClient(recording=False),
    )
    output_path = tmp_path / "output2.txt"

    def _raise_replace(*_args, **_kwargs):
        raise OSError("replace failed")

    def _raise_unlink(*_args, **_kwargs):
        raise OSError("unlink failed")

    monkeypatch.setattr("Services.schedule_service.runtime.measurement.os.replace", _raise_replace)
    monkeypatch.setattr("Services.schedule_service.runtime.measurement.os.unlink", _raise_unlink)

    with pytest.raises(OSError):
        runtime._atomic_write_text_file(str(output_path), "content")



def test_finalize_measurement_records_success_and_failure_paths(tmp_path: Path) -> None:
    success_data = FakeDataClient(recording=True, session_name="session-x")
    success_runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=success_data,
    )
    success_runtime._run_log_path = str(tmp_path / "run.log")
    success_runtime._schedule_export_path = str(tmp_path / "sched.json")

    success_runtime._finalize_measurement_if_recording_locked("completed")
    records = success_runtime.status()["data_records"]
    assert any(item.get("kind") == "measurement_finalized" for item in records)
    assert success_runtime._run_log_path is None
    assert success_runtime._schedule_export_path is None

    fail_runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"reactor.temp": 20.0}),
        data=StopFailDataClient(recording=True, session_name="session-y"),
    )
    fail_runtime._finalize_measurement_if_recording_locked("stopped")
    assert any("finalize failed" in entry for entry in fail_runtime.status()["event_log"])
