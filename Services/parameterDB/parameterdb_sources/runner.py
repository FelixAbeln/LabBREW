from __future__ import annotations

import logging
from dataclasses import dataclass
import threading
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

try:
    from ..parameterdb_core.client import SignalClient, SignalSession
except ImportError:
    from parameterdb_core.client import SignalClient, SignalSession

from .base import DataSourceBase
from .loader import DataSourceRegistry
from .repository import FileSourceConfigRepository, SourceConfigRepository, SourceRecord


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
        config_dir: str | None = None,
        repository: SourceConfigRepository | None = None,
    ) -> None:
        self.base_client = base_client
        self.registry = registry
        if repository is None:
            if not config_dir:
                raise ValueError("SourceRunner requires config_dir or repository")
            repository = FileSourceConfigRepository(config_dir)
        self.repository = repository
        self.config_dir = getattr(repository, "config_dir", None)
        self._lock = threading.RLock()
        self.records: dict[str, SourceRecord] = {}
        self.instances: dict[str, SourceInstance] = {}
        self._source_errors: dict[str, str] = {}

    def _record_from_payload(
        self, payload: dict[str, Any], *, storage_ref: str
    ) -> SourceRecord:
        name = str(payload["name"]).strip()
        source_type = str(payload["source_type"]).strip()
        config = dict(payload.get("config") or {})
        if not name or not source_type:
            raise ValueError("Source config must include non-empty name and source_type")
        self.registry.get(source_type)
        return SourceRecord(
            name=name, source_type=source_type, config=config, storage_ref=storage_ref
        )

    def _config_path_for_name(self, name: str) -> Path:
        if not isinstance(self.repository, FileSourceConfigRepository):
            raise RuntimeError("config paths are only available for file-backed repositories")
        return self.repository._config_path_for_name(name)

    def _write_record(self, record: SourceRecord) -> None:
        saved = self.repository.save_record(record)
        record.storage_ref = saved.storage_ref

    def _cleanup_stale_config_tmp_files(self) -> None:
        if isinstance(self.repository, FileSourceConfigRepository):
            self.repository._cleanup_stale_tmp_files()

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
        loaded: list[SourceRecord] = []
        for repo_record in self.repository.load_records():
            try:
                record = self._record_from_payload(
                    {
                        "name": repo_record.name,
                        "source_type": repo_record.source_type,
                        "config": repo_record.config,
                    },
                    storage_ref=repo_record.storage_ref,
                )
                loaded.append(record)
            except Exception as exc:
                LOGGER.warning(
                    "Skipping source config '%s' (type '%s') due to load error: %s",
                    repo_record.name,
                    repo_record.source_type,
                    exc,
                )
                with self._lock:
                    self._source_errors[repo_record.name] = str(exc)
        with self._lock:
            for record in loaded:
                self.records[record.name] = record
                self._source_errors.pop(record.name, None)
        return loaded

    def start_all(self) -> None:
        with self._lock:
            for record in sorted(self.records.values(), key=lambda item: item.name):
                try:
                    self._start_instance_locked(record)
                    self._source_errors.pop(record.name, None)
                except Exception as exc:
                    LOGGER.warning(
                        "Failed to start source '%s': %s; skipping",
                        record.name,
                        exc,
                    )
                    self._source_errors[record.name] = str(exc)

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
                    "running": name in self.instances and self.instances[name].thread.is_alive(),
                    "config_path": record.storage_ref,
                    "error": self._source_errors.get(name),
                }
            for name, error in self._source_errors.items():
                if name not in result:
                    result[name] = {
                        "name": name,
                        "source_type": None,
                        "config": {},
                        "running": False,
                        "config_path": None,
                        "error": error,
                    }
            return result

    def stats(self) -> dict[str, Any]:
        with self._lock:
            running_count = sum(
                1 for item in self.instances.values() if item.thread.is_alive()
            )
            error_names = list(self._source_errors.keys())
            return {
                "source_persistence": dict(self.repository.stats()),
                "source_count": len(self.records),
                "running_count": running_count,
                "source_errors": dict(self._source_errors),
                "error_count": len(error_names),
            }

    def get_source_record(self, name: str) -> dict[str, Any]:
        with self._lock:
            record = self.records.get(name)
            if record is None:
                raise KeyError(f"Unknown source '{name}'")
            return {
                "name": record.name,
                "source_type": record.source_type,
                "config": dict(record.config),
                "config_path": record.storage_ref,
                "running": name in self.instances and self.instances[name].thread.is_alive(),
            }

    def invoke_source_ui_action(
        self,
        source_type: str,
        action: str,
        *,
        payload: dict[str, Any] | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        record = None
        if isinstance(name, str) and name.strip():
            try:
                record = self.get_source_record(name.strip())
            except Exception:
                record = None
        return self.registry.invoke_ui_action(
            source_type,
            action,
            payload=payload or {},
            record=record,
        )

    def create_source(self, name: str, source_type: str, *, config: dict[str, Any]) -> None:
        record = SourceRecord(
            name=name,
            source_type=source_type,
            config=dict(config),
            storage_ref="",
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
                storage_ref=existing.storage_ref,
            )
            self._stop_instance_locked(name)
            self._write_record(updated)
            self.records[name] = updated
            self._start_instance_locked(updated)

    def _delete_owned_parameters(self, record: SourceRecord) -> int:
        removed = 0
        session = self.base_client.session()
        try:
            session.connect()
            described = session.describe()
            if not isinstance(described, dict):
                return 0
            for param_name, param_record in described.items():
                if not isinstance(param_record, dict):
                    continue
                metadata = param_record.get("metadata")
                if not isinstance(metadata, dict):
                    continue
                if str(metadata.get("created_by") or "") != "data_source":
                    continue
                if str(metadata.get("owner") or "") != record.name:
                    continue
                metadata_source_type = str(metadata.get("source_type") or "").strip()
                if metadata_source_type and metadata_source_type != record.source_type:
                    continue
                session.delete_parameter(str(param_name))
                removed += 1
        finally:
            session.close()
        return removed

    def delete_source(self, name: str, *, delete_owned_parameters: bool = False) -> None:
        with self._lock:
            record = self.records.get(name)
            if record is None:
                raise KeyError(f"Unknown source '{name}'")
            self._stop_instance_locked(name)
            if delete_owned_parameters:
                self._delete_owned_parameters(record)
            self.records.pop(name, None)
            self.repository.delete_record(name)
