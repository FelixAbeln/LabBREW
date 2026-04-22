from __future__ import annotations

import json

import pytest

from Services._shared.postgres_persistence import PostgresPersistenceConfig
from Services.parameterDB.parameterdb_service.transducers import (
    DEFAULT_SHARED_TRANSDUCERS_TABLE,
    PostgresTransducerCatalog,
    TransducerCatalog,
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

        if normalized.startswith("select transducer_json") and "where name = %s" not in normalized:
            rows = list(self.state.get("rows") or [])
            self._rows = [(row[1],) for row in sorted(rows, key=lambda row: row[0])]
            return

        if normalized.startswith("select transducer_json") and "where name = %s" in normalized:
            assert params is not None
            key = params[0]
            rows = [row for row in list(self.state.get("rows") or []) if row[0] == key]
            self._rows = [(rows[0][1],)] if rows else []
            return

        if normalized.startswith("insert into"):
            assert params is not None
            key = params[0]
            payload_json = params[1]
            updated_at = params[2]
            has_conflict_clause = "on conflict" in normalized
            existing = [row for row in list(self.state.get("rows") or []) if row[0] == key]
            if has_conflict_clause and existing:
                self.rowcount = 0
                return
            rows = [row for row in list(self.state.get("rows") or []) if row[0] != key]
            rows.append((key, payload_json, updated_at))
            self.state["rows"] = rows
            self.rowcount = 1
            return

        if normalized.startswith("update"):
            assert params is not None
            payload_json = params[0]
            updated_at = params[1]
            key = params[2]
            rows = list(self.state.get("rows") or [])
            next_rows: list[tuple[object, ...]] = []
            updated = False
            for row in rows:
                if row[0] == key:
                    next_rows.append((key, payload_json, updated_at))
                    updated = True
                else:
                    next_rows.append(row)
            self.state["rows"] = next_rows
            self.rowcount = 1 if updated else 0
            return

        if normalized.startswith("delete from"):
            assert params is not None
            key = params[0]
            rows = list(self.state.get("rows") or [])
            next_rows = [row for row in rows if row[0] != key]
            self.state["rows"] = next_rows
            self.rowcount = 1 if len(next_rows) != len(rows) else 0
            return

        raise AssertionError(f"Unexpected query: {query}")

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakePostgresConnection:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state

    def cursor(self) -> FakePostgresCursor:
        return FakePostgresCursor(self.state)

    def commit(self) -> None:
        return None

    def close(self) -> None:
        return None


def test_postgres_transducer_catalog_roundtrip(monkeypatch) -> None:
    state: dict[str, object] = {"rows": []}
    config = PostgresPersistenceConfig(
        host="db.internal",
        port=5432,
        database="labbrew",
        username="brew",
        password="secret",
        table_prefix="fermenter_a",
    )

    monkeypatch.setattr(
        "Services.parameterDB.parameterdb_service.transducers.connect_postgres",
        lambda _config: FakePostgresConnection(state),
    )

    catalog = PostgresTransducerCatalog(config)

    created = catalog.create(
        {
            "name": "volt_to_pressure",
            "equation": "0.6*x",
            "min_limit": 0.0,
            "max_limit": 10.0,
            "input_unit": "V",
            "output_unit": "bar",
        }
    )
    assert created["name"] == "volt_to_pressure"

    listed = catalog.list()
    assert len(listed) == 1
    assert listed[0]["input_unit"] == "V"
    assert listed[0]["max_limit"] == 10.0

    updated = catalog.update("volt_to_pressure", {"equation": "0.8*x"})
    assert updated["equation"] == "0.8*x"

    fetched = catalog.get("volt_to_pressure")
    assert fetched is not None
    assert fetched["equation"] == "0.8*x"

    assert catalog.delete("volt_to_pressure") is True
    assert catalog.list() == []


def test_postgres_transducer_catalog_duplicate_create_raises_value_error(monkeypatch) -> None:
    state: dict[str, object] = {"rows": []}
    config = PostgresPersistenceConfig(
        host="db.internal",
        port=5432,
        database="labbrew",
        username="brew",
        password="secret",
        table_prefix="fermenter_a",
    )

    monkeypatch.setattr(
        "Services.parameterDB.parameterdb_service.transducers.connect_postgres",
        lambda _config: FakePostgresConnection(state),
    )

    catalog = PostgresTransducerCatalog(config)
    payload = {
        "name": "dup_name",
        "equation": "x + 1",
        "min_limit": -1.0,
        "max_limit": 1.0,
        "input_unit": "V",
        "output_unit": "bar",
    }

    catalog.create(payload)
    with pytest.raises(ValueError, match="already exists"):
        catalog.create(payload)


def test_postgres_transducer_catalog_uses_shared_table_name(monkeypatch) -> None:
    state: dict[str, object] = {"rows": []}
    config = PostgresPersistenceConfig(
        host="db.internal",
        port=5432,
        database="labbrew",
        username="brew",
        password="secret",
        table_prefix="fermenter_b",
    )

    seen_queries: list[str] = []

    class RecordingCursor(FakePostgresCursor):
        def execute(self, query: str, params=None) -> None:
            seen_queries.append(query)
            super().execute(query, params)

    class RecordingConnection(FakePostgresConnection):
        def cursor(self) -> RecordingCursor:
            return RecordingCursor(self.state)

    monkeypatch.setattr(
        "Services.parameterDB.parameterdb_service.transducers.connect_postgres",
        lambda _config: RecordingConnection(state),
    )

    catalog = PostgresTransducerCatalog(config)
    catalog.list()

    all_sql = "\n".join(seen_queries)
    assert DEFAULT_SHARED_TRANSDUCERS_TABLE in all_sql
    assert "fermenter_b" not in all_sql


def test_postgres_transducer_update_can_clear_optional_limits(monkeypatch) -> None:
    state: dict[str, object] = {"rows": []}
    config = PostgresPersistenceConfig(
        host="db.internal",
        port=5432,
        database="labbrew",
        username="brew",
        password="secret",
        table_prefix="fermenter_a",
    )

    monkeypatch.setattr(
        "Services.parameterDB.parameterdb_service.transducers.connect_postgres",
        lambda _config: FakePostgresConnection(state),
    )

    catalog = PostgresTransducerCatalog(config)
    catalog.create(
        {
            "name": "volt_to_pressure",
            "equation": "0.6*x",
            "min_limit": 0.0,
            "max_limit": 10.0,
            "input_unit": "V",
            "output_unit": "bar",
        }
    )

    updated = catalog.update(
        "volt_to_pressure",
        {
            "equation": "0.8*x",
            "min_limit": None,
            "max_limit": None,
            "input_unit": "V",
            "output_unit": "bar",
            "description": "",
        },
    )

    assert "min_limit" not in updated
    assert "max_limit" not in updated

    fetched = catalog.get("volt_to_pressure")
    assert fetched is not None
    assert "min_limit" not in fetched
    assert "max_limit" not in fetched


def test_postgres_transducer_update_preserves_omitted_fields(monkeypatch) -> None:
    state: dict[str, object] = {"rows": []}
    config = PostgresPersistenceConfig(
        host="db.internal",
        port=5432,
        database="labbrew",
        username="brew",
        password="secret",
        table_prefix="fermenter_a",
    )

    monkeypatch.setattr(
        "Services.parameterDB.parameterdb_service.transducers.connect_postgres",
        lambda _config: FakePostgresConnection(state),
    )

    catalog = PostgresTransducerCatalog(config)
    catalog.create(
        {
            "name": "volt_to_pressure",
            "equation": "0.6*x",
            "min_limit": 0.0,
            "max_limit": 10.0,
            "input_unit": "V",
            "output_unit": "bar",
            "description": "original",
        }
    )

    updated = catalog.update(
        "volt_to_pressure",
        {
            "equation": "0.8*x",
        },
    )

    assert updated["input_unit"] == "V"
    assert updated["output_unit"] == "bar"
    assert updated["description"] == "original"
    assert updated["min_limit"] == 0.0
    assert updated["max_limit"] == 10.0


def test_json_transducer_catalog_still_file_backed(tmp_path) -> None:
    path = tmp_path / "transducers.json"
    catalog = TransducerCatalog(path)

    catalog.create(
        {
            "name": "t1",
            "equation": "2*x + 4",
        }
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["transducers"][0]["name"] == "t1"


def test_json_transducer_update_can_clear_optional_limits(tmp_path) -> None:
    path = tmp_path / "transducers.json"
    catalog = TransducerCatalog(path)

    catalog.create(
        {
            "name": "t1",
            "equation": "x",
            "min_limit": 0.0,
            "max_limit": 5.0,
            "input_unit": "V",
            "output_unit": "bar",
            "description": "Has limits",
        }
    )

    updated = catalog.update(
        "t1",
        {
            "equation": "x",
            "min_limit": None,
            "max_limit": None,
            "input_unit": "V",
            "output_unit": "bar",
            "description": "Has limits",
        },
    )

    assert "min_limit" not in updated
    assert "max_limit" not in updated

    fetched = catalog.get("t1")
    assert fetched is not None
    assert "min_limit" not in fetched
    assert "max_limit" not in fetched


def test_json_transducer_update_preserves_omitted_fields(tmp_path) -> None:
    path = tmp_path / "transducers.json"
    catalog = TransducerCatalog(path)

    catalog.create(
        {
            "name": "t1",
            "equation": "x",
            "min_limit": 0.0,
            "max_limit": 5.0,
            "input_unit": "V",
            "output_unit": "bar",
            "description": "Has limits",
        }
    )

    updated = catalog.update(
        "t1",
        {
            "equation": "x + 1",
        },
    )

    assert updated["input_unit"] == "V"
    assert updated["output_unit"] == "bar"
    assert updated["description"] == "Has limits"
    assert updated["min_limit"] == 0.0
    assert updated["max_limit"] == 5.0


def test_json_transducer_catalog_rejects_unsupported_format_version(tmp_path) -> None:
    path = tmp_path / "transducers.json"
    path.write_text(
        json.dumps(
            {
                "format_version": 2,
                "transducers": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="format_version"):
        TransducerCatalog(path)


def test_postgres_transducer_catalog_rejects_invalid_table_name() -> None:
    config = PostgresPersistenceConfig(
        host="db.internal",
        port=5432,
        database="labbrew",
        username="brew",
        password="secret",
        table_prefix="ignored",
    )
    with pytest.raises(ValueError, match="table name"):
        PostgresTransducerCatalog(config, table_name="bad-name")


def test_transducer_payload_requires_equation(tmp_path) -> None:
    path = tmp_path / "transducers.json"
    catalog = TransducerCatalog(path)

    with pytest.raises(ValueError, match="equation"):
        catalog.create(
            {
                "name": "missing_eq",
            }
        )


def test_transducer_payload_accepts_equation_without_linear_ranges(tmp_path) -> None:
    path = tmp_path / "transducers.json"
    catalog = TransducerCatalog(path)

    created = catalog.create(
        {
            "name": "eq_map",
            "equation": "x**2 + 2*x + 1",
            "input_unit": "V",
            "output_unit": "psi",
            "description": "Quadratic fit",
        }
    )

    assert created["equation"] == "x**2 + 2*x + 1"
    assert "input_min" not in created


def test_transducer_payload_rejects_equation_with_parameter_dependencies(tmp_path) -> None:
    path = tmp_path / "transducers.json"
    catalog = TransducerCatalog(path)

    with pytest.raises(ValueError, match="only supports symbols"):
        catalog.create(
            {
                "name": "bad_eq",
                "equation": "x + tank.offset",
            }
        )


def test_transducer_payload_rejects_invalid_limit_range(tmp_path) -> None:
    path = tmp_path / "transducers.json"
    catalog = TransducerCatalog(path)

    with pytest.raises(ValueError, match="min_limit"):
        catalog.create(
            {
                "name": "bad_limits",
                "equation": "x",
                "min_limit": 5.0,
                "max_limit": 1.0,
            }
        )
