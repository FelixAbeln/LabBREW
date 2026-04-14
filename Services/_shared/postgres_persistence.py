from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

_VALID_TABLE_PREFIX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class PostgresPersistenceConfig:
    host: str
    port: int
    database: str
    username: str
    password: str
    table_prefix: str = "parameterdb"
    sslmode: str | None = None


@dataclass(frozen=True, slots=True)
class PostgresPersistenceEnvNames:
    kind: str
    host: str
    port: str
    database: str
    username: str
    password: str
    table_prefix: str
    sslmode: str


def resolve_postgres_persistence_settings(
    *,
    env_names: PostgresPersistenceEnvNames,
    kind: str | None = None,
    postgres_host: str | None = None,
    postgres_port: int | None = None,
    postgres_database: str | None = None,
    postgres_username: str | None = None,
    postgres_password: str | None = None,
    postgres_table_prefix: str | None = None,
    postgres_sslmode: str | None = None,
) -> tuple[str, PostgresPersistenceConfig | None]:
    resolved_kind = str(kind or os.getenv(env_names.kind, "json")).strip().lower() or "json"
    if resolved_kind not in {"json", "postgres"}:
        raise ValueError(f"Unsupported persistence kind: {resolved_kind!r}")

    if resolved_kind == "json":
        return "json", None

    host = str(postgres_host or os.getenv(env_names.host, "")).strip()
    database = str(postgres_database or os.getenv(env_names.database, "")).strip()
    username = str(postgres_username or os.getenv(env_names.username, "")).strip()
    password = str(postgres_password or os.getenv(env_names.password, "")).strip()
    sslmode = str(postgres_sslmode or os.getenv(env_names.sslmode, "")).strip() or None
    table_prefix = str(
        postgres_table_prefix or os.getenv(env_names.table_prefix, "parameterdb")
    ).strip() or "parameterdb"

    raw_port = postgres_port
    if raw_port is None:
        env_port = str(os.getenv(env_names.port, "")).strip()
        raw_port = int(env_port) if env_port else 5432

    missing = [
        name
        for name, value in (
            ("host", host),
            ("database", database),
            ("username", username),
            ("password", password),
        )
        if not value
    ]
    if missing:
        raise ValueError("Postgres persistence requires: " + ", ".join(missing))

    validate_table_prefix(table_prefix)

    return "postgres", PostgresPersistenceConfig(
        host=host,
        port=int(raw_port),
        database=database,
        username=username,
        password=password,
        table_prefix=table_prefix,
        sslmode=sslmode,
    )


def validate_table_prefix(table_prefix: str) -> None:
    if not _VALID_TABLE_PREFIX.fullmatch(str(table_prefix or "")):
        raise ValueError(
            "Postgres table_prefix must match ^[A-Za-z_][A-Za-z0-9_]*$"
        )


def connect_postgres(config: PostgresPersistenceConfig) -> Any:
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "Postgres persistence requires the 'psycopg' package"
        ) from exc

    connect_kwargs: dict[str, Any] = {
        "host": config.host,
        "port": config.port,
        "dbname": config.database,
        "user": config.username,
        "password": config.password,
    }
    if config.sslmode:
        connect_kwargs["sslmode"] = config.sslmode
    return psycopg.connect(**connect_kwargs)


def build_prefixed_table_names(
    config: PostgresPersistenceConfig,
    *suffixes: str,
) -> tuple[str, ...]:
    return tuple(f"{config.table_prefix}_{suffix}" for suffix in suffixes)