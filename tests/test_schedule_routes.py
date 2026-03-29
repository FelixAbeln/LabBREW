from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Services.schedule_service.api import routes_schedule


class StubRuntime:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    def get_schedule(self):
        self.calls.append(("get_schedule", None))
        return {"schedule": {"id": "x"}}

    def load_schedule(self, payload: dict):
        self.calls.append(("load_schedule", payload))
        return {"ok": True, "loaded": payload}

    def clear_schedule(self):
        self.calls.append(("clear_schedule", None))
        return {"ok": True}

    def start_run(self):
        self.calls.append(("start_run", None))
        return {"ok": True}

    def pause_run(self):
        self.calls.append(("pause_run", None))
        return {"ok": True}

    def resume_run(self):
        self.calls.append(("resume_run", None))
        return {"ok": True}

    def stop_run(self):
        self.calls.append(("stop_run", None))
        return {"ok": True}

    def next_step(self):
        self.calls.append(("next_step", None))
        return {"ok": True}

    def previous_step(self):
        self.calls.append(("previous_step", None))
        return {"ok": True}

    def status(self):
        self.calls.append(("status", None))
        return {"state": "idle"}


def _client(runtime: StubRuntime | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(routes_schedule.router)
    if runtime is not None:
        routes_schedule.set_runtime(runtime)
    return TestClient(app)


def test_schedule_requires_runtime() -> None:
    response = _client().get("/schedule")
    assert response.status_code == 503


def test_schedule_put_delegates_payload() -> None:
    runtime = StubRuntime()
    payload = {"id": "test-schedule", "plan_steps": []}

    response = _client(runtime).put("/schedule", json=payload)
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert ("load_schedule", payload) in runtime.calls


def test_schedule_start_pause_resume_stop() -> None:
    runtime = StubRuntime()
    client = _client(runtime)

    assert client.post("/schedule/start").status_code == 200
    assert client.post("/schedule/pause").status_code == 200
    assert client.post("/schedule/resume").status_code == 200
    assert client.post("/schedule/stop").status_code == 200

    called = [name for name, _ in runtime.calls]
    assert "start_run" in called
    assert "pause_run" in called
    assert "resume_run" in called
    assert "stop_run" in called


def test_schedule_status() -> None:
    runtime = StubRuntime()
    response = _client(runtime).get("/schedule/status")
    assert response.status_code == 200
    assert response.json() == {"state": "idle"}
