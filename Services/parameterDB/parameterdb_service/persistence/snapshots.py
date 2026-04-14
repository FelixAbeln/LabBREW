from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from ...._shared.json_persistence import atomic_write_json
from ...._shared.postgres_persistence import (
    PostgresPersistenceConfig,
    PostgresPersistenceEnvNames,
    build_prefixed_table_names,
    connect_postgres,
    resolve_postgres_persistence_settings,
)
from ..loader import PluginRegistry
from ..store import ParameterStore

SNAPSHOT_FORMAT_VERSION = 1

PERSISTENCE_KIND_ENV = "LABBREW_PARAMETERDB_PERSISTENCE_KIND"
POSTGRES_HOST_ENV = "LABBREW_PARAMETERDB_POSTGRES_HOST"
POSTGRES_PORT_ENV = "LABBREW_PARAMETERDB_POSTGRES_PORT"
POSTGRES_DATABASE_ENV = "LABBREW_PARAMETERDB_POSTGRES_DATABASE"
POSTGRES_USERNAME_ENV = "LABBREW_PARAMETERDB_POSTGRES_USERNAME"
POSTGRES_PASSWORD_ENV = "LABBREW_PARAMETERDB_POSTGRES_PASSWORD"
POSTGRES_TABLE_PREFIX_ENV = "LABBREW_PARAMETERDB_POSTGRES_TABLE_PREFIX"
POSTGRES_SSLMODE_ENV = "LABBREW_PARAMETERDB_POSTGRES_SSLMODE"

PARAMETERDB_PERSISTENCE_ENV_NAMES = PostgresPersistenceEnvNames(
    kind=PERSISTENCE_KIND_ENV,
    host=POSTGRES_HOST_ENV,
    port=POSTGRES_PORT_ENV,
    database=POSTGRES_DATABASE_ENV,
    username=POSTGRES_USERNAME_ENV,
    password=POSTGRES_PASSWORD_ENV,
    table_prefix=POSTGRES_TABLE_PREFIX_ENV,
    sslmode=POSTGRES_SSLMODE_ENV,
)

PostgresSnapshotConfig = PostgresPersistenceConfig


def resolve_snapshot_persistence_settings(
    *,
    kind: str | None = None,
    postgres_host: str | None = None,
    postgres_port: int | None = None,
    postgres_database: str | None = None,
    postgres_username: str | None = None,
    postgres_password: str | None = None,
    postgres_table_prefix: str | None = None,
    postgres_sslmode: str | None = None,
) -> tuple[str, PostgresSnapshotConfig | None]:
    return resolve_postgres_persistence_settings(
        env_names=PARAMETERDB_PERSISTENCE_ENV_NAMES,
        kind=kind,
        postgres_host=postgres_host,
        postgres_port=postgres_port,
        postgres_database=postgres_database,
        postgres_username=postgres_username,
        postgres_password=postgres_password,
        postgres_table_prefix=postgres_table_prefix,
        postgres_sslmode=postgres_sslmode,
    )


def _connect_postgres(config: PostgresSnapshotConfig) -> Any:
    return connect_postgres(config)


def _postgres_table_names(config: PostgresSnapshotConfig) -> tuple[str, str]:
    parameters_table, meta_table = build_prefixed_table_names(
        config,
        "snapshot_parameters",
        "snapshot_meta",
    )
    return parameters_table, meta_table


def _ensure_snapshot_postgres_schema(cursor: Any, config: PostgresSnapshotConfig) -> None:
    parameters_table, meta_table = _postgres_table_names(config)
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {parameters_table} (
            name TEXT PRIMARY KEY,
            parameter_type TEXT NOT NULL,
            value_json TEXT NOT NULL,
            config_json TEXT NOT NULL,
            state_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL
        )
        """
    )
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {meta_table} (
            singleton_id INTEGER PRIMARY KEY,
            format_version INTEGER NOT NULL,
            saved_at DOUBLE PRECISION,
            store_revision BIGINT NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL
        )
        """
    )


class SnapshotManager:
    """Periodically writes a full store snapshot to disk and can force a final save."""

    def __init__(
        self,
        store: ParameterStore,
        path: str | Path,
        *,
        persistence_kind: str = "json",
        postgres_config: PostgresSnapshotConfig | None = None,
        interval_s: float = 5.0,
        enabled: bool = True,
    ) -> None:
        self.store = store
        self.path = Path(path)
        self.persistence_kind = persistence_kind
        self.postgres_config = postgres_config
        self.interval_s = max(0.5, float(interval_s))
        self.enabled = enabled
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.RLock()
        self._last_saved_revision = -1
        self._last_saved_at: float | None = None
        self._last_save_ok: bool | None = None
        self._last_success_at: float | None = None
        self._last_error: str | None = None
        self._last_error_at: float | None = None

    def start(self) -> None:
        if not self.enabled:
            return
        with self._state_lock:
            if self._thread is not None:
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop, name="ParameterSnapshotManager", daemon=True
            )
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
                "backend": self.persistence_kind,
                "path": str(self.path),
                "postgres": None
                if self.postgres_config is None
                else {
                    "host": self.postgres_config.host,
                    "port": self.postgres_config.port,
                    "database": self.postgres_config.database,
                    "table_prefix": self.postgres_config.table_prefix,
                    "sslmode": self.postgres_config.sslmode,
                },
                "interval_s": self.interval_s,
                "last_saved_revision": self._last_saved_revision,
                "last_saved_at": self._last_saved_at,
                "last_save_ok": self._last_save_ok,
                "last_success_at": self._last_success_at,
                "last_error": self._last_error,
                "last_error_at": self._last_error_at,
            }

    def save_now(self, *, force: bool = False) -> bool:
        if not self.enabled:
            return False

        revision = self.store.revision()
        with self._state_lock:
            if not force and revision == self._last_saved_revision:
                return False

        payload = build_snapshot_payload(self.store)
        try:
            if self.persistence_kind == "json":
                write_snapshot_file(self.path, payload)
            elif self.persistence_kind == "postgres":
                write_snapshot_postgres(self._require_postgres_config(), payload)
            else:
                raise ValueError(f"Unsupported persistence kind: {self.persistence_kind!r}")
        except Exception as exc:
            with self._state_lock:
                self._last_save_ok = False
                self._last_error = str(exc)
                self._last_error_at = time.time()
            raise

        with self._state_lock:
            self._last_saved_revision = revision
            self._last_saved_at = time.time()
            self._last_save_ok = True
            self._last_success_at = self._last_saved_at
            self._last_error = None
            self._last_error_at = None
        return True

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self.interval_s):
            with contextlib.suppress(Exception):
                self.save_now()

    def _require_postgres_config(self) -> PostgresSnapshotConfig:
        if self.postgres_config is None:
            raise ValueError("Postgres persistence selected without configuration")
        return self.postgres_config


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
    cleanup_stale_snapshot_tmp_files(snapshot_path)
    atomic_write_json(snapshot_path, payload, indent=2, sort_keys=True)


def write_snapshot_postgres(
    config: PostgresSnapshotConfig,
    payload: dict[str, Any],
) -> None:
    parameters_table, meta_table = _postgres_table_names(config)
    updated_at = time.time()
    rows = [
        (
            name,
            str(record.get("parameter_type") or ""),
            json.dumps(record.get("value")),
            json.dumps(record.get("config") or {}, sort_keys=True),
            json.dumps(record.get("state") or {}, sort_keys=True),
            json.dumps(record.get("metadata") or {}, sort_keys=True),
            updated_at,
        )
        for name, record in sorted((payload.get("parameters") or {}).items())
        if isinstance(name, str) and isinstance(record, dict)
    ]

    with contextlib.closing(_connect_postgres(config)) as connection:
        with connection.cursor() as cursor:
            _ensure_snapshot_postgres_schema(cursor, config)
            cursor.execute(f"DELETE FROM {parameters_table}")
            if rows:
                cursor.executemany(
                    f"""
                    INSERT INTO {parameters_table} (
                        name,
                        parameter_type,
                        value_json,
                        config_json,
                        state_json,
                        metadata_json,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    rows,
                )
            cursor.execute(
                f"""
                INSERT INTO {meta_table} (
                    singleton_id,
                    format_version,
                    saved_at,
                    store_revision,
                    updated_at
                )
                VALUES (1, %s, %s, %s, %s)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    format_version = EXCLUDED.format_version,
                    saved_at = EXCLUDED.saved_at,
                    store_revision = EXCLUDED.store_revision,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    int(payload.get("format_version", SNAPSHOT_FORMAT_VERSION)),
                    payload.get("saved_at"),
                    int(payload.get("store_revision", 0)),
                    updated_at,
                ),
            )
        connection.commit()


def load_snapshot_postgres(config: PostgresSnapshotConfig) -> dict[str, Any] | None:
    parameters_table, meta_table = _postgres_table_names(config)
    with contextlib.closing(_connect_postgres(config)) as connection:
        with connection.cursor() as cursor:
            _ensure_snapshot_postgres_schema(cursor, config)
            cursor.execute(
                f"SELECT format_version, saved_at, store_revision FROM {meta_table} WHERE singleton_id = 1"
            )
            meta_row = cursor.fetchone()
            cursor.execute(
                f"""
                SELECT name, parameter_type, value_json, config_json, state_json, metadata_json
                FROM {parameters_table}
                ORDER BY name
                """
            )
            parameter_rows = cursor.fetchall()

    if meta_row is None and not parameter_rows:
        return None

    payload: dict[str, Any] = {
        "format_version": meta_row[0] if meta_row is not None else SNAPSHOT_FORMAT_VERSION,
        "saved_at": meta_row[1] if meta_row is not None else None,
        "store_revision": meta_row[2] if meta_row is not None else 0,
        "parameters": {},
    }
    parameters = payload["parameters"]
    for row in parameter_rows:
        parameters[row[0]] = {
            "parameter_type": row[1],
            "value": json.loads(row[2]),
            "config": json.loads(row[3]),
            "state": json.loads(row[4]),
            "metadata": json.loads(row[5]),
        }
    return payload


def load_snapshot_file(path: str | Path) -> dict[str, Any] | None:
    snapshot_path = Path(path)
    cleanup_stale_snapshot_tmp_files(snapshot_path)
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

    return load_snapshot_payload_into_store(store, registry, payload)


def load_snapshot_postgres_into_store(
    store: ParameterStore,
    registry: PluginRegistry,
    config: PostgresSnapshotConfig,
) -> int:
    payload = load_snapshot_postgres(config)
    if payload is None:
        return 0

    return load_snapshot_payload_into_store(store, registry, payload)


def restore_snapshot_into_store(
    store: ParameterStore,
    registry: PluginRegistry,
    json_path: str | Path,
    *,
    persistence_kind: str = "json",
    postgres_config: PostgresSnapshotConfig | None = None,
) -> int:
    if persistence_kind == "json":
        return load_snapshot_into_store(store, registry, json_path)
    if persistence_kind == "postgres":
        if postgres_config is None:
            raise ValueError("Postgres persistence selected without configuration")
        return load_snapshot_postgres_into_store(store, registry, postgres_config)
    raise ValueError(f"Unsupported persistence kind: {persistence_kind!r}")


def load_snapshot_payload_into_store(
    store: ParameterStore,
    registry: PluginRegistry,
    payload: dict[str, Any],
) -> int:
    if not isinstance(payload, dict):
        raise ValueError("Snapshot payload does not contain an object")

    version = payload.get("format_version")
    if version != SNAPSHOT_FORMAT_VERSION:
        raise ValueError(f"Unsupported snapshot format version: {version!r}")

    parameters = payload.get("parameters", {})
    if not isinstance(parameters, dict):
        raise ValueError("Snapshot 'parameters' must be an object")

    restored = 0
    skipped_unknown_types: set[str] = set()
    for name, raw_record in parameters.items():
        if not isinstance(name, str) or not isinstance(raw_record, dict):
            continue

        parameter_type = raw_record.get("parameter_type")
        if not isinstance(parameter_type, str) or not parameter_type:
            continue

        try:
            spec = registry.get(parameter_type)
        except ValueError:
            skipped_unknown_types.add(parameter_type)
            continue
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

    if skipped_unknown_types:
        skipped = ", ".join(sorted(skipped_unknown_types))
        print(f"[WARN] Skipping snapshot parameters with unknown types: {skipped}")

    return restored


def cleanup_stale_snapshot_tmp_files(snapshot_path: str | Path) -> None:
    """Best-effort cleanup for orphaned temp files from interrupted atomic writes."""
    path = Path(snapshot_path)
    pattern = f"{path.name}.*.tmp"
    for tmp_path in path.parent.glob(pattern):
        try:
            if tmp_path.is_file():
                tmp_path.unlink()
        except OSError:
            pass
