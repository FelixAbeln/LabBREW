from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Services.data_service.api import routes


class StubRuntime:
    def __init__(self):
        self.last_setup = None

    def setup_measurement(self, **kwargs):
        self.last_setup = kwargs
        return {"ok": True, "session_name": kwargs.get("session_name") or "session_a"}

    def measure_start(self):
        return {"ok": True, "message": "started"}

    def measure_stop(self):
        return {"ok": True, "message": "stopped"}

    def take_loadstep(self, **kwargs):
        return {"ok": True, **kwargs}

    def get_status(self):
        return {"backend_connected": True, "recording": False}

    def list_archives(self, **kwargs):
        return {"ok": True, "archives": [], "args": kwargs}

    def view_archive(self, **kwargs):
        return {"ok": True, "archive": {"name": kwargs.get("archive_name", "")}, "measurement": {}, "loadsteps": {}}

    def delete_archive(self, **kwargs):
        return {"ok": True, **kwargs}

    def resolve_archive_path(self, **kwargs):
        return {"ok": False, "error": "not found", **kwargs}


def _client(runtime: StubRuntime | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router)
    routes.set_runtime(None)
    if runtime is not None:
        routes.set_runtime(runtime)
    return TestClient(app)


def test_setup_requires_runtime() -> None:
    response = _client().post("/measurement/setup", json={"parameters": ["x"]})
    assert response.status_code == 500
    assert "runtime not initialized" in response.json()["detail"].lower()


def test_setup_delegates_runtime_arguments() -> None:
    runtime = StubRuntime()
    response = _client(runtime).post(
        "/measurement/setup",
        json={
            "parameters": ["brewcan.temperature.0"],
            "hz": 5,
            "output_dir": "tmp",
            "output_format": "csv",
            "session_name": "run_1",
            "include_files": ["a.txt"],
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert runtime.last_setup == {
        "parameters": ["brewcan.temperature.0"],
        "hz": 5.0,
        "output_dir": "tmp",
        "output_format": "csv",
        "session_name": "run_1",
        "include_files": ["a.txt"],
        "include_payloads": None,
    }


def test_setup_returns_400_when_runtime_rejects_request() -> None:
    runtime = StubRuntime()
    runtime.setup_measurement = lambda **_kwargs: {"ok": False, "error": "bad setup"}

    response = _client(runtime).post("/measurement/setup", json={"parameters": ["x"]})
    assert response.status_code == 400
    assert "bad setup" in response.json()["detail"]


def test_measure_start_requires_runtime_and_returns_400_on_failure() -> None:
    requires_runtime = _client().post("/measurement/start")
    assert requires_runtime.status_code == 500

    runtime = StubRuntime()
    runtime.measure_start = lambda: {"ok": False, "error": "not configured"}
    failed = _client(runtime).post("/measurement/start")
    assert failed.status_code == 400
    assert "not configured" in failed.json()["detail"]


def test_measure_stop_requires_runtime_and_returns_400_on_failure() -> None:
    requires_runtime = _client().post("/measurement/stop")
    assert requires_runtime.status_code == 500

    runtime = StubRuntime()
    runtime.measure_stop = lambda: {"ok": False, "error": "not recording"}
    failed = _client(runtime).post("/measurement/stop")
    assert failed.status_code == 400
    assert "not recording" in failed.json()["detail"]


def test_take_loadstep_requires_runtime_and_returns_400_on_failure() -> None:
    requires_runtime = _client().post("/loadstep/take", json={})
    assert requires_runtime.status_code == 500

    runtime = StubRuntime()
    runtime.take_loadstep = lambda **_kwargs: {"ok": False, "error": "no active session"}
    failed = _client(runtime).post("/loadstep/take", json={})
    assert failed.status_code == 400
    assert "no active session" in failed.json()["detail"]


def test_status_requires_runtime_and_returns_payload_when_available() -> None:
    requires_runtime = _client().get("/status")
    assert requires_runtime.status_code == 500

    runtime = StubRuntime()
    runtime.get_status = lambda: {"backend_connected": True, "recording": True, "note": "ok"}
    response = _client(runtime).get("/status")
    assert response.status_code == 200
    assert response.json()["note"] == "ok"


def test_archives_list_requires_runtime_and_returns_400_on_error() -> None:
    requires_runtime = _client().get("/archives")
    assert requires_runtime.status_code == 500

    runtime = StubRuntime()
    runtime.list_archives = lambda **_kwargs: {"ok": False}
    failed = _client(runtime).get("/archives")
    assert failed.status_code == 400
    assert "unknown error" in failed.json()["detail"].lower()


def test_delete_archive_requires_runtime_and_returns_404_on_error() -> None:
    requires_runtime = _client().delete("/archives/file.zip")
    assert requires_runtime.status_code == 500

    runtime = StubRuntime()
    runtime.delete_archive = lambda **_kwargs: {"ok": False, "error": "missing archive"}
    failed = _client(runtime).delete("/archives/file.zip")
    assert failed.status_code == 404
    assert "missing archive" in failed.json()["detail"]


def test_view_archive_requires_runtime_and_handles_errors() -> None:
    requires_runtime = _client().get("/archives/view/a.zip")
    assert requires_runtime.status_code == 500

    runtime = StubRuntime()
    runtime.view_archive = lambda **_kwargs: {"ok": False, "error": "archive not found"}
    not_found = _client(runtime).get("/archives/view/a.zip")
    assert not_found.status_code == 404

    runtime.view_archive = lambda **_kwargs: {"ok": False, "error": "bad archive format"}
    invalid = _client(runtime).get("/archives/view/a.zip")
    assert invalid.status_code == 400


def test_view_archive_success() -> None:
    runtime = StubRuntime()
    response = _client(runtime).get(
        "/archives/view/session.archive.zip",
        params={"output_dir": "tmp", "max_points": 777},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["archive"]["name"] == "session.archive.zip"


def test_health_reports_unhealthy_without_runtime() -> None:
    response = _client().get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "unhealthy"


def test_download_archive_returns_404_when_runtime_cannot_resolve() -> None:
    runtime = StubRuntime()
    response = _client(runtime).get("/archives/download/missing.zip")
    assert response.status_code == 404


def test_download_archive_requires_runtime() -> None:
    response = _client().get("/archives/download/missing.zip")
    assert response.status_code == 500


def test_download_archive_streams_file(tmp_path) -> None:
    archive_path = tmp_path / "bundle.zip"
    archive_path.write_bytes(b"PK\x03\x04")

    runtime = StubRuntime()

    def _resolve_archive_path(**kwargs):
        return {"ok": True, "path": str(archive_path), "name": Path(kwargs["archive_name"]).name}

    runtime.resolve_archive_path = _resolve_archive_path

    response = _client(runtime).get("/archives/download/bundle.zip")
    assert response.status_code == 200
    assert response.content.startswith(b"PK")


def test_health_reports_connected_and_disconnected_runtime_states() -> None:
    healthy_runtime = StubRuntime()
    healthy_runtime.get_status = lambda: {"backend_connected": True, "recording": False}
    healthy = _client(healthy_runtime).get("/health")
    assert healthy.status_code == 200
    assert healthy.json()["status"] == "healthy"

    unhealthy_runtime = StubRuntime()
    unhealthy_runtime.get_status = lambda: {"backend_connected": False, "recording": False}
    unhealthy = _client(unhealthy_runtime).get("/health")
    assert unhealthy.status_code == 200
    assert unhealthy.json()["status"] == "unhealthy"
    assert "backend" in unhealthy.json()["reason"].lower()


def test_start_stop_loadstep_and_archive_operations_success_paths() -> None:
    runtime = StubRuntime()
    client = _client(runtime)

    start = client.post("/measurement/start")
    assert start.status_code == 200
    assert start.json()["ok"] is True

    stop = client.post("/measurement/stop")
    assert stop.status_code == 200
    assert stop.json()["ok"] is True

    loadstep = client.post("/loadstep/take", json={"duration_seconds": 12.5, "loadstep_name": "ls1", "parameters": ["x"]})
    assert loadstep.status_code == 200
    assert loadstep.json()["ok"] is True

    archives = client.get("/archives", params={"output_dir": "tmp", "limit": 10})
    assert archives.status_code == 200
    assert archives.json()["ok"] is True

    deleted = client.delete("/archives/archive.zip", params={"output_dir": "tmp"})
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True
