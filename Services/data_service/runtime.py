"""Data logging service runtime.

Records parameter values from parameterDB at a configurable rate,
saves to files, and supports loadstep averaging.
"""

from __future__ import annotations

import base64
import contextlib
import csv
import importlib.util
import io
import json
import os
import shutil
import tempfile
import threading
import time
import zipfile
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .._shared.parameterDB.paremeterDB import SignalStoreBackend
from .._shared.storage_paths import default_measurements_dir
from .storage.loadstep import LoadstepAverager
from .storage.writer import FileWriter, FileWriterFactory

# Sleep durations for the recording loop
_IDLE_SLEEP_INTERVAL = 0.1  # 100ms when not recording (reduces idle CPU usage)
_MIN_SAMPLE_SLEEP = 0.0005  # 0.5ms minimum sleep floor to prevent busy-waiting
_VALIDITY_REFRESH_INTERVAL_S = 0.5  # Re-check parameter validity at most 2 Hz
_PARQUET_VALIDATION_ATTEMPTS = 4
_PARQUET_VALIDATION_RETRY_SLEEP_S = 0.02
DEFAULT_MEASUREMENTS_DIR = default_measurements_dir()


@dataclass
class MeasurementConfig:
    """Configuration for a measurement session."""

    parameters: list[str] = field(default_factory=list)
    hz: float = 10.0  # Recording frequency (1-150 Hz)
    output_dir: str = DEFAULT_MEASUREMENTS_DIR
    output_format: str = "parquet"  # "parquet", "csv", or "jsonl"
    session_name: str = ""  # Auto-generated if empty
    include_files: list[str] = field(default_factory=list)
    include_payloads: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class LoadstepConfig:
    """Configuration for a loadstep."""

    name: str = ""
    parameters: list[str] = field(default_factory=list)
    duration_seconds: float = 30.0
    timestamp: datetime = field(default_factory=datetime.now)


class DataRecordingRuntime:
    """Runtime for the data recording service.

    Runs in a background thread and records parameter values from parameterDB
    at a configurable frequency, writes to files, and supports loadstep averaging.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        """Initialize the data recording runtime.

        Args:
            host: parameterDB service host
            port: parameterDB service port
        """
        self.backend = SignalStoreBackend(host=host, port=port)
        self._running = False
        self._lock = threading.RLock()

        # Measurement state
        self.config: MeasurementConfig | None = None
        self._measurement_data: deque = deque()  # Circular buffer for raw data
        self._start_time: float | None = None
        self._file_writer: FileWriter | None = None
        self._recording = False
        self._missing_parameters: set[str] = set()
        self._setup_warnings: list[str] = []

        # Loadstep tracking
        self._active_loadsteps: list[LoadstepConfig] = []
        self._loadstep_averagers: dict[str, LoadstepAverager] = {}
        self._completed_loadsteps: list[dict] = []
        self._loadsteps_archive_path: str = ""
        self._loadsteps_archive_format: str = "jsonl"

        # Validity cache: keyed by param name, True = valid, False = invalid.
        # Refreshed periodically (not per-sample) to keep the recording hot path cheap.
        self._validity_cache: dict[str, bool] = {}
        self._validity_last_refresh: float = 0.0

    def run(self) -> None:
        """Main runtime loop - runs in background thread."""
        self._running = True
        last_write_time = time.time()

        # Recovery sweep: archive leftover session files from a previous crash.
        try:
            self._recover_unarchived_outputs(output_dir=DEFAULT_MEASUREMENTS_DIR)
        except Exception as exc:
            print(f"Startup archive recovery failed: {exc}")

        while self._running:
            try:
                current_time = time.time()
                sleep_time = _IDLE_SLEEP_INTERVAL  # Default: 100ms when not recording
                sample_due = False

                # Phase 1: check under lock whether a sample is due this cycle.
                with self._lock:
                    if self._recording and self.config:
                        elapsed = current_time - last_write_time
                        target_interval = 1.0 / self.config.hz
                        if elapsed >= target_interval:
                            sample_due = True
                            sleep_time = target_interval
                        else:
                            sleep_time = max(
                                _MIN_SAMPLE_SLEEP, target_interval - elapsed
                            )

                if sample_due:
                    # Phase 2 (outside lock): refresh validity cache when empty or due.
                    # This guarantees the very first sample uses a populated cache, and
                    # subsequent refreshes happen before the sample they gate — not after.
                    if current_time - self._validity_last_refresh >= _VALIDITY_REFRESH_INTERVAL_S:
                        self._refresh_validity_cache()
                        self._validity_last_refresh = current_time

                    # Phase 3: record sample and maintain loadsteps under lock.
                    with self._lock:
                        if self._recording and self.config:
                            self._record_sample()
                            last_write_time = current_time
                            self._check_loadsteps()

                time.sleep(sleep_time)

            except Exception as e:
                print(f"Error in recording loop: {e}")
                time.sleep(0.1)

    def stop(self) -> None:
        """Stop the runtime loop."""
        self._running = False

    def setup_measurement(
        self,
        parameters: list[str],
        hz: float = 10.0,
        output_dir: str = DEFAULT_MEASUREMENTS_DIR,
        output_format: str = "parquet",
        session_name: str = "",
        include_files: list[str] | None = None,
        include_payloads: list[dict[str, Any]] | None = None,
    ) -> dict:
        """Configure a measurement session.

        Args:
            parameters: List of parameterDB parameter names to record
            hz: Recording frequency in Hz (1-150)
            output_dir: Directory to save data files
            output_format: Format for output files ("parquet", "csv", or "jsonl")
            session_name: Name for the measurement session

        Returns:
            Status dictionary
        """
        with self._lock:
            if self._recording:
                return {"ok": False, "error": "Measurement already in progress"}

            # Validate Hz
            if hz < 1.0 or hz > 150.0:
                return {"ok": False, "error": f"Hz must be between 1 and 150, got {hz}"}

            if not parameters:
                return {"ok": False, "error": "At least one parameter is required"}

            if not self.backend.connected():
                return {"ok": False, "error": "parameterDB backend not connected"}

            self._setup_warnings = []
            self._missing_parameters = set()
            snapshot = self.backend.full_snapshot()

            if snapshot:
                available_params = set(snapshot.keys())
                unavailable = sorted(
                    param for param in parameters if param not in available_params
                )
                if unavailable:
                    self._setup_warnings.append(
                        "Parameters not currently available in parameterDB: "
                        f"{unavailable}. Missing values will be recorded as null "
                        "until they appear."
                    )
            else:
                self._setup_warnings.append(
                    "parameterDB snapshot is currently empty. Setup accepted, "
                    "but samples may be null until values appear."
                )

            # Keep explicit session names stable unless collisions require disambiguation.
            requested_session_name = Path(str(session_name or "").strip()).name
            if not requested_session_name:
                requested_session_name = "measurement"
            output_dir_path = Path(output_dir)
            run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            if str(session_name or "").strip():
                session_name = requested_session_name
                collision_pattern = f"{requested_session_name}.*"
                if output_dir_path.exists() and any(output_dir_path.glob(collision_pattern)):
                    session_name = f"{requested_session_name}_{run_stamp}"
            else:
                session_name = f"{requested_session_name}_{run_stamp}"

            normalized_include_files = [
                str(item) for item in (include_files or []) if str(item).strip()
            ]
            remapped_include_files: list[str] = []
            for item in normalized_include_files:
                candidate = Path(str(item)).resolve()
                if (
                    requested_session_name
                    and candidate.name.startswith(f"{requested_session_name}.")
                ):
                    suffix = candidate.name[len(requested_session_name) :]
                    candidate = candidate.with_name(f"{session_name}{suffix}")
                remapped_include_files.append(str(candidate))

            selected_format = str(output_format or "parquet").lower()
            if (
                selected_format == "parquet"
                and importlib.util.find_spec("pyarrow") is None
            ):
                self._setup_warnings.append(
                    "pyarrow is not installed; falling back from parquet to "
                    "jsonl so data is persisted."
                )
                selected_format = "jsonl"

            self.config = MeasurementConfig(
                parameters=parameters,
                hz=hz,
                output_dir=output_dir,
                output_format=selected_format,
                session_name=session_name,
                include_files=remapped_include_files,
                include_payloads=self._normalize_include_payloads(include_payloads),
            )
            self._loadsteps_archive_format = selected_format
            self._loadsteps_archive_path = str(
                output_dir_path
                / f"{session_name}.loadsteps.{self._loadsteps_archive_format}"
            )

            # Initialize file writer
            output_dir_path.mkdir(parents=True, exist_ok=True)
            self._file_writer = FileWriterFactory.create(
                format_type=selected_format,
                output_dir=output_dir,
                session_name=session_name,
                parameters=parameters,
            )

            self._measurement_data = deque(
                maxlen=10000
            )  # Circular buffer for ~100 seconds at 100 Hz
            self._start_time = None

            return {
                "ok": True,
                "session_name": session_name,
                "parameters": parameters,
                "hz": hz,
                "output_format": selected_format,
                "output_dir": output_dir,
                "include_files": list(self.config.include_files),
                "include_payloads": [
                    {
                        "name": item.get("name", ""),
                        "size": int(item.get("size", 0)),
                        "media_type": item.get("media_type"),
                    }
                    for item in self.config.include_payloads
                ],
                "warnings": list(self._setup_warnings),
            }

    def measure_start(self) -> dict:
        """Start recording measurements.

        Returns:
            Status dictionary
        """
        with self._lock:
            if not self.config:
                return {
                    "ok": False,
                    "error": (
                        "Measurement not configured. "
                        "Call setup_measurement first."
                    ),
                }

            if self._recording:
                return {"ok": False, "error": "Recording already in progress"}

            self._recording = True
            self._start_time = time.time()
            self._measurement_data.clear()
            self._active_loadsteps = []
            self._completed_loadsteps = []
            self._missing_parameters = set()
            self._validity_cache = {}
            self._validity_last_refresh = 0.0  # Force a refresh on the first sample
            self._initialize_loadstep_archive_file()

            return {
                "ok": True,
                "message": f"Started recording session: {self.config.session_name}",
            }

    def measure_stop(self) -> dict:
        """Stop recording measurements and finalize file.

        Returns:
            Status dictionary with summary
        """
        with self._lock:
            if not self._recording:
                return {"ok": False, "error": "No measurement in progress"}

            self._recording = False

            # Finalize any active loadsteps
            for ls_config in self._active_loadsteps:
                self._finalize_loadstep(ls_config)

            # Write remaining data to file
            if self._file_writer:
                filepath = self._file_writer.finalize()
                filepath = self._prepare_measurement_file_for_archive(filepath)
                total_samples = getattr(
                    self._file_writer, "sample_count", len(self._measurement_data)
                )
                try:
                    configured_payloads = list(self.config.include_payloads) if self.config else []
                    runtime_payloads = self._build_parameterdb_runtime_payloads()
                    archive = self._build_session_archive(
                        measurement_file=filepath,
                        loadsteps_file=self._loadsteps_archive_path,
                        extra_files=self.config.include_files if self.config else [],
                        extra_payloads=[*configured_payloads, *runtime_payloads],
                    )
                except Exception as exc:
                    archive = {"archive_path": None, "members": [], "missing": []}
                    self._setup_warnings.append(f"Archive build failed: {exc}")

                return {
                    "ok": True,
                    "message": f"Recording stopped: {self.config.session_name}",
                    "samples_recorded": total_samples,
                    "file": archive.get("archive_path") or filepath,
                    "loadsteps_file": self._loadsteps_archive_path,
                    "archive_file": archive.get("archive_path"),
                    "archived_members": archive.get("members", []),
                    "archived_missing": archive.get("missing", []),
                    "completed_loadsteps": len(self._completed_loadsteps),
                    "loadsteps": self._completed_loadsteps,
                    "missing_parameters": sorted(self._missing_parameters),
                    "warnings": list(self._setup_warnings),
                }

            return {"ok": True, "message": "Recording stopped"}

    def _is_probably_valid_parquet_file(self, file_path: str) -> bool:
        raw_path = str(file_path or "").strip()
        if not raw_path:
            return False
        path = Path(raw_path).resolve()
        if not path.is_file():
            return False
        delay_s = _PARQUET_VALIDATION_RETRY_SLEEP_S
        for attempt in range(_PARQUET_VALIDATION_ATTEMPTS):
            try:
                size = path.stat().st_size
                if size < 8:
                    return False
                with path.open("rb") as handle:
                    head = handle.read(4)
                    handle.seek(-4, os.SEEK_END)
                    tail = handle.read(4)
                return head == b"PAR1" and tail == b"PAR1"
            except OSError:
                if attempt >= _PARQUET_VALIDATION_ATTEMPTS - 1:
                    return False
                time.sleep(delay_s)
                delay_s *= 2
        return False

    def _quarantine_corrupt_file(self, file_path: str, reason: str) -> str:
        raw_path = str(file_path or "").strip()
        if not raw_path:
            return raw_path
        path = Path(raw_path).resolve()
        if not path.exists():
            return str(path)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        quarantined = path.with_name(f"{path.name}.corrupt.{stamp}")
        try:
            path.replace(quarantined)
            self._setup_warnings.append(
                f"Quarantined corrupt file {path.name}: {reason}"
            )
            return str(quarantined)
        except OSError as exc:
            self._setup_warnings.append(
                "Detected corrupt file "
                f"{path.name} but could not quarantine it: {exc}"
            )
            return str(path)

    def _write_measurement_jsonl_from_buffer(self, output_path: str) -> bool:
        raw_path = str(output_path or "").strip()
        if not raw_path:
            return False
        path = Path(raw_path).resolve()

        rows = list(self._measurement_data)
        if not rows:
            return False

        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            Path(tmp_name).replace(path)
            return True
        except Exception:
            try:
                tmp_path = Path(tmp_name)
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            return False

    def _prepare_measurement_file_for_archive(self, measurement_file: str) -> str:
        raw_path = str(measurement_file or "").strip()
        if not raw_path:
            return raw_path
        path = Path(raw_path).resolve()

        if path.suffix.lower() != ".parquet":
            return str(path)

        if self._is_probably_valid_parquet_file(path):
            return str(path)

        session_name = (
            self.config.session_name
            if self.config
            else path.stem
        )
        output_dir = Path(self.config.output_dir) if self.config else path.parent
        fallback_path = output_dir / f"{session_name}.jsonl"
        if self._write_measurement_jsonl_from_buffer(str(fallback_path)):
            self._quarantine_corrupt_file(str(path), "invalid parquet footer/header")
            self._setup_warnings.append(
                "Recovered measurement by writing JSONL fallback from "
                "in-memory samples after parquet corruption"
            )
            return str(fallback_path)

        self._setup_warnings.append(
            "Parquet measurement file appears corrupted and JSONL fallback "
            "could not be produced"
        )
        return str(path)

    def take_loadstep(
        self,
        duration_seconds: float = 30.0,
        loadstep_name: str = "",
        parameters: list[str] | None = None,
    ) -> dict:
        """Start recording a loadstep (averaged data over a time period).

        Args:
            duration_seconds: Duration for the loadstep
            loadstep_name: Name for the loadstep
            parameters: Parameters to average. If None, uses measurement parameters.

        Returns:
            Status dictionary
        """
        with self._lock:
            if not self._recording:
                return {"ok": False, "error": "No measurement in progress"}

            if duration_seconds <= 0:
                return {
                    "ok": False,
                    "error": (
                        "duration_seconds must be greater than 0, "
                        f"got {duration_seconds}"
                    ),
                }

            # Use measurement parameters if not specified
            params = parameters if parameters else self.config.parameters

            # Generate loadstep name if not provided
            if not loadstep_name:
                loadstep_name = f"loadstep_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            ls_config = LoadstepConfig(
                name=loadstep_name,
                parameters=params,
                duration_seconds=duration_seconds,
                timestamp=datetime.now(),
            )

            self._active_loadsteps.append(ls_config)

            # Create averager for this loadstep
            self._loadstep_averagers[loadstep_name] = LoadstepAverager(
                parameters=params, duration_seconds=duration_seconds
            )

            return {
                "ok": True,
                "loadstep_name": loadstep_name,
                "duration_seconds": duration_seconds,
                "parameters": params,
            }

    def _refresh_validity_cache(self) -> None:
        """Refresh validity cache from parameterDB. Called outside the recording lock."""
        try:
            described = self.backend.describe()
            new_cache: dict[str, bool] = {
                name: info.get("state", {}).get("parameter_valid") is not False
                for name, info in described.items()
                if isinstance(info, dict)
            }

            # If describe() returns no usable data (for example because the backend
            # swallowed a transient error and returned {}), keep the existing cache
            # rather than clearing it.
            configured_params = set(self.config.parameters)
            has_configured_validity = any(name in configured_params for name in new_cache)
            if not has_configured_validity:
                return

            with self._lock:
                self._validity_cache = new_cache
        except (OSError, ConnectionError, RuntimeError) as exc:
            # Expected when parameterDB is temporarily unreachable — keep the
            # existing cache and carry on so recording is not interrupted.
            print(f"[data_service] validity refresh failed (will retry): {exc}")
        except Exception as exc:
            # Unexpected coding error — log prominently so it is not silently lost.
            import traceback
            print(f"[data_service] unexpected error in validity refresh:\n{traceback.format_exc()}")

    def _record_sample(self) -> None:
        """Record a single sample of all configured parameters."""
        try:
            sample = {
                "timestamp": time.time() - (self._start_time or 0),
                "datetime": datetime.now().isoformat(),
                "data": {},
            }

            # Fetch all values in a single round-trip instead of one call per parameter.
            snapshot = self.backend.full_snapshot()
            for param in self.config.parameters:
                value = snapshot.get(param)
                if value is None:
                    self._missing_parameters.add(param)
                elif self._validity_cache.get(param) is False:
                    # Parameter is currently invalid; record None rather than stale data.
                    value = None
                sample["data"][param] = value

            # Store in circular buffer
            self._measurement_data.append(sample)

            # Add to active loadsteps
            for averager in self._loadstep_averagers.values():
                averager.add_sample(sample["data"])

            # Write to file
            if self._file_writer:
                self._file_writer.write_sample(sample)

        except Exception as e:
            print(f"Error recording sample: {e}")

    def _check_loadsteps(self) -> None:
        """Check if any active loadsteps have completed."""
        completed = []

        for ls_config in self._active_loadsteps:
            elapsed = (datetime.now() - ls_config.timestamp).total_seconds()

            if elapsed >= ls_config.duration_seconds:
                self._finalize_loadstep(ls_config)
                completed.append(ls_config.name)

        # Remove completed loadsteps
        self._active_loadsteps = [
            ls for ls in self._active_loadsteps if ls.name not in completed
        ]

    def _finalize_loadstep(self, ls_config: LoadstepConfig) -> None:
        """Finalize a loadstep and store its averaged data."""
        averager = self._loadstep_averagers.get(ls_config.name)
        if averager:
            averaged_data = averager.get_average()
            loadstep_record = {
                "name": ls_config.name,
                "duration_seconds": ls_config.duration_seconds,
                "average": averaged_data,
                "timestamp": ls_config.timestamp.isoformat(),
            }
            self._completed_loadsteps.append(loadstep_record)
            self._append_loadstep_archive_record(loadstep_record)
            # Once finalized and archived, remove the averager to avoid
            # accumulating further samples for this completed loadstep.
            self._loadstep_averagers.pop(ls_config.name, None)

    def _append_loadstep_archive_record(self, loadstep_record: dict[str, Any]) -> None:
        """Append a finalized loadstep record to the session archive file."""
        if not self._loadsteps_archive_path:
            return
        try:
            archive_path = Path(self._loadsteps_archive_path)
            if self._loadsteps_archive_format == "jsonl":
                with archive_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(loadstep_record, ensure_ascii=False) + "\n")
                return

            if self._loadsteps_archive_format == "csv":
                average_json = json.dumps(
                    loadstep_record.get("average", {}), ensure_ascii=False
                )
                row = [
                    str(loadstep_record.get("name", "")),
                    str(loadstep_record.get("duration_seconds", "")),
                    str(loadstep_record.get("timestamp", "")),
                    average_json,
                ]
                with archive_path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        ",".join(self._csv_escape(item) for item in row) + "\n"
                    )
                return

            if self._loadsteps_archive_format == "parquet":
                import pyarrow as pa
                import pyarrow.parquet as pq

                table = pa.Table.from_pylist(
                    [
                        {
                            "name": loadstep_record.get("name"),
                            "duration_seconds": float(
                                loadstep_record.get("duration_seconds") or 0.0
                            ),
                            "timestamp": loadstep_record.get("timestamp"),
                            "average_json": json.dumps(
                                loadstep_record.get("average", {}), ensure_ascii=False
                            ),
                        }
                    ]
                )

                if archive_path.exists():
                    existing = pq.read_table(str(archive_path))
                    table = pa.concat_tables([existing, table])
                pq.write_table(table, str(archive_path))
                return

            # Fallback if an unknown format string appears.
            with archive_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(loadstep_record, ensure_ascii=False) + "\n")
        except Exception as exc:
            print(f"Error writing loadstep archive record: {exc}")

    def _initialize_loadstep_archive_file(self) -> None:
        """Create/reset loadstep archive using the measurement output format."""
        if not self._loadsteps_archive_path:
            return
        try:
            archive_path = Path(self._loadsteps_archive_path)
            if self._loadsteps_archive_format == "jsonl":
                self._atomic_write_text_file(self._loadsteps_archive_path, "")
                return

            if self._loadsteps_archive_format == "csv":
                self._atomic_write_text_file(
                    self._loadsteps_archive_path,
                    "name,duration_seconds,timestamp,average_json\n",
                )
                return

            if self._loadsteps_archive_format == "parquet":
                if archive_path.exists():
                    archive_path.unlink()
                return

            # Unknown format fallback.
            self._atomic_write_text_file(self._loadsteps_archive_path, "")
        except Exception as exc:
            print(f"Error initializing loadstep archive file: {exc}")

    def _atomic_write_text_file(self, path: str, text: str) -> None:
        """Write a full text file atomically to avoid partial content on crashes."""
        target = Path(path).resolve()
        target_dir = target.parent
        target_dir.mkdir(parents=True, exist_ok=True)

        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{target.name}.",
            suffix=".tmp",
            dir=str(target_dir),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())

            Path(tmp_name).replace(target)

            try:
                dir_fd = os.open(str(target_dir), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
        except Exception:
            try:
                tmp_path = Path(tmp_name)
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise

    def _csv_escape(self, text: str) -> str:
        """Escape a CSV value with quotes when needed."""
        value = str(text)
        if any(ch in value for ch in [",", '"', "\n", "\r"]):
            return '"' + value.replace('"', '""') + '"'
        return value

    def _build_session_archive(
        self,
        *,
        measurement_file: str,
        loadsteps_file: str,
        extra_files: list[str],
        extra_payloads: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a session archive for measurement outputs and sidecar files."""
        if not self.config:
            return {"archive_path": None, "members": [], "missing": []}

        output_dir = Path(self.config.output_dir).resolve()
        archive_path = output_dir / f"{self.config.session_name}.archive.zip"
        candidates = [measurement_file, loadsteps_file, *list(extra_files or [])]
        return self._build_archive_from_sources(
            archive_path=str(archive_path),
            source_files=candidates,
            inline_payloads=list(extra_payloads or []),
        )

    def _normalize_include_payloads(
        self, include_payloads: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for item in include_payloads or []:
            if not isinstance(item, dict):
                continue
            name = Path(str(item.get("name") or "").strip()).name
            content_b64 = str(item.get("content_b64") or "").strip()
            if not name or not content_b64:
                continue
            try:
                raw = base64.b64decode(content_b64, validate=True)
            except Exception:
                continue
            payloads.append(
                {
                    "name": name,
                    "content_b64": content_b64,
                    "size": len(raw),
                    "media_type": str(item.get("media_type") or "").strip()
                    or "application/octet-stream",
                }
            )
        return payloads

    def _build_parameterdb_runtime_payloads(self) -> list[dict[str, Any]]:
        """Build sidecar payloads that capture ParameterDB logical runtime context."""
        payloads: list[dict[str, Any]] = []

        def _append_json_payload(name: str, data: dict[str, Any]) -> None:
            if not isinstance(data, dict) or not data:
                return
            raw = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
            payloads.append(
                {
                    "name": name,
                    "content_b64": base64.b64encode(raw).decode("ascii"),
                    "size": len(raw),
                    "media_type": "application/json",
                }
            )

        # Exported snapshot includes values/config/state/metadata and is the
        # canonical logical runtime capture for post-processing.
        with contextlib.suppress(Exception):
            export_fn = getattr(self.backend, "export_snapshot", None)
            if callable(export_fn):
                _append_json_payload("parameterdb.export_snapshot.json", export_fn())

        # Graph metadata helps consumers interpret dependency and write ordering.
        with contextlib.suppress(Exception):
            graph_fn = getattr(self.backend, "graph_info", None)
            if callable(graph_fn):
                _append_json_payload("parameterdb.graph_info.json", graph_fn())

        # Backend/service describe metadata for additional runtime context.
        with contextlib.suppress(Exception):
            describe_fn = getattr(self.backend, "describe", None)
            if callable(describe_fn):
                _append_json_payload("parameterdb.describe.json", describe_fn())

        return payloads

    def _recover_unarchived_outputs(self, *, output_dir: str) -> dict[str, Any]:
        """Archive leftover measurement outputs that were not zipped due to crashes."""
        target_dir = Path(
            str(output_dir or "").strip() or DEFAULT_MEASUREMENTS_DIR
        ).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)

        measurement_exts = {".jsonl", ".csv", ".parquet"}
        recovered_archives: list[str] = []
        skipped_sessions: list[str] = []
        sessions: dict[str, dict[str, str]] = {}

        for file_path in sorted(target_dir.iterdir(), key=lambda item: item.name):
            if not file_path.is_file():
                continue
            name = file_path.name

            if name.endswith(".tmp"):
                continue

            session_name: str | None = None
            measurement_file: str | None = None
            loadsteps_file: str | None = None

            root = file_path.stem
            ext = file_path.suffix.lower()

            if ext in measurement_exts and not root.endswith(".loadsteps"):
                session_name = root
                measurement_file = str(file_path)
                loadsteps_file = str(target_dir / f"{session_name}.loadsteps{ext}")
            elif ext in measurement_exts and root.endswith(".loadsteps"):
                session_name = root[: -len(".loadsteps")]
                loadsteps_file = str(file_path)
                measurement_file = str(target_dir / f"{session_name}{ext}")
            elif name.endswith(".run.log"):
                session_name = name[: -len(".run.log")]
            elif name.endswith(".schedule.json"):
                session_name = name[: -len(".schedule.json")]
            elif name.endswith(".recipe.json"):
                session_name = name[: -len(".recipe.json")]

            if not session_name:
                continue

            entry = sessions.setdefault(session_name, {})
            if measurement_file:
                measurement_path = str(Path(measurement_file).resolve())
                if Path(measurement_path).is_file() or "measurement" not in entry:
                    entry["measurement"] = measurement_path
            if loadsteps_file:
                loadsteps_path = str(Path(loadsteps_file).resolve())
                if Path(loadsteps_path).is_file() or "loadsteps" not in entry:
                    entry["loadsteps"] = loadsteps_path
            entry.setdefault("run_log", str(target_dir / f"{session_name}.run.log"))
            entry.setdefault(
                "schedule", str(target_dir / f"{session_name}.schedule.json")
            )
            entry.setdefault("recipe", str(target_dir / f"{session_name}.recipe.json"))

        for session_name in sorted(sessions):
            archive_name = f"{session_name}.archive.zip"
            archive_path = target_dir / archive_name
            if archive_path.exists():
                skipped_sessions.append(session_name)
                continue

            entry = sessions[session_name]
            sources = [
                entry.get("measurement", ""),
                entry.get("loadsteps", ""),
                entry.get("run_log", ""),
                entry.get("schedule", ""),
                entry.get("recipe", ""),
            ]
            archive = self._build_archive_from_sources(
                archive_path=str(archive_path),
                source_files=[source for source in sources if source],
            )
            if archive.get("archive_path"):
                recovered_archives.append(str(archive_path))

        return {
            "ok": True,
            "output_dir": str(target_dir),
            "recovered_archives": recovered_archives,
            "skipped_sessions": skipped_sessions,
        }

    def _build_archive_from_sources(
        self,
        *,
        archive_path: str,
        source_files: list[str],
        inline_payloads: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build archive from source file paths and remove archived sources."""
        raw_archive_path = str(archive_path or "").strip()
        if not raw_archive_path:
            return {"archive_path": None, "members": [], "missing": []}
        archive_path_obj = Path(raw_archive_path).resolve()

        tmp_archive_path = archive_path_obj.with_name(f"{archive_path_obj.name}.tmp")
        candidates = list(source_files or [])

        existing: list[str] = []
        missing: list[str] = []
        repaired: list[str] = []
        seen: set[Path] = set()
        for raw in candidates:
            raw_path = str(raw or "").strip()
            if not raw_path:
                continue
            path = Path(raw_path).resolve()
            if path in seen:
                continue
            seen.add(path)

            if (
                path.suffix.lower() == ".parquet"
                and path.is_file()
                and not self._is_probably_valid_parquet_file(str(path))
            ):
                # Try sibling fallbacks created by resilient writers/recovery.
                original_parquet = path
                sibling_jsonl = path.with_suffix(".jsonl")
                sibling_csv = path.with_suffix(".csv")
                if sibling_jsonl.is_file():
                    self._quarantine_corrupt_file(
                        str(original_parquet),
                        "invalid parquet footer/header (repaired using sibling jsonl)",
                    )
                    repaired.append(
                        f"{path.name} -> {sibling_jsonl.name}"
                    )
                    path = sibling_jsonl
                elif sibling_csv.is_file():
                    self._quarantine_corrupt_file(
                        str(original_parquet),
                        "invalid parquet footer/header (repaired using sibling csv)",
                    )
                    repaired.append(
                        f"{path.name} -> {sibling_csv.name}"
                    )
                    path = sibling_csv
                else:
                    self._quarantine_corrupt_file(
                        str(path), "invalid parquet footer/header"
                    )
                    missing.append(str(path))
                    continue

            if path.is_file():
                existing.append(str(path))
            else:
                missing.append(str(path))

        payload_members: list[dict[str, Any]] = []
        payload_names: set[str] = {Path(path).name for path in existing}
        for item in inline_payloads or []:
            if not isinstance(item, dict):
                continue
            member_name = Path(str(item.get("name") or "").strip()).name
            content_b64 = str(item.get("content_b64") or "").strip()
            if not member_name or not content_b64:
                continue
            if member_name in payload_names:
                continue
            try:
                payload_bytes = base64.b64decode(content_b64, validate=True)
            except Exception:
                missing.append(f"inline:{member_name}")
                continue
            payload_members.append({"name": member_name, "bytes": payload_bytes})
            payload_names.add(member_name)

        if not existing and not payload_members:
            return {"archive_path": None, "members": [], "missing": missing}

        archive_path_obj.parent.mkdir(parents=True, exist_ok=True)

        members: list[str] = []
        try:
            with zipfile.ZipFile(
                tmp_archive_path, mode="w", compression=zipfile.ZIP_DEFLATED
            ) as zf:
                for file_path in existing:
                    arcname = Path(file_path).name
                    zf.write(file_path, arcname=arcname)
                    members.append(arcname)
                for item in payload_members:
                    zf.writestr(item["name"], item["bytes"])
                    members.append(item["name"])

            tmp_archive_path.replace(archive_path_obj)
        except Exception:
            try:
                if tmp_archive_path.exists():
                    tmp_archive_path.unlink()
            except OSError:
                pass
            raise

        for file_path in existing:
            try:
                file_path_obj = Path(file_path).resolve()
                if file_path_obj != archive_path_obj:
                    file_path_obj.unlink()
            except OSError:
                pass

        return {
            "archive_path": str(archive_path_obj),
            "members": members,
            "missing": missing,
            "repaired": repaired,
        }

    def _build_active_loadstep_status(
        self, ls_config: LoadstepConfig, now: datetime
    ) -> dict[str, Any]:
        """Return a status payload for an active loadstep."""
        elapsed_seconds = max(0.0, (now - ls_config.timestamp).total_seconds())
        remaining_seconds = max(0.0, ls_config.duration_seconds - elapsed_seconds)
        return {
            "name": ls_config.name,
            "parameters": list(ls_config.parameters),
            "duration_seconds": ls_config.duration_seconds,
            "started_at": ls_config.timestamp.isoformat(),
            "elapsed_seconds": round(elapsed_seconds, 3),
            "remaining_seconds": round(remaining_seconds, 3),
        }

    def _resolve_output_dir(self, output_dir: str | None = None) -> str:
        if output_dir and str(output_dir).strip():
            return str(Path(str(output_dir).strip()).resolve())
        if self.config and self.config.output_dir:
            return str(Path(self.config.output_dir).resolve())
        return str(Path(DEFAULT_MEASUREMENTS_DIR).resolve())

    def _safe_archive_name(self, archive_name: str) -> str:
        name = Path(str(archive_name or "").strip()).name
        if not name:
            raise ValueError("archive_name is required")
        if not name.endswith(".archive.zip"):
            raise ValueError("archive_name must end with '.archive.zip'")
        return name

    def resolve_archive_path(
        self, *, archive_name: str, output_dir: str | None = None
    ) -> dict[str, Any]:
        try:
            name = self._safe_archive_name(archive_name)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        archive_dir = self._resolve_output_dir(output_dir)
        path = Path(archive_dir) / name
        if not path.is_file():
            return {"ok": False, "error": "archive not found"}
        return {
            "ok": True,
            "name": name,
            "path": str(path),
            "output_dir": archive_dir,
        }

    def list_archives(
        self, *, output_dir: str | None = None, limit: int = 200
    ) -> dict[str, Any]:
        archive_dir = self._resolve_output_dir(output_dir)
        archive_dir_path = Path(archive_dir)
        archive_dir_path.mkdir(parents=True, exist_ok=True)

        entries: list[dict[str, Any]] = []
        for path in archive_dir_path.iterdir():
            name = path.name
            if not name.endswith(".archive.zip"):
                continue
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append(
                {
                    "name": name,
                    "size_bytes": int(stat.st_size),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
            )

        entries.sort(key=lambda item: item["modified_at"], reverse=True)
        max_items = max(1, min(int(limit), 1000))
        entries = entries[:max_items]

        usage = shutil.disk_usage(archive_dir_path)
        return {
            "ok": True,
            "archives": entries,
            "disk": {
                "total_bytes": int(usage.total),
                "used_bytes": int(usage.used),
                "free_bytes": int(usage.free),
            },
        }

    def delete_archive(
        self, *, archive_name: str, output_dir: str | None = None
    ) -> dict[str, Any]:
        resolved = self.resolve_archive_path(
            archive_name=archive_name, output_dir=output_dir
        )
        if not resolved.get("ok"):
            return resolved

        path = resolved["path"]
        try:
            Path(path).unlink()
        except OSError as exc:
            return {"ok": False, "error": f"failed to delete archive: {exc}"}
        return {"ok": True, "deleted": resolved["name"]}

    def _downsample_rows(
        self, rows: list[dict[str, Any]], max_points: int
    ) -> list[dict[str, Any]]:
        if max_points <= 0 or len(rows) <= max_points:
            return rows
        if max_points == 1:
            return [rows[-1]]
        step = (len(rows) - 1) / float(max_points - 1)
        selected = [rows[round(idx * step)] for idx in range(max_points - 1)]
        selected.append(rows[-1])
        deduped: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for item in selected:
            marker = id(item)
            if marker in seen_ids:
                continue
            seen_ids.add(marker)
            deduped.append(item)
        return deduped

    def _load_jsonl_rows(self, text: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def _load_csv_rows(self, text: str) -> list[dict[str, Any]]:
        reader = csv.DictReader(io.StringIO(text))
        rows: list[dict[str, Any]] = []
        for row in reader:
            if not isinstance(row, dict):
                continue
            rows.append({str(k): v for k, v in row.items() if k is not None})
        return rows

    def _load_parquet_rows(self, data: bytes) -> list[dict[str, Any]]:
        try:
            import pyarrow.parquet as pq
        except Exception as exc:
            raise RuntimeError("parquet archive view requires pyarrow") from exc
        table = pq.read_table(io.BytesIO(data))
        return [dict(item) for item in table.to_pylist()]

    def _parse_measurement_member(
        self, *, member_name: str, payload: bytes, max_points: int
    ) -> dict[str, Any]:
        lower = member_name.lower()
        if lower.endswith(".jsonl"):
            rows = self._load_jsonl_rows(payload.decode("utf-8", errors="replace"))
            fmt = "jsonl"
        elif lower.endswith(".csv"):
            rows = self._load_csv_rows(payload.decode("utf-8", errors="replace"))
            fmt = "csv"
        elif lower.endswith(".parquet"):
            rows = self._load_parquet_rows(payload)
            fmt = "parquet"
        else:
            return {
                "member": member_name,
                "format": "unknown",
                "parameters": [],
                "sample_count": 0,
                "samples": [],
            }

        normalized: list[dict[str, Any]] = []
        parameter_names: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            timestamp = row.get("timestamp")
            try:
                ts = float(timestamp) if timestamp is not None else None
            except Exception:
                ts = None
            dt_value = row.get("datetime")
            dt_text = str(dt_value) if dt_value is not None else ""

            if isinstance(row.get("data"), dict):
                data_map = {str(k): v for k, v in row.get("data", {}).items()}
            else:
                data_map = {}
                for key, value in row.items():
                    if key in {"timestamp", "datetime"}:
                        continue
                    data_map[str(key)] = value
            parameter_names.update(data_map.keys())
            normalized.append(
                {
                    "timestamp": ts,
                    "datetime": dt_text,
                    "data": data_map,
                }
            )

        normalized = self._downsample_rows(normalized, max_points=max_points)
        return {
            "member": member_name,
            "format": fmt,
            "parameters": sorted(parameter_names),
            "sample_count": len(rows),
            "samples": normalized,
        }

    def _parse_loadsteps_member(
        self, *, member_name: str, payload: bytes
    ) -> dict[str, Any]:
        lower = member_name.lower()
        if lower.endswith(".jsonl"):
            rows = self._load_jsonl_rows(payload.decode("utf-8", errors="replace"))
            fmt = "jsonl"
        elif lower.endswith(".csv"):
            rows = self._load_csv_rows(payload.decode("utf-8", errors="replace"))
            fmt = "csv"
        elif lower.endswith(".parquet"):
            rows = self._load_parquet_rows(payload)
            fmt = "parquet"
        else:
            rows = []
            fmt = "unknown"

        items: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            average = row.get("average")
            if isinstance(average, str):
                try:
                    average = json.loads(average)
                except Exception:
                    average = {}
            average = average if isinstance(average, dict) else {}
            try:
                duration = float(row.get("duration_seconds") or 0.0)
            except Exception:
                duration = 0.0
            items.append(
                {
                    "name": str(row.get("name") or ""),
                    "duration_seconds": duration,
                    "timestamp": str(row.get("timestamp") or ""),
                    "average": average,
                }
            )

        return {
            "member": member_name,
            "format": fmt,
            "count": len(items),
            "items": items,
        }

    def view_archive(
        self,
        *,
        archive_name: str,
        output_dir: str | None = None,
        max_points: int = 1500,
    ) -> dict[str, Any]:
        resolved = self.resolve_archive_path(
            archive_name=archive_name, output_dir=output_dir
        )
        if not resolved.get("ok"):
            return resolved

        points_limit = max(50, min(int(max_points), 5000))
        path = resolved["path"]
        members: list[str] = []
        measurement_member = ""
        loadsteps_member = ""
        measurement: dict[str, Any] = {
            "member": "",
            "format": "unknown",
            "parameters": [],
            "sample_count": 0,
            "samples": [],
        }
        loadsteps: dict[str, Any] = {
            "member": "",
            "format": "unknown",
            "count": 0,
            "items": [],
        }

        try:
            with zipfile.ZipFile(path) as zf:
                members = sorted(zf.namelist())
                for member in members:
                    lower = member.lower()
                    if lower.endswith("/"):
                        continue
                    if ".loadsteps." in lower and not loadsteps_member:
                        loadsteps_member = member
                        continue
                    if (
                        lower.endswith((".jsonl", ".csv", ".parquet"))
                        and not measurement_member
                    ):
                        measurement_member = member

                if measurement_member:
                    measurement_payload = zf.read(measurement_member)
                    measurement = self._parse_measurement_member(
                        member_name=measurement_member,
                        payload=measurement_payload,
                        max_points=points_limit,
                    )
                if loadsteps_member:
                    loadstep_payload = zf.read(loadsteps_member)
                    loadsteps = self._parse_loadsteps_member(
                        member_name=loadsteps_member,
                        payload=loadstep_payload,
                    )
        except Exception as exc:
            return {"ok": False, "error": f"failed to inspect archive: {exc}"}

        return {
            "ok": True,
            "archive": {
                "name": resolved.get("name", archive_name),
                "path": resolved.get("path", path),
                "output_dir": resolved.get("output_dir", output_dir),
            },
            "members": members,
            "measurement": measurement,
            "loadsteps": loadsteps,
        }

    def get_status(self) -> dict:
        """Get current runtime status."""
        with self._lock:
            now = datetime.now()
            active_loadsteps = [
                self._build_active_loadstep_status(ls, now)
                for ls in self._active_loadsteps
            ]
            return {
                "backend_connected": self.backend.connected(),
                "recording": self._recording,
                "config": {
                    "parameters": self.config.parameters if self.config else [],
                    "hz": self.config.hz if self.config else 0,
                    "session_name": self.config.session_name if self.config else "",
                    "output_dir": self.config.output_dir if self.config else "",
                    "output_format": self.config.output_format if self.config else "",
                    "include_files": list(self.config.include_files)
                    if self.config
                    else [],
                    "include_payloads": [
                        {
                            "name": item.get("name", ""),
                            "size": int(item.get("size", 0)),
                            "media_type": item.get("media_type"),
                        }
                        for item in (self.config.include_payloads if self.config else [])
                    ],
                }
                if self.config
                else None,
                "samples_recorded": len(self._measurement_data),
                "active_loadsteps": active_loadsteps,
                "active_loadstep_names": [
                    loadstep["name"] for loadstep in active_loadsteps
                ],
                "completed_loadsteps_count": len(self._completed_loadsteps),
                "completed_loadsteps": list(self._completed_loadsteps),
                "missing_parameters": sorted(self._missing_parameters),
                "warnings": list(self._setup_warnings),
            }
