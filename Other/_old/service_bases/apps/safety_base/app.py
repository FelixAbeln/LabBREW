from __future__ import annotations

from typing import Any

from ....service_bases.core.app_server import Route
from ....safety_service.service import SafetyRuleEngine


class SafetyBaseApp:
    def __init__(self, engine: SafetyRuleEngine) -> None:
        self.engine = engine

    def health(self, _: dict[str, Any]) -> dict[str, Any]:
        rules = self.engine.list_rules()
        return {
            'ok': True,
            'service': 'safety',
            'rule_count': len(rules.get('rules', [])),
        }

    def list_rules(self, _: dict[str, Any]) -> dict[str, Any]:
        return self.engine.list_rules()

    def replace_rules(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.engine.replace_rules(payload)

    def list_operators(self, _: dict[str, Any]) -> dict[str, Any]:
        defs = []
        for name in self.engine.operators.names():
            op = self.engine.operators.get(name)
            defs.append({
                'name': op.name,
                'description': op.description,
                'arg_schema': op.arg_schema or {},
            })
        return {'operators': [item['name'] for item in defs], 'operator_defs': defs}

    def evaluate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            'ok': True,
            'matches': self.engine.evaluate_reading(str(payload.get('signal_name', '')), payload.get('value')),
        }


def build_safety_routes(app: SafetyBaseApp) -> list[Route]:
    return [
        Route('GET', '/health', app.health),
        Route('GET', '/status', app.health),
        Route('GET', '/rules', app.list_rules),
        Route('GET', '/operators', app.list_operators),
        Route('POST', '/rules', app.replace_rules),
        Route('POST', '/evaluate', app.evaluate),
    ]
