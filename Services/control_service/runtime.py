from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from copy import deepcopy
from pathlib import Path
from collections import defaultdict

from ..parameterDB.parameterdb_core.client import SignalSession
from .._shared.parameterDB.paremeterDB import SignalStoreBackend
from .rules.storage import load_rules
from .rules.engine import RuleEngine
from .control.executor import execute_action, read_value, set_value_checked
from .control.ownership import OwnershipManager
from .control.utils import get_targets


ROOT = Path(__file__).resolve().parents[2]
CONTROL_VARIABLE_MAP_FILE = ROOT / "data" / "control_variable_map.json"
SAFETY_OWNER = "safety"
MANUAL_OWNER = "operator"
DATASOURCE_ADMIN_PORT = 8766


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
        self.datasource_admin = SignalSession(host=host, port=DATASOURCE_ADMIN_PORT, timeout=2.0)
        self.rule_engine = RuleEngine()
        self.rules: list[dict] = []
        self.ownership = OwnershipManager()
        self._rule_states: dict[str, ActiveRuleState] = {}
        self._ramps: dict[str, dict[str, Any]] = {}
        self._stop_event = threading.Event()
        self.reload_rules()

    def reload_rules(self):
        self.rules = load_rules()
        active_rule_ids = {
            str(rule.get("id"))
            for rule in self.rules
            if isinstance(rule, dict) and rule.get("id")
        }
        # Prevent long-lived growth from deleted/renamed rules.
        self._rule_states = {
            rule_id: state
            for rule_id, state in self._rule_states.items()
            if rule_id in active_rule_ids
        }
        self.rule_engine.prune_rules(active_rule_ids)

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

    def manual_set_parameter(self, target: str, value: Any, owner: str = MANUAL_OWNER, reason: str = "manual override") -> dict:
        """Manual write path: manual owner can take over any non-safety owner before writing."""
        # Ignore caller-provided owner for manual path to prevent safety lock bypass.
        owner = MANUAL_OWNER
        current_owner = self.ownership.get_owner(target)
        if current_owner == SAFETY_OWNER and owner != SAFETY_OWNER:
            return {
                "ok": False,
                "written": False,
                "blocked": True,
                "target": target,
                "value": value,
                "owner": owner,
                "current_owner": current_owner,
                "reason": "target owned by safety",
            }

        takeover = False
        if current_owner not in (None, owner):
            self._drop_target_from_rule_tracking(target)
            self.ownership.force_takeover(target, owner, reason=reason, owner_source="manual")
            self.stop_ramp(target)
            takeover = True
        elif current_owner is None:
            self.ownership.request(target, owner, reason=reason, owner_source="manual")

        written = bool(self.backend.set_value(target, value))
        return {
            "ok": written,
            "written": written,
            "blocked": False,
            "target": target,
            "value": value,
            "owner": owner,
            "takeover": takeover,
            "previous_owner": current_owner,
            "current_owner": self.ownership.get_owner(target),
            "backend_value": self.backend.get_value(target),
        }

    def release_manual_controls(self, targets: list[str] | None = None) -> dict:
        snapshot = self.ownership.snapshot()
        target_filter = set(targets or []) if targets else None
        released: list[str] = []
        skipped: list[str] = []

        for target, meta in snapshot.items():
            if target_filter is not None and target not in target_filter:
                continue

            owner_source = meta.get("owner_source")
            owner = meta.get("owner")
            is_manual = owner_source == "manual" or owner == MANUAL_OWNER
            if not is_manual:
                skipped.append(target)
                continue

            if self.ownership.release(target, owner):
                self._drop_target_from_rule_tracking(target)
                self.stop_ramp(target)
                released.append(target)

        return {
            "ok": True,
            "released": sorted(released),
            "released_count": len(released),
            "skipped": sorted(skipped),
        }

    def _load_control_contract(self) -> dict[str, Any]:
        default_contract: dict[str, Any] = {
            "version": 1,
            "description": "Control-to-parameter mapping for UI generation",
            "controls": [],
            "groups": [],
        }
        if not CONTROL_VARIABLE_MAP_FILE.exists():
            return default_contract
        try:
            payload = json.loads(CONTROL_VARIABLE_MAP_FILE.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            return {
                **default_contract,
                "error": f"failed to parse control contract: {exc}",
            }
        if not isinstance(payload, dict):
            return {
                **default_contract,
                "error": "contract root must be an object",
            }
        contract = dict(default_contract)
        contract.update(payload)
        if not isinstance(contract.get("controls"), list):
            contract["controls"] = []
        if not isinstance(contract.get("groups"), list):
            contract["groups"] = []

        sanitized_controls: list[dict[str, Any]] = []
        for control in contract["controls"]:
            if not isinstance(control, dict):
                continue
            item = dict(control)
            # Owner semantics are fixed by runtime policy, not map config.
            item.pop("owner", None)
            item.pop("manual_owner", None)
            sanitized_controls.append(item)
        contract["controls"] = sanitized_controls
        return contract

    def get_control_contract_snapshot(self) -> dict[str, Any]:
        contract = self._load_control_contract()
        values = self.backend.full_snapshot()
        ownership = self.ownership.snapshot()

        resolved_controls: list[dict[str, Any]] = []
        for control in contract.get("controls", []):
            if not isinstance(control, dict):
                continue
            item = dict(control)
            target = str(item.get("target", "")).strip()
            owner_meta = ownership.get(target) if target else None
            item["manual_owner"] = MANUAL_OWNER
            item["target_exists"] = bool(target) and (target in values)
            item["current_value"] = values.get(target) if target else None
            item["current_owner"] = owner_meta.get("owner") if isinstance(owner_meta, dict) else None
            item["safety_locked"] = item["current_owner"] == SAFETY_OWNER
            resolved_controls.append(item)

        return {
            "ok": True,
            "source": str(CONTROL_VARIABLE_MAP_FILE),
            "contract": contract,
            "resolved_controls": resolved_controls,
            "available_targets": sorted(values.keys()),
        }

    def get_datasource_contract_snapshot(self) -> dict[str, Any]:
        control_contract_snapshot = self.get_control_contract_snapshot()
        resolved_controls = control_contract_snapshot.get("resolved_controls", [])
        controls_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
        all_controls_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for control in resolved_controls:
            if not isinstance(control, dict):
                continue
            target = str(control.get("target", "")).strip()
            if not target:
                continue
            map_item = {
                "id": control.get("id"),
                "label": control.get("label"),
                "group": control.get("group"),
                "target": target,
                "widget": control.get("widget"),
                "write": deepcopy(control.get("write")) if isinstance(control.get("write"), dict) else control.get("write"),
                "kind": control.get("kind"),
                "unit": control.get("unit"),
                "step": control.get("step"),
                "min": control.get("min"),
                "max": control.get("max"),
                "current_value": control.get("current_value"),
                "current_owner": control.get("current_owner"),
                "safety_locked": bool(control.get("safety_locked")),
                "target_exists": bool(control.get("target_exists")),
            }
            controls_by_target[target].append(map_item)
            all_controls_by_target[target].append(map_item)

        try:
            raw_sources = self.datasource_admin.list_sources()
            source_backend_error = None
        except Exception as exc:
            raw_sources = {}
            source_backend_error = str(exc)

        described = self.backend.describe()
        source_parameters: dict[str, list[dict[str, Any]]] = defaultdict(list)
        all_source_parameter_names: set[str] = set()
        orphan_parameters: list[dict[str, Any]] = []

        for parameter_name, record in described.items():
            if not isinstance(record, dict):
                continue

            metadata = record.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}

            if metadata.get("created_by") != "data_source":
                continue

            source_name = str(metadata.get("owner", "")).strip()
            source_type = str(metadata.get("source_type", "")).strip()
            mapped_controls = controls_by_target.get(parameter_name, [])
            item = {
                "name": parameter_name,
                "parameter_type": record.get("parameter_type"),
                "value": record.get("value"),
                "role": metadata.get("role"),
                "unit": metadata.get("unit"),
                "device": metadata.get("device"),
                "source_type": source_type or None,
                "metadata": metadata,
                "mapped_controls": mapped_controls,
            }

            if source_name:
                source_parameters[source_name].append(item)
                all_source_parameter_names.add(parameter_name)
            else:
                orphan_parameters.append(item)

        datasources: list[dict[str, Any]] = []
        ui_cards: list[dict[str, Any]] = []
        active_source_names: set[str] = set()
        if isinstance(raw_sources, dict):
            for source_name in sorted(raw_sources):
                source = raw_sources[source_name]
                if not isinstance(source, dict):
                    continue
                active_source_names.add(source_name)
                parameters = sorted(source_parameters.get(source_name, []), key=lambda item: item["name"])
                parameters_by_name = {item["name"]: item for item in parameters}

                source_type = str(source.get("source_type") or "").strip()
                source_control_spec: dict[str, Any] = {}
                source_control_spec_error: str | None = None
                if source_type:
                    try:
                        source_control_spec = self.datasource_admin.get_source_type_ui(source_type, name=source_name, mode="control")
                        if not isinstance(source_control_spec, dict):
                            source_control_spec = {}
                    except Exception as exc:
                        source_control_spec = {}
                        source_control_spec_error = str(exc)

                control_items: list[dict[str, Any]] = []
                seen_targets: set[str] = set()

                for control in source_control_spec.get("controls", []) if isinstance(source_control_spec.get("controls"), list) else []:
                    if not isinstance(control, dict):
                        continue
                    target = str(control.get("target", "")).strip()
                    if not target:
                        continue
                    seen_targets.add(target)
                    param = parameters_by_name.get(target)
                    map_hint = controls_by_target.get(target, [])
                    map_item = map_hint[0] if map_hint else {}
                    control_items.append(
                        {
                            "id": control.get("id") or map_item.get("id") or target,
                            "label": map_item.get("label") or control.get("label") or target,
                            "target": target,
                            "widget": map_item.get("widget") or control.get("widget") or "text",
                            "unit": map_item.get("unit") or control.get("unit") or (param.get("unit") if isinstance(param, dict) else None),
                            "write": control.get("write") if isinstance(control.get("write"), dict) else {},
                            "role": control.get("role") or (param.get("role") if isinstance(param, dict) else None),
                            "current_value": param.get("value") if isinstance(param, dict) else None,
                            "source": "sourcedef",
                            "mapped": bool(map_item),
                        }
                    )

                for parameter in parameters:
                    role = str(parameter.get("role") or "").strip().lower()
                    target = str(parameter.get("name") or "").strip()
                    if not target or role not in {"command", "control"} or target in seen_targets:
                        continue
                    seen_targets.add(target)
                    value = parameter.get("value")
                    if isinstance(value, bool):
                        widget = "toggle"
                        write = {"kind": "bool"}
                    elif isinstance(value, (int, float)):
                        widget = "number"
                        write = {"kind": "number"}
                    else:
                        widget = "text"
                        write = {"kind": "string"}
                    map_hint = controls_by_target.get(target, [])
                    map_item = map_hint[0] if map_hint else {}
                    control_items.append(
                        {
                            "id": map_item.get("id") or f"auto:{target}",
                            "label": map_item.get("label") or target,
                            "target": target,
                            "widget": map_item.get("widget") or widget,
                            "unit": map_item.get("unit") or parameter.get("unit"),
                            "write": write,
                            "role": parameter.get("role"),
                            "current_value": value,
                            "source": "discovered",
                            "mapped": bool(map_item),
                        }
                    )

                for target, map_items in controls_by_target.items():
                    if target not in parameters_by_name or target in seen_targets:
                        continue
                    map_item = map_items[0] if map_items else {}
                    seen_targets.add(target)
                    param = parameters_by_name.get(target)
                    control_items.append(
                        {
                            "id": map_item.get("id") or target,
                            "label": map_item.get("label") or target,
                            "target": target,
                            "widget": map_item.get("widget") or "text",
                            "unit": map_item.get("unit") or (param.get("unit") if isinstance(param, dict) else None),
                            "write": {},
                            "role": param.get("role") if isinstance(param, dict) else None,
                            "current_value": param.get("value") if isinstance(param, dict) else None,
                            "source": "manual_map",
                            "mapped": True,
                        }
                    )

                controls = sorted(control_items, key=lambda item: (str(item.get("label") or "").lower(), str(item.get("target") or "")))
                datasources.append(
                    {
                        "name": source_name,
                        "source_type": source_type or source.get("source_type"),
                        "running": bool(source.get("running")),
                        "config": source.get("config") if isinstance(source.get("config"), dict) else {},
                        "parameter_count": len(parameters),
                        "control_count": len(controls),
                        "parameters": parameters,
                        "controls": controls,
                        "source_control_spec": source_control_spec,
                        "source_control_spec_error": source_control_spec_error,
                    }
                )
                ui_cards.append(
                    {
                        "card_id": f"source:{source_name}",
                        "kind": "datasource",
                        "title": source_name,
                        "subtitle": source_type,
                        "running": bool(source.get("running")),
                        "source_name": source_name,
                        "source_type": source_type,
                        "controls": controls,
                    }
                )

        orphan_sources: list[dict[str, Any]] = []
        for source_name in sorted(source_parameters):
            if source_name in active_source_names:
                continue
            parameters = sorted(source_parameters[source_name], key=lambda item: item["name"])
            controls = sorted(
                {
                    control.get("id"): control
                    for parameter in parameters
                    for control in parameter.get("mapped_controls", [])
                    if isinstance(control, dict) and control.get("id")
                }.values(),
                key=lambda item: str(item.get("id")),
            )
            source_type_candidates = {
                item.get("source_type")
                for item in parameters
                if item.get("source_type")
            }
            orphan_sources.append(
                {
                    "name": source_name,
                    "source_type": sorted(source_type_candidates)[0] if source_type_candidates else None,
                    "running": False,
                    "missing_from_datasource_service": True,
                    "parameter_count": len(parameters),
                    "control_count": len(controls),
                    "parameters": parameters,
                    "controls": controls,
                }
            )

        manual_controls: list[dict[str, Any]] = []
        for target, map_items in all_controls_by_target.items():
            if target in all_source_parameter_names:
                continue
            map_item = map_items[0] if map_items else {}
            widget = map_item.get("widget") or "text"
            # Build a write configuration for manual controls so that the UI
            # can infer input type and bounds from kind/min/max/step.
            write: dict[str, Any] = {}
            raw_write = map_item.get("write")
            if isinstance(raw_write, dict):
                # Preserve any explicit write configuration from the manual map.
                write = deepcopy(raw_write)
            else:
                kind = map_item.get("kind")
                if not kind:
                    # Infer kind from widget type if possible.
                    numeric_widgets = {"dial", "slider", "number", "numeric", "knob"}
                    bool_widgets = {"checkbox", "switch", "toggle"}
                    pulse_widgets = {"button", "momentary"}
                    if widget in numeric_widgets:
                        kind = "number"
                    elif widget in bool_widgets:
                        kind = "bool"
                    elif widget in pulse_widgets:
                        kind = "pulse"
                    else:
                        kind = "string"
                write["kind"] = kind
                # Propagate numeric hints from the manual map if present.
                for key in ("min", "max", "step"):
                    if key in map_item:
                        write[key] = map_item[key]
            manual_controls.append(
                {
                    "id": map_item.get("id") or target,
                    "label": map_item.get("label") or target,
                    "target": target,
                    "widget": widget,
                    "unit": map_item.get("unit"),
                    "write": write,
                    "current_value": map_item.get("current_value"),
                    "current_owner": map_item.get("current_owner"),
                    "safety_locked": bool(map_item.get("safety_locked")),
                    "source": "manual_map",
                    "mapped": True,
                    "target_exists": bool(map_item.get("target_exists")),
                }
            )
        manual_controls = sorted(manual_controls, key=lambda item: str(item.get("label") or "").lower())

        if manual_controls:
            ui_cards.append(
                {
                    "card_id": "manual:custom-map",
                    "kind": "manual",
                    "title": "Custom Manual Controls",
                    "subtitle": "control_variable_map.json",
                    "running": True,
                    "source_name": "manual_map",
                    "source_type": "manual",
                    "controls": manual_controls,
                }
            )

        return {
            "ok": True,
            "datasource_backend": {
                "host": self.datasource_admin.host,
                "port": self.datasource_admin.port,
                "reachable": source_backend_error is None,
                "error": source_backend_error,
            },
            "control_map": {
                "source": control_contract_snapshot.get("source"),
                "control_count": len(resolved_controls),
            },
            "datasources": datasources,
            "orphan_sources": orphan_sources,
            "orphan_parameters": sorted(orphan_parameters, key=lambda item: item["name"]),
            "manual_controls": manual_controls,
            "ui_cards": ui_cards,
        }

    def get_control_ui_spec(self) -> dict[str, Any]:
        snapshot = self.get_datasource_contract_snapshot()
        return {
            "ok": bool(snapshot.get("ok", False)),
            "manual_owner": MANUAL_OWNER,
            "write_path": "/control/manual-write",
            "release_path": "/control/release-manual",
            "cards": snapshot.get("ui_cards", []),
            "datasource_backend": snapshot.get("datasource_backend", {}),
            "control_map": snapshot.get("control_map", {}),
        }

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

        try:
            end_value = float(action["value"])
        except Exception:
            return {"ok": False, "error": "invalid value; must be numeric", "targets": targets}

        owner = action.get("owner", "rules")
        started = {}
        for target in targets:
            start_value = values.get(target, self.backend.get_value(target, 0))
            self._ramps[target] = {
                "start": start_value,
                "end": end_value,
                "duration": duration,
                "start_time": time.monotonic(),
                "owner": owner,
            }
            print(f"[RAMP] start {target} -> {end_value} in {duration}s")
            started[target] = {
                "start": start_value,
                "end": end_value,
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
                                    SAFETY_OWNER,
                                    action.get("reason", ""),
                                    owner_source="rule",
                                    rule_id=rule_id,
                                )
                                state.owned_targets.add(target)
                            if "value" in action:
                                set_action = {"type": "set", "targets": get_targets(action), "value": action["value"]}
                                action_result = execute_action(self.backend, set_action)
                            else:
                                action_result = {"ok": True, "targets": get_targets(action), "owner": SAFETY_OWNER}
                        elif action_type == "ramp":
                            ramp_action = dict(action)
                            ramp_action["owner"] = SAFETY_OWNER
                            action_result = self.start_ramp(ramp_action, values)
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

    def stop(self) -> None:
        """Signal the run loop to exit on its next iteration."""
        self._stop_event.set()

    def run(self, interval: float = 0.2):
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:
                print("Runtime error:", exc)

            self._stop_event.wait(timeout=interval)
