import time

from ..._shared.operator_engine.loader import load_registry
from ..._shared.operator_engine.evaluator import ConditionEngine
from ..._shared.operator_engine.models import EvaluationState

from .parser import parse_condition


class RuleEngine:
    def __init__(self):
        self.registry = load_registry()
        self.engine = ConditionEngine(self.registry)
        self._states: dict[str, EvaluationState] = {}

    def evaluate(self, rule: dict, values: dict):
        rule_id = rule["id"]
        now = time.monotonic()

        condition = parse_condition(rule["condition"], path=f"rule:{rule_id}")
        state = self._states.get(rule_id, EvaluationState())

        result = self.engine.evaluate(
            condition,
            values=values,
            now_monotonic=now,
            previous_state=state,
        )

        self._states[rule_id] = result.next_state
        return result