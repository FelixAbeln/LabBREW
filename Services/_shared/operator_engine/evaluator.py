from __future__ import annotations

from dataclasses import replace
from typing import Any

from .models import AtomicCondition, CompositeCondition, ConditionNode, EvaluationResult, EvaluationState
from .registry import OperatorRegistry


class ConditionEngine:
    def __init__(self, registry: OperatorRegistry) -> None:
        self._registry = registry

    def evaluate(
        self,
        condition: ConditionNode,
        *,
        values: dict[str, Any],
        now_monotonic: float,
        previous_state: EvaluationState | None = None,
    ) -> EvaluationResult:
        state = previous_state or EvaluationState()
        return self._evaluate_node(condition, values=values, now_monotonic=now_monotonic, state=state, path='root')

    def available_operators(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for metadata in self._registry.list_metadata():
            items.append(
                {
                    'name': metadata.name,
                    'label': metadata.label,
                    'description': metadata.description,
                    'value_type': metadata.value_type,
                    'supports_for_s': metadata.supports_for_s,
                    'param_schema': metadata.param_schema,
                }
            )
        return items

    def _evaluate_node(
        self,
        node: ConditionNode,
        *,
        values: dict[str, Any],
        now_monotonic: float,
        state: EvaluationState,
        path: str,
    ) -> EvaluationResult:
        if isinstance(node, AtomicCondition):
            return self._evaluate_atomic(node, values=values, now_monotonic=now_monotonic, state=state, path=path)
        return self._evaluate_composite(node, values=values, now_monotonic=now_monotonic, state=state, path=path)

    def _evaluate_atomic(
        self,
        node: AtomicCondition,
        *,
        values: dict[str, Any],
        now_monotonic: float,
        state: EvaluationState,
        path: str,
    ) -> EvaluationResult:
        node_id = node.node_id or path
        value = values.get(node.source)
        observed = {node.source: value}

        if value is None:
            return EvaluationResult(
                matched=False,
                raw_matched=False,
                true_for_s=0.0,
                node_id=node_id,
                message=f'Missing value for {node.source}',
                observed_values=observed,
                next_state=state,
            )

        raw = self._registry.evaluate(node.operator, value, node.params)
        return self._finish_result(
            node_id=node_id,
            raw_matched=raw,
            for_s=node.for_s,
            now_monotonic=now_monotonic,
            state=state,
            observed_values=observed,
            message=f'{node.source} {node.operator} {node.params}',
            children=[],
        )

    def _evaluate_composite(
        self,
        node: CompositeCondition,
        *,
        values: dict[str, Any],
        now_monotonic: float,
        state: EvaluationState,
        path: str,
    ) -> EvaluationResult:
        node_id = node.node_id or path
        children: list[EvaluationResult] = []
        for index, child in enumerate(node.children):
            child_result = self._evaluate_node(
                child,
                values=values,
                now_monotonic=now_monotonic,
                state=state,
                path=f'{node_id}.{index}',
            )
            children.append(child_result)

        if node.kind == 'all':
            raw = all(child.matched for child in children)
        elif node.kind == 'any':
            raw = any(child.matched for child in children)
        elif node.kind == 'not':
            if len(children) != 1:
                raise ValueError('not condition expects exactly one child')
            raw = not children[0].matched
        else:
            raise ValueError(f'Unsupported composite kind: {node.kind}')

        observed: dict[str, Any] = {}
        for child in children:
            observed.update(child.observed_values)

        return self._finish_result(
            node_id=node_id,
            raw_matched=raw,
            for_s=node.for_s,
            now_monotonic=now_monotonic,
            state=state,
            observed_values=observed,
            message=f'{node.kind} condition',
            children=children,
        )

    def _finish_result(
        self,
        *,
        node_id: str,
        raw_matched: bool,
        for_s: float,
        now_monotonic: float,
        state: EvaluationState,
        observed_values: dict[str, Any],
        message: str,
        children: list[EvaluationResult],
    ) -> EvaluationResult:
        node_state = state.get_or_create(node_id)
        if raw_matched:
            if not node_state.true_since_monotonic:
                node_state.true_since_monotonic = now_monotonic
            true_for_s = max(0.0, now_monotonic - node_state.true_since_monotonic)
        else:
            node_state.true_since_monotonic = None
            true_for_s = 0.0

        node_state.last_raw_matched = raw_matched
        required = max(0.0, float(for_s or 0.0))
        matched = raw_matched and true_for_s >= required
        hold_text = f' true for {true_for_s:.2f}/{required:.2f}s' if required > 0 else ''
        return EvaluationResult(
            matched=matched,
            raw_matched=raw_matched,
            true_for_s=true_for_s,
            node_id=node_id,
            message=f'{message}{hold_text}',
            observed_values=observed_values,
            children=children,
            next_state=state,
        )
