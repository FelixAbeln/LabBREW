from __future__ import annotations

from typing import Any

from .utils import get_targets

SAFE_RULE_OWNER = "safety"


def set_value_checked(backend, ownership, target: str, value: Any, owner: str) -> dict:
    current_owner = ownership.get_owner(target)
    if current_owner not in (None, owner):
        return {
            "ok": False,
            "written": False,
            "blocked": True,
            "target": target,
            "value": value,
            "owner": owner,
            "current_owner": current_owner,
        }

    ownership.request(target, owner)
    success = backend.set_value(target, value)
    return {
        "ok": bool(success),
        "written": bool(success),
        "blocked": False,
        "target": target,
        "value": value,
        "owner": owner,
        "current_owner": ownership.get_owner(target),
    }


def read_value(backend, target: str, default: Any = None) -> dict:
    value = backend.get_value(target, default)
    return {
        "ok": True,
        "target": target,
        "value": value,
    }


def execute_action(backend, action: dict) -> dict:
    action_type = action.get("type")
    targets = get_targets(action)

    if not targets:
        return {"ok": False, "written": False, "reason": "missing target(s)"}

    if action_type == "set":
        if "value" not in action:
            return {
                "ok": False,
                "written": False,
                "reason": "missing value",
                "targets": targets,
            }

        written = {}
        for target in targets:
            written[target] = bool(backend.set_value(target, action["value"]))

        return {
            "ok": all(written.values()) if written else False,
            "written": written,
            "blocked": False,
            "targets": targets,
            "value": action["value"],
        }

    return {
        "ok": False,
        "written": False,
        "reason": f"unsupported action type: {action_type}",
        "targets": targets,
    }
