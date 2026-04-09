"""File writers for different output formats."""

from __future__ import annotations

import contextlib
import json
import os
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any


class FileWriter(ABC):
    """Abstract base class for file writers."""

    def __init__(self, output_dir: str, session_name: str, parameters: list[str]):
        """Initialize the file writer.

        Args:
            output_dir: Directory to save files
            session_name: Name of the measurement session
            parameters: List of parameter names
        """
        self.output_dir = output_dir
        self.session_name = session_name
        self.parameters = parameters
        self.filepath = self._get_filepath()
        self.sample_count = 0
        self._lock = threading.Lock()  # Protect file I/O operations

    @abstractmethod
    def write_sample(self, sample: dict) -> None:
        """Write a sample to the file.

        Args:
            sample: Dictionary containing 'timestamp', 'datetime', and 'data' keys
        """
        pass

    @abstractmethod
    def finalize(self) -> str:
        """Finalize the file and return the filepath.

        Returns:
            Path to the written file
        """
        pass

    def _get_filepath(self) -> str:
        """Get the output file path."""
        raise NotImplementedError


class ParquetWriter(FileWriter):
    """Writer for Parquet format using pyarrow."""

    def __init__(self, output_dir: str, session_name: str, parameters: list[str]):
        """Initialize Parquet writer."""
        super().__init__(output_dir, session_name, parameters)
        self._sample_buffer = []
        self._buffer_size = 100  # Write in batches
        self._parquet_writer = None
        self._fallback_writer: JSONLWriter | None = None

    def _get_filepath(self) -> str:
        """Get the output file path."""
        return str(Path(self.output_dir) / f"{self.session_name}.parquet")

    def write_sample(self, sample: dict) -> None:
        """Buffer and write samples."""
        with self._lock:
            if self._fallback_writer is not None:
                self._fallback_writer.write_sample(sample)
                self.sample_count += 1
                return

            row = {
                "timestamp": sample["timestamp"],
                "datetime": sample["datetime"],
            }
            # Add parameter values
            for param in self.parameters:
                row[param] = self._normalize_value_for_parquet(
                    sample["data"].get(param)
                )

            self._sample_buffer.append(row)
            self.sample_count += 1

            # Write batch when buffer is full
            if len(self._sample_buffer) >= self._buffer_size:
                self._write_batch()

    def _normalize_value_for_parquet(self, value: Any) -> Any:
        """Coerce complex values into stable scalar types for parquet serialization."""
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, set):
            value = sorted(str(v) for v in value)
        if isinstance(value, (dict, list, tuple)):
            try:
                return json.dumps(
                    value, ensure_ascii=False, sort_keys=True, default=str
                )
            except Exception:
                return str(value)
        return str(value)

    def _build_sample_from_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "timestamp": row.get("timestamp"),
            "datetime": row.get("datetime"),
            "data": {param: row.get(param) for param in self.parameters},
        }

    def _fallback_to_jsonl_writer(self) -> None:
        if self._fallback_writer is None:
            self._fallback_writer = JSONLWriter(
                self.output_dir, self.session_name, self.parameters
            )

        for row in self._sample_buffer:
            self._fallback_writer.write_sample(self._build_sample_from_row(row))
        self._sample_buffer.clear()

        if self._parquet_writer is not None:
            with contextlib.suppress(Exception):
                self._parquet_writer.close()
            self._parquet_writer = None

        try:
            existing_path = Path(self.filepath)
            if existing_path.exists():
                partial_path = existing_path.with_suffix(
                    f"{existing_path.suffix}.partial"
                )
                if partial_path.exists():
                    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
                    partial_path = existing_path.with_suffix(
                        f"{existing_path.suffix}.{timestamp}.partial"
                    )
                existing_path.replace(partial_path)
        except OSError:
            pass

    def _write_batch(self) -> None:
        """Write buffered samples to Parquet file."""
        if not self._sample_buffer:
            return

        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            print("Warning: pyarrow not available. Samples buffered but not written.")
            return

        try:
            # Convert current batch to a row group table.
            table = pa.Table.from_pylist(self._sample_buffer)

            # First write creates the file; subsequent writes append row groups.
            if self._parquet_writer is None:
                existing_path = Path(self.filepath)
                if existing_path.exists():
                    existing_path.unlink()
                self._parquet_writer = pq.ParquetWriter(self.filepath, table.schema)

            self._parquet_writer.write_table(table)
            self._sample_buffer.clear()

        except Exception as e:
            print(f"Error writing Parquet batch: {e}")
            print("Warning: Falling back to JSONL writer for this measurement session.")
            self._fallback_to_jsonl_writer()

    def finalize(self) -> str:
        """Finalize and write all remaining samples."""
        with self._lock:
            if self._fallback_writer is not None:
                if self._sample_buffer:
                    self._fallback_to_jsonl_writer()
                self._fallback_writer.finalize()
                return self._fallback_writer.filepath

            self._write_batch()

            if self._fallback_writer is not None:
                self._fallback_writer.finalize()
                return self._fallback_writer.filepath

            if self._parquet_writer is not None:
                self._parquet_writer.close()
                self._parquet_writer = None
        return self.filepath


class CSVWriter(FileWriter):
    """Writer for CSV format."""

    def __init__(self, output_dir: str, session_name: str, parameters: list[str]):
        """Initialize CSV writer."""
        super().__init__(output_dir, session_name, parameters)
        self.file_handle = None
        self._write_header()

    def _get_filepath(self) -> str:
        """Get the output file path."""
        return str(Path(self.output_dir) / f"{self.session_name}.csv")

    def _write_header(self) -> None:
        """Write CSV header."""
        try:
            fd = os.open(self.filepath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
            self.file_handle = os.fdopen(fd, "w", encoding="utf-8", newline="")
            header = "timestamp,datetime," + ",".join(self.parameters) + "\n"
            self.file_handle.write(header)
            self.file_handle.flush()
        except Exception as e:
            print(f"Error writing CSV header: {e}")

    def write_sample(self, sample: dict) -> None:
        """Write a single sample to CSV."""
        with self._lock:
            if not self.file_handle:
                self._write_header()

            try:
                row = [
                    str(sample["timestamp"]),
                    sample["datetime"],
                ]
                # Add parameter values
                for param in self.parameters:
                    val = sample["data"].get(param)
                    row.append(str(val) if val is not None else "")

                line = ",".join(row) + "\n"
                self.file_handle.write(line)
                self.sample_count += 1

                # Flush occasionally
                if self.sample_count % 100 == 0:
                    self.file_handle.flush()

            except Exception as e:
                print(f"Error writing CSV sample: {e}")

    def finalize(self) -> str:
        """Close the file."""
        with self._lock:
            if self.file_handle:
                self.file_handle.close()
        return self.filepath


class JSONLWriter(FileWriter):
    """Writer for JSONL (JSON Lines) format."""

    def __init__(self, output_dir: str, session_name: str, parameters: list[str]):
        """Initialize JSONL writer."""
        super().__init__(output_dir, session_name, parameters)
        self.file_handle = None
        self._open_file()

    def _get_filepath(self) -> str:
        """Get the output file path."""
        return str(Path(self.output_dir) / f"{self.session_name}.jsonl")

    def _open_file(self) -> None:
            fd = os.open(
                self.filepath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644
            )
        try:
            fd = os.open(self.filepath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
            self.file_handle = os.fdopen(fd, "w", encoding="utf-8")
        except Exception as e:
            print(f"Error opening JSONL file: {e}")

    def write_sample(self, sample: dict) -> None:
        """Write a single sample as JSON line."""
        with self._lock:
            if not self.file_handle:
                self._open_file()

            try:
                row = {
                    "timestamp": sample["timestamp"],
                    "datetime": sample["datetime"],
                    "data": {
                        param: sample["data"].get(param) for param in self.parameters
                    },
                }
                line = json.dumps(row) + "\n"
                self.file_handle.write(line)
                self.sample_count += 1

                # Flush occasionally
                if self.sample_count % 100 == 0:
                    self.file_handle.flush()

            except Exception as e:
                print(f"Error writing JSONL sample: {e}")

    def finalize(self) -> str:
        """Close the file."""
        with self._lock:
            if self.file_handle:
                self.file_handle.close()
        return self.filepath


class FileWriterFactory:
    """Factory for creating file writers based on format type."""

    @staticmethod
    def create(
        format_type: str, output_dir: str, session_name: str, parameters: list[str]
    ) -> FileWriter:
        """Create a file writer for the specified format.

        Args:
            format_type: Format type ("parquet", "csv", or "jsonl")
            output_dir: Output directory
            session_name: Session name
            parameters: List of parameters

        Returns:
            Appropriate FileWriter instance

        Raises:
            ValueError: If format_type is not recognized
        """
        format_type = format_type.lower()

        if format_type == "parquet":
            return ParquetWriter(output_dir, session_name, parameters)
        if format_type == "csv":
            return CSVWriter(output_dir, session_name, parameters)
        if format_type == "jsonl":
            return JSONLWriter(output_dir, session_name, parameters)
        raise ValueError(
            f"Unknown format type: {format_type}. "
            "Supported formats: parquet, csv, jsonl"
        )
