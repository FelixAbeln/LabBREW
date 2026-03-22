from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..shared_service.condition_engine import evaluate_condition_spec
from ..shared_service.condition_spec import condition_from_rule
from ..shared_service.operators import OperatorRegistry, build_default_operator_registry
from ..shared_service.rule_store import JsonRuleStore


@dataclass(slots=True)
class SafetyRuleEngine:
    rule_store: JsonRuleStore
    operators: OperatorRegistry

    @classmethod
    def from_root_data(cls, root_data: str) -> "SafetyRuleEngine":
        return cls(rule_store=JsonRuleStore(root_data), operators=build_default_operator_registry())

    def list_rules(self) -> dict[str, Any]:
        return self.rule_store.load()

    def replace_rules(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "schema_version": int(payload.get("schema_version", 1)),
            "rules": list(payload.get("rules", [])),
        }
        self.rule_store.save(payload)
        return {"ok": True, "message": f"Saved {len(payload['rules'])} rules", "rules": payload}

    def evaluate_reading(self, signal_name: str, value: Any) -> list[dict[str, Any]]:
        payload = self.rule_store.load()
        matches: list[dict[str, Any]] = []
        for rule in payload.get("rules", []):
            if not rule.get("enabled", True):
                continue
            if rule.get("target") != signal_name:
                continue
            spec = condition_from_rule(rule)
            result = evaluate_condition_spec(
                spec,
                now=0.0,
                step_started_monotonic=0.0,
                hold_started_monotonic=0.0 if float(rule.get("hold_for_s", 0.0) or 0.0) > 0 else None,
                get_value=lambda name: value if name == signal_name else None,
                registry=self.operators,
            )
            if result.ready:
                matches.append(
                    {
                        "rule_id": rule.get("id"),
                        "severity": rule.get("severity", "block"),
                        "message": rule.get("message", "Rule matched"),
                        "matched": True,
                        "rule": dict(rule),
                        "condition_spec": {
                            "kind": spec.kind,
                            "source": spec.source,
                            "operator": spec.operator,
                            "params": dict(spec.params),
                            "duration_s": spec.duration_s,
                            "hold_for_s": spec.hold_for_s,
                            "valid_sources": list(spec.valid_sources),
                            "label": spec.label,
                        },
                        "observed_values": result.observed_values,
                    }
                )
        return matches
