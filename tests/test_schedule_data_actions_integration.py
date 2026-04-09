from __future__ import annotations

import contextlib

import pytest

from tests.integration_helpers import (
    IntegrationApi,
    managed_test_parameters,
    skip_if_parameterdb_unreachable,
    skip_if_unreachable,
    utc_stamp,
    wait_until,
)

pytestmark = pytest.mark.integration

SCHEDULE_BASE = "http://127.0.0.1:8768"
DATA_BASE = "http://127.0.0.1:8769"


def _build_schedule(schedule_id: str, measurement_parameter: str) -> dict:
    return {
        "id": schedule_id,
        "name": "Schedule Data Actions Test",
        "setup_steps": [
            {
                "id": "setup-1",
                "name": "Start global measurement",
                "enabled": True,
                "actions": [
                    {
                        "kind": "global_measurement",
                        "value": "start",
                        "params": {
                            "parameters": [measurement_parameter],
                            "hz": 10.0,
                            "output_format": "jsonl",
                            "output_dir": "data/measurements",
                            "session_name": schedule_id,
                        },
                    }
                ],
                "wait": {"kind": "elapsed", "duration_s": 0.4},
            }
        ],
        "plan_steps": [
            {
                "id": "plan-1",
                "name": "Take loadstep",
                "enabled": True,
                "actions": [
                    {
                        "kind": "take_loadstep",
                        "duration_s": 1.0,
                        "params": {
                            "loadstep_name": "pytest_ls",
                            "parameters": [measurement_parameter],
                        },
                    }
                ],
                "wait": {"kind": "elapsed", "duration_s": 1.2},
            },
            {
                "id": "plan-2",
                "name": "Stop global measurement",
                "enabled": True,
                "actions": [
                    {
                        "kind": "global_measurement",
                        "value": "stop",
                        "params": {},
                    }
                ],
                "wait": {"kind": "elapsed", "duration_s": 0.2},
            },
        ],
    }


def _hard_reset(schedule_api: IntegrationApi, data_api: IntegrationApi) -> None:
    with contextlib.suppress(Exception):
        schedule_api.post("/schedule/stop")
    with contextlib.suppress(Exception):
        schedule_api.delete("/schedule")
    with contextlib.suppress(Exception):
        data_api.post("/measurement/stop")


@pytest.fixture
def live_apis():
    skip_if_unreachable(SCHEDULE_BASE, "/schedule/status")
    skip_if_unreachable(DATA_BASE, "/health")
    skip_if_parameterdb_unreachable()

    schedule_api = IntegrationApi(base_url=SCHEDULE_BASE)
    data_api = IntegrationApi(base_url=DATA_BASE)

    _hard_reset(schedule_api, data_api)
    yield schedule_api, data_api
    _hard_reset(schedule_api, data_api)


def test_schedule_data_actions_flow(live_apis) -> None:
    schedule_api, data_api = live_apis
    schedule_id = f"schedule-data-actions-{utc_stamp()}"
    parameter_name = f"pytest.schedule.data.{utc_stamp()}"

    with managed_test_parameters([
        {
            "name": parameter_name,
            "parameter_type": "static",
            "value": 21.5,
            "metadata": {"created_by": "pytest", "test": "schedule_data_actions"},
        }
    ]):
        load_result = schedule_api.put("/schedule", _build_schedule(schedule_id, parameter_name))
        assert load_result.get("ok") is True

        start_result = schedule_api.post("/schedule/start")
        assert start_result.get("ok") is True

        wait_until(
            lambda: data_api.get("/status") if data_api.get("/status").get("recording") else None,
            timeout_s=8.0,
            label="data recording started",
        )

        status_after_loadstep = wait_until(
            lambda: data_api.get("/status") if int(data_api.get("/status").get("completed_loadsteps_count", 0)) >= 1 else None,
            timeout_s=12.0,
            label="loadstep completed",
        )
        assert int(status_after_loadstep.get("completed_loadsteps_count", 0)) >= 1

        wait_until(
            lambda: data_api.get("/status") if not data_api.get("/status").get("recording") else None,
            timeout_s=12.0,
            label="data recording stopped",
        )

        final_schedule = wait_until(
            lambda: schedule_api.get("/schedule/status") if schedule_api.get("/schedule/status").get("state") == "completed" else None,
            timeout_s=12.0,
            label="schedule completed",
        )

        event_log = final_schedule.get("event_log", [])
        assert any("Start global measurement" in entry for entry in event_log)
        assert any("Take loadstep" in entry for entry in event_log)
        assert any("Stop global measurement" in entry for entry in event_log)
