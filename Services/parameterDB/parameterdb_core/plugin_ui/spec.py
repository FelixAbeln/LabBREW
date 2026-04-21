from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_CREATE = {
    "required": ["name"],
    "defaults": {
        "value": None,
        "config": {},
        "metadata": {},
    },
    "sections": [],
}

DEFAULT_EDIT = {
    "allow_rename": False,
    "sections": [],
}

DB_OWNED_CONFIG_DEFAULTS = {
    "mirror_to": [],
    "timeshift": 0.0,
    "calibration_equation": "",
    "transducer_id": "",
}

DB_OWNED_SCHEMA_PROPERTIES = {
    "mirror_to": {"type": ["array", "string"]},
    "timeshift": {"type": "number"},
    "calibration_equation": {"type": "string"},
    "transducer_id": {"type": "string"},
}


def augment_type_defaults(defaults: dict[str, Any]) -> dict[str, Any]:
    merged = dict(defaults or {})
    merged.pop("output_params", None)
    for key, value in DB_OWNED_CONFIG_DEFAULTS.items():
        merged.setdefault(key, deepcopy(value))
    return merged


def augment_type_schema(schema: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(schema or {})
    properties = dict(result.get("properties") or {})
    properties.pop("output_params", None)
    properties.update(DB_OWNED_SCHEMA_PROPERTIES)
    result["properties"] = properties
    return result


def _normalize_section_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for field in fields:
        f = dict(field)
        key = str(f.get("key") or "")
        if key == "config.output_params":
            continue
        f.setdefault("label", f.get("key", "field"))
        f.setdefault("type", "string")
        f.setdefault("required", False)
        f.setdefault("readonly", False)
        normalized.append(f)
    return normalized


def _section_has_field(sections: list[dict[str, Any]], field_key: str) -> bool:
    for section in sections:
        for field in section.get("fields") or []:
            if str(field.get("key") or "") == field_key:
                return True
    return False


def _append_db_owned_section(sections: list[dict[str, Any]], *, editable: bool) -> None:
    db_fields: list[dict[str, Any]] = []
    if not _section_has_field(sections, "config.mirror_to"):
        db_fields.append(
            {
                "key": "config.mirror_to",
                "label": "Mirror Output To",
                "type": "parameter_ref_list",
                "readonly": not editable,
                "help": "Optional target parameters that receive this value each scan cycle.",
            }
        )
    if not _section_has_field(sections, "config.calibration_equation"):
        db_fields.append(
            {
                "key": "config.calibration_equation",
                "label": "Calibration Equation",
                "type": "string",
                "readonly": not editable,
                "help": "Applied after plugin scan. Use x for the plugin output (example: 2*x + 5).",
            }
        )
    if not _section_has_field(sections, "config.timeshift"):
        db_fields.append(
            {
                "key": "config.timeshift",
                "label": "Timeshift (s)",
                "type": "float",
                "readonly": not editable,
                "help": "Metadata for export: offset to align this parameter's timeseries with real events during post-processing.",
            }
        )
    if not _section_has_field(sections, "config.transducer_id"):
        db_fields.append(
            {
                "key": "config.transducer_id",
                "label": "Transducer",
                "type": "transducer_ref",
                "readonly": not editable,
                "help": "Optional transducer mapping name applied after calibration and before mirror output.",
            }
        )

    if db_fields:
        sections.append(
            {
                "title": "Database Output Pipeline",
                "fields": db_fields,
            }
        )


def normalize_ui_spec(
    parameter_type: str,
    spec: dict[str, Any] | None,
    *,
    display_name: str = "",
    description: str = "",
) -> dict[str, Any]:
    raw = deepcopy(spec or {})
    normalized: dict[str, Any] = {
        "parameter_type": raw.get("parameter_type", parameter_type),
        "display_name": raw.get("display_name", display_name or parameter_type),
        "description": raw.get("description", description or ""),
        "create": deepcopy(DEFAULT_CREATE),
        "edit": deepcopy(DEFAULT_EDIT),
    }

    create = raw.get("create") or {}
    normalized["create"].update(create)
    normalized["create"]["required"] = list(
        normalized["create"].get("required") or ["name"]
    )
    defaults = dict(DEFAULT_CREATE["defaults"])
    defaults.update(normalized["create"].get("defaults") or {})
    defaults["config"] = dict(defaults.get("config") or {})
    defaults["config"] = augment_type_defaults(defaults["config"])
    defaults["metadata"] = dict(defaults.get("metadata") or {})
    normalized["create"]["defaults"] = defaults

    create_sections = []
    for index, section in enumerate(normalized["create"].get("sections") or []):
        sec = dict(section)
        sec.setdefault("title", f"Section {index + 1}")
        sec["fields"] = _normalize_section_fields(sec.get("fields") or [])
        create_sections.append(sec)
    _append_db_owned_section(create_sections, editable=True)
    normalized["create"]["sections"] = create_sections

    edit = raw.get("edit") or {}
    normalized["edit"].update(edit)
    sections = []
    for index, section in enumerate(normalized["edit"].get("sections") or []):
        sec = dict(section)
        sec.setdefault("title", f"Section {index + 1}")
        sec["fields"] = _normalize_section_fields(sec.get("fields") or [])
        sections.append(sec)
    _append_db_owned_section(sections, editable=True)
    normalized["edit"]["sections"] = sections
    return normalized
