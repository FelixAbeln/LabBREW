from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import threading
import builtins
import types

import pytest

import Services.data_service.runtime as runtime_module
from Services.data_service.runtime import DataRecordingRuntime, LoadstepConfig, MeasurementConfig


class _Backend:
    def connected(self) -> bool:
        return True

    def full_snapshot(self) -> dict:
        return {"x": 1.0}

    def get_value(self, _name: str):
        return 1.0


def _runtime(tmp_path: Path) -> DataRecordingRuntime:
    runtime = DataRecordingRuntime()
    runtime.backend = _Backend()
    runtime.config = MeasurementConfig(parameters=["x"], output_dir=str(tmp_path), session_name="sess", output_format="jsonl")
    runtime._loadsteps_archive_path = str(tmp_path / "sess.loadsteps.jsonl")
    runtime._loadsteps_archive_format = "jsonl"
    return runtime


def test_append_loadstep_archive_csv_and_fallback_formats(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    record = {
        "name": "ls,1",
        "duration_seconds": 1.2,
        "average": {"x": 2.0},
        "timestamp": "2026-01-01T00:00:00",
    }

    runtime._loadsteps_archive_format = "csv"
    runtime._loadsteps_archive_path = str(tmp_path / "ls.csv")
    runtime._append_loadstep_archive_record(record)
    csv_text = (tmp_path / "ls.csv").read_text(encoding="utf-8")
    assert '"ls,1"' in csv_text

    runtime._loadsteps_archive_format = "other"
    runtime._loadsteps_archive_path = str(tmp_path / "ls.other")
    runtime._append_loadstep_archive_record(record)
    assert "ls,1" in (tmp_path / "ls.other").read_text(encoding="utf-8")


def test_append_loadstep_archive_parquet_without_pyarrow_is_tolerated(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime._loadsteps_archive_format = "parquet"
    runtime._loadsteps_archive_path = str(tmp_path / "ls.parquet")

    runtime._append_loadstep_archive_record({"name": "ls", "duration_seconds": 1.0, "average": {}, "timestamp": "t"})


def test_append_loadstep_archive_parquet_existing_table_concat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(tmp_path)
    runtime._loadsteps_archive_format = "parquet"
    path = tmp_path / "ls.parquet"
    path.write_text("old", encoding="utf-8")
    runtime._loadsteps_archive_path = str(path)

    written = {}

    pyarrow_mod = types.ModuleType("pyarrow")

    class _TableFactory:
        @staticmethod
        def from_pylist(_rows):
            return "new"

    pyarrow_mod.Table = _TableFactory
    pyarrow_mod.concat_tables = lambda items: "combined" if items == ["existing", "new"] else "bad"

    pyarrow_parquet_mod = types.ModuleType("pyarrow.parquet")
    pyarrow_parquet_mod.read_table = lambda _path: "existing"
    pyarrow_parquet_mod.write_table = lambda table, out: written.update({"table": table, "out": out})
    pyarrow_mod.parquet = pyarrow_parquet_mod

    monkeypatch.setitem(__import__("sys").modules, "pyarrow", pyarrow_mod)
    monkeypatch.setitem(__import__("sys").modules, "pyarrow.parquet", pyarrow_parquet_mod)

    runtime._append_loadstep_archive_record({"name": "ls", "duration_seconds": 1.0, "average": {}, "timestamp": "t"})

    assert written["table"] == "combined"
    assert written["out"] == str(path)


def test_append_loadstep_archive_write_errors_are_tolerated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(tmp_path)
    runtime._loadsteps_archive_format = "csv"

    def _raise_open(*_args, **_kwargs):
        raise OSError("open failed")

    monkeypatch.setattr("builtins.open", _raise_open)
    runtime._append_loadstep_archive_record({"name": "ls", "duration_seconds": 1.0, "average": {}, "timestamp": "t"})


def test_initialize_loadstep_archive_file_modes_and_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(tmp_path)

    runtime._loadsteps_archive_format = "jsonl"
    runtime._initialize_loadstep_archive_file()
    assert (tmp_path / "sess.loadsteps.jsonl").exists()

    runtime._loadsteps_archive_format = "csv"
    runtime._loadsteps_archive_path = str(tmp_path / "sess.loadsteps.csv")
    runtime._initialize_loadstep_archive_file()
    assert "name,duration_seconds" in (tmp_path / "sess.loadsteps.csv").read_text(encoding="utf-8")

    parquet_path = tmp_path / "sess.loadsteps.parquet"
    parquet_path.write_text("x", encoding="utf-8")
    runtime._loadsteps_archive_format = "parquet"
    runtime._loadsteps_archive_path = str(parquet_path)
    runtime._initialize_loadstep_archive_file()
    assert not parquet_path.exists()

    runtime._loadsteps_archive_format = "unknown"
    runtime._loadsteps_archive_path = str(tmp_path / "sess.loadsteps.unknown")
    runtime._initialize_loadstep_archive_file()
    assert (tmp_path / "sess.loadsteps.unknown").exists()

    monkeypatch.setattr(runtime, "_atomic_write_text_file", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("boom")))
    runtime._initialize_loadstep_archive_file()

    runtime._loadsteps_archive_path = ""
    runtime._initialize_loadstep_archive_file()


def test_atomic_write_text_file_cleans_tmp_on_replace_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(tmp_path)

    def _raise_replace(*_args, **_kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr("Services.data_service.runtime.os.replace", _raise_replace)

    with pytest.raises(OSError):
        runtime._atomic_write_text_file(str(tmp_path / "out.txt"), "x")

    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_text_file_fsync_dir_and_cleanup_unlink_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(tmp_path)
    out = tmp_path / "ok.txt"

    original_open = runtime_module.os.open

    def _open_selective(path, flags, *args, **kwargs):
        if flags == runtime_module.os.O_RDONLY:
            return 123
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr("Services.data_service.runtime.os.open", _open_selective)
    monkeypatch.setattr("Services.data_service.runtime.os.close", lambda _fd: None)
    monkeypatch.setattr("Services.data_service.runtime.os.fsync", lambda _fd: None)
    runtime._atomic_write_text_file(str(out), "ok")
    assert out.read_text(encoding="utf-8") == "ok"

    monkeypatch.setattr("Services.data_service.runtime.os.replace", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("replace failed")))
    monkeypatch.setattr("Services.data_service.runtime.os.unlink", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unlink failed")))
    with pytest.raises(OSError):
        runtime._atomic_write_text_file(str(tmp_path / "boom.txt"), "x")


def test_build_session_archive_helpers_and_delete_error_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(tmp_path)

    runtime.config = None
    assert runtime._build_session_archive(measurement_file="a", loadsteps_file="b", extra_files=[])["archive_path"] is None

    runtime.config = MeasurementConfig(parameters=["x"], output_dir=str(tmp_path), session_name="sess", output_format="jsonl")
    assert runtime._build_session_archive(measurement_file="missing", loadsteps_file="missing2", extra_files=["missing"])["archive_path"] is None

    m = tmp_path / "m.jsonl"
    l = tmp_path / "l.jsonl"
    x = tmp_path / "x.txt"
    m.write_text("m", encoding="utf-8")
    l.write_text("l", encoding="utf-8")
    x.write_text("x", encoding="utf-8")

    removed = []
    _real_remove = __import__("os").remove

    def _remove_with_one_error(path):
        if str(path).endswith("x.txt"):
            raise OSError("cannot remove")
        removed.append(str(path))
        return _real_remove(path)

    monkeypatch.setattr("Services.data_service.runtime.os.remove", _remove_with_one_error)
    archive = runtime._build_session_archive(measurement_file=str(m), loadsteps_file=str(l), extra_files=[str(x), str(m)])
    assert archive["archive_path"]
    assert "m.jsonl" in archive["members"]

    status = runtime._build_active_loadstep_status(
        LoadstepConfig(name="ls", parameters=["x"], duration_seconds=5.0, timestamp=datetime.now() - timedelta(seconds=10)),
        datetime.now(),
    )
    assert status["remaining_seconds"] == 0.0

    assert runtime._resolve_output_dir(" ") == str(tmp_path)
    assert runtime._resolve_output_dir("./data")

    with pytest.raises(ValueError):
        runtime._safe_archive_name("")
    with pytest.raises(ValueError):
        runtime._safe_archive_name("a.zip")

    # list_archives stat failure + non-file filtering
    bad = tmp_path / "bad.archive.zip"
    bad.write_text("b", encoding="utf-8")
    (tmp_path / "not_archive.txt").write_text("n", encoding="utf-8")
    (tmp_path / "dir.archive.zip").mkdir()
    monkeypatch.setattr("Services.data_service.runtime.os.stat", lambda _path: (_ for _ in ()).throw(OSError("stat fail")))
    listed = runtime.list_archives(output_dir=str(tmp_path), limit=0)
    assert listed["ok"] is True

    # delete path when os.remove fails
    monkeypatch.setattr(runtime, "resolve_archive_path", lambda **_kwargs: {"ok": True, "path": "x", "name": "x.archive.zip"})
    monkeypatch.setattr("Services.data_service.runtime.os.remove", lambda _path: (_ for _ in ()).throw(OSError("nope")))
    deleted = runtime.delete_archive(archive_name="x.archive.zip", output_dir=str(tmp_path))
    assert deleted["ok"] is False

    monkeypatch.setattr(runtime, "resolve_archive_path", lambda **_kwargs: {"ok": False, "error": "missing"})
    unresolved = runtime.delete_archive(archive_name="x.archive.zip", output_dir=str(tmp_path))
    assert unresolved == {"ok": False, "error": "missing"}


def test_build_session_archive_raises_and_cleans_temp_on_zip_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(tmp_path)
    runtime.config = MeasurementConfig(parameters=["x"], output_dir=str(tmp_path), session_name="sess", output_format="jsonl")

    m = tmp_path / "m.jsonl"
    m.write_text("m", encoding="utf-8")

    class _BrokenZip:
        def __init__(self, *args, **kwargs):
            self.path = args[0]

        def __enter__(self):
            raise RuntimeError("zip failed")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("Services.data_service.runtime.zipfile.ZipFile", _BrokenZip)
    with pytest.raises(RuntimeError):
        runtime._build_session_archive(measurement_file=str(m), loadsteps_file=str(m), extra_files=[])


def test_get_status_with_and_without_config(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime._recording = True
    runtime._measurement_data.extend([{"x": 1}, {"x": 2}])
    runtime._active_loadsteps = [LoadstepConfig(name="ls", parameters=["x"], duration_seconds=1.0)]
    runtime._completed_loadsteps = [{"name": "done"}]
    runtime._missing_parameters = {"x"}
    runtime._setup_warnings = ["warn"]

    status = runtime.get_status()
    assert status["recording"] is True
    assert status["samples_recorded"] == 2
    assert status["active_loadstep_names"] == ["ls"]

    runtime.config = None
    status2 = runtime.get_status()
    assert status2["config"] is None

    runtime.config = MeasurementConfig(parameters=["x"], output_dir=str(tmp_path), session_name="sess", output_format="jsonl")
    runtime.config.output_dir = ""
    assert runtime._resolve_output_dir(None).replace("\\", "/").endswith("data/measurements")


def test_stop_setup_measurement_and_loadstep_remaining_branches(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    runtime._running = True
    runtime.stop()
    assert runtime._running is False

    runtime._recording = True
    busy = runtime.setup_measurement(parameters=["x"], output_dir=str(tmp_path))
    assert busy["ok"] is False
    runtime._recording = False

    setup = runtime.setup_measurement(parameters=["x"], hz=2.0, output_dir=str(tmp_path), session_name="")
    assert setup["ok"] is True
    assert setup["session_name"].startswith("measurement_")

    runtime._recording = True
    taken = runtime.take_loadstep(duration_seconds=1.0, loadstep_name="")
    assert taken["ok"] is True
    assert taken["loadstep_name"].startswith("loadstep_")


def test_measure_stop_archive_error_and_finalize_active_loadstep(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(tmp_path)
    runtime.setup_measurement(parameters=["x"], hz=2.0, output_dir=str(tmp_path), session_name="s")
    runtime._recording = True

    class _Writer:
        sample_count = 3

        def finalize(self):
            p = tmp_path / "m.jsonl"
            p.write_text("m", encoding="utf-8")
            return str(p)

    runtime._file_writer = _Writer()
    runtime._active_loadsteps = [
        LoadstepConfig(name="ls", parameters=["x"], duration_seconds=1.0, timestamp=datetime.now())
    ]
    runtime._loadstep_averagers["ls"] = SimpleNamespace(get_average=lambda: {"x": 1.0})

    monkeypatch.setattr(runtime, "_build_session_archive", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("archive fail")))

    result = runtime.measure_stop()
    assert result["ok"] is True
    assert result["completed_loadsteps"] >= 1
    assert any("Archive build failed" in warning for warning in result["warnings"])


def test_record_sample_exception_and_no_archive_path_branch(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.config = MeasurementConfig(parameters=["x"], output_dir=str(tmp_path), session_name="sess", output_format="jsonl")

    class _BadBackend:
        def get_value(self, _name):
            raise RuntimeError("boom")

    runtime.backend = _BadBackend()
    runtime._record_sample()

    runtime._loadsteps_archive_path = ""
    runtime._append_loadstep_archive_record({"name": "ls"})


def test_archive_remaining_not_found_nonfile_and_tmp_cleanup_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(tmp_path)
    runtime.config = MeasurementConfig(parameters=["x"], output_dir=str(tmp_path), session_name="sess", output_format="jsonl")

    # Resolve-path valid name but missing file.
    missing = runtime.resolve_archive_path(archive_name="missing.archive.zip", output_dir=str(tmp_path))
    assert missing == {"ok": False, "error": "archive not found"}

    # list_archives should skip non-files with .archive.zip suffix.
    (tmp_path / "folder.archive.zip").mkdir()
    listed = runtime.list_archives(output_dir=str(tmp_path), limit=200)
    assert listed["ok"] is True

    # _build_session_archive exception cleanup where tmp exists and remove also errors.
    m = tmp_path / "m.jsonl"
    m.write_text("m", encoding="utf-8")
    tmp_archive = tmp_path / "sess.archive.zip.tmp"

    class _BrokenZip:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs

        def __enter__(self):
            raise RuntimeError("zip failed")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("Services.data_service.runtime.zipfile.ZipFile", _BrokenZip)
    monkeypatch.setattr("Services.data_service.runtime.os.path.exists", lambda p: str(p).endswith(".tmp"))
    monkeypatch.setattr("Services.data_service.runtime.os.remove", lambda _p: (_ for _ in ()).throw(OSError("remove failed")))

    with pytest.raises(RuntimeError):
        runtime._build_session_archive(measurement_file=str(m), loadsteps_file=str(m), extra_files=[])


def test_runtime_run_loop_idle_recording_and_exception_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(tmp_path)
    runtime._lock = threading.RLock()

    # Idle branch: not recording -> uses idle sleep and exits.
    idle_times = iter([0.0, 0.1])
    sleeps = []

    def _idle_sleep(seconds):
        sleeps.append(seconds)
        runtime._running = False

    monkeypatch.setattr(runtime_module.time, "time", lambda: next(idle_times))
    monkeypatch.setattr(runtime_module.time, "sleep", _idle_sleep)
    runtime._recording = False
    runtime.run()
    assert sleeps and sleeps[0] == pytest.approx(0.1)

    # Recording branch: elapsed >= target interval, records and checks.
    rec_times = iter([0.0, 1.0])
    flags = {"record": 0, "check": 0}

    def _rec_sleep(_seconds):
        runtime._running = False

    monkeypatch.setattr(runtime_module.time, "time", lambda: next(rec_times))
    monkeypatch.setattr(runtime_module.time, "sleep", _rec_sleep)
    runtime._record_sample = lambda: flags.__setitem__("record", flags["record"] + 1)
    runtime._check_loadsteps = lambda: flags.__setitem__("check", flags["check"] + 1)
    runtime.config = MeasurementConfig(parameters=["x"], hz=2.0, output_dir=str(tmp_path), session_name="sess", output_format="jsonl")
    runtime._recording = True
    runtime.run()
    assert flags["record"] == 1
    assert flags["check"] == 1

    # Recording branch: elapsed below target interval.
    wait_times = iter([0.0, 0.1])
    wait_sleeps = []

    def _wait_sleep(seconds):
        wait_sleeps.append(seconds)
        runtime._running = False

    monkeypatch.setattr(runtime_module.time, "time", lambda: next(wait_times))
    monkeypatch.setattr(runtime_module.time, "sleep", _wait_sleep)
    runtime.run()
    assert wait_sleeps and wait_sleeps[0] > 0.0

    # Exception branch inside loop.
    err_times = iter([0.0, RuntimeError("clock failed")])

    def _raise_time_after_first():
        value = next(err_times)
        if isinstance(value, Exception):
            raise value
        return value

    err_sleeps = []

    def _err_sleep(seconds):
        err_sleeps.append(seconds)
        runtime._running = False

    monkeypatch.setattr(runtime_module.time, "time", _raise_time_after_first)
    monkeypatch.setattr(runtime_module.time, "sleep", _err_sleep)
    runtime.run()
    assert err_sleeps and err_sleeps[0] == pytest.approx(0.1)
