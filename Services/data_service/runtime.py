"""Data logging service runtime.

Records parameter values from parameterDB at a configurable rate,
saves to files, and supports loadstep averaging.
"""

from __future__ import annotations

import os
import time
import threading
import importlib.util
from dataclasses import dataclass, field
from typing import Any
from collections import deque
from datetime import datetime

from .._shared.parameterDB.paremeterDB import SignalStoreBackend
from .storage.writer import FileWriter, FileWriterFactory
from .storage.loadstep import LoadstepAverager


@dataclass
class MeasurementConfig:
    """Configuration for a measurement session."""
    parameters: list[str] = field(default_factory=list)
    hz: float = 10.0  # Recording frequency (1-150 Hz)
    output_dir: str = "data/measurements"
    output_format: str = "parquet"  # "parquet", "csv", or "jsonl"
    session_name: str = ""  # Auto-generated if empty


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

    def run(self) -> None:
        """Main runtime loop - runs in background thread."""
        self._running = True
        last_write_time = time.time()

        while self._running:
            try:
                current_time = time.time()

                if self._recording and self.config:
                    # Calculate time since last recording
                    elapsed = current_time - last_write_time
                    target_interval = 1.0 / self.config.hz

                    if elapsed >= target_interval:
                        self._record_sample()
                        last_write_time = current_time
                        
                        # Check and finalize completed loadsteps
                        self._check_loadsteps()

                # Sleep briefly to avoid busy-waiting
                time.sleep(0.001)

            except Exception as e:
                print(f"Error in recording loop: {e}")
                time.sleep(0.1)

    def stop(self) -> None:
        """Stop the runtime loop."""
        self._running = False

    def setup_measurement(self, parameters: list[str], hz: float = 10.0,
                         output_dir: str = "data/measurements",
                         output_format: str = "parquet",
                         session_name: str = "") -> dict:
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
                session_name=session_name
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
                total_samples = len(self._measurement_data)

                return {
                    "ok": True,
                    "message": f"Recording stopped: {self.config.session_name}",
                    "samples_recorded": total_samples,
                    "file": filepath,
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
            self._completed_loadsteps.append({
                "name": ls_config.name,
                "duration_seconds": ls_config.duration_seconds,
                "average": averaged_data,
                "timestamp": ls_config.timestamp.isoformat()
            })

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
                } if self.config else None,
                "samples_recorded": len(self._measurement_data),
                "active_loadsteps": active_loadsteps,
                "active_loadstep_names": [loadstep["name"] for loadstep in active_loadsteps],
                "completed_loadsteps_count": len(self._completed_loadsteps),
                "completed_loadsteps": list(self._completed_loadsteps),
                "missing_parameters": sorted(self._missing_parameters),
                "warnings": list(self._setup_warnings),
            }
