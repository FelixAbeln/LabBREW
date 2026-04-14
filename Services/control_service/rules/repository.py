from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..._shared.json_persistence import atomic_write_json, cleanup_stale_tmp_files
from ..._shared.postgres_persistence import (
    PostgresPersistenceConfig,
    PostgresPersistenceEnvNames,
    build_prefixed_table_names,
    connect_postgres,
    resolve_postgres_persistence_settings,
)
from ..._shared.repository_status import RepositoryStatusMixin
from ..._shared.storage_paths import storage_subdir

CONTROL_RULES_PERSISTENCE_KIND_ENV = "LABBREW_CONTROL_RULES_PERSISTENCE_KIND"
CONTROL_RULES_POSTGRES_HOST_ENV = "LABBREW_CONTROL_RULES_POSTGRES_HOST"
CONTROL_RULES_POSTGRES_PORT_ENV = "LABBREW_CONTROL_RULES_POSTGRES_PORT"
CONTROL_RULES_POSTGRES_DATABASE_ENV = "LABBREW_CONTROL_RULES_POSTGRES_DATABASE"
CONTROL_RULES_POSTGRES_USERNAME_ENV = "LABBREW_CONTROL_RULES_POSTGRES_USERNAME"
CONTROL_RULES_POSTGRES_PASSWORD_ENV = "LABBREW_CONTROL_RULES_POSTGRES_PASSWORD"
CONTROL_RULES_POSTGRES_TABLE_PREFIX_ENV = "LABBREW_CONTROL_RULES_POSTGRES_TABLE_PREFIX"
CONTROL_RULES_POSTGRES_SSLMODE_ENV = "LABBREW_CONTROL_RULES_POSTGRES_SSLMODE"

CONTROL_RULES_PERSISTENCE_ENV_NAMES = PostgresPersistenceEnvNames(
    kind=CONTROL_RULES_PERSISTENCE_KIND_ENV,
    host=CONTROL_RULES_POSTGRES_HOST_ENV,
    port=CONTROL_RULES_POSTGRES_PORT_ENV,
    database=CONTROL_RULES_POSTGRES_DATABASE_ENV,
    username=CONTROL_RULES_POSTGRES_USERNAME_ENV,
    password=CONTROL_RULES_POSTGRES_PASSWORD_ENV,
    table_prefix=CONTROL_RULES_POSTGRES_TABLE_PREFIX_ENV,
    sslmode=CONTROL_RULES_POSTGRES_SSLMODE_ENV,
)

DEFAULT_RULE_DIR = storage_subdir("Rules")


@dataclass(frozen=True, slots=True)
class RuleRecord:
    rule_id: str
    payload: dict[str, Any]
    storage_ref: str


class RuleRepository(Protocol):
    def load_rules(self) -> list[dict[str, Any]]: ...
    def save_rule(self, rule: dict[str, Any]) -> str: ...
    def delete_rule(self, rule_id: str) -> bool: ...
    def stats(self) -> dict[str, Any]: ...


def resolve_rule_repository_settings(
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
        env_names=CONTROL_RULES_PERSISTENCE_ENV_NAMES,
        kind=kind,
        postgres_host=postgres_host,
        postgres_port=postgres_port,
        postgres_database=postgres_database,
        postgres_username=postgres_username,
        postgres_password=postgres_password,
        postgres_table_prefix=postgres_table_prefix,
        postgres_sslmode=postgres_sslmode,
    )


class FileRuleRepository(RepositoryStatusMixin):
    def __init__(self, rule_dir: str | Path = DEFAULT_RULE_DIR) -> None:
        super().__init__()
        self.rule_dir = Path(rule_dir)
        self.rule_dir.mkdir(parents=True, exist_ok=True)

    def _rule_path(self, rule_id: str) -> Path:
        return self.rule_dir / f"{rule_id}.json"

    def _cleanup_stale_tmp_files(self) -> None:
        cleanup_stale_tmp_files(self.rule_dir, "*.json.*.tmp")

    def load_rules(self) -> list[dict[str, Any]]:
        try:
            self._cleanup_stale_tmp_files()
            rules: list[dict[str, Any]] = []
            for file in sorted(self.rule_dir.glob("*.json")):
                try:
                    with file.open(encoding="utf-8") as handle:
                        rules.append(json.load(handle))
                except Exception as exc:
                    print(f"Failed to load rule file {file}: {exc}")
            self._record_success()
            return rules
        except Exception as exc:
            self._record_failure(exc)
            raise

    def save_rule(self, rule: dict[str, Any]) -> str:
        rule_id = rule.get("id")
        if not rule_id:
            raise ValueError("Rule must contain an 'id'")

        path = self._rule_path(str(rule_id))
        try:
            atomic_write_json(path, rule, indent=2, sort_keys=False, ensure_ascii=False)
            self._record_success(save_ok=True)
            return str(path)
        except Exception as exc:
            self._record_failure(exc, save_ok=False)
            raise

    def delete_rule(self, rule_id: str) -> bool:
        try:
            path = self._rule_path(rule_id)
            if path.exists():
                path.unlink()
                self._record_success(save_ok=True)
                return True
            self._record_success(save_ok=True)
            return False
        except Exception as exc:
            self._record_failure(exc, save_ok=False)
            raise

    def stats(self) -> dict[str, Any]:
        return {
            "backend": "json",
            "path": str(self.rule_dir),
            **self._status_fields(),
        }


class PostgresRuleRepository(RepositoryStatusMixin):
    def __init__(self, config: PostgresPersistenceConfig) -> None:
        super().__init__()
        self.config = config

    def _table_name(self) -> str:
        (table_name,) = build_prefixed_table_names(self.config, "control_rules")
        return table_name

    def _storage_ref(self, rule_id: str) -> str:
        return f"postgres:{self.config.table_prefix}:control_rules:{rule_id}"

    def _ensure_schema(self, cursor: Any) -> None:
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self._table_name()} (
                rule_id TEXT PRIMARY KEY,
                rule_json TEXT NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL
            )
            """
        )

    def load_rules(self) -> list[dict[str, Any]]:
        try:
            with contextlib.closing(connect_postgres(self.config)) as connection:
                with connection.cursor() as cursor:
                    self._ensure_schema(cursor)
                    cursor.execute(
                        f"SELECT rule_json FROM {self._table_name()} ORDER BY rule_id"
                    )
                    rows = cursor.fetchall()
            self._record_success()
            return [dict(json.loads(row[0]) or {}) for row in rows]
        except Exception as exc:
            self._record_failure(exc)
            raise

    def save_rule(self, rule: dict[str, Any]) -> str:
        rule_id = str(rule.get("id") or "").strip()
        if not rule_id:
            raise ValueError("Rule must contain an 'id'")
        try:
            with contextlib.closing(connect_postgres(self.config)) as connection:
                with connection.cursor() as cursor:
                    self._ensure_schema(cursor)
                    cursor.execute(
                        f"""
                        INSERT INTO {self._table_name()} (rule_id, rule_json, updated_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT(rule_id) DO UPDATE SET
                            rule_json = EXCLUDED.rule_json,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (rule_id, json.dumps(rule, sort_keys=True), time.time()),
                    )
                connection.commit()
            self._record_success(save_ok=True)
            return self._storage_ref(rule_id)
        except Exception as exc:
            self._record_failure(exc, save_ok=False)
            raise

    def delete_rule(self, rule_id: str) -> bool:
        try:
            with contextlib.closing(connect_postgres(self.config)) as connection:
                with connection.cursor() as cursor:
                    self._ensure_schema(cursor)
                    cursor.execute(
                        f"DELETE FROM {self._table_name()} WHERE rule_id = %s",
                        (rule_id,),
                    )
                    deleted = cursor.rowcount > 0
                connection.commit()
            self._record_success(save_ok=True)
            return deleted
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
