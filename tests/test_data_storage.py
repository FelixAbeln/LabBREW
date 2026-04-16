from __future__ import annotations

import builtins
import json
import types

import pytest

from Services.data_service.storage import writer as writer_module
from Services.data_service.storage.loadstep import LoadstepAverager
from Services.data_service.storage.writer import (
    CSVWriter,
    FileWriter,
    FileWriterFactory,
    JSONLWriter,
    ParquetWriter,
)


def test_loadstep_averager_ignores_missing_and_non_numeric_values() -> None:
    averager = LoadstepAverager(["temp", "ph"], duration_seconds=5)

    averager.add_sample({"temp": 20, "ph": 4.5})
    averager.add_sample({"temp": None, "ph": "bad"})
    averager.add_sample({"temp": 22.0})

    assert averager.sample_count == 3
    assert averager.get_average() == {"temp": 21.0, "ph": 4.5}


def test_loadstep_averager_returns_none_for_empty_samples() -> None:
    averager = LoadstepAverager(["temp", "ph"], duration_seconds=5)

    assert averager.get_average() == {"temp": None, "ph": None}


def test_csv_writer_writes_header_and_rows(tmp_path) -> None:
    writer = CSVWriter(str(tmp_path), "session", ["temp", "ph"])

    writer.write_sample(
        {
            "timestamp": 123.4,
            "datetime": "2026-03-29T12:00:00Z",
            "data": {"temp": 19.5, "ph": None},
        }
    )
    output = writer.finalize()

    content = (tmp_path / "session.csv").read_text(encoding="utf-8")
    assert output.endswith("session.csv")
    assert content.splitlines() == [
        "timestamp,datetime,temp,ph",
        "123.4,2026-03-29T12:00:00Z,19.5,",
    ]
    assert writer.sample_count == 1


def test_jsonl_writer_persists_filtered_payloads(tmp_path) -> None:
    writer = JSONLWriter(str(tmp_path), "session", ["temp"])

    writer.write_sample(
        {
            "timestamp": 1.0,
            "datetime": "2026-03-29T12:00:00Z",
            "data": {"temp": 18.2, "ph": 4.4},
        }
    )
    output = writer.finalize()

    payload = json.loads((tmp_path / "session.jsonl").read_text(encoding="utf-8").strip())
    assert output.endswith("session.jsonl")
    assert payload == {
        "timestamp": 1.0,
        "datetime": "2026-03-29T12:00:00Z",
        "data": {"temp": 18.2},
    }
    assert writer.sample_count == 1


def test_file_writer_factory_rejects_unknown_format(tmp_path) -> None:
    try:
        FileWriterFactory.create("xlsx", str(tmp_path), "session", ["temp"])
    except ValueError as exc:
        assert "Unknown format type" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unsupported format")


def test_file_writer_factory_creates_known_writers(tmp_path) -> None:
    assert isinstance(FileWriterFactory.create("parquet", str(tmp_path), "s", ["x"]), ParquetWriter)
    assert isinstance(FileWriterFactory.create("csv", str(tmp_path), "s", ["x"]), CSVWriter)
    assert isinstance(FileWriterFactory.create("jsonl", str(tmp_path), "s", ["x"]), JSONLWriter)


def test_parquet_writer_handles_importerror_and_finalize(tmp_path) -> None:
    writer = ParquetWriter(str(tmp_path), "session", ["temp"])
    writer.write_sample({"timestamp": 1.0, "datetime": "t", "data": {"temp": 1.0}})

    original_import = builtins.__import__

    def _raise_pyarrow(name, *args, **kwargs):
        if name.startswith("pyarrow"):
            raise ImportError("pyarrow not available")
        return original_import(name, *args, **kwargs)

    builtins.__import__ = _raise_pyarrow
    try:
        writer._write_batch()
    finally:
        builtins.__import__ = original_import

    output = writer.finalize()
    assert output.endswith("session.parquet")


def test_parquet_writer_write_error_path(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = monkeypatch
    writer = ParquetWriter(str(tmp_path), "session", ["temp"])
    writer._sample_buffer = [{"timestamp": 1.0, "datetime": "t", "temp": 1.0}]

    class _FakeTable:
        schema = "schema"

    class _FakePA:
        class Table:
            @staticmethod
            def from_pylist(_rows):
                return _FakeTable()

    class _BadParquetWriter:
        def write_table(self, _table):
            raise RuntimeError("write failed")

        def close(self):
            return None

    class _FakePQ:
        @staticmethod
        def ParquetWriter(_path, _schema):
            return _BadParquetWriter()

    original_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pyarrow":
            return _FakePA()
        if name == "pyarrow.parquet":
            return _FakePQ()
        return original_import(name, globals, locals, fromlist, level)

    builtins.__import__ = _fake_import
    try:
        writer._write_batch()
        writer.finalize()
    finally:
        builtins.__import__ = original_import


def test_csv_writer_flush_and_error_paths(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    writer = CSVWriter(str(tmp_path), "session", ["temp"])
    writer.sample_count = 99
    writer.write_sample({"timestamp": 1.0, "datetime": "t", "data": {"temp": 1.0}})
    assert writer.sample_count == 100

    class _BadHandle:
        def write(self, _line):
            raise OSError("write failed")

        def flush(self):
            return None

        def close(self):
            return None

    writer.file_handle = _BadHandle()
    writer.write_sample({"timestamp": 2.0, "datetime": "t", "data": {"temp": 2.0}})
    writer.finalize()

    # header open failure path
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("open failed")))
    broken = CSVWriter(str(tmp_path), "broken", ["x"])
    broken.write_sample({"timestamp": 0.0, "datetime": "t", "data": {"x": 1}})


def test_jsonl_writer_flush_and_error_paths(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    writer = JSONLWriter(str(tmp_path), "session", ["temp"])
    writer.sample_count = 99
    writer.write_sample({"timestamp": 1.0, "datetime": "t", "data": {"temp": 1.0}})
    assert writer.sample_count == 100

    class _BadHandle:
        def write(self, _line):
            raise OSError("write failed")

        def flush(self):
            return None

        def close(self):
            return None

    writer.file_handle = _BadHandle()
    writer.write_sample({"timestamp": 2.0, "datetime": "t", "data": {"temp": 2.0}})
    writer.finalize()

    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("open failed")))
    broken = JSONLWriter(str(tmp_path), "broken", ["x"])
    broken.write_sample({"timestamp": 0.0, "datetime": "t", "data": {"x": 1}})


def test_file_writer_base_methods_and_not_implemented_path() -> None:
    class _ConcreteWriter(FileWriter):
        def _get_filepath(self) -> str:
            return "dummy"

        def write_sample(self, sample: dict) -> None:
            FileWriter.write_sample(self, sample)

        def finalize(self) -> str:
            FileWriter.finalize(self)
            return self.filepath

    writer = _ConcreteWriter("out", "session", ["x"])
    assert writer.write_sample({"data": {}}) is None
    assert writer.finalize() == "dummy"
    with pytest.raises(NotImplementedError):
        FileWriter._get_filepath(writer)


def test_parquet_writer_empty_batch_and_full_buffer_trigger(tmp_path) -> None:
    writer = ParquetWriter(str(tmp_path), "session", ["temp"])
    writer._write_batch()

    writer._buffer_size = 1
    writer.write_sample({"timestamp": 1.0, "datetime": "t", "data": {"temp": 1.0}})
    writer.finalize()


def test_parquet_writer_removes_existing_file_before_first_write(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    writer = ParquetWriter(str(tmp_path), "session", ["temp"])
    writer._sample_buffer = [{"timestamp": 1.0, "datetime": "t", "temp": 1.0}]

    existing = tmp_path / "session.parquet"
    existing.write_text("old", encoding="utf-8")

    class _FakeTable:
        schema = "schema"

    removed = {"called": False}

    class _Writer:
        def write_table(self, _table):
            return None

        def close(self):
            return None

    pyarrow_mod = types.ModuleType("pyarrow")

    class _TableFactory:
        @staticmethod
        def from_pylist(_rows):
            return _FakeTable()

    pyarrow_mod.Table = _TableFactory
    pyarrow_mod.concat_tables = lambda items: items[-1]

    pyarrow_parquet_mod = types.ModuleType("pyarrow.parquet")
    pyarrow_parquet_mod.ParquetWriter = lambda _path, _schema: _Writer()
    pyarrow_mod.parquet = pyarrow_parquet_mod

    monkeypatch.setattr(writer_module.Path, "exists", lambda _self: True)
    monkeypatch.setattr(
        writer_module.Path,
        "unlink",
        lambda _self: removed.__setitem__("called", True),
    )
    monkeypatch.setitem(__import__("sys").modules, "pyarrow", pyarrow_mod)
    monkeypatch.setitem(__import__("sys").modules, "pyarrow.parquet", pyarrow_parquet_mod)

    writer._write_batch()

    assert removed["called"] is True
    assert writer._sample_buffer == []


def test_parquet_writer_write_batch_exception_branch(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    writer = ParquetWriter(str(tmp_path), "session", ["temp"])
    writer._sample_buffer = [{"timestamp": 1.0, "datetime": "t", "temp": 1.0}]

    class _FakeTable:
        schema = "schema"

    class _TableFactory:
        @staticmethod
        def from_pylist(_rows):
            return _FakeTable()

    class _Writer:
        def write_table(self, _table):
            raise RuntimeError("write failed")

        def close(self):
            return None

    import types

    pyarrow_mod = types.ModuleType("pyarrow")
    pyarrow_mod.Table = _TableFactory
    pyarrow_parquet_mod = types.ModuleType("pyarrow.parquet")
    pyarrow_parquet_mod.ParquetWriter = lambda _path, _schema: _Writer()
    pyarrow_mod.parquet = pyarrow_parquet_mod

    monkeypatch.setitem(__import__("sys").modules, "pyarrow", pyarrow_mod)
    monkeypatch.setitem(__import__("sys").modules, "pyarrow.parquet", pyarrow_parquet_mod)

    writer._write_batch()
    assert writer._sample_buffer == []
    assert writer._fallback_writer is not None
    assert writer._fallback_writer.sample_count == 1


def test_parquet_writer_normalizes_numeric_variants_to_float(tmp_path) -> None:
    writer = ParquetWriter(str(tmp_path), "session", ["temp"])

    assert writer._normalize_value_for_parquet(True) == 1.0
    assert writer._normalize_value_for_parquet(False) == 0.0
    assert writer._normalize_value_for_parquet(5) == 5.0
    assert writer._normalize_value_for_parquet(5.25) == 5.25
    assert writer._normalize_value_for_parquet("12.5") == 12.5
    assert writer._normalize_value_for_parquet("not-a-number") == "not-a-number"
