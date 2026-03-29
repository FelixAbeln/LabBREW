from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace

import Services.schedule_service.runtime.utils as utils_module
from tests.test_schedule_runtime_behavior import FakeControlClient, FakeDataClient, _make_runtime



def test_utils_slugify_default_name_and_action_timing(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())

    runtime._status.schedule_id = "  Weird ID!!  "
    generated = runtime._default_data_name()

    assert generated.startswith("scheduling_weird_id_")
    assert runtime._slugify("###") == "item"
    assert runtime._slugify("A  B---C") == "a_b_c"

    assert runtime._action_timing(SimpleNamespace(params={"timing": "  BEFORE_NEXT  "})) == "before_next"
    assert runtime._action_timing(SimpleNamespace(params=None)) == "on_enter"



def test_utils_collect_wait_sources_and_collect_values(tmp_path: Path) -> None:
    runtime = _make_runtime(
        tmp_path,
        control=FakeControlClient(values={"a": 1.0, "b": 2.0, "c": 3.0}),
        data=FakeDataClient(),
    )
    wait_payload = {
        "kind": "all_of",
        "children": [
            {
                "kind": "condition",
                "condition": {"source": "a", "operator": ">", "threshold": 0},
            },
            {
                "kind": "condition",
                "condition": {
                    "all": [{"source": "b"}],
                    "not": {"source": "c"},
                },
            },
        ],
    }

    sources = runtime._collect_wait_sources(wait_payload)

    assert sources == {"a", "b", "c"}

    step = SimpleNamespace(wait=wait_payload)
    values = runtime._collect_values(step)
    assert values == {"a": 1.0, "b": 2.0, "c": 3.0}



def test_utils_append_event_writes_log_and_reports_write_error_once(monkeypatch, tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())
    run_log = tmp_path / "run.log"
    runtime._run_log_path = str(run_log)

    runtime._append_event("first")
    text = run_log.read_text(encoding="utf-8")
    assert "first" in text

    real_open = builtins.open

    def _raising_open(path, *args, **kwargs):
        if str(path) == str(run_log):
            raise OSError("disk full")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _raising_open)

    runtime._append_event("second")
    runtime._append_event("third")

    warnings = [item for item in runtime.status()["event_log"] if "Run log write failed" in item]
    assert len(warnings) == 1



def test_navigation_activate_step_early_return_and_valid_activation(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())

    runtime._phase = "plan"
    runtime._step_index = 0
    runtime._activate_step_locked()  # no schedule loaded
    assert runtime.status()["current_step_name"] == ""

    runtime.load_schedule(
        {
            "id": "nav-activate",
            "name": "Nav Activate",
            "plan_steps": [{"id": "p1", "name": "Plan 1", "actions": []}],
        }
    )

    runtime._phase = "plan"
    runtime._step_index = 99
    runtime._activate_step_locked()  # out of range
    assert runtime.status()["current_step_name"] == ""

    runtime._step_index = 0
    runtime._activate_step_locked()
    status = runtime.status()
    assert status["current_step_name"] == "Plan 1"
    assert status["wait_message"] == "Active step: Plan 1"



def test_navigation_advance_step_manual_event_and_completion_behavior(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())
    runtime.load_schedule(
        {
            "id": "nav-advance",
            "name": "Nav Advance",
            "plan_steps": [
                {"id": "p1", "name": "Plan 1", "actions": []},
                {"id": "p2", "name": "Plan 2", "actions": []},
            ],
        }
    )
    schedule = runtime.repository.get_current()
    assert schedule is not None

    runtime._status.state = "running"
    runtime._phase = "plan"
    runtime._step_index = 0

    runtime._advance_step_locked(schedule, manual=True)
    assert runtime.status()["current_step_name"] == "Plan 2"
    assert any(item == "Moved to next step" for item in runtime.status()["event_log"])

    moved_count_before = sum(1 for item in runtime.status()["event_log"] if item == "Moved to next step")
    runtime._advance_step_locked(schedule, manual=True)
    moved_count_after = sum(1 for item in runtime.status()["event_log"] if item == "Moved to next step")

    assert runtime.status()["state"] == "completed"
    assert moved_count_after == moved_count_before



def test_navigation_move_previous_cross_phase_and_no_previous(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())
    runtime.load_schedule(
        {
            "id": "nav-prev",
            "name": "Nav Prev",
            "setup_steps": [{"id": "s1", "name": "Setup 1", "actions": []}],
            "plan_steps": [{"id": "p1", "name": "Plan 1", "actions": []}],
        }
    )
    schedule = runtime.repository.get_current()
    assert schedule is not None

    runtime._phase = "plan"
    runtime._step_index = 0

    assert runtime._move_previous_locked(schedule) is True
    assert runtime.status()["phase"] == "setup"
    assert runtime.status()["current_step_name"] == "Setup 1"

    runtime._phase = "setup"
    runtime._step_index = 0
    assert runtime._move_previous_locked(schedule) is False


def test_navigation_move_previous_within_same_phase(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path, control=FakeControlClient(values={}), data=FakeDataClient())
    runtime.load_schedule(
        {
            "id": "nav-prev-same-phase",
            "name": "Nav Prev Same Phase",
            "plan_steps": [
                {"id": "p1", "name": "Plan 1", "actions": []},
                {"id": "p2", "name": "Plan 2", "actions": []},
            ],
        }
    )
    schedule = runtime.repository.get_current()
    assert schedule is not None

    runtime._phase = "plan"
    runtime._step_index = 1

    assert runtime._move_previous_locked(schedule) is True
    assert runtime._step_index == 0
    assert runtime.status()["current_step_name"] == "Plan 1"
