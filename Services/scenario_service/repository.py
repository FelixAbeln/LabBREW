from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .._shared.storage_paths import storage_path
from .models import ScenarioPackageDefinition

_STALE_TMP_AGE_SECS: float = 60.0


@dataclass(slots=True)
class InMemoryScenarioRepository:
    _package: ScenarioPackageDefinition | None = None

    def get_current(self) -> ScenarioPackageDefinition | None:
        return self._package

    def save(self, package: ScenarioPackageDefinition) -> None:
        self._package = package

    def clear(self) -> None:
        self._package = None


class JsonScenarioStateStore:
    def __init__(self, path: str | Path | None = None) -> None:
        state_file = storage_path("scenario_state.json") if path is None else Path(path)
        self.path = Path(state_file)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _replace_with_retry(self, tmp_name: str, destination: Path) -> None:
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
        pattern = f"{self.path.name}.*.tmp"
        now = time.time()
        for tmp_path in self.path.parent.glob(pattern):
            try:
                if (
                    tmp_path.is_file()
                    and (now - tmp_path.stat().st_mtime) > _STALE_TMP_AGE_SECS
                ):
                    tmp_path.unlink()
            except OSError:
                pass

    def load(self) -> dict[str, Any] | None:
        with self._lock:
            self._cleanup_stale_tmp_files()
            if not self.path.exists():
                return None
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None

    def save(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, indent=2, sort_keys=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._cleanup_stale_tmp_files()
            fd, tmp_name = tempfile.mkstemp(
                prefix=f"{self.path.name}.",
                suffix=".tmp",
                dir=str(self.path.parent),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())

                try:
                    self._replace_with_retry(tmp_name, self.path)
                except PermissionError:
                    with self.path.open("w", encoding="utf-8") as handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    try:
                        tmp_path = Path(tmp_name)
                        if tmp_path.exists():
                            tmp_path.unlink()
                    except OSError:
                        pass

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
                    tmp_path = Path(tmp_name)
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass
                raise

    def clear(self) -> None:
        with self._lock:
            if self.path.exists():
                self.path.unlink()
