from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from ..loader import PluginRegistry
from ..store import ParameterStore


SNAPSHOT_FORMAT_VERSION = 1


class SnapshotManager:
    """Periodically writes a full store snapshot to disk and can force a final save."""

    def __init__(
        self,
        store: ParameterStore,
        path: str | Path,
        *,
        interval_s: float = 5.0,
        enabled: bool = True,
    ) -> None:
        self.store = store
        self.path = Path(path)
        self.interval_s = max(0.5, float(interval_s))
        self.enabled = enabled
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.RLock()
        self._last_saved_revision = -1
        self._last_saved_at: float | None = None

    def start(self) -> None:
        if not self.enabled:
            return
        with self._state_lock:
            if self._thread is not None:
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, name="ParameterSnapshotManager", daemon=True)
            self._thread.start()

    def stop(self, *, save_final: bool = True) -> None:
        thread: threading.Thread | None
        with self._state_lock:
            self._stop_event.set()
            thread = self._thread
            self._thread = None
        if thread is not None:
            thread.join(timeout=2.0)
        if self.enabled and save_final:
            self.save_now(force=True)

    def stats(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "enabled": self.enabled,
                "path": str(self.path),
                "interval_s": self.interval_s,
                "last_saved_revision": self._last_saved_revision,
                "last_saved_at": self._last_saved_at,
            }

    def save_now(self, *, force: bool = False) -> bool:
        if not self.enabled:
            return False

        revision = self.store.revision()
        with self._state_lock:
            if not force and revision == self._last_saved_revision:
                return False

        payload = build_snapshot_payload(self.store)
        write_snapshot_file(self.path, payload)

        with self._state_lock:
            self._last_saved_revision = revision
            self._last_saved_at = time.time()
        return True

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self.interval_s):
            try:
                self.save_now()
            except Exception:
                # Keep snapshot persistence non-fatal for the service.
                pass


def build_snapshot_payload(store: ParameterStore) -> dict[str, Any]:
    return {
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "saved_at": time.time(),
        "store_revision": store.revision(),
        "parameters": store.records(),
    }


def write_snapshot_file(path: str | Path, payload: dict[str, Any]) -> None:
    snapshot_path = Path(path)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = snapshot_path.with_suffix(snapshot_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    tmp_path.replace(snapshot_path)


def load_snapshot_file(path: str | Path) -> dict[str, Any] | None:
    snapshot_path = Path(path)
    if not snapshot_path.exists():
        return None
    with snapshot_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError("Snapshot file does not contain an object")
    return payload


def load_snapshot_into_store(
    store: ParameterStore,
    registry: PluginRegistry,
    path: str | Path,
) -> int:
    payload = load_snapshot_file(path)
    if payload is None:
        return 0

    version = payload.get("format_version")
    if version != SNAPSHOT_FORMAT_VERSION:
        raise ValueError(f"Unsupported snapshot format version: {version!r}")

    parameters = payload.get("parameters", {})
    if not isinstance(parameters, dict):
        raise ValueError("Snapshot 'parameters' must be an object")

    restored = 0
    for name, raw_record in parameters.items():
        if not isinstance(name, str) or not isinstance(raw_record, dict):
            continue

        parameter_type = raw_record.get("parameter_type")
        if not isinstance(parameter_type, str) or not parameter_type:
            continue

        spec = registry.get(parameter_type)
        param = spec.create(
            name,
            config=dict(raw_record.get("config") or {}),
            value=raw_record.get("value"),
            metadata=dict(raw_record.get("metadata") or {}),
        )
        store.add(param)
        param.on_added(store)
        state = raw_record.get("state")
        if isinstance(state, dict):
            param.state.clear()
            param.state.update(state)
        restored += 1

    return restored
