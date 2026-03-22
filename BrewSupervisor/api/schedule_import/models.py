from __future__ import annotations

from dataclasses import dataclass
from typing import Any

@dataclass(slots=True)
class ParsedWorkbook:
    schedule: dict[str, Any]
    source_filename: str