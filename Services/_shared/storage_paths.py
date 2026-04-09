from __future__ import annotations

import os
from pathlib import Path

try:
    import yaml
except ImportError:
    class _MissingYamlModule:
        class YAMLError(Exception):
            pass

        @staticmethod
        def safe_load(_content: str) -> dict:
            return {}

        @staticmethod
        def safe_dump(*_args, **_kwargs) -> str:
            raise RuntimeError(
                "PyYAML is required to save the topology document. "
                "Install the 'PyYAML' package or add it to the service dependencies."
            )

        @staticmethod
        def dump(*_args, **_kwargs) -> str:
            raise RuntimeError(
                "PyYAML is required to save the topology document. "
                "Install the 'PyYAML' package or add it to the service dependencies."
            )

    yaml = _MissingYamlModule()
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
    if normalized.startswith("./data/"):
        normalized = normalized.removeprefix("./data/")
    elif normalized.startswith("data/"):
        normalized = normalized.removeprefix("data/")
    elif normalized.startswith("./"):
        normalized = normalized.removeprefix("./")

    return str((root / normalized).resolve())


def default_parameterdb_snapshot_path() -> str:
    return storage_path_text("./data/parameterdb_snapshot.json")


def default_parameterdb_audit_path() -> str:
    return storage_path_text("./data/parameterdb_audit.jsonl")


def default_sources_dir() -> str:
    return storage_path_text("./data/sources")


def default_measurements_dir() -> str:
    return storage_path_text("data/measurements")


def load_topology_document() -> dict:
    path = topology_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def save_topology_document(document: dict) -> None:
    path = topology_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=False), encoding="utf-8"
    )


def configured_network_drives() -> list[dict[str, str]]:
    document = load_topology_document()
    storage = document.get("storage") or {}
    drives = storage.get("network_drives") or []
    results: list[dict[str, str]] = []
    for item in drives:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        path = str(item.get("path") or "").strip()
        if not name or not path:
            continue
        results.append({"name": name, "path": path})
    return results


def add_network_drive_to_topology(name: str, path_text: str) -> dict[str, str]:
    name = str(name or "").strip()
    path_text = str(path_text or "").strip()
    if not name:
        raise ValueError("Network drive name is required")
    if not path_text:
        raise ValueError("Network drive path is required")

    document = load_topology_document()
    storage = document.setdefault("storage", {})
    if not isinstance(storage, dict):
        raise ValueError("Topology key 'storage' must be a mapping")
    drives = storage.setdefault("network_drives", [])
    if not isinstance(drives, list):
        raise ValueError("Topology key 'storage.network_drives' must be a list")

    normalized = {"name": name, "path": path_text}
    replaced = False
    for idx, item in enumerate(drives):
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip() == name:
            drives[idx] = normalized
            replaced = True
            break
    if not replaced:
        drives.append(normalized)

    save_topology_document(document)
    return normalized
