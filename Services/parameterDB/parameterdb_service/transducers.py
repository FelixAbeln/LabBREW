from __future__ import annotations

import contextlib
import json
import math
import re
import threading
import time
from pathlib import Path
from typing import Any

from ..._shared.json_persistence import atomic_write_json
from ..._shared.postgres_persistence import (
    PostgresPersistenceConfig,
    connect_postgres,
)

DEFAULT_SHARED_TRANSDUCERS_TABLE = "parameterdb_shared_transducers"
_VALID_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class TransducerCatalog:
    """Persistent catalog of linear signal transducer mappings."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.RLock()
        self._items: dict[str, dict[str, Any]] = {}
        if self.path is not None:
            self.load()

    def load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        payload = _load_catalog_file(self.path)
        with self._lock:
            self._items = {item["name"]: item for item in payload}

    def save(self) -> None:
        if self.path is None:
            return
        with self._lock:
            payload = {
                "format_version": 1,
                "transducers": [
                    dict(self._items[name]) for name in sorted(self._items)
                ],
            }
        atomic_write_json(self.path, payload, indent=2, sort_keys=True)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(self._items[name]) for name in sorted(self._items)]

    def get(self, name: str) -> dict[str, Any] | None:
        key = str(name or "").strip()
        if not key:
            return None
        with self._lock:
            item = self._items.get(key)
            return dict(item) if item is not None else None

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = _normalize_transducer_payload(payload)
        with self._lock:
            if item["name"] in self._items:
                raise ValueError(f"Transducer '{item['name']}' already exists")
            self._items[item["name"]] = item
        self.save()
        return dict(item)

    def update(self, name: str, changes: dict[str, Any]) -> dict[str, Any]:
        key = str(name or "").strip()
        if not key:
            raise ValueError("Transducer name is required")
        with self._lock:
            existing = self._items.get(key)
            if existing is None:
                raise ValueError(f"Unknown transducer '{key}'")
            merged = dict(existing)
            merged.update(dict(changes or {}))
            # Keep endpoint path authoritative for identity.
            merged["name"] = key
            item = _normalize_transducer_payload(merged)
            self._items[key] = item
        self.save()
        return dict(item)

    def delete(self, name: str) -> bool:
        key = str(name or "").strip()
        if not key:
            return False
        removed = False
        with self._lock:
            removed = self._items.pop(key, None) is not None
        if removed:
            self.save()
        return removed


class PostgresTransducerCatalog:
    """Shared transducer catalog stored in a Postgres table."""

    def __init__(
        self,
        config: PostgresPersistenceConfig,
        *,
        table_name: str = DEFAULT_SHARED_TRANSDUCERS_TABLE,
    ) -> None:
        self.config = config
        self.table_name = _validate_table_name(table_name)
        self._lock = threading.RLock()

    def load(self) -> None:
        # Catalog is read directly from Postgres; no in-memory warmup needed.
        return

    def save(self) -> None:
        # Each write operation is persisted immediately.
        return

    def list(self) -> list[dict[str, Any]]:
        with contextlib.closing(connect_postgres(self.config)) as connection:
            with connection.cursor() as cursor:
                _ensure_postgres_schema(cursor, self.table_name)
                cursor.execute(
                    f"SELECT transducer_json FROM {self.table_name} ORDER BY name"
                )
                rows = cursor.fetchall() or []
        items: list[dict[str, Any]] = []
        for (raw_json,) in rows:
            payload = json.loads(raw_json)
            items.append(_normalize_transducer_payload(dict(payload or {})))
        return items

    def get(self, name: str) -> dict[str, Any] | None:
        key = str(name or "").strip()
        if not key:
            return None
        with contextlib.closing(connect_postgres(self.config)) as connection:
            with connection.cursor() as cursor:
                _ensure_postgres_schema(cursor, self.table_name)
                cursor.execute(
                    f"SELECT transducer_json FROM {self.table_name} WHERE name = %s",
                    (key,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return _normalize_transducer_payload(dict(json.loads(row[0]) or {}))

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = _normalize_transducer_payload(payload)
        with self._lock:
            with contextlib.closing(connect_postgres(self.config)) as connection:
                with connection.cursor() as cursor:
                    _ensure_postgres_schema(cursor, self.table_name)
                    cursor.execute(
                        f"""
                        INSERT INTO {self.table_name} (
                            name,
                            transducer_json,
                            updated_at
                        )
                        VALUES (%s, %s, %s)
                        ON CONFLICT (name) DO NOTHING
                        """,
                        (item["name"], json.dumps(item, sort_keys=True), time.time()),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError(f"Transducer '{item['name']}' already exists")
                connection.commit()
        return dict(item)

    def update(self, name: str, changes: dict[str, Any]) -> dict[str, Any]:
        key = str(name or "").strip()
        if not key:
            raise ValueError("Transducer name is required")
        with self._lock:
            with contextlib.closing(connect_postgres(self.config)) as connection:
                with connection.cursor() as cursor:
                    _ensure_postgres_schema(cursor, self.table_name)
                    cursor.execute(
                        f"SELECT transducer_json FROM {self.table_name} WHERE name = %s",
                        (key,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ValueError(f"Unknown transducer '{key}'")
                    existing = _normalize_transducer_payload(
                        dict(json.loads(row[0]) or {})
                    )
                    merged = dict(existing)
                    merged.update(dict(changes or {}))
                    merged["name"] = key
                    item = _normalize_transducer_payload(merged)
                    cursor.execute(
                        f"""
                        UPDATE {self.table_name}
                        SET transducer_json = %s,
                            updated_at = %s
                        WHERE name = %s
                        """,
                        (json.dumps(item, sort_keys=True), time.time(), key),
                    )
                    if cursor.rowcount == 0:
                        raise ValueError(f"Unknown transducer '{key}'")
                connection.commit()
        return dict(item)

    def delete(self, name: str) -> bool:
        key = str(name or "").strip()
        if not key:
            return False
        with self._lock:
            with contextlib.closing(connect_postgres(self.config)) as connection:
                with connection.cursor() as cursor:
                    _ensure_postgres_schema(cursor, self.table_name)
                    cursor.execute(
                        f"DELETE FROM {self.table_name} WHERE name = %s",
                        (key,),
                    )
                    removed = bool(cursor.rowcount)
                connection.commit()
        return removed


def _validate_table_name(table_name: str) -> str:
    cleaned = str(table_name or "").strip()
    if not _VALID_TABLE_NAME.fullmatch(cleaned):
        raise ValueError("Postgres transducer table name must match ^[A-Za-z_][A-Za-z0-9_]*$")
    return cleaned


def _ensure_postgres_schema(cursor: Any, table_name: str) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            name TEXT PRIMARY KEY,
            transducer_json TEXT NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL
        )
        """
    )


def _require_number(payload: dict[str, Any], key: str) -> float:
    raw = payload.get(key)
    if isinstance(raw, bool):
        raise ValueError(f"Field '{key}' must be a number")
    if not isinstance(raw, (int, float)):
        raise ValueError(f"Field '{key}' must be a number")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"Field '{key}' must be finite")
    return value


def _optional_text(payload: dict[str, Any], key: str) -> str:
    raw = payload.get(key)
    if raw is None:
        return ""
    return str(raw).strip()


def _normalize_transducer_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Transducer payload must be an object")

    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("Field 'name' is required")

    input_min = _require_number(payload, "input_min")
    input_max = _require_number(payload, "input_max")
    if input_min == input_max:
        raise ValueError("input_min and input_max must not be equal")

    output_min = _require_number(payload, "output_min")
    output_max = _require_number(payload, "output_max")

    clamp_raw = payload.get("clamp", True)
    if not isinstance(clamp_raw, bool):
        raise ValueError("Field 'clamp' must be a boolean")

    return {
        "name": name,
        "input_min": input_min,
        "input_max": input_max,
        "output_min": output_min,
        "output_max": output_max,
        "input_unit": _optional_text(payload, "input_unit"),
        "output_unit": _optional_text(payload, "output_unit"),
        "description": _optional_text(payload, "description"),
        "clamp": clamp_raw,
    }


def _load_catalog_file(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as fh:
        payload = json.load(fh)

    if not isinstance(payload, dict):
        raise ValueError("Transducer catalog must be an object")
    format_version = payload.get("format_version", 1)
    if not isinstance(format_version, int):
        raise ValueError("Field 'format_version' must be an integer")
    if format_version != 1:
        raise ValueError(f"Unsupported transducer catalog format_version: {format_version}")
    rows = payload.get("transducers", [])
    if not isinstance(rows, list):
        raise ValueError("Field 'transducers' must be an array")

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Transducer payload must be an object")
        item = _normalize_transducer_payload(row)
        if item["name"] in seen:
            raise ValueError(f"Duplicate transducer '{item['name']}' in catalog")
        seen.add(item["name"])
        items.append(item)
    return items
