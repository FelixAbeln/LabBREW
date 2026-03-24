
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ScheduleDefinition


@dataclass(slots=True)
class InMemoryScheduleRepository:
    _schedule: ScheduleDefinition | None = None

    def get_current(self) -> ScheduleDefinition | None:
        return self._schedule

    def save(self, schedule: ScheduleDefinition) -> None:
        self._schedule = schedule

    def clear(self) -> None:
        self._schedule = None


class JsonScheduleStateStore:
    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            ROOT = Path(__file__).resolve().parents[2]
            STATE_FILE = ROOT / "data" / "schedule_state.json"
        self.path = Path(STATE_FILE)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _cleanup_stale_tmp_files(self) -> None:
        pattern = f"{self.path.name}.*.tmp"
        for tmp_path in self.path.parent.glob(pattern):
            try:
                if tmp_path.is_file():
                    tmp_path.unlink()
            except OSError:
                # Non-fatal: keep startup/load resilient.
                pass

    def load(self) -> dict[str, Any] | None:
        self._cleanup_stale_tmp_files()
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            return None

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(payload, indent=2, sort_keys=True)
        self._cleanup_stale_tmp_files()

        # Atomic write: write to temp file in same directory, fsync, then replace.
        with self._lock:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f"{self.path.name}.",
                suffix=".tmp",
                dir=str(self.path.parent),
            )
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())

                os.replace(tmp_name, self.path)

                # Best-effort durability of directory metadata.
                try:
                    dir_fd = os.open(str(self.path.parent), os.O_RDONLY)
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

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
