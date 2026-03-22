from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .condition_spec import ConditionSpec, condition_from_schedule_step
from .operators import OperatorRegistry, build_default_operator_registry


@dataclass(slots=True)
class ConditionEvaluation:
    ready: bool
    reason: str
    hold_started_monotonic: float | None = None
    hold_elapsed_s: float = 0.0
    observed_values: dict[str, Any] = field(default_factory=dict)


GetValue = Callable[[str], Any]


def _evaluate_hold(
    *,
    now: float,
    hold_started_monotonic: float | None,
    hold_for_s: float | None,
    label: str,
    observed_values: dict[str, Any] | None = None,
) -> ConditionEvaluation:
    active_hold_start = hold_started_monotonic if hold_started_monotonic is not None else now
    hold = max(0.0, float(hold_for_s or 0.0))
    held = max(0.0, now - active_hold_start)
    return ConditionEvaluation(
        ready=held >= hold,
        reason=f"{label}; hold {held:.1f}/{hold:.1f}s",
        hold_started_monotonic=active_hold_start,
        hold_elapsed_s=held,
        observed_values=dict(observed_values or {}),
    )


def evaluate_elapsed_wait(*, now: float, step_started_monotonic: float | None, duration_s: float | None, label: str = "Elapsed time") -> ConditionEvaluation:
    active_step_start = step_started_monotonic if step_started_monotonic is not None else now
    duration = max(0.0, float(duration_s or 0.0))
    elapsed = max(0.0, now - active_step_start)
    return ConditionEvaluation(
        ready=elapsed >= duration,
        reason=f"{label} {elapsed:.1f}/{duration:.1f}s",
    )


def evaluate_condition_spec(
    spec: ConditionSpec,
    *,
    now: float,
    step_started_monotonic: float | None,
    hold_started_monotonic: float | None,
    get_value: GetValue,
    registry: OperatorRegistry | None = None,
) -> ConditionEvaluation:
    active_registry = registry or build_default_operator_registry()

    if spec.kind == "elapsed_time":
        return evaluate_elapsed_wait(
            now=now,
            step_started_monotonic=step_started_monotonic,
            duration_s=spec.duration_s,
            label=(spec.label or "Elapsed time"),
        )

    if spec.kind == "signal":
        value = get_value(spec.source)
        if value is None or not spec.operator:
            return ConditionEvaluation(
                ready=False,
                reason=f"Waiting for {spec.source or 'signal'} (current={value})",
                observed_values={spec.source or 'signal': value},
            )
        try:
            ok = active_registry.evaluate(spec.operator, value, spec.params)
        except Exception:
            ok = False
        if not ok:
            return ConditionEvaluation(
                ready=False,
                reason=f"Waiting for {spec.source or 'signal'} (current={value})",
                observed_values={spec.source or 'signal': value},
            )
        return _evaluate_hold(
            now=now,
            hold_started_monotonic=hold_started_monotonic,
            hold_for_s=spec.hold_for_s,
            label=f"Condition met on {spec.source or 'signal'}",
            observed_values={spec.source or 'signal': value},
        )

    if spec.kind == "all_valid":
        source_values = {name: get_value(name) for name in spec.valid_sources}
        missing = [name for name, value in source_values.items() if not bool(value)]
        if missing:
            return ConditionEvaluation(
                ready=False,
                reason=f"Waiting for valid sources: {', '.join(missing)}",
                observed_values=source_values,
            )
        return _evaluate_hold(
            now=now,
            hold_started_monotonic=hold_started_monotonic,
            hold_for_s=spec.hold_for_s,
            label="All valid",
            observed_values=source_values,
        )

    return ConditionEvaluation(ready=False, reason=f"Unknown wait type: {spec.kind}")


def evaluate_step_wait(
    step: Any,
    *,
    now: float,
    step_started_monotonic: float | None,
    hold_started_monotonic: float | None,
    get_value: GetValue,
    registry: OperatorRegistry | None = None,
) -> ConditionEvaluation:
    return evaluate_condition_spec(
        condition_from_schedule_step(step),
        now=now,
        step_started_monotonic=step_started_monotonic,
        hold_started_monotonic=hold_started_monotonic,
        get_value=get_value,
        registry=registry,
    )
