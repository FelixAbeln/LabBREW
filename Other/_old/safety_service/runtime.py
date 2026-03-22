from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..shared_service.condition_engine import evaluate_condition_spec, ConditionEvaluation
from ..shared_service.condition_spec import condition_from_rule
from ..shared_service.backend import SignalStoreBackend
from .service import SafetyRuleEngine


@dataclass(slots=True)
class SafetyRuntimeState:
    running: bool = False
    connected: bool = False
    last_tick_monotonic: float = 0.0
    last_error: str = ""
    active_rule_ids: list[str] = field(default_factory=list)
    active_count: int = 0
    block: bool = False
    message: str = ""
    rule_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "connected": self.connected,
            "last_tick_monotonic": self.last_tick_monotonic,
            "last_error": self.last_error,
            "active_rule_ids": list(self.active_rule_ids),
            "active_count": self.active_count,
            "block": self.block,
            "message": self.message,
            "rule_id": self.rule_id,
        }


class SafetyRuntimeService:
    """Continuously evaluates safety rules against backend values and publishes minimal safety.* state."""

    def __init__(self, engine: SafetyRuleEngine, backend: SignalStoreBackend, poll_interval_s: float = 0.25) -> None:
        self.engine = engine
        self.backend = backend
        self.poll_interval_s = max(0.05, float(poll_interval_s))

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._state = SafetyRuntimeState()
        self._rule_hold_started: dict[str, float | None] = {}
        self._published_once = False

    def start_background(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._state.running = True
            self._thread = threading.Thread(target=self._loop, name='safety-runtime', daemon=True)
            self._thread.start()

    def shutdown(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        with self._lock:
            self._state.running = False

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._state.to_dict()

    def tick_once(self) -> dict[str, Any]:
        with self._lock:
            self._tick_locked()
            return self._state.to_dict()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                with self._lock:
                    self._tick_locked()
            except Exception as exc:  # pragma: no cover
                with self._lock:
                    self._state.last_error = str(exc)
            time.sleep(self.poll_interval_s)

    def _ensure_output_parameters_locked(self) -> None:
        if self._published_once:
            return
        specs = [
            ('safety.block', 'bool', False),
            ('safety.message', 'string', ''),
            ('safety.rule_id', 'string', ''),
            ('safety.active_count', 'int', 0),
        ]
        for name, parameter_type, value in specs:
            try:
                self.backend.ensure_parameter(name=name, value=value)
            except Exception:
                pass
        self._published_once = True

    def _tick_locked(self) -> None:
        self._state.connected = self.backend.connected()
        self._state.last_tick_monotonic = time.monotonic()
        self._ensure_output_parameters_locked()

        payload = self.engine.list_rules()
        rules = [r for r in payload.get('rules', []) if r.get('enabled', True)]
        targets = sorted({str(r.get('target', '')).strip() for r in rules if str(r.get('target', '')).strip()})
        values = self.backend.snapshot(targets) if targets else {}

        active: list[dict[str, Any]] = []
        now = time.monotonic()


        for rule in rules:
            target = str(rule.get('target', '')).strip()
            if not target:
                continue
            rule_id = str(rule.get('id', '') or target)
            spec = condition_from_rule(rule)
            hold_started = self._rule_hold_started.get(rule_id)
            result = evaluate_condition_spec(
                spec,
                now=now,
                step_started_monotonic=now,
                hold_started_monotonic=hold_started,
                get_value=lambda name, _values=values: _values.get(name),
                registry=self.engine.operators,
            )
   
            if result.ready and hold_started is None and float(spec.hold_for_s or 0.0) > 0.0:
                self._rule_hold_started[rule_id] = now
            elif not result.ready:
                self._rule_hold_started[rule_id] = None

            if result.ready:
                active.append({
                    'rule_id': rule.get('id'),
                    'severity': rule.get('severity', 'block'),
                    'message': rule.get('message', 'Rule matched'),
                    'target': target,
                    'observed_values': result.observed_values,
                })

        block_rules = [r for r in active if str(r.get('severity', 'block')).lower() == 'block']
        top = block_rules[0] if block_rules else (active[0] if active else None)
        block = bool(block_rules)
        message = '' if top is None else str(top.get('message', ''))
        rule_id = '' if top is None else str(top.get('rule_id', ''))
        active_count = len(active)

        self.backend.set_value('safety.block', block)
        self.backend.set_value('safety.message', message)
        self.backend.set_value('safety.rule_id', rule_id)
        self.backend.set_value('safety.active_count', active_count)

        self._state.active_rule_ids = [str(r.get('rule_id', '')) for r in active if r.get('rule_id')]
        self._state.active_count = active_count
        self._state.block = block
        self._state.message = message
        self._state.rule_id = rule_id
        self._state.last_error = ''
