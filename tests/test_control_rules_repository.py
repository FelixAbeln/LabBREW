from __future__ import annotations

from pathlib import Path

import pytest

from Services.control_service.rules.repository import (
    CONTROL_RULES_PERSISTENCE_KIND_ENV,
    CONTROL_RULES_POSTGRES_DATABASE_ENV,
    CONTROL_RULES_POSTGRES_HOST_ENV,
    CONTROL_RULES_POSTGRES_PASSWORD_ENV,
    CONTROL_RULES_POSTGRES_PORT_ENV,
    CONTROL_RULES_POSTGRES_SSLMODE_ENV,
    CONTROL_RULES_POSTGRES_TABLE_PREFIX_ENV,
    CONTROL_RULES_POSTGRES_USERNAME_ENV,
    FileRuleRepository,
    PostgresRuleRepository,
    resolve_rule_repository_settings,
)


class FakePostgresCursor:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state
        self._rows: list[tuple[object, ...]] = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _ = exc_type, exc, tb

    def execute(self, query: str, params=None) -> None:
        normalized = " ".join(query.split()).lower()
        if normalized.startswith("create table if not exists"):
            return
        if normalized.startswith("select rule_json"):
            rows = list(self.state.get("rows") or [])
            self._rows = [(row[1],) for row in sorted(rows, key=lambda row: row[0])]
            return
        if normalized.startswith("delete from"):
            assert params is not None
            before = list(self.state.get("rows") or [])
            after = [row for row in before if row[0] != params[0]]
            self.state["rows"] = after
            self.rowcount = 1 if len(after) != len(before) else 0
            return
        if "insert into" in normalized and "control_rules" in normalized:
            assert params is not None
            next_row = (params[0], params[1], params[2])
            rows = [row for row in list(self.state.get("rows") or []) if row[0] != params[0]]
            rows.append(next_row)
            self.state["rows"] = rows
            self.rowcount = 1
            return
        raise AssertionError(f"Unexpected query: {query}")

    def fetchall(self):
        return list(self._rows)


class FakePostgresConnection:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state
        self.closed = False

    def cursor(self) -> FakePostgresCursor:
        return FakePostgresCursor(self.state)

    def commit(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_file_rule_repository_roundtrip(tmp_path: Path) -> None:
    repo = FileRuleRepository(tmp_path / "Rules")
    rule = {"id": "r1", "enabled": True}

    saved = repo.save_rule(rule)
    assert saved.endswith("r1.json")
    assert repo.stats()["last_save_ok"] is True
    assert repo.stats()["last_success_at"] is not None
    assert repo.load_rules() == [rule]
    assert repo.delete_rule("r1") is True
    assert repo.load_rules() == []


def test_postgres_rule_repository_roundtrip(monkeypatch) -> None:
    state: dict[str, object] = {"rows": []}
    config = resolve_rule_repository_settings(
        kind="postgres",
        postgres_host="db.internal",
        postgres_database="labbrew",
        postgres_username="brew",
        postgres_password="secret",
        postgres_table_prefix="control_rules",
    )[1]
    assert config is not None
    repo = PostgresRuleRepository(config)

    monkeypatch.setattr(
        "Services.control_service.rules.repository.connect_postgres",
        lambda _config: FakePostgresConnection(state),
    )

    rule = {"id": "r1", "enabled": True}
    storage_ref = repo.save_rule(rule)
    assert storage_ref.startswith("postgres:")
    assert repo.stats()["last_save_ok"] is True
    assert repo.stats()["last_success_at"] is not None
    assert repo.load_rules() == [rule]
    assert repo.delete_rule("r1") is True
    assert repo.load_rules() == []


def test_resolve_rule_repository_settings_reads_control_env(monkeypatch) -> None:
    monkeypatch.setenv(CONTROL_RULES_PERSISTENCE_KIND_ENV, "postgres")
    monkeypatch.setenv(CONTROL_RULES_POSTGRES_HOST_ENV, "db.internal")
    monkeypatch.setenv(CONTROL_RULES_POSTGRES_PORT_ENV, "5432")
    monkeypatch.setenv(CONTROL_RULES_POSTGRES_DATABASE_ENV, "labbrew")
    monkeypatch.setenv(CONTROL_RULES_POSTGRES_USERNAME_ENV, "brew")
    monkeypatch.setenv(CONTROL_RULES_POSTGRES_PASSWORD_ENV, "secret")
    monkeypatch.setenv(CONTROL_RULES_POSTGRES_TABLE_PREFIX_ENV, "control_rules")
    monkeypatch.setenv(CONTROL_RULES_POSTGRES_SSLMODE_ENV, "require")

    kind, config = resolve_rule_repository_settings()

    assert kind == "postgres"
    assert config is not None
    assert config.host == "db.internal"
    assert config.database == "labbrew"
    assert config.table_prefix == "control_rules"
    assert config.sslmode == "require"


def test_resolve_rule_repository_settings_rejects_invalid_kind() -> None:
    with pytest.raises(ValueError, match="Unsupported persistence kind"):
        resolve_rule_repository_settings(kind="oracle")
