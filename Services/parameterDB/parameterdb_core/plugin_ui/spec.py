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


def normalize_ui_spec(parameter_type: str, spec: dict[str, Any] | None, *, display_name: str = "", description: str = "") -> dict[str, Any]:
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
    normalized["create"]["required"] = list(normalized["create"].get("required") or ["name"])
    defaults = dict(DEFAULT_CREATE["defaults"])
    defaults.update(normalized["create"].get("defaults") or {})
    defaults["config"] = dict(defaults.get("config") or {})
    defaults["metadata"] = dict(defaults.get("metadata") or {})
    normalized["create"]["defaults"] = defaults

    create_sections = []
    for index, section in enumerate(normalized["create"].get("sections") or []):
        sec = dict(section)
        sec.setdefault("title", f"Section {index + 1}")
        fields = []
        for field in sec.get("fields") or []:
            f = dict(field)
            f.setdefault("label", f.get("key", "field"))
            f.setdefault("type", "string")
            f.setdefault("required", False)
            f.setdefault("readonly", False)
            fields.append(f)
        sec["fields"] = fields
        create_sections.append(sec)
    normalized["create"]["sections"] = create_sections

    edit = raw.get("edit") or {}
    normalized["edit"].update(edit)
    sections = []
    for index, section in enumerate(normalized["edit"].get("sections") or []):
        sec = dict(section)
        sec.setdefault("title", f"Section {index + 1}")
        fields = []
        for field in sec.get("fields") or []:
            f = dict(field)
            f.setdefault("label", f.get("key", "field"))
            f.setdefault("type", "string")
            f.setdefault("required", False)
            f.setdefault("readonly", False)
            fields.append(f)
        sec["fields"] = fields
        sections.append(sec)
    normalized["edit"]["sections"] = sections
    return normalized
