from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_STORAGE_ROOT = _PROJECT_ROOT / "data"
_STORAGE_ROOT_ENV = "LABBREW_STORAGE_ROOT"
_TOPOLOGY_PATH_ENV = "LABBREW_TOPOLOGY_PATH"


def _configured_storage_root() -> Path | None:
    raw = str(os.getenv(_STORAGE_ROOT_ENV, "")).strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def storage_root() -> Path:
    return _configured_storage_root() or _DEFAULT_STORAGE_ROOT


def storage_path(*parts: str) -> Path:
    return storage_root().joinpath(*parts)


def storage_subdir(name: str) -> Path:
    return storage_path(name)


def topology_path() -> Path:
    raw = str(os.getenv(_TOPOLOGY_PATH_ENV, "")).strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return storage_path("system_topology.yaml")


def storage_path_text(default_relative_path: str) -> str:
    root = _configured_storage_root()
    if root is None:
        return default_relative_path

    normalized = default_relative_path.strip().replace("\\", "/")
    normalized = normalized.lstrip("./")
    return str((root / normalized).resolve())


def default_parameterdb_snapshot_path() -> str:
    return storage_path_text("./data/parameterdb_snapshot.json")


def default_parameterdb_audit_path() -> str:
    return storage_path_text("./data/parameterdb_audit.jsonl")


def default_sources_dir() -> str:
    return storage_path_text("./data/sources")


def default_measurements_dir() -> str:
    return storage_path_text("data/measurements")
