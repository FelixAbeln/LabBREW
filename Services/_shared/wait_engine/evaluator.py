from __future__ import annotations

from typing import Any

from ..operator_engine import (
    AtomicCondition,
    CompositeCondition,
    ConditionEngine,
    EvaluationState,
)
from .models import EventNodeState, WaitContext, WaitResult, WaitSpec, WaitState


class WaitEngine:
    def __init__(self, condition_engine: ConditionEngine) -> None:
        self._condition_engine = condition_engine

    def evaluate(
        self,
        spec: WaitSpec | None,
        *,
        context: WaitContext,
        previous_state: WaitState | None = None,
    ) -> WaitResult:
        state = previous_state or WaitState(condition_state=EvaluationState())
        if spec is None:
            spec = WaitSpec(kind="none")
        return self._evaluate(spec, context=context, state=state, path="root")

    def _evaluate(
        self, spec: WaitSpec, *, context: WaitContext, state: WaitState, path: str
    ) -> WaitResult:
        if spec.kind == "none":
            return WaitResult(True, "No wait", next_state=state)

        if spec.kind == "elapsed":
            required = max(0.0, float(spec.duration_s or 0.0))
            if context.step_started_monotonic is None:
                return WaitResult(False, "Step not started", next_state=state)
            elapsed = max(0.0, context.now_monotonic - context.step_started_monotonic)
            return WaitResult(
                matched=elapsed >= required,
                message=f"elapsed {elapsed:.2f}/{required:.2f}s",
                observed_values={"elapsed_s": elapsed, "required_s": required},
                next_state=state,
            )

        if spec.kind == "condition":
            condition = parse_condition_node(spec.condition)
            condition_state = state.condition_state
            if condition_state is None:
                condition_state = EvaluationState()
            result = self._condition_engine.evaluate(
                condition,
                values=context.values,
                now_monotonic=context.now_monotonic,
                previous_state=condition_state,
            )
            return WaitResult(
                matched=result.matched,
                message=result.message,
                observed_values=dict(result.observed_values),
                next_state=WaitState(
                    condition_state=result.next_state,
                    event_nodes=dict(state.event_nodes),
                ),
            )

        if spec.kind in {"rising", "falling", "pulse"}:
            child_spec = spec.child
            if child_spec is None:
                raise ValueError(f"{spec.kind} wait requires a child expression")

            child_result = self._evaluate(
                child_spec,
                context=context,
                state=state,
                path=f"{path}.child",
            )
            next_state = child_result.next_state

            node_state = next_state.event_nodes.get(path)
            if node_state is None:
                node_state = EventNodeState()
                next_state.event_nodes[path] = node_state

            current_matched = bool(child_result.matched)
            previous_matched = bool(node_state.previous_child_matched)

            edge_detected = False
            if spec.kind == "rising":
                edge_detected = (not previous_matched) and current_matched
            elif spec.kind == "falling":
                edge_detected = previous_matched and (not current_matched)
            else:
                # pulse: start pulse on rising edge of child truth.
                if (not previous_matched) and current_matched:
                    node_state.pulse_started_monotonic = context.now_monotonic

                hold_s = max(0.0, float(spec.hold_s or 0.0))
                if node_state.pulse_started_monotonic is None:
                    edge_detected = False
                elif hold_s <= 0.0:
                    edge_detected = True
                    node_state.pulse_started_monotonic = None
                else:
                    elapsed_since_pulse = max(
                        0.0, context.now_monotonic - node_state.pulse_started_monotonic
                    )
                    edge_detected = elapsed_since_pulse <= hold_s
                    if not edge_detected:
                        node_state.pulse_started_monotonic = None

            node_state.previous_child_matched = current_matched

            if spec.kind == "pulse":
                hold_s = max(0.0, float(spec.hold_s or 0.0))
                if node_state.pulse_started_monotonic is None:
                    elapsed_since_pulse = 0.0
                else:
                    elapsed_since_pulse = max(
                        0.0, context.now_monotonic - node_state.pulse_started_monotonic
                    )
                message = (
                    f"pulse active {elapsed_since_pulse:.2f}/{hold_s:.2f}s"
                    if edge_detected
                    else f"pulse inactive {elapsed_since_pulse:.2f}/{hold_s:.2f}s"
                )
                observed = dict(child_result.observed_values)
                observed["pulse_elapsed_s"] = elapsed_since_pulse
                observed["pulse_hold_s"] = hold_s
            else:
                message = (
                    f"{spec.kind} edge"
                    if edge_detected
                    else f"waiting for {spec.kind} edge"
                )
                observed = dict(child_result.observed_values)

            return WaitResult(
                matched=edge_detected,
                message=message,
                observed_values=observed,
                children=[child_result],
                next_state=next_state,
            )

        if spec.kind in {"all_of", "any_of"}:
            children: list[WaitResult] = []
            next_state = state

            for index, child in enumerate(spec.children):
                child_result = self._evaluate(
                    child,
                    context=context,
                    state=next_state,
                    path=f"{path}.{index}",
                )
                next_state = child_result.next_state
                children.append(child_result)

            matched = (
                all(c.matched for c in children)
                if spec.kind == "all_of"
                else any(c.matched for c in children)
            )

            observed: dict[str, Any] = {}
            for child in children:
                observed.update(child.observed_values)

            child_messages = [
                c.message.strip() for c in children if c.message and c.message.strip()
            ]
            message = (
                spec.kind + "\n" + "\n".join(f"- {m}" for m in child_messages)
                if child_messages
                else spec.kind
            )

            return WaitResult(
                matched=matched,
                message=message,
                observed_values=observed,
                children=children,
                next_state=next_state,
            )

        raise ValueError(f"Unsupported wait kind: {spec.kind}")


def parse_wait_spec(payload: Any) -> WaitSpec | None:
    if payload in (None, "", False):
        return None
    if not isinstance(payload, dict):
        raise ValueError("wait spec must be a dict")

    kind = str(payload.get("kind", "none") or "none")
    if kind in {"none", "elapsed", "condition"}:
        return WaitSpec(
            kind=kind,
            duration_s=payload.get("duration_s"),
            condition=payload.get("condition"),
            label=str(payload.get("label", "") or ""),
            node_id=payload.get("node_id"),
        )

    if kind in {"rising", "falling", "pulse"}:
        child_payload = payload.get("child")
        child = parse_wait_spec(child_payload)
        if child is None:
            raise ValueError(f"{kind} wait requires a child wait payload")
        return WaitSpec(
            kind=kind,
            child=child,
            hold_s=payload.get("hold_s"),
            label=str(payload.get("label", "") or ""),
            node_id=payload.get("node_id"),
        )

    if kind in {"all_of", "any_of"}:
        children_payload = payload.get("children") or []
        children = tuple(
            parse_wait_spec(child) or WaitSpec(kind="none")
            for child in children_payload
        )
        return WaitSpec(
            kind=kind,
            children=children,
            label=str(payload.get("label", "") or ""),
            node_id=payload.get("node_id"),
        )

    raise ValueError(f"Unsupported wait kind: {kind}")


def parse_condition_node(payload: Any) -> AtomicCondition | CompositeCondition:
    if isinstance(payload, (AtomicCondition, CompositeCondition)):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("condition must be a dict")

    if "all" in payload:
        children = tuple(
            parse_condition_node(item) for item in payload.get("all") or []
        )
        return CompositeCondition(
            kind="all", children=children, for_s=float(payload.get("for_s") or 0.0)
        )
    if "any" in payload:
        children = tuple(
            parse_condition_node(item) for item in payload.get("any") or []
        )
        return CompositeCondition(
            kind="any", children=children, for_s=float(payload.get("for_s") or 0.0)
        )
    if "not" in payload:
        child = parse_condition_node(payload["not"])
        return CompositeCondition(
            kind="not", children=(child,), for_s=float(payload.get("for_s") or 0.0)
        )

    source = str(payload["source"])
    operator = str(payload["operator"])
    params = dict(payload.get("params") or {})
    if "threshold" in payload and "threshold" not in params:
        params["threshold"] = payload["threshold"]
    return AtomicCondition(
        source=source,
        operator=operator,
        params=params,
        for_s=float(payload.get("for_s") or 0.0),
        node_id=payload.get("node_id"),
        label=str(payload.get("label", "") or ""),
    )
