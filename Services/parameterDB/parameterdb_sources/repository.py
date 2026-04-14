from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..._shared.json_persistence import atomic_write_text, cleanup_stale_tmp_files
from ..._shared.postgres_persistence import (
    PostgresPersistenceConfig,
    PostgresPersistenceEnvNames,
    build_prefixed_table_names,
    connect_postgres,
    resolve_postgres_persistence_settings,
)
from ..._shared.repository_status import RepositoryStatusMixin

DATASOURCE_PERSISTENCE_KIND_ENV = "LABBREW_PARAMETERDB_DATASOURCE_PERSISTENCE_KIND"
DATASOURCE_POSTGRES_HOST_ENV = "LABBREW_PARAMETERDB_DATASOURCE_POSTGRES_HOST"
DATASOURCE_POSTGRES_PORT_ENV = "LABBREW_PARAMETERDB_DATASOURCE_POSTGRES_PORT"
DATASOURCE_POSTGRES_DATABASE_ENV = "LABBREW_PARAMETERDB_DATASOURCE_POSTGRES_DATABASE"
DATASOURCE_POSTGRES_USERNAME_ENV = "LABBREW_PARAMETERDB_DATASOURCE_POSTGRES_USERNAME"
DATASOURCE_POSTGRES_PASSWORD_ENV = "LABBREW_PARAMETERDB_DATASOURCE_POSTGRES_PASSWORD"
DATASOURCE_POSTGRES_TABLE_PREFIX_ENV = "LABBREW_PARAMETERDB_DATASOURCE_POSTGRES_TABLE_PREFIX"
DATASOURCE_POSTGRES_SSLMODE_ENV = "LABBREW_PARAMETERDB_DATASOURCE_POSTGRES_SSLMODE"

DATASOURCE_PERSISTENCE_ENV_NAMES = PostgresPersistenceEnvNames(
    kind=DATASOURCE_PERSISTENCE_KIND_ENV,
    host=DATASOURCE_POSTGRES_HOST_ENV,
    port=DATASOURCE_POSTGRES_PORT_ENV,
    database=DATASOURCE_POSTGRES_DATABASE_ENV,
    username=DATASOURCE_POSTGRES_USERNAME_ENV,
    password=DATASOURCE_POSTGRES_PASSWORD_ENV,
    table_prefix=DATASOURCE_POSTGRES_TABLE_PREFIX_ENV,
    sslmode=DATASOURCE_POSTGRES_SSLMODE_ENV,
)


@dataclass(slots=True)
class SourceRecord:
    name: str
    source_type: str
    config: dict[str, Any]
    storage_ref: str


class SourceConfigRepository(Protocol):
    def load_records(self) -> list[SourceRecord]: ...
    def save_record(self, record: SourceRecord) -> SourceRecord: ...
    def delete_record(self, name: str) -> None: ...
    def stats(self) -> dict[str, Any]: ...


def resolve_source_repository_settings(
    *,
    kind: str | None = None,
    postgres_host: str | None = None,
    postgres_port: int | None = None,
    postgres_database: str | None = None,
    postgres_username: str | None = None,
    postgres_password: str | None = None,
    postgres_table_prefix: str | None = None,
    postgres_sslmode: str | None = None,
) -> tuple[str, PostgresPersistenceConfig | None]:
    return resolve_postgres_persistence_settings(
        env_names=DATASOURCE_PERSISTENCE_ENV_NAMES,
        kind=kind,
        postgres_host=postgres_host,
        postgres_port=postgres_port,
        postgres_database=postgres_database,
        postgres_username=postgres_username,
        postgres_password=postgres_password,
        postgres_table_prefix=postgres_table_prefix,
        postgres_sslmode=postgres_sslmode,
    )


class FileSourceConfigRepository(RepositoryStatusMixin):
    def __init__(self, config_dir: str | Path) -> None:
        super().__init__()
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def _config_path_for_name(self, name: str) -> Path:
        safe = "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in name)
        return self.config_dir / f"{safe}.json"

    def _cleanup_stale_tmp_files(self) -> None:
        cleanup_stale_tmp_files(self.config_dir, "*.json.*.tmp")

    def load_records(self) -> list[SourceRecord]:
        try:
            self._cleanup_stale_tmp_files()
            loaded: list[SourceRecord] = []
            for cfg_path in sorted(self.config_dir.glob("*.json")):
                payload = json.loads(cfg_path.read_text(encoding="utf-8"))
                loaded.append(
                    SourceRecord(
                        name=str(payload["name"]),
                        source_type=str(payload["source_type"]),
                        config=dict(payload.get("config") or {}),
                        storage_ref=str(cfg_path),
                    )
                )
            self._record_success()
            return loaded
        except Exception as exc:
            self._record_failure(exc)
            raise

    def save_record(self, record: SourceRecord) -> SourceRecord:
        path = self._config_path_for_name(record.name)
        payload = {
            "name": record.name,
            "source_type": record.source_type,
            "config": record.config,
        }
        data = json.dumps(payload, indent=2, sort_keys=True)
        try:
            atomic_write_text(path, data)
            self._record_success(save_ok=True)
        except Exception as exc:
            self._record_failure(exc, save_ok=False)
            raise

        return SourceRecord(
            name=record.name,
            source_type=record.source_type,
            config=dict(record.config),
            storage_ref=str(path),
        )

    def delete_record(self, name: str) -> None:
        try:
            path = self._config_path_for_name(name)
            try:
                path.unlink(missing_ok=True)
            except TypeError:
                if path.exists():
                    path.unlink()
            self._record_success(save_ok=True)
        except Exception as exc:
            self._record_failure(exc, save_ok=False)
            raise

    def stats(self) -> dict[str, Any]:
        return {
            "backend": "json",
            "path": str(self.config_dir),
            **self._status_fields(),
        }


class PostgresSourceConfigRepository(RepositoryStatusMixin):
    def __init__(self, config: PostgresPersistenceConfig) -> None:
        super().__init__()
        self.config = config

    def _table_name(self) -> str:
        (table_name,) = build_prefixed_table_names(self.config, "datasource_sources")
        return table_name

    def _storage_ref(self, name: str) -> str:
        return f"postgres:{self.config.table_prefix}:datasource_sources:{name}"

    def _ensure_schema(self, cursor: Any) -> None:
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self._table_name()} (
                name TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                config_json TEXT NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL
            )
            """
        )

    def load_records(self) -> list[SourceRecord]:
        try:
            with contextlib.closing(connect_postgres(self.config)) as connection:
                with connection.cursor() as cursor:
                    self._ensure_schema(cursor)
                    cursor.execute(
                        f"SELECT name, source_type, config_json FROM {self._table_name()} ORDER BY name"
                    )
                    rows = cursor.fetchall()

            self._record_success()
            return [
                SourceRecord(
                    name=row[0],
                    source_type=row[1],
                    config=dict(json.loads(row[2]) or {}),
                    storage_ref=self._storage_ref(row[0]),
                )
                for row in rows
            ]
        except Exception as exc:
            self._record_failure(exc)
            raise

    def save_record(self, record: SourceRecord) -> SourceRecord:
        try:
            with contextlib.closing(connect_postgres(self.config)) as connection:
                with connection.cursor() as cursor:
                    self._ensure_schema(cursor)
                    cursor.execute(
                        f"""
                        INSERT INTO {self._table_name()} (name, source_type, config_json, updated_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT(name) DO UPDATE SET
                            source_type = EXCLUDED.source_type,
                            config_json = EXCLUDED.config_json,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (
                            record.name,
                            record.source_type,
                            json.dumps(record.config, sort_keys=True),
                            time.time(),
                        ),
                    )
                connection.commit()
            self._record_success(save_ok=True)
        except Exception as exc:
            self._record_failure(exc, save_ok=False)
            raise

        return SourceRecord(
            name=record.name,
            source_type=record.source_type,
            config=dict(record.config),
            storage_ref=self._storage_ref(record.name),
        )

    def delete_record(self, name: str) -> None:
        try:
            with contextlib.closing(connect_postgres(self.config)) as connection:
                with connection.cursor() as cursor:
                    self._ensure_schema(cursor)
                    cursor.execute(
                        f"DELETE FROM {self._table_name()} WHERE name = %s",
                        (name,),
                    )
                connection.commit()
            self._record_success(save_ok=True)
        except Exception as exc:
            self._record_failure(exc, save_ok=False)
            raise

    def stats(self) -> dict[str, Any]:
        return {
            "backend": "postgres",
            "postgres": {
                "host": self.config.host,
                "port": self.config.port,
                "database": self.config.database,
                "table_prefix": self.config.table_prefix,
                "sslmode": self.config.sslmode,
            },
            **self._status_fields(),
        }