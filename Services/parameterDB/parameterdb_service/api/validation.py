from __future__ import annotations

from pathlib import Path
from typing import Any

from ...parameterdb_core.errors import ValidationError


def require_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValidationError(f"Field '{key}' must be an object")
    return value


def require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"Field '{key}' must be a non-empty string")
    return value


def optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValidationError(f"Field '{key}' must be a string")
    return value


def optional_bool(payload: dict[str, Any], key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise ValidationError(f"Field '{key}' must be a boolean")
    return value


def optional_list_of_str(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValidationError(f"Field '{key}' must be a list of strings")
    return list(value)


def optional_path_str(payload: dict[str, Any], key: str) -> str | None:
    value = optional_str(payload, key)
    if value is None:
        return None
    return str(Path(value))


def validate_empty_ok(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("Payload must be an object")
    return payload


def validate_get_parameter_type_ui(payload: dict[str, Any]) -> dict[str, Any]:
    return {"parameter_type": require_str(payload, "parameter_type")}


def validate_create_parameter(payload: dict[str, Any]) -> dict[str, Any]:
    config = payload.get("config", {})
    metadata = payload.get("metadata", {})
    if not isinstance(config, dict):
        raise ValidationError("Field 'config' must be an object")
    if not isinstance(metadata, dict):
        raise ValidationError("Field 'metadata' must be an object")
    return {
        "name": require_str(payload, "name"),
        "parameter_type": require_str(payload, "parameter_type"),
        "value": payload.get("value"),
        "config": config,
        "metadata": metadata,
    }


def validate_delete_parameter(payload: dict[str, Any]) -> dict[str, Any]:
    return {"name": require_str(payload, "name")}


def validate_get_value(payload: dict[str, Any]) -> dict[str, Any]:
    return {"name": require_str(payload, "name"), "default": payload.get("default")}


def validate_set_value(payload: dict[str, Any]) -> dict[str, Any]:
    return {"name": require_str(payload, "name"), "value": payload.get("value")}


def validate_update_changes(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": require_str(payload, "name"),
        "changes": require_dict(payload, "changes"),
    }


def validate_load_parameter_type_folder(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "folder": optional_path_str(payload, "folder") or require_str(payload, "folder")
    }


def validate_subscribe(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "names": optional_list_of_str(payload, "names"),
        "send_initial": optional_bool(payload, "send_initial", default=True),
        "max_queue": max(1, optional_int(payload, "max_queue", default=1000)),
    }


def validate_export_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    validate_empty_ok(payload)
    return {}


def validate_import_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = require_dict(payload, "snapshot")
    return {
        "snapshot": snapshot,
        "replace_existing": optional_bool(payload, "replace_existing", default=True),
        "save_to_disk": optional_bool(payload, "save_to_disk", default=True),
    }


def validate_snapshot_names(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "names": optional_list_of_str(payload, "names"),
    }


def validate_create_transducer(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "transducer": require_dict(payload, "transducer"),
    }


def validate_update_transducer(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": require_str(payload, "name"),
        "transducer": require_dict(payload, "transducer"),
    }


def validate_delete_transducer(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": require_str(payload, "name"),
    }


def optional_int(payload: dict[str, Any], key: str, default: int) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int):
        raise ValidationError(f"Field '{key}' must be an integer")
    return value
