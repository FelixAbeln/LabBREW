from __future__ import annotations

import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from Services.data_service.runtime import DataRecordingRuntime


class FakeBackend:
    def __init__(self, *, connected: bool = True, snapshot: dict | None = None, values: dict | None = None) -> None:
        self._connected = connected
        self._snapshot = dict(snapshot or {})
        self._values = dict(values or {})

    def connected(self) -> bool:
        return self._connected

    def full_snapshot(self) -> dict:
        return dict(self._snapshot)

    def get_value(self, name: str):
        return self._values.get(name)


def _runtime(backend: FakeBackend) -> DataRecordingRuntime:
    runtime = DataRecordingRuntime()
    runtime.backend = backend
    return runtime


def test_setup_measurement_reports_missing_parameters_warning(tmp_path: Path) -> None:
    runtime = _runtime(FakeBackend(snapshot={"available.temp": 20.0}))

    result = runtime.setup_measurement(
        parameters=["available.temp", "missing.temp"],
        hz=5.0,
        output_dir=str(tmp_path),
        output_format="jsonl",
        session_name="warning-session",
    )

    assert result["ok"] is True
    assert result["output_format"] == "jsonl"
    assert any("missing.temp" in warning for warning in result["warnings"])


def test_runtime_records_samples_tracks_missing_parameters_and_finalizes_archive(tmp_path: Path) -> None:
    extra_file = tmp_path / "notes.txt"
    extra_file.write_text("sidecar", encoding="utf-8")
    runtime = _runtime(FakeBackend(snapshot={"temp": 20.0}, values={"temp": 21.5}))

    setup = runtime.setup_measurement(
        parameters=["temp", "missing"],
        hz=5.0,
        output_dir=str(tmp_path),
        output_format="jsonl",
        session_name="archive-session",
        include_files=[str(extra_file)],
    )
    assert setup["ok"] is True
    assert runtime.measure_start()["ok"] is True
    assert runtime.take_loadstep(duration_seconds=0.5, loadstep_name="ls1")["ok"] is True

    runtime._record_sample()
    runtime._active_loadsteps[0].timestamp = datetime.now() - timedelta(seconds=1)
    runtime._check_loadsteps()
    result = runtime.measure_stop()

    archive_path = Path(result["archive_file"])
    assert result["ok"] is True
    assert result["samples_recorded"] == 1
    assert result["completed_loadsteps"] == 1
    assert result["missing_parameters"] == ["missing"]
    assert archive_path.exists()

    with zipfile.ZipFile(archive_path) as zf:
        names = sorted(zf.namelist())
    assert names == ["archive-session.jsonl", "archive-session.loadsteps.jsonl", "notes.txt"]
    assert not (tmp_path / "archive-session.jsonl").exists()
    assert not (tmp_path / "archive-session.loadsteps.jsonl").exists()


def test_archive_list_resolve_and_delete_cycle(tmp_path: Path) -> None:
    archive_path = tmp_path / "session.archive.zip"
    archive_path.write_bytes(b"PK\x03\x04")
    runtime = _runtime(FakeBackend())
    runtime.config = type("Config", (), {"output_dir": str(tmp_path)})()

    listed = runtime.list_archives(output_dir=str(tmp_path))
    resolved = runtime.resolve_archive_path(archive_name="session.archive.zip", output_dir=str(tmp_path))
    deleted = runtime.delete_archive(archive_name="session.archive.zip", output_dir=str(tmp_path))

    assert listed["ok"] is True
    assert listed["archives"][0]["name"] == "session.archive.zip"
    assert resolved == {
        "ok": True,
        "name": "session.archive.zip",
        "path": str(archive_path),
        "output_dir": str(tmp_path),
    }
    assert deleted == {"ok": True, "deleted": "session.archive.zip"}
    assert not archive_path.exists()


def test_resolve_archive_path_rejects_invalid_names(tmp_path: Path) -> None:
    runtime = _runtime(FakeBackend())

    result = runtime.resolve_archive_path(archive_name="../bad.zip", output_dir=str(tmp_path))

    assert result["ok"] is False
    assert "must end with '.archive.zip'" in result["error"]


def test_setup_measurement_validation_and_backend_guardrails(tmp_path: Path) -> None:
    runtime = _runtime(FakeBackend(connected=False))

    assert runtime.setup_measurement(parameters=["x"], hz=0.5, output_dir=str(tmp_path))["ok"] is False
    assert runtime.setup_measurement(parameters=[], hz=10.0, output_dir=str(tmp_path))["ok"] is False
    assert runtime.setup_measurement(parameters=["x"], hz=10.0, output_dir=str(tmp_path))["ok"] is False


def test_setup_measurement_empty_snapshot_and_parquet_fallback_warning(tmp_path: Path, monkeypatch) -> None:
    runtime = _runtime(FakeBackend(snapshot={}, values={"x": 1.0}))
    monkeypatch.setattr("Services.data_service.runtime.importlib.util.find_spec", lambda _name: None)

    result = runtime.setup_measurement(
        parameters=["x"],
        hz=5.0,
        output_dir=str(tmp_path),
        output_format="parquet",
        session_name="fallback-session",
    )

    assert result["ok"] is True
    assert result["output_format"] == "jsonl"
    assert any("snapshot is currently empty" in warning for warning in result["warnings"])
    assert any("pyarrow is not installed" in warning for warning in result["warnings"])


def test_measure_start_stop_and_loadstep_error_paths(tmp_path: Path) -> None:
    runtime = _runtime(FakeBackend(snapshot={"x": 1.0}, values={"x": 1.0}))

    assert runtime.measure_start()["ok"] is False
    assert runtime.measure_stop()["ok"] is False
    assert runtime.take_loadstep(duration_seconds=1.0)["ok"] is False

    setup = runtime.setup_measurement(
        parameters=["x"],
        hz=10.0,
        output_dir=str(tmp_path),
        output_format="jsonl",
        session_name="error-paths",
    )
    assert setup["ok"] is True

    assert runtime.measure_start()["ok"] is True
    assert runtime.measure_start()["ok"] is False
    assert runtime.take_loadstep(duration_seconds=0.0)["ok"] is False


def test_measure_stop_without_writer_returns_basic_success(tmp_path: Path) -> None:
    runtime = _runtime(FakeBackend(snapshot={"x": 1.0}, values={"x": 2.0}))
    runtime.setup_measurement(
        parameters=["x"],
        hz=2.0,
        output_dir=str(tmp_path),
        output_format="jsonl",
        session_name="no-writer",
    )
    runtime.measure_start()
    runtime._file_writer = None

    stopped = runtime.measure_stop()
    assert stopped == {"ok": True, "message": "Recording stopped"}


def test_recovery_sweep_archives_leftover_session_files(tmp_path: Path) -> None:
    runtime = _runtime(FakeBackend())
    measurement_file = tmp_path / "crash-session.jsonl"
    loadsteps_file = tmp_path / "crash-session.loadsteps.jsonl"
    run_log_file = tmp_path / "crash-session.run.log"
    schedule_file = tmp_path / "crash-session.schedule.json"
    recipe_file = tmp_path / "crash-session.recipe.json"
    measurement_file.write_text('{"value": 1}\n', encoding="utf-8")
    loadsteps_file.write_text('{"step": "a"}\n', encoding="utf-8")
    run_log_file.write_text("run log line\n", encoding="utf-8")
    schedule_file.write_text('{"name": "schedule-a"}\n', encoding="utf-8")
    recipe_file.write_text('{"name": "recipe-a"}\n', encoding="utf-8")

    result = runtime._recover_unarchived_outputs(output_dir=str(tmp_path))

    archive_path = tmp_path / "crash-session.archive.zip"
    assert result["ok"] is True
    assert str(archive_path) in result["recovered_archives"]
    assert archive_path.exists()
    assert not measurement_file.exists()
    assert not loadsteps_file.exists()
    assert not run_log_file.exists()
    assert not schedule_file.exists()
    assert not recipe_file.exists()

    with zipfile.ZipFile(archive_path) as zf:
        assert sorted(zf.namelist()) == [
            "crash-session.jsonl",
            "crash-session.loadsteps.jsonl",
            "crash-session.recipe.json",
            "crash-session.run.log",
            "crash-session.schedule.json",
        ]


def test_recovery_sweep_skips_when_archive_already_exists(tmp_path: Path) -> None:
    runtime = _runtime(FakeBackend())
    measurement_file = tmp_path / "existing-session.jsonl"
    archive_path = tmp_path / "existing-session.archive.zip"
    measurement_file.write_text('{"value": 2}\n', encoding="utf-8")
    archive_path.write_bytes(b"PK\x03\x04")

    result = runtime._recover_unarchived_outputs(output_dir=str(tmp_path))

    assert result["ok"] is True
    assert result["recovered_archives"] == []
    assert result["skipped_sessions"] == ["existing-session"]
    assert measurement_file.exists()


def test_recovery_sweep_archives_session_without_measurement_file(tmp_path: Path) -> None:
    runtime = _runtime(FakeBackend())
    loadsteps_file = tmp_path / "no-main.loadsteps.parquet"
    run_log_file = tmp_path / "no-main.run.log"
    schedule_file = tmp_path / "no-main.schedule.json"
    loadsteps_file.write_text("stub", encoding="utf-8")
    run_log_file.write_text("run log line\n", encoding="utf-8")
    schedule_file.write_text('{"name": "schedule-no-main"}\n', encoding="utf-8")

    result = runtime._recover_unarchived_outputs(output_dir=str(tmp_path))

    archive_path = tmp_path / "no-main.archive.zip"
    assert result["ok"] is True
    assert str(archive_path) in result["recovered_archives"]
    assert archive_path.exists()
    assert not loadsteps_file.exists()
    assert not run_log_file.exists()
    assert not schedule_file.exists()

    with zipfile.ZipFile(archive_path) as zf:
        assert sorted(zf.namelist()) == [
            "no-main.loadsteps.parquet",
            "no-main.run.log",
            "no-main.schedule.json",
        ]