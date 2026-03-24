from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any


class AuditLogger:
    """Append-only JSONL audit logger.

    Intended for connection/access/change logging, not high-volume scan data.
    """

    def __init__(self, path: str | Path, *, enabled: bool = True, audit_external_writes: bool = False) -> None:
        self.path = Path(path)
        self.enabled = enabled
        self.audit_external_writes = audit_external_writes
        self._lock = threading.RLock()
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, *, category: str, action: str, **data: Any) -> None:
        if not self.enabled:
            return
        record = {
            "ts": time.time(),
            "category": category,
            "action": action,
            **data,
        }
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
