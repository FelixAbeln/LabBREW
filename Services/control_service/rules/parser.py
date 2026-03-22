from __future__ import annotations

from ..._shared.operator_engine.models import AtomicCondition, CompositeCondition


def parse_condition(data: dict, path: str = "root"):
    if not isinstance(data, dict):
        raise ValueError(f"Condition must be a dict, got: {type(data)!r}")

    if "source" in data:
        return AtomicCondition(
            source=data["source"],
            operator=data["operator"],
            params=data.get("params", {}),
            for_s=float(data.get("for_s", 0.0)),
            node_id=data.get("node_id", path),
        )

    if "all" in data:
        children = tuple(
            parse_condition(child, f"{path}.all[{i}]")
            for i, child in enumerate(data["all"])
        )
        return CompositeCondition(
            kind="all",
            children=children,
            node_id=data.get("node_id", path),
        )

    if "any" in data:
        children = tuple(
            parse_condition(child, f"{path}.any[{i}]")
            for i, child in enumerate(data["any"])
        )
        return CompositeCondition(
            kind="any",
            children=children,
            node_id=data.get("node_id", path),
        )

    if "not" in data:
        child = parse_condition(data["not"], f"{path}.not")
        return CompositeCondition(
            kind="not",
            children=(child,),
            node_id=data.get("node_id", path),
        )

    raise ValueError(f"Invalid condition format: {data}")