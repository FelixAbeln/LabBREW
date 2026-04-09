from __future__ import annotations

import os
import logging
import tempfile
from pathlib import Path

_LOG = logging.getLogger(__name__)

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

    class _MissingYamlModule:
        class YAMLError(Exception):
            pass

        @staticmethod
        def safe_load(_content: str) -> dict:
            raise RuntimeError(
                "PyYAML is required to read the topology document. "
                "Install the 'PyYAML' package or add it to the service dependencies."
            )

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
    if not _YAML_AVAILABLE:
        _LOG.warning(
            "Topology file exists at %s but PyYAML is not installed; returning empty topology.",
            path,
        )
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        _LOG.warning(
            "Failed to load topology document at %s (%s); returning empty topology.",
            path,
            exc,
        )
        return {}
    if not isinstance(data, dict):
        _LOG.warning(
            "Topology document at %s has non-mapping root (%s); returning empty topology.",
            path,
            type(data).__name__,
        )
        return {}
    return data


def save_topology_document(document: dict) -> None:
    path = topology_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_dump(document, sort_keys=False, allow_unicode=False)

    # Atomic write to avoid partially-written topology files if interrupted.
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            tmp_path = Path(handle.name)
        tmp_path.replace(path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


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
