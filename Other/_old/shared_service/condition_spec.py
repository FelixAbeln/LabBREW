from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ConditionSpec:
    kind: str
    source: str = ""
    operator: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    duration_s: float | None = None
    hold_for_s: float = 0.0
    valid_sources: tuple[str, ...] = ()
    label: str = ""


def _coerce_float(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except Exception:
        return default


def condition_from_schedule_step(step: Any) -> ConditionSpec:
    wait_type = str(getattr(step, "wait_type", "") or "")
    if wait_type == "elapsed_time":
        return ConditionSpec(
            kind="elapsed_time",
            duration_s=_coerce_float(getattr(step, "duration_s", None), 0.0),
            label=str(getattr(step, "name", "") or "Elapsed time"),
        )

    if wait_type == "signal":
        operator = str(getattr(step, "operator", "") or "").strip()
        params: dict[str, Any]
        if operator in {"in_range", "out_of_range"}:
            params = {
                "min": getattr(step, "threshold_low", None),
                "max": getattr(step, "threshold_high", None),
            }
        else:
            params = {"threshold": getattr(step, "threshold", None)}
        source = str(getattr(step, "wait_source", "") or "")
        return ConditionSpec(
            kind="signal",
            source=source,
            operator=operator,
            params=params,
            hold_for_s=float(_coerce_float(getattr(step, "hold_for_s", 0.0), 0.0) or 0.0),
            label=source or str(getattr(step, "name", "") or "signal"),
        )

    if wait_type == "all_valid":
        valid_sources = tuple(str(item).strip() for item in (getattr(step, "valid_sources", []) or []) if str(item).strip())
        return ConditionSpec(
            kind="all_valid",
            valid_sources=valid_sources,
            hold_for_s=float(_coerce_float(getattr(step, "hold_for_s", 0.0), 0.0) or 0.0),
            label="all_valid",
        )

    return ConditionSpec(kind=wait_type or "unknown", label=str(getattr(step, "name", "") or wait_type or "unknown"))


def condition_from_rule(rule: dict[str, Any]) -> ConditionSpec:
    source = str(rule.get("target", "") or "")
    return ConditionSpec(
        kind="signal",
        source=source,
        operator=str(rule.get("operator", "") or "").strip(),
        params=dict(rule.get("params", {}) or {}),
        hold_for_s=float(_coerce_float(rule.get("hold_for_s", 0.0), 0.0) or 0.0),
        label=str(rule.get("id", "") or source or "rule"),
    )
