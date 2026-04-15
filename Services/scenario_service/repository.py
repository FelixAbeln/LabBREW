from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .._shared.storage_paths import storage_path
from .models import ScenarioPackageDefinition


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

    def load(self) -> dict[str, Any] | None:
        with self._lock:
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
                Path(tmp_name).replace(self.path)
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
