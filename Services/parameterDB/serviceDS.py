from __future__ import annotations

import json
import os
import signal
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .._shared.cli import parse_args
from .._shared.storage_paths import default_sources_dir
from .parameterdb_core.client import SignalClient, SignalSession
from .parameterdb_sources.admin_server import SourceAdminTCPServer
from .parameterdb_sources.base import DataSourceBase
from .parameterdb_sources.loader import DataSourceRegistry, autodiscover_sources


@dataclass(slots=True)
class SourceRecord:
    name: str
    source_type: str
    config: dict[str, Any]
    config_path: Path


@dataclass(slots=True)
class SourceInstance:
    record: SourceRecord
    source: DataSourceBase
    session: SignalSession
    thread: threading.Thread


class SourceRunner:
    def __init__(
        self,
        base_client: SignalClient,
        registry: DataSourceRegistry,
        *,
        config_dir: str,
    ) -> None:
        self.base_client = base_client
        self.registry = registry
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.records: dict[str, SourceRecord] = {}
        self.instances: dict[str, SourceInstance] = {}

    def _record_from_payload(
        self, payload: dict[str, Any], *, config_path: Path
    ) -> SourceRecord:
        name = str(payload["name"]).strip()
        source_type = str(payload["source_type"]).strip()
        config = dict(payload.get("config") or {})
        if not name or not source_type:
            raise ValueError(
                "Source config must include non-empty name and source_type"
            )
        self.registry.get(source_type)
        return SourceRecord(
            name=name, source_type=source_type, config=config, config_path=config_path
        )

    def _config_path_for_name(self, name: str) -> Path:
        safe = "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in name)
        return self.config_dir / f"{safe}.json"

    def _write_record(self, record: SourceRecord) -> None:
        payload = {
            "name": record.name,
            "source_type": record.source_type,
            "config": record.config,
        }
        data = json.dumps(payload, indent=2, sort_keys=True)

        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{record.config_path.name}.",
            suffix=".tmp",
            dir=str(record.config_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())

            Path(tmp_name).replace(record.config_path)

            try:
                dir_fd = os.open(str(record.config_path.parent), os.O_RDONLY)
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

    def _cleanup_stale_config_tmp_files(self) -> None:
        for tmp_path in self.config_dir.glob("*.json.*.tmp"):
            try:
                if tmp_path.is_file():
                    tmp_path.unlink()
            except OSError:
                pass

    def _build_instance(self, record: SourceRecord) -> SourceInstance:
        spec = self.registry.get(record.source_type)
        session = self.base_client.session()
        session.connect()
        source = spec.create(record.name, session, config=record.config)
        thread = threading.Thread(
            target=source.run, name=f"source:{record.name}", daemon=True
        )
        return SourceInstance(
            record=record, source=source, session=session, thread=thread
        )

    def _start_instance_locked(self, record: SourceRecord) -> None:
        if record.name in self.instances:
            raise ValueError(f"Source '{record.name}' already running")
        inst = self._build_instance(record)
        inst.source.start()
        inst.thread.start()
        self.instances[record.name] = inst

    def _stop_instance_locked(self, name: str) -> None:
        inst = self.instances.pop(name, None)
        if inst is None:
            return
        inst.source.stop()
        inst.thread.join(timeout=2.0)
        inst.session.close()

    def load_config_dir(self) -> list[SourceRecord]:
        self._cleanup_stale_config_tmp_files()
        loaded: list[SourceRecord] = []
        for cfg_path in sorted(self.config_dir.glob("*.json")):
            payload = json.loads(cfg_path.read_text(encoding="utf-8"))
            record = self._record_from_payload(payload, config_path=cfg_path)
            loaded.append(record)
        with self._lock:
            for record in loaded:
                self.records[record.name] = record
        return loaded

    def start_all(self) -> None:
        with self._lock:
            for record in sorted(self.records.values(), key=lambda item: item.name):
                self._start_instance_locked(record)

    def stop_all(self) -> None:
        with self._lock:
            names = list(self.instances)
        for name in names:
            with self._lock:
                self._stop_instance_locked(name)

    def list_sources(self) -> dict[str, Any]:
        with self._lock:
            result: dict[str, Any] = {}
            for name, record in sorted(self.records.items()):
                result[name] = {
                    "name": record.name,
                    "source_type": record.source_type,
                    "config": dict(record.config),
                    "running": name in self.instances
                    and self.instances[name].thread.is_alive(),
                    "config_path": str(record.config_path),
                }
            return result

    def get_source_record(self, name: str) -> dict[str, Any]:
        with self._lock:
            record = self.records.get(name)
            if record is None:
                raise KeyError(f"Unknown source '{name}'")
            return {
                "name": record.name,
                "source_type": record.source_type,
                "config": dict(record.config),
                "config_path": str(record.config_path),
                "running": name in self.instances
                and self.instances[name].thread.is_alive(),
            }

    def create_source(
        self, name: str, source_type: str, *, config: dict[str, Any]
    ) -> None:
        record = SourceRecord(
            name=name,
            source_type=source_type,
            config=dict(config),
            config_path=self._config_path_for_name(name),
        )
        self.registry.get(source_type)
        with self._lock:
            if name in self.records:
                raise ValueError(f"Source '{name}' already exists")
            self._write_record(record)
            self.records[name] = record
            self._start_instance_locked(record)

    def update_source(self, name: str, *, config: dict[str, Any]) -> None:
        with self._lock:
            existing = self.records.get(name)
            if existing is None:
                raise KeyError(f"Unknown source '{name}'")
            updated = SourceRecord(
                name=existing.name,
                source_type=existing.source_type,
                config=dict(config),
                config_path=existing.config_path,
            )
            self._stop_instance_locked(name)
            self._write_record(updated)
            self.records[name] = updated
            self._start_instance_locked(updated)

    def delete_source(self, name: str) -> None:
        with self._lock:
            record = self.records.pop(name, None)
            if record is None:
                raise KeyError(f"Unknown source '{name}'")
            self._stop_instance_locked(name)
            try:
                record.config_path.unlink(missing_ok=True)
            except TypeError:
                if record.config_path.exists():
                    record.config_path.unlink()


def _builtin_source_root() -> str:
    return str(Path(__file__).resolve().parent / "sourceDefs")


def _default_config_dir() -> str:
    return default_sources_dir()


def main() -> None:
    args = parse_args("Datasource Service")

    base_client = SignalClient(args.backend_host, args.backend_port, timeout=5.0)
    registry = DataSourceRegistry()

    builtin_root = _builtin_source_root()
    loaded_builtin = autodiscover_sources(builtin_root, registry)

    print(f"[INFO] Built-in source root: {builtin_root}")
    print(f"[INFO] Loaded built-in source types: {loaded_builtin}")

    runner = SourceRunner(base_client, registry, config_dir=_default_config_dir())
    records = runner.load_config_dir()

    print(f"[INFO] Loaded source instances: {[r.name for r in records]}")

    runner.start_all()
    admin_server = SourceAdminTCPServer("127.0.0.1", 8766, runner)
    admin_thread = threading.Thread(target=admin_server.serve_forever, daemon=True)
    admin_thread.start()
    print("[INFO] Source admin running on 127.0.0.1:8766")

    def shutdown(*_args: Any) -> None:
        print("[INFO] Stopping data sources...")
        admin_server.shutdown()
        admin_server.server_close()
        runner.stop_all()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
