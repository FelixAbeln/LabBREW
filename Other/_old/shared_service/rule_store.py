from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonRuleStore:
    def __init__(self, root_data: str | Path, filename: str = "safety_rules.json") -> None:
        self.root_data = Path(root_data)
        self.path = self.root_data / filename

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "rules": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, payload: dict[str, Any]) -> Path:
        self.root_data.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.path)
        return self.path
