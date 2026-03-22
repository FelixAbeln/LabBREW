from __future__ import annotations


def get_targets(action: dict) -> list[str]:
    if isinstance(action.get("targets"), list):
        return [str(t) for t in action["targets"] if t is not None and str(t) != ""]
    if action.get("target") is not None and str(action.get("target")) != "":
        return [str(action["target"])]
    return []
