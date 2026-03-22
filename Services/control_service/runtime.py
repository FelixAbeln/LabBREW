from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from copy import deepcopy

from .._shared.parameterDB.paremeterDB import SignalStoreBackend
from .rules.storage import load_rules
from .rules.engine import RuleEngine
from .control.executor import execute_action, read_value, set_value_checked
from .control.ownership import OwnershipManager
from .control.utils import get_targets


@dataclass
class ActiveRuleState:
    active: bool = False
    owned_targets: set[str] = field(default_factory=set)


def collect_sources(condition: dict) -> set[str]:
    found: set[str] = set()

    if not isinstance(condition, dict):
        return found

    source = condition.get("source")
    if isinstance(source, str) and source:
        found.add(source)

    for child in condition.get("all", []):
        found |= collect_sources(child)

    for child in condition.get("any", []):
        found |= collect_sources(child)

    if "not" in condition:
        found |= collect_sources(condition["not"])

    return found


class ControlRuntime:
    def __init__(self, host: str, port: int):
        self.backend = SignalStoreBackend(host=host, port=port)
        self.rule_engine = RuleEngine()
        self.rules: list[dict] = []
        self.ownership = OwnershipManager()
        self._rule_states: dict[str, ActiveRuleState] = {}
        self._ramps: dict[str, dict[str, Any]] = {}
        self.reload_rules()

    def reload_rules(self):
        self.rules = load_rules()

    def _drop_target_from_rule_tracking(self, target: str, *, rule_id: str | None = None) -> None:
        states = [self._rule_states.get(rule_id)] if rule_id is not None else self._rule_states.values()
        for state in states:
            if state is not None:
                state.owned_targets.discard(target)

    def _group_held_rules_from_ownership(self, ownership: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        held_rules: dict[str, dict[str, Any]] = {}
        for target, meta in ownership.items():
            rule_id = meta.get("rule_id")
            if not rule_id:
                continue
            state = self._rule_states.get(rule_id)
            entry = held_rules.setdefault(
                rule_id,
                {
                    "active": bool(state.active) if state is not None else False,
                    "owned_targets": [],
                    "owner": meta.get("owner"),
                    "reason": meta.get("reason", ""),
                },
            )
            entry["owned_targets"].append(target)

        for info in held_rules.values():
            info["owned_targets"] = sorted(info["owned_targets"])
        return held_rules

    def request_control(self, target: str, owner: str) -> dict:
        ok = self.ownership.request(target, owner)
        if ok:
            self._drop_target_from_rule_tracking(target)
        return {
            "ok": ok,
            "target": target,
            "owner": owner,
            "current_owner": self.ownership.get_owner(target),
        }

    def release_control(self, target: str, owner: str) -> dict:
        ok = self.ownership.release(target, owner)
        if ok:
            self._drop_target_from_rule_tracking(target)
        return {
            "ok": ok,
            "target": target,
            "owner": owner,
            "current_owner": self.ownership.get_owner(target),
        }

    def force_takeover(self, target: str, owner: str, reason: str = "") -> dict:
        self._drop_target_from_rule_tracking(target)
        self.ownership.force_takeover(target, owner, reason=reason)
        self.stop_ramp(target)
        return {
            "ok": True,
            "target": target,
            "owner": owner,
            "reason": reason,
            "current_owner": self.ownership.get_owner(target),
        }

    def reset_target(self, target: str) -> dict:
        current_owner = self.ownership.get_owner(target)
        released = False
        if current_owner is not None:
            released = self.ownership.release(target, current_owner)
            if released:
                self._drop_target_from_rule_tracking(target)
        self.stop_ramp(target)
        return {
            "ok": True,
            "target": target,
            "released": released,
            "previous_owner": current_owner,
            "current_owner": self.ownership.get_owner(target),
        }

    def clear_all_ownership(self) -> dict:
        snapshot = self.ownership.snapshot()
        for target, meta in snapshot.items():
            owner = meta.get("owner")
            if owner is not None:
                released = self.ownership.release(target, owner)
                if released:
                    self._drop_target_from_rule_tracking(target)
            self.stop_ramp(target)
        return {"ok": True, "cleared": list(snapshot.keys())}

    def read_parameter(self, target: str, default: Any = None) -> dict:
        result = read_value(self.backend, target, default=default)
        result["current_owner"] = self.ownership.get_owner(target)
        return result

    def set_parameter(self, target: str, value: Any, owner: str) -> dict:
        result = set_value_checked(self.backend, self.ownership, target, value, owner)
        result["backend_value"] = self.backend.get_value(target)
        return result

    def start_ramp(self, action: dict, values: dict[str, Any] | None = None) -> dict:
        values = values or {}
        targets = get_targets(action)
        if not targets:
            return {"ok": False, "error": "missing target(s)"}
        if "value" not in action:
            return {"ok": False, "error": "missing value", "targets": targets}
        if "duration" not in action:
            return {"ok": False, "error": "missing duration", "targets": targets}

        try:
            duration = float(action["duration"])
        except Exception:
            return {"ok": False, "error": "invalid duration", "targets": targets}

        if duration <= 0:
            return {"ok": False, "error": "duration must be > 0", "targets": targets}

        owner = action.get("owner", "rules")
        started = {}
        for target in targets:
            start_value = values.get(target, self.backend.get_value(target, 0))
            self._ramps[target] = {
                "start": start_value,
                "end": action["value"],
                "duration": duration,
                "start_time": time.monotonic(),
                "owner": owner,
            }
            print(f"[RAMP] start {target} -> {action['value']} in {duration}s")
            started[target] = {
                "start": start_value,
                "end": action["value"],
                "duration": duration,
                "owner": owner,
            }
        return {"ok": True, "targets": targets, "started": started}

    def stop_ramp(self, target: str) -> bool:
        existed = target in self._ramps
        if existed:
            del self._ramps[target]
            print(f"[RAMP] stopped {target}")
        return existed

    def _tick_ramps(self) -> None:
        now = time.monotonic()
        for target, ramp in list(self._ramps.items()):
            current_owner = self.ownership.get_owner(target)

            if current_owner != ramp["owner"]:
                print(f"[RAMP] stopped {target} (ownership lost)")
                del self._ramps[target]
                continue

            elapsed = now - ramp["start_time"]
            fraction = min(elapsed / ramp["duration"], 1.0)
            value = ramp["start"] + (ramp["end"] - ramp["start"]) * fraction
            self.backend.set_value(target, value)

            if fraction >= 1.0:
                print(f"[RAMP] finished {target}")
                del self._ramps[target]

    def _iter_actions(self, rule: dict) -> list[dict]:
        if isinstance(rule.get("actions"), list):
            return [a for a in rule["actions"] if isinstance(a, dict)]
        if isinstance(rule.get("action"), dict):
            return [rule["action"]]
        return []

    def _release_rule_targets_if_needed(self, rule: dict, state: ActiveRuleState) -> None:
        if not rule.get("release_when_clear", False):
            return

        for target in list(state.owned_targets):
            current_owner = self.ownership.get_owner(target)
            if current_owner == "safety":
                released = self.ownership.release(target, "safety")
                if released:
                    print(f"[RULE] released ownership for {target}")
        state.owned_targets.clear()

    def tick(self):
        self.reload_rules()

        sources: set[str] = set()
        for rule in self.rules:
            sources |= collect_sources(rule.get("condition", {}))

        values = self.backend.snapshot(sorted(sources)) if sources else {}

        for rule in self.rules:
            rule_id = rule.get("id", "<no id>")
            if not rule.get("enabled", True):
                continue

            try:
                result = self.rule_engine.evaluate(rule, values)
            except Exception as exc:
                print(f"Rule evaluation error for {rule_id}: {exc}")
                continue

            state = self._rule_states.setdefault(rule_id, ActiveRuleState())
            actions = self._iter_actions(rule)

            if result.matched and not state.active:
                print(f"[RULE] ACTIVATE {rule_id}")
                for action in actions:
                    try:
                        action_type = action.get("type")
                        if action_type == "takeover":
                            for target in get_targets(action):
                                self._drop_target_from_rule_tracking(target)
                                self.ownership.force_takeover(
                                    target,
                                    action.get("owner", "safety"),
                                    action.get("reason", ""),
                                    owner_source="rule",
                                    rule_id=rule_id,
                                )
                                state.owned_targets.add(target)
                            if "value" in action:
                                set_action = {"type": "set", "targets": get_targets(action), "value": action["value"]}
                                action_result = execute_action(self.backend, set_action)
                            else:
                                action_result = {"ok": True, "targets": get_targets(action), "owner": action.get("owner", "safety")}
                        elif action_type == "ramp":
                            action_result = self.start_ramp(action, values)
                        else:
                            action_result = execute_action(self.backend, action)
                        print(f"[RULE] {rule_id} -> {action_result}")
                    except Exception as exc:
                        print(f"Rule action error for {rule_id}: {exc}")
                state.active = True

            elif result.matched and state.active:
                pass

            elif not result.matched and state.active:
                print(f"[RULE] CLEAR {rule_id}")
                self._release_rule_targets_if_needed(rule, state)
                state.active = False

        self._tick_ramps()


    def get_live_snapshot(self, targets: list[str] | None = None) -> dict[str, Any]:
        ownership = self.ownership.snapshot()
        ramp_snapshot: dict[str, dict[str, Any]] = {}
        for target, ramp in self._ramps.items():
            current = deepcopy(ramp)
            current["current_owner"] = self.ownership.get_owner(target)
            ramp_snapshot[target] = current

        held_rules = self._group_held_rules_from_ownership(ownership)
        active_rules = {
            rule_id: {
                "active": True,
                "owned_targets": sorted(state.owned_targets),
            }
            for rule_id, state in self._rule_states.items()
            if state.active
        }

        sample_targets: set[str] = set()
        sample_targets.update(ownership.keys())
        sample_targets.update(ramp_snapshot.keys())

        if targets:
            sample_targets.update(targets)

        if targets:
            values = self.backend.snapshot(sorted(sample_targets)) if sample_targets else {}
        else:
            values = self.backend.full_snapshot()

        if targets:
            ownership = {k: v for k, v in ownership.items() if k in targets}
            ramp_snapshot = {k: v for k, v in ramp_snapshot.items() if k in targets}
            values = {k: v for k, v in values.items() if k in targets}
            active_rules = {
                rule_id: info
                for rule_id, info in active_rules.items()
                if any(t in targets for t in info["owned_targets"])
            }
            held_rules = {
                rule_id: info
                for rule_id, info in held_rules.items()
                if any(t in targets for t in info["owned_targets"])
            }

        return {
            "ok": True,
            "timestamp": time.time(),
            "ownership": ownership,
            "ramps": ramp_snapshot,
            "active_rules": active_rules,
            "held_rules": held_rules,
            "values": values,
        }

    def run(self, interval: float = 0.2):
        while True:
            try:
                self.tick()
            except Exception as exc:
                print("Runtime error:", exc)

            time.sleep(interval)
