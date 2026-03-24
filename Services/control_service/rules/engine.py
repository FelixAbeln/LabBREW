import time
import threading

from ..._shared.operator_engine.loader import load_registry
from ..._shared.operator_engine.evaluator import ConditionEngine
from ..._shared.operator_engine.models import EvaluationState

from .parser import parse_condition


class RuleEngine:
    def __init__(self):
        self.registry = load_registry()
        self.engine = ConditionEngine(self.registry)
        self._states: dict[str, EvaluationState] = {}
        self._states_lock = threading.RLock()
        self._rule_locks: dict[str, threading.RLock] = {}

    def _get_rule_lock(self, rule_id: str) -> threading.RLock:
        # Guard lock-map mutation so each rule_id gets a stable lock instance.
        with self._states_lock:
            lock = self._rule_locks.get(rule_id)
            if lock is None:
                lock = threading.RLock()
                self._rule_locks[rule_id] = lock
            return lock

    def prune_rules(self, active_rule_ids: set[str]) -> None:
        """Drop state/locks for rules that no longer exist."""
        with self._states_lock:
            stale_state_ids = [rule_id for rule_id in self._states if rule_id not in active_rule_ids]
            for rule_id in stale_state_ids:
                self._states.pop(rule_id, None)

            stale_lock_ids = [rule_id for rule_id in self._rule_locks if rule_id not in active_rule_ids]
            for rule_id in stale_lock_ids:
                self._rule_locks.pop(rule_id, None)

    def evaluate(self, rule: dict, values: dict):
        rule_id = rule["id"]
        now = time.monotonic()

        condition = parse_condition(rule["condition"], path=f"rule:{rule_id}")
        # Serialize per-rule state transitions while allowing different rules
        # to evaluate concurrently.
        with self._get_rule_lock(rule_id):
            state = self._states.get(rule_id, EvaluationState())

            result = self.engine.evaluate(
                condition,
                values=values,
                now_monotonic=now,
                previous_state=state,
            )

            self._states[rule_id] = result.next_state
        return result