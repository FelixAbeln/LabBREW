from __future__ import annotations

from typing import Any


def build_section_app(sections: list[dict[str, Any]] | None) -> dict[str, Any]:
    app_sections: list[dict[str, Any]] = []
    for index, section in enumerate(sections or []):
        if not isinstance(section, dict):
            continue
        items = [
            {"kind": "field", "field": dict(field)}
            for field in section.get("fields", [])
            if isinstance(field, dict)
        ]
        app_sections.append(
            {
                "id": section.get("id") or f"section-{index + 1}",
                "title": section.get("title"),
                "description": section.get("description"),
                "items": items,
            }
        )
    return {"kind": "sections", "version": 1, "sections": app_sections}


def _default_action_label(control: dict[str, Any]) -> str | None:
    widget = str(control.get("widget") or "").strip().lower()
    write = control.get("write") if isinstance(control.get("write"), dict) else {}
    write_kind = str(write.get("kind") or "").strip().lower()
    if widget == "toggle" or write_kind == "bool":
        return None
    if widget == "button" or write_kind == "pulse":
        return "Run"
    if widget == "number_button":
        return "Apply"
    return "Apply"



def build_control_app(
    controls: list[dict[str, Any]] | None,
    *,
    title: str = "Controls",
) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}

    for control in (controls or []):
        if not isinstance(control, dict):
            continue
        control_id = str(control.get("id") or "").strip()
        if not control_id:
            continue
        raw_node = control.get("node_id")
        if isinstance(raw_node, int):
            section_id = f"node-{raw_node}"
            section_title = f"Node {raw_node}"
        else:
            section_id = "controls"
            section_title = title
        section = grouped.setdefault(
            section_id,
            {
                "id": section_id,
                "title": section_title,
                "items": [],
            },
        )
        section["items"].append(
            {
                "kind": "control",
                "control_id": control_id,
                "title": str(control.get("label") or control.get("target") or control_id),
                "description": str(control.get("hint") or "").strip() or None,
                "action_label": str(control.get("action_label") or "").strip() or _default_action_label(control),
            }
        )

    return {
        "kind": "sections",
        "version": 1,
        "sections": list(grouped.values()) or [{"id": "controls", "title": title, "items": []}],
    }
