
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ScheduleDefinition

_STALE_TMP_AGE_SECS: float = 60.0  # Only delete temp files older than this threshold


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
            state_file = ROOT / "data" / "schedule_state.json"
        else:
            state_file = Path(path)
        self.path = Path(state_file)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _replace_with_retry(self, tmp_name: str, destination: Path) -> None:
        """Retry replace on Windows where transient file locks can cause WinError 5."""
        attempts = 6
        delay_s = 0.02
        for attempt in range(attempts):
            try:
                os.replace(tmp_name, destination)
                return
            except PermissionError:
                if attempt >= attempts - 1:
                    raise
                time.sleep(delay_s)
                delay_s *= 2

    def _cleanup_stale_tmp_files(self) -> None:
        """Delete leftover temp files older than _STALE_TMP_AGE_SECS.

        Must be called with ``self._lock`` held so that in-progress temp files
        created by a concurrent ``save()`` (which are younger than the threshold)
        are never deleted.
        """
        pattern = f"{self.path.name}.*.tmp"
        now = time.time()
        for tmp_path in self.path.parent.glob(pattern):
            try:
                if tmp_path.is_file() and (now - tmp_path.stat().st_mtime) > _STALE_TMP_AGE_SECS:
                    tmp_path.unlink()
            except OSError:
                # Non-fatal: keep startup/load resilient.
                pass

    def load(self) -> dict[str, Any] | None:
        with self._lock:
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

        # Atomic write: write to temp file in same directory, fsync, then replace.
        # Stale-tmp cleanup runs inside the lock so a concurrent save's in-progress
        # temp file is never mistakenly deleted.
        with self._lock:
            self._cleanup_stale_tmp_files()
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

                try:
                    self._replace_with_retry(tmp_name, self.path)
                except PermissionError:
                    # Fallback for Windows lock contention: overwrite in-place so
                    # schedule execution can continue even if atomic replace is blocked.
                    with open(self.path, 'w', encoding='utf-8') as handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    try:
                        if os.path.exists(tmp_name):
                            os.unlink(tmp_name)
                    except OSError:
                        pass

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
