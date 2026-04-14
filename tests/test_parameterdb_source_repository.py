from __future__ import annotations

import json
from pathlib import Path

import pytest

from Services.parameterDB.parameterdb_sources.repository import (
    DATASOURCE_PERSISTENCE_KIND_ENV,
    DATASOURCE_POSTGRES_DATABASE_ENV,
    DATASOURCE_POSTGRES_HOST_ENV,
    DATASOURCE_POSTGRES_PASSWORD_ENV,
    DATASOURCE_POSTGRES_PORT_ENV,
    DATASOURCE_POSTGRES_SSLMODE_ENV,
    DATASOURCE_POSTGRES_TABLE_PREFIX_ENV,
    DATASOURCE_POSTGRES_USERNAME_ENV,
    FileSourceConfigRepository,
    PostgresSourceConfigRepository,
    SourceRecord,
    resolve_source_repository_settings,
)


class FakePostgresCursor:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state
        self._rows: list[tuple[object, ...]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _ = exc_type, exc, tb

    def execute(self, query: str, params=None) -> None:
        normalized = " ".join(query.split()).lower()
        if normalized.startswith("create table if not exists"):
            return
        if normalized.startswith("select name, source_type, config_json"):
            rows = list(self.state.get("rows") or [])
            self._rows = sorted(rows, key=lambda row: row[0])
            return
        if normalized.startswith("delete from"):
            assert params is not None
            self.state["rows"] = [
                row for row in list(self.state.get("rows") or []) if row[0] != params[0]
            ]
            return
        if "insert into" in normalized and "datasource_sources" in normalized:
            assert params is not None
            next_row = (params[0], params[1], params[2], params[3])
            rows = [row for row in list(self.state.get("rows") or []) if row[0] != params[0]]
            rows.append(next_row)
            self.state["rows"] = rows
            return
        raise AssertionError(f"Unexpected query: {query}")

    def fetchall(self):
        return list(self._rows)


class FakePostgresConnection:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state
        self.committed = False
        self.closed = False

    def cursor(self) -> FakePostgresCursor:
        return FakePostgresCursor(self.state)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


def test_file_source_config_repository_roundtrip(tmp_path: Path) -> None:
    repo = FileSourceConfigRepository(tmp_path / "sources")
    saved = repo.save_record(
        SourceRecord(name="alpha", source_type="fake", config={"interval": 1}, storage_ref="")
    )

    assert saved.storage_ref.endswith("alpha.json")
    assert repo.stats()["last_save_ok"] is True
    assert repo.stats()["last_success_at"] is not None
    loaded = repo.load_records()
    assert [(item.name, item.source_type, item.config) for item in loaded] == [
        ("alpha", "fake", {"interval": 1})
    ]

    repo.delete_record("alpha")
    assert repo.load_records() == []


def test_file_source_config_repository_cleans_stale_tmp_files(tmp_path: Path) -> None:
    repo = FileSourceConfigRepository(tmp_path / "sources")
    stale = repo.config_dir / "alpha.json.123.tmp"
    stale.write_text("tmp", encoding="utf-8")

    repo.load_records()

    assert stale.exists() is False


def test_postgres_source_config_repository_roundtrip(monkeypatch) -> None:
    state: dict[str, object] = {"rows": []}
    repo = PostgresSourceConfigRepository(
        config=resolve_source_repository_settings(
            kind="postgres",
            postgres_host="db.internal",
            postgres_database="labbrew",
            postgres_username="brew",
            postgres_password="secret",
            postgres_table_prefix="datasource",
        )[1]
    )
    assert repo.config is not None

    monkeypatch.setattr(
        "Services.parameterDB.parameterdb_sources.repository.connect_postgres",
        lambda _config: FakePostgresConnection(state),
    )

    repo.save_record(
        SourceRecord(name="alpha", source_type="fake", config={"interval": 1}, storage_ref="")
    )
    assert repo.stats()["last_save_ok"] is True
    assert repo.stats()["last_success_at"] is not None
    loaded = repo.load_records()

    assert [(item.name, item.source_type, item.config) for item in loaded] == [
        ("alpha", "fake", {"interval": 1})
    ]

    repo.delete_record("alpha")
    assert repo.load_records() == []


def test_resolve_source_repository_settings_reads_datasource_env(monkeypatch) -> None:
    monkeypatch.setenv(DATASOURCE_PERSISTENCE_KIND_ENV, "postgres")
    monkeypatch.setenv(DATASOURCE_POSTGRES_HOST_ENV, "db.internal")
    monkeypatch.setenv(DATASOURCE_POSTGRES_PORT_ENV, "5432")
    monkeypatch.setenv(DATASOURCE_POSTGRES_DATABASE_ENV, "labbrew")
    monkeypatch.setenv(DATASOURCE_POSTGRES_USERNAME_ENV, "brew")
    monkeypatch.setenv(DATASOURCE_POSTGRES_PASSWORD_ENV, "secret")
    monkeypatch.setenv(DATASOURCE_POSTGRES_TABLE_PREFIX_ENV, "datasource")
    monkeypatch.setenv(DATASOURCE_POSTGRES_SSLMODE_ENV, "require")

    kind, config = resolve_source_repository_settings()

    assert kind == "postgres"
    assert config is not None
    assert config.host == "db.internal"
    assert config.database == "labbrew"
    assert config.table_prefix == "datasource"
    assert config.sslmode == "require"


def test_resolve_source_repository_settings_rejects_invalid_kind() -> None:
    with pytest.raises(ValueError, match="Unsupported persistence kind"):
        resolve_source_repository_settings(kind="oracle")