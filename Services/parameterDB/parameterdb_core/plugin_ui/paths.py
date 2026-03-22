from __future__ import annotations

from copy import deepcopy
from typing import Any


ROOT_KEYS = {"name", "value", "config", "state", "metadata", "parameter_type"}


def deep_copy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(payload)


def get_by_path(data: dict[str, Any], path: str, default: Any = None) -> Any:
    if not path:
        return default
    current: Any = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def set_by_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = data
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def patch_from_flat_fields(values: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for path, value in values.items():
        set_by_path(patch, path, value)
    return patch
