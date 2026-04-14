from __future__ import annotations

import pytest

from Services._shared.postgres_persistence import (
    PostgresPersistenceConfig,
    PostgresPersistenceEnvNames,
    build_prefixed_table_names,
    resolve_postgres_persistence_settings,
)


TEST_ENV_NAMES = PostgresPersistenceEnvNames(
    kind="LABBREW_TEST_PERSISTENCE_KIND",
    host="LABBREW_TEST_POSTGRES_HOST",
    port="LABBREW_TEST_POSTGRES_PORT",
    database="LABBREW_TEST_POSTGRES_DATABASE",
    username="LABBREW_TEST_POSTGRES_USERNAME",
    password="LABBREW_TEST_POSTGRES_PASSWORD",
    table_prefix="LABBREW_TEST_POSTGRES_TABLE_PREFIX",
    sslmode="LABBREW_TEST_POSTGRES_SSLMODE",
)


def test_resolve_postgres_persistence_settings_reads_custom_env(monkeypatch) -> None:
    monkeypatch.setenv(TEST_ENV_NAMES.kind, "postgres")
    monkeypatch.setenv(TEST_ENV_NAMES.host, "db.internal")
    monkeypatch.setenv(TEST_ENV_NAMES.port, "5432")
    monkeypatch.setenv(TEST_ENV_NAMES.database, "labbrew")
    monkeypatch.setenv(TEST_ENV_NAMES.username, "brew")
    monkeypatch.setenv(TEST_ENV_NAMES.password, "secret")
    monkeypatch.setenv(TEST_ENV_NAMES.table_prefix, "runtime")
    monkeypatch.setenv(TEST_ENV_NAMES.sslmode, "require")

    kind, config = resolve_postgres_persistence_settings(env_names=TEST_ENV_NAMES)

    assert kind == "postgres"
    assert config == PostgresPersistenceConfig(
        host="db.internal",
        port=5432,
        database="labbrew",
        username="brew",
        password="secret",
        table_prefix="runtime",
        sslmode="require",
    )


def test_resolve_postgres_persistence_settings_supports_json_kind() -> None:
    kind, config = resolve_postgres_persistence_settings(
        env_names=TEST_ENV_NAMES,
        kind="json",
    )

    assert kind == "json"
    assert config is None


def test_resolve_postgres_persistence_settings_rejects_invalid_prefix() -> None:
    with pytest.raises(ValueError, match="table_prefix"):
        resolve_postgres_persistence_settings(
            env_names=TEST_ENV_NAMES,
            kind="postgres",
            postgres_host="db.internal",
            postgres_database="labbrew",
            postgres_username="brew",
            postgres_password="secret",
            postgres_table_prefix="bad-prefix",
        )


def test_build_prefixed_table_names_uses_table_prefix() -> None:
    config = PostgresPersistenceConfig(
        host="db.internal",
        port=5432,
        database="labbrew",
        username="brew",
        password="secret",
        table_prefix="runtime",
    )

    assert build_prefixed_table_names(config, "sources", "rules") == (
        "runtime_sources",
        "runtime_rules",
    )