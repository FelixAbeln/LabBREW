
from __future__ import annotations

import json
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

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            return None

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
