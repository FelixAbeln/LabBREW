"""Data logging service runtime.

Records parameter values from parameterDB at a configurable rate,
saves to files, and supports loadstep averaging.
"""

from __future__ import annotations

import os
import json
import shutil
import time
import threading
import importlib.util
import tempfile
import zipfile
from dataclasses import dataclass, field
from typing import Any
from collections import deque
from datetime import datetime

from .._shared.parameterDB.paremeterDB import SignalStoreBackend
from .storage.writer import FileWriter, FileWriterFactory
from .storage.loadstep import LoadstepAverager

# Sleep durations for the recording loop
_IDLE_SLEEP_INTERVAL = 0.1      # 100ms when not recording (reduces idle CPU usage)
_MIN_SAMPLE_SLEEP = 0.0005      # 0.5ms minimum sleep floor to prevent busy-waiting


@dataclass
class MeasurementConfig:
    """Configuration for a measurement session."""
    parameters: list[str] = field(default_factory=list)
    hz: float = 10.0  # Recording frequency (1-150 Hz)
    output_dir: str = "data/measurements"
    output_format: str = "parquet"  # "parquet", "csv", or "jsonl"
    session_name: str = ""  # Auto-generated if empty
    include_files: list[str] = field(default_factory=list)


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

    def run(self) -> None:
        """Main runtime loop - runs in background thread."""
        self._running = True
        last_write_time = time.time()

        while self._running:
            try:
                current_time = time.time()
                sleep_time = _IDLE_SLEEP_INTERVAL  # Default: 100ms when not recording

                # Synchronize access to shared measurement/loadstep state with API handlers
                with self._lock:
                    if self._recording and self.config:
                        # Calculate time since last recording
                        elapsed = current_time - last_write_time
                        target_interval = 1.0 / self.config.hz

                        if elapsed >= target_interval:
                            self._record_sample()
                            last_write_time = current_time

                            # Check and finalize completed loadsteps
                            self._check_loadsteps()

                            # Sleep until the next sample is due
                            sleep_time = target_interval
                        else:
                            # Sleep for remaining time until the next sample
                            sleep_time = max(_MIN_SAMPLE_SLEEP, target_interval - elapsed)

                time.sleep(sleep_time)

            except Exception as e:
                print(f"Error in recording loop: {e}")
                time.sleep(0.1)

    def stop(self) -> None:
        """Stop the runtime loop."""
        self._running = False

    def setup_measurement(self, parameters: list[str], hz: float = 10.0,
                         output_dir: str = "data/measurements",
                         output_format: str = "parquet",
                         session_name: str = "",
                         include_files: list[str] | None = None) -> dict:
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
                unavailable = sorted(param for param in parameters if param not in available_params)
                if unavailable:
                    self._setup_warnings.append(
                        f"Parameters not currently available in parameterDB: {unavailable}. Missing values will be recorded as null until they appear."
                    )
            else:
                self._setup_warnings.append(
                    "parameterDB snapshot is currently empty. Setup accepted, but samples may be null until values appear."
                )

            # Generate session name if not provided
            if not session_name:
                session_name = f"measurement_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            selected_format = str(output_format or "parquet").lower()
            if selected_format == "parquet" and importlib.util.find_spec("pyarrow") is None:
                self._setup_warnings.append(
                    "pyarrow is not installed; falling back from parquet to jsonl so data is persisted."
                )
                selected_format = "jsonl"

            self.config = MeasurementConfig(
                parameters=parameters,
                hz=hz,
                output_dir=output_dir,
                output_format=selected_format,
                session_name=session_name,
                include_files=[str(item) for item in (include_files or []) if str(item).strip()],
            )
            self._loadsteps_archive_format = selected_format
            self._loadsteps_archive_path = os.path.join(
                output_dir,
                f"{session_name}.loadsteps.{self._loadsteps_archive_format}",
            )

            # Initialize file writer
            os.makedirs(output_dir, exist_ok=True)
            self._file_writer = FileWriterFactory.create(
                format_type=selected_format,
                output_dir=output_dir,
                session_name=session_name,
                parameters=parameters
            )

            self._measurement_data = deque(maxlen=10000)  # Circular buffer for ~100 seconds at 100 Hz
            self._start_time = None

            return {
                "ok": True,
                "session_name": session_name,
                "parameters": parameters,
                "hz": hz,
                "output_format": selected_format,
                "output_dir": output_dir,
                "include_files": list(self.config.include_files),
                "warnings": list(self._setup_warnings),
            }

    def measure_start(self) -> dict:
        """Start recording measurements.
        
        Returns:
            Status dictionary
        """
        with self._lock:
            if not self.config:
                return {"ok": False, "error": "Measurement not configured. Call setup_measurement first."}

            if self._recording:
                return {"ok": False, "error": "Recording already in progress"}

            self._recording = True
            self._start_time = time.time()
            self._measurement_data.clear()
            self._active_loadsteps = []
            self._completed_loadsteps = []
            self._missing_parameters = set()
            self._initialize_loadstep_archive_file()
            
            return {
                "ok": True,
                "message": f"Started recording session: {self.config.session_name}"
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
                total_samples = getattr(self._file_writer, "sample_count", len(self._measurement_data))
                try:
                    archive = self._build_session_archive(
                        measurement_file=filepath,
                        loadsteps_file=self._loadsteps_archive_path,
                        extra_files=self.config.include_files if self.config else [],
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

    def take_loadstep(self, duration_seconds: float = 30.0, 
                     loadstep_name: str = "", parameters: list[str] | None = None) -> dict:
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
                return {"ok": False, "error": f"duration_seconds must be greater than 0, got {duration_seconds}"}

            # Use measurement parameters if not specified
            params = parameters if parameters else self.config.parameters

            # Generate loadstep name if not provided
            if not loadstep_name:
                loadstep_name = f"loadstep_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            ls_config = LoadstepConfig(
                name=loadstep_name,
                parameters=params,
                duration_seconds=duration_seconds,
                timestamp=datetime.now()
            )

            self._active_loadsteps.append(ls_config)

            # Create averager for this loadstep
            self._loadstep_averagers[loadstep_name] = LoadstepAverager(
                parameters=params,
                duration_seconds=duration_seconds
            )

            return {
                "ok": True,
                "loadstep_name": loadstep_name,
                "duration_seconds": duration_seconds,
                "parameters": params
            }

    def _record_sample(self) -> None:
        """Record a single sample of all configured parameters."""
        try:
            sample = {
                "timestamp": time.time() - (self._start_time or 0),
                "datetime": datetime.now().isoformat(),
                "data": {}
            }

            # Read current values from parameterDB
            for param in self.config.parameters:
                value = self.backend.get_value(param)
                if value is None:
                    self._missing_parameters.add(param)
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
        current_time = time.time() - (self._start_time or 0)
        completed = []

        for ls_config in self._active_loadsteps:
            elapsed = (datetime.now() - ls_config.timestamp).total_seconds()
            
            if elapsed >= ls_config.duration_seconds:
                self._finalize_loadstep(ls_config)
                completed.append(ls_config.name)

        # Remove completed loadsteps
        self._active_loadsteps = [ls for ls in self._active_loadsteps if ls.name not in completed]

    def _finalize_loadstep(self, ls_config: LoadstepConfig) -> None:
        """Finalize a loadstep and store its averaged data."""
        averager = self._loadstep_averagers.get(ls_config.name)
        if averager:
            averaged_data = averager.get_average()
            loadstep_record = {
                "name": ls_config.name,
                "duration_seconds": ls_config.duration_seconds,
                "average": averaged_data,
                "timestamp": ls_config.timestamp.isoformat()
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
            if self._loadsteps_archive_format == 'jsonl':
                with open(self._loadsteps_archive_path, 'a', encoding='utf-8') as handle:
                    handle.write(json.dumps(loadstep_record, ensure_ascii=False) + '\n')
                return

            if self._loadsteps_archive_format == 'csv':
                average_json = json.dumps(loadstep_record.get('average', {}), ensure_ascii=False)
                row = [
                    str(loadstep_record.get('name', '')),
                    str(loadstep_record.get('duration_seconds', '')),
                    str(loadstep_record.get('timestamp', '')),
                    average_json,
                ]
                with open(self._loadsteps_archive_path, 'a', encoding='utf-8') as handle:
                    handle.write(','.join(self._csv_escape(item) for item in row) + '\n')
                return

            if self._loadsteps_archive_format == 'parquet':
                import pyarrow as pa
                import pyarrow.parquet as pq

                table = pa.Table.from_pylist([
                    {
                        'name': loadstep_record.get('name'),
                        'duration_seconds': float(loadstep_record.get('duration_seconds') or 0.0),
                        'timestamp': loadstep_record.get('timestamp'),
                        'average_json': json.dumps(loadstep_record.get('average', {}), ensure_ascii=False),
                    }
                ])

                if os.path.exists(self._loadsteps_archive_path):
                    existing = pq.read_table(self._loadsteps_archive_path)
                    table = pa.concat_tables([existing, table])
                pq.write_table(table, self._loadsteps_archive_path)
                return

            # Fallback if an unknown format string appears.
            with open(self._loadsteps_archive_path, 'a', encoding='utf-8') as handle:
                handle.write(json.dumps(loadstep_record, ensure_ascii=False) + '\n')
        except Exception as exc:
            print(f"Error writing loadstep archive record: {exc}")

    def _initialize_loadstep_archive_file(self) -> None:
        """Create/reset the loadstep archive file using the same format as measurement output."""
        if not self._loadsteps_archive_path:
            return
        try:
            if self._loadsteps_archive_format == 'jsonl':
                self._atomic_write_text_file(self._loadsteps_archive_path, '')
                return

            if self._loadsteps_archive_format == 'csv':
                self._atomic_write_text_file(
                    self._loadsteps_archive_path,
                    'name,duration_seconds,timestamp,average_json\n',
                )
                return

            if self._loadsteps_archive_format == 'parquet':
                if os.path.exists(self._loadsteps_archive_path):
                    os.remove(self._loadsteps_archive_path)
                return

            # Unknown format fallback.
            self._atomic_write_text_file(self._loadsteps_archive_path, '')
        except Exception as exc:
            print(f"Error initializing loadstep archive file: {exc}")

    def _atomic_write_text_file(self, path: str, text: str) -> None:
        """Write a full text file atomically to avoid partial content on crashes."""
        target = os.path.abspath(path)
        target_dir = os.path.dirname(target) or '.'
        os.makedirs(target_dir, exist_ok=True)

        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{os.path.basename(target)}.",
            suffix='.tmp',
            dir=target_dir,
        )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(tmp_name, target)

            try:
                dir_fd = os.open(target_dir, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
        except Exception:
            try:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _csv_escape(self, text: str) -> str:
        """Escape a CSV value with quotes when needed."""
        value = str(text)
        if any(ch in value for ch in [',', '"', '\n', '\r']):
            return '"' + value.replace('"', '""') + '"'
        return value

    def _build_session_archive(self, *, measurement_file: str, loadsteps_file: str, extra_files: list[str]) -> dict[str, Any]:
        """Create a single archive for measurement outputs and optional sidecar files."""
        if not self.config:
            return {"archive_path": None, "members": [], "missing": []}

        output_dir = os.path.abspath(self.config.output_dir)
        archive_path = os.path.join(output_dir, f"{self.config.session_name}.archive.zip")
        tmp_archive_path = f"{archive_path}.tmp"

        candidates = [measurement_file, loadsteps_file, *list(extra_files or [])]
        existing: list[str] = []
        missing: list[str] = []
        seen: set[str] = set()
        for raw in candidates:
            path = os.path.abspath(str(raw or '').strip())
            if not path or path in seen:
                continue
            seen.add(path)
            if os.path.isfile(path):
                existing.append(path)
            else:
                missing.append(path)

        if not existing:
            return {"archive_path": None, "members": [], "missing": missing}

        os.makedirs(output_dir, exist_ok=True)

        members: list[str] = []
        try:
            with zipfile.ZipFile(tmp_archive_path, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
                for file_path in existing:
                    arcname = os.path.basename(file_path)
                    zf.write(file_path, arcname=arcname)
                    members.append(arcname)

            os.replace(tmp_archive_path, archive_path)
        except Exception:
            try:
                if os.path.exists(tmp_archive_path):
                    os.remove(tmp_archive_path)
            except OSError:
                pass
            raise

        # Best-effort cleanup: keep only the archive by removing included source files.
        for file_path in existing:
            try:
                if os.path.abspath(file_path) != os.path.abspath(archive_path):
                    os.remove(file_path)
            except OSError:
                pass

        return {"archive_path": archive_path, "members": members, "missing": missing}

    def _build_active_loadstep_status(self, ls_config: LoadstepConfig, now: datetime) -> dict[str, Any]:
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
            return os.path.abspath(str(output_dir).strip())
        if self.config and self.config.output_dir:
            return os.path.abspath(self.config.output_dir)
        return os.path.abspath("data/measurements")

    def _safe_archive_name(self, archive_name: str) -> str:
        name = os.path.basename(str(archive_name or "").strip())
        if not name:
            raise ValueError("archive_name is required")
        if not name.endswith(".archive.zip"):
            raise ValueError("archive_name must end with '.archive.zip'")
        return name

    def resolve_archive_path(self, *, archive_name: str, output_dir: str | None = None) -> dict[str, Any]:
        try:
            name = self._safe_archive_name(archive_name)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        archive_dir = self._resolve_output_dir(output_dir)
        path = os.path.join(archive_dir, name)
        if not os.path.isfile(path):
            return {"ok": False, "error": "archive not found"}
        return {"ok": True, "name": name, "path": path, "output_dir": archive_dir}

    def list_archives(self, *, output_dir: str | None = None, limit: int = 200) -> dict[str, Any]:
        archive_dir = self._resolve_output_dir(output_dir)
        os.makedirs(archive_dir, exist_ok=True)

        entries: list[dict[str, Any]] = []
        for name in os.listdir(archive_dir):
            if not name.endswith(".archive.zip"):
                continue
            path = os.path.join(archive_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                stat = os.stat(path)
            except OSError:
                continue
            entries.append({
                "name": name,
                "size_bytes": int(stat.st_size),
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })

        entries.sort(key=lambda item: item["modified_at"], reverse=True)
        max_items = max(1, min(int(limit), 1000))
        entries = entries[:max_items]

        usage = shutil.disk_usage(archive_dir)
        return {
            "ok": True,
            "archives": entries,
            "disk": {
                "total_bytes": int(usage.total),
                "used_bytes": int(usage.used),
                "free_bytes": int(usage.free),
            },
        }

    def delete_archive(self, *, archive_name: str, output_dir: str | None = None) -> dict[str, Any]:
        resolved = self.resolve_archive_path(archive_name=archive_name, output_dir=output_dir)
        if not resolved.get("ok"):
            return resolved

        path = resolved["path"]
        try:
            os.remove(path)
        except OSError as exc:
            return {"ok": False, "error": f"failed to delete archive: {exc}"}
        return {"ok": True, "deleted": resolved["name"]}

    def get_status(self) -> dict:
        """Get current runtime status."""
        with self._lock:
            now = datetime.now()
            active_loadsteps = [self._build_active_loadstep_status(ls, now) for ls in self._active_loadsteps]
            return {
                "backend_connected": self.backend.connected(),
                "recording": self._recording,
                "config": {
                    "parameters": self.config.parameters if self.config else [],
                    "hz": self.config.hz if self.config else 0,
                    "session_name": self.config.session_name if self.config else "",
                    "output_dir": self.config.output_dir if self.config else "",
                    "output_format": self.config.output_format if self.config else "",
                    "include_files": list(self.config.include_files) if self.config else [],
                } if self.config else None,
                "samples_recorded": len(self._measurement_data),
                "active_loadsteps": active_loadsteps,
                "active_loadstep_names": [loadstep["name"] for loadstep in active_loadsteps],
                "completed_loadsteps_count": len(self._completed_loadsteps),
                "completed_loadsteps": list(self._completed_loadsteps),
                "missing_parameters": sorted(self._missing_parameters),
                "warnings": list(self._setup_warnings),
            }
