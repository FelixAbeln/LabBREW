from __future__ import annotations

import base64
import zipfile
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

from Services.data_service.runtime import DataRecordingRuntime


class FakeBackend:
    def __init__(
        self,
        *,
        connected: bool = True,
        snapshot: dict | None = None,
        values: dict | None = None,
        describe_result: dict | None = None,
        describe_raises: Exception | None = None,
    ) -> None:
        self._connected = connected
        self._snapshot = dict(snapshot or {})
        self._values = dict(values or {})
        self._describe_result = describe_result  # None = not configured
        self._describe_raises = describe_raises

    def connected(self) -> bool:
        return self._connected

    def full_snapshot(self) -> dict:
        return dict(self._snapshot)

    def snapshot(self, names: list[str]) -> dict:
        data = dict(self._snapshot)
        return {name: data.get(name) for name in names}

    def get_value(self, name: str):
        return self._values.get(name)

    def describe(self) -> dict:
        if self._describe_raises is not None:
            raise self._describe_raises
        return dict(self._describe_result) if self._describe_result is not None else {}

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
    effective_session = setup["session_name"]
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
    assert names == [f"{effective_session}.jsonl", f"{effective_session}.loadsteps.jsonl", "notes.txt"]
    assert not (tmp_path / f"{effective_session}.jsonl").exists()
    assert not (tmp_path / f"{effective_session}.loadsteps.jsonl").exists()


def test_archive_includes_inline_payload_members(tmp_path: Path) -> None:
    runtime = _runtime(FakeBackend(snapshot={"temp": 20.0}, values={"temp": 21.0}))
    package_json = '{"id":"pkg-1","name":"Scenario"}'
    setup = runtime.setup_measurement(
        parameters=["temp"],
        hz=5.0,
        output_dir=str(tmp_path),
        output_format="jsonl",
        session_name="inline-payload",
        include_payloads=[
            {
                "name": "scenario.package.snapshot.json",
                "media_type": "application/json",
                "content_b64": base64.b64encode(package_json.encode("utf-8")).decode("ascii"),
            }
        ],
    )

    assert setup["ok"] is True
    effective_session = setup["session_name"]
    assert runtime.measure_start()["ok"] is True
    runtime._record_sample()
    result = runtime.measure_stop()
    archive_path = Path(result["archive_file"])

    assert result["ok"] is True
    with zipfile.ZipFile(archive_path) as zf:
        names = sorted(zf.namelist())
        payload = zf.read("scenario.package.snapshot.json").decode("utf-8")

    assert f"{effective_session}.jsonl" in names
    assert f"{effective_session}.loadsteps.jsonl" in names
    assert "scenario.package.snapshot.json" in names
    assert payload == package_json


def test_archive_auto_includes_parameterdb_runtime_context_payloads(tmp_path: Path) -> None:
    class BackendWithRuntimeContext(FakeBackend):
        def export_snapshot(self) -> dict:
            return {
                "format_version": 1,
                "parameters": {
                    "temp": {
                        "value": 21.0,
                        "config": {"timeshift": 1.25},
                    }
                },
            }

        def graph_info(self) -> dict:
            return {
                "scan_order": ["temp"],
                "dependencies": {"temp": []},
                "write_targets": {"temp": []},
                "warnings": [],
            }

        def describe(self) -> dict:
            return {"service": "parameterdb", "status": "ok"}

    runtime = _runtime(BackendWithRuntimeContext(snapshot={"temp": 20.0}, values={"temp": 21.0}))
    setup = runtime.setup_measurement(
        parameters=["temp"],
        hz=5.0,
        output_dir=str(tmp_path),
        output_format="jsonl",
        session_name="runtime-context",
    )

    assert setup["ok"] is True
    effective_session = setup["session_name"]
    assert runtime.measure_start()["ok"] is True
    runtime._record_sample()
    result = runtime.measure_stop()
    archive_path = Path(result["archive_file"])

    assert result["ok"] is True
    with zipfile.ZipFile(archive_path) as zf:
        names = sorted(zf.namelist())
        exported_snapshot = zf.read("parameterdb.export_snapshot.json").decode("utf-8")

    assert f"{effective_session}.jsonl" in names
    assert f"{effective_session}.loadsteps.jsonl" in names
    assert "parameterdb.export_snapshot.json" in names
    assert "parameterdb.graph_info.json" in names
    assert "parameterdb.describe.json" in names
    assert '"timeshift": 1.25' in exported_snapshot


def test_setup_measurement_remaps_session_scoped_include_file_to_stamped_name(
    tmp_path: Path,
) -> None:
    runtime = _runtime(FakeBackend(snapshot={"temp": 20.0}, values={"temp": 21.0}))
    requested_log = tmp_path / "lager-1h-test-plan.run.log"

    setup = runtime.setup_measurement(
        parameters=["temp"],
        hz=5.0,
        output_dir=str(tmp_path),
        output_format="jsonl",
        session_name="lager-1h-test-plan",
        include_files=[str(requested_log)],
    )

    assert setup["ok"] is True
    effective_session = setup["session_name"]
    effective_log = tmp_path / f"{effective_session}.run.log"
    assert setup["include_files"] == [str(effective_log)]

    effective_log.write_text("line1\n", encoding="utf-8")
    assert runtime.measure_start()["ok"] is True
    runtime._record_sample()
    stopped = runtime.measure_stop()

    archive_path = Path(stopped["archive_file"])
    assert stopped["ok"] is True
    with zipfile.ZipFile(archive_path) as zf:
        names = sorted(zf.namelist())

    assert f"{effective_session}.run.log" in names
    assert not effective_log.exists()


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
    assert list(tmp_path.glob("no-main.loadsteps.parquet.corrupt.*"))

    with zipfile.ZipFile(archive_path) as zf:
        assert sorted(zf.namelist()) == [
            "no-main.run.log",
            "no-main.schedule.json",
        ]


def test_view_archive_parses_measurement_and_loadsteps_jsonl(tmp_path: Path) -> None:
    runtime = _runtime(FakeBackend())
    runtime.config = type("Config", (), {"output_dir": str(tmp_path)})()
    archive_path = tmp_path / "session-a.archive.zip"

    measurement_rows = "\n".join([
        '{"timestamp": 1000.0, "datetime": "2026-04-09T12:00:00", "data": {"temp": 20.1, "ph": 5.2}}',
        '{"timestamp": 1001.0, "datetime": "2026-04-09T12:00:01", "data": {"temp": 20.4, "ph": 5.3}}',
        "",
    ])
    loadstep_rows = "\n".join([
        '{"name": "ls1", "duration_seconds": 30, "timestamp": "2026-04-09T12:00:30", "average": {"temp": 20.25}}',
        "",
    ])

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("session-a.jsonl", measurement_rows)
        zf.writestr("session-a.loadsteps.jsonl", loadstep_rows)

    viewed = runtime.view_archive(archive_name="session-a.archive.zip", output_dir=str(tmp_path), max_points=2)

    assert viewed["ok"] is True
    assert viewed["archive"]["name"] == "session-a.archive.zip"
    assert viewed["measurement"]["format"] == "jsonl"
    assert viewed["measurement"]["sample_count"] == 2
    assert viewed["measurement"]["parameters"] == ["ph", "temp"]
    assert len(viewed["measurement"]["samples"]) == 2
    assert viewed["loadsteps"]["count"] == 1
    assert viewed["loadsteps"]["items"][0]["name"] == "ls1"


def test_measure_stop_recovers_corrupt_parquet_to_jsonl_archive(tmp_path: Path) -> None:
    class _BrokenParquetWriter:
        sample_count = 1

        def __init__(self, path: Path) -> None:
            self.path = path

        def finalize(self) -> str:
            # Looks like parquet at the head but missing footer marker.
            self.path.write_bytes(b"PAR1BROKEN")
            return str(self.path)

    runtime = _runtime(FakeBackend(snapshot={"temp": 20.0}, values={"temp": 21.5}))
    setup = runtime.setup_measurement(
        parameters=["temp"],
        hz=2.0,
        output_dir=str(tmp_path),
        output_format="jsonl",
        session_name="repair-session",
    )
    assert setup["ok"] is True
    effective_session = setup["session_name"]
    assert runtime.measure_start()["ok"] is True

    runtime._record_sample()
    runtime.config.output_format = "parquet"
    runtime._measurement_data = deque(runtime._measurement_data, maxlen=10000)
    runtime._file_writer = _BrokenParquetWriter(tmp_path / "repair-session.parquet")

    stopped = runtime.measure_stop()
    assert stopped["ok"] is True
    assert stopped["archive_file"]

    archive_path = Path(stopped["archive_file"])
    with zipfile.ZipFile(archive_path) as zf:
        names = sorted(zf.namelist())

    assert f"{effective_session}.jsonl" in names
    assert any("Recovered measurement by writing JSONL fallback" in warning for warning in stopped["warnings"])
    assert list(tmp_path.glob("repair-session.parquet.corrupt.*"))


def test_recovery_sweep_quarantines_unrepairable_corrupt_parquet(tmp_path: Path) -> None:
    runtime = _runtime(FakeBackend())
    broken = tmp_path / "broken-session.parquet"
    broken.write_bytes(b"PAR1BROKEN")

    result = runtime._recover_unarchived_outputs(output_dir=str(tmp_path))

    assert result["ok"] is True
    assert result["recovered_archives"] == []
    assert not (tmp_path / "broken-session.archive.zip").exists()
    assert not broken.exists()
    assert list(tmp_path.glob("broken-session.parquet.corrupt.*"))


def test_recovery_sweep_repairs_corrupt_parquet_using_sibling_jsonl(tmp_path: Path) -> None:
    runtime = _runtime(FakeBackend())
    broken = tmp_path / "repaired-session.parquet"
    sibling = tmp_path / "repaired-session.jsonl"
    loadsteps = tmp_path / "repaired-session.loadsteps.jsonl"

    broken.write_bytes(b"PAR1BROKEN")
    sibling.write_text('{"timestamp": 1, "data": {"temp": 20.0}}\n', encoding="utf-8")
    loadsteps.write_text('{"name": "ls1", "average": {"temp": 20.0}}\n', encoding="utf-8")

    result = runtime._recover_unarchived_outputs(output_dir=str(tmp_path))

    archive_path = tmp_path / "repaired-session.archive.zip"
    assert result["ok"] is True
    assert str(archive_path) in result["recovered_archives"]
    assert archive_path.exists()
    assert not broken.exists()
    assert not sibling.exists()
    assert list(tmp_path.glob("repaired-session.parquet.corrupt.*"))

    with zipfile.ZipFile(archive_path) as zf:
        assert sorted(zf.namelist()) == [
            "repaired-session.jsonl",
            "repaired-session.loadsteps.jsonl",
        ]


# ---------------------------------------------------------------------------
# Validity-cache / _record_sample unit tests
# ---------------------------------------------------------------------------

def _setup_and_start(runtime: DataRecordingRuntime, tmp_path, parameters: list[str]) -> None:
    runtime.setup_measurement(
        parameters=parameters,
        hz=10.0,
        output_dir=str(tmp_path),
        output_format="jsonl",
        session_name="validity-test",
    )
    runtime.measure_start()


def test_record_sample_records_none_for_invalid_parameter_not_as_missing(tmp_path: Path) -> None:
    """An invalid parameter must be written as None, not tracked in missing_parameters."""
    backend = FakeBackend(
        snapshot={"valid.temp": 25.0, "bad.temp": 99.0},
        describe_result={
            "valid.temp": {"state": {"parameter_valid": True}},
            "bad.temp": {"state": {"parameter_valid": False}},
        },
    )
    runtime = _runtime(backend)
    _setup_and_start(runtime, tmp_path, ["valid.temp", "bad.temp"])

    runtime._refresh_validity_cache()
    runtime._record_sample()

    sample = runtime._measurement_data[-1]
    assert sample["data"]["valid.temp"] == 25.0, "valid parameter value should be preserved"
    assert sample["data"]["bad.temp"] is None, "invalid parameter should be recorded as None"
    assert "bad.temp" not in runtime._missing_parameters, "invalid param must not appear in missing_parameters"


def test_record_sample_preserves_values_for_all_valid_parameters(tmp_path: Path) -> None:
    """All valid parameters in the snapshot should pass through unchanged."""
    backend = FakeBackend(
        snapshot={"a": 1.0, "b": 2.0},
        describe_result={
            "a": {"state": {"parameter_valid": True}},
            "b": {"state": {}},  # no parameter_valid key → treated as valid
        },
    )
    runtime = _runtime(backend)
    _setup_and_start(runtime, tmp_path, ["a", "b"])

    runtime._refresh_validity_cache()
    runtime._record_sample()

    sample = runtime._measurement_data[-1]
    assert sample["data"]["a"] == 1.0
    assert sample["data"]["b"] == 2.0
    assert runtime._missing_parameters == set()


def test_record_sample_uses_stale_cache_when_describe_fails(tmp_path: Path) -> None:
    """If describe() raises, the existing cache is kept and recording continues."""
    backend = FakeBackend(
        snapshot={"x": 5.0},
        describe_result={"x": {"state": {"parameter_valid": True}}},
    )
    runtime = _runtime(backend)
    _setup_and_start(runtime, tmp_path, ["x"])

    # Prime the cache with a successful refresh.
    runtime._refresh_validity_cache()
    assert runtime._validity_cache.get("x") is True
    previous_refresh = runtime._validity_last_refresh

    # Now make describe() fail and attempt another refresh.
    backend._describe_raises = OSError("backend down")
    runtime._refresh_validity_cache()

    # Cache should still contain the previously fetched data.
    assert runtime._validity_cache.get("x") is True
    assert runtime._validity_last_refresh >= previous_refresh

    # Recording should still work correctly using the stale cache.
    runtime._record_sample()
    sample = runtime._measurement_data[-1]
    assert sample["data"]["x"] == 5.0


def test_record_sample_with_empty_describe_treats_all_params_as_valid(tmp_path: Path) -> None:
    """Empty describe result (e.g. backend not yet populated) should not null out values."""
    backend = FakeBackend(
        snapshot={"y": 7.0},
        describe_result={},
    )
    runtime = _runtime(backend)
    _setup_and_start(runtime, tmp_path, ["y"])

    runtime._refresh_validity_cache()
    assert runtime._validity_last_refresh > 0.0
    runtime._record_sample()

    sample = runtime._measurement_data[-1]
    # With an empty describe result, configured parameters are treated as valid
    # and cached as True, so the value should be passed through unchanged.
    assert sample["data"]["y"] == 7.0


def test_refresh_validity_cache_rate_limits_expected_failure_logs(tmp_path: Path, monkeypatch) -> None:
    backend = FakeBackend(
        snapshot={"x": 5.0},
        describe_raises=OSError("backend down"),
    )
    runtime = _runtime(backend)
    _setup_and_start(runtime, tmp_path, ["x"])

    messages: list[str] = []

    def _capture_print(*args, **_kwargs) -> None:
        messages.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr("builtins.print", _capture_print)
    monkeypatch.setattr(
        "Services.data_service.runtime._VALIDITY_REFRESH_FAILURE_LOG_INTERVAL_S",
        3600.0,
    )

    runtime._refresh_validity_cache()
    runtime._refresh_validity_cache()
    runtime._refresh_validity_cache()

    failures = [msg for msg in messages if "validity refresh failed (will retry)" in msg]
    assert len(failures) == 1


def test_refresh_validity_cache_logs_suppressed_count_on_periodic_reminder(monkeypatch) -> None:
    runtime = _runtime(FakeBackend())
    messages: list[str] = []

    def _capture_print(*args, **_kwargs) -> None:
        messages.append(" ".join(str(arg) for arg in args))

    timeline = iter([100.0, 101.0, 102.0, 106.0])

    monkeypatch.setattr("builtins.print", _capture_print)
    monkeypatch.setattr("Services.data_service.runtime.time.monotonic", lambda: next(timeline))
    monkeypatch.setattr(
        "Services.data_service.runtime._VALIDITY_REFRESH_FAILURE_LOG_INTERVAL_S",
        5.0,
    )

    runtime._log_validity_refresh_failure(OSError("backend down"))
    runtime._log_validity_refresh_failure(OSError("backend down"))
    runtime._log_validity_refresh_failure(OSError("backend down"))
    runtime._log_validity_refresh_failure(OSError("backend down"))

    failures = [msg for msg in messages if "validity refresh failed (will retry)" in msg]
    assert len(failures) == 2
    assert "3 similar failures suppressed" in failures[1]
