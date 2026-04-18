from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import Services.control_service.runtime as control_runtime_module
from Services.control_service.control.ownership import OwnershipManager
from Services.control_service.runtime import ActiveRuleState, ControlRuntime


class FakeBackend:
    def __init__(self, values: dict[str, float] | None = None):
        self.values = values or {}

    def get_value(self, target: str, default=0):
        return self.values.get(target, default)

    def set_value(self, target: str, value):
        self.values[target] = float(value)
        return True

    def snapshot(self, names: list[str]):
        return {name: self.values.get(name) for name in names if name in self.values}

    def full_snapshot(self):
        return dict(self.values)

    def describe(self):
        records: dict[str, dict[str, object]] = {}
        for name, value in self.values.items():
            records[name] = {
                "parameter_type": "fake",
                "value": value,
                "metadata": {},
            }
        return records


class FakeDatasourceAdmin:
    def __init__(self):
        self.host = "127.0.0.1"
        self.port = 8766
        self._sources: dict[str, dict[str, object]] = {}
        self._ui_specs: dict[str, dict[str, object]] = {}

    def list_sources(self):
        return dict(self._sources)

    def get_source_type_ui(self, source_type: str, *, name: str, mode: str):
        _ = name, mode
        return self._ui_specs.get(source_type, {})


def _make_runtime_for_ramps(initial_values: dict[str, float]) -> ControlRuntime:
    runtime = ControlRuntime.__new__(ControlRuntime)
    runtime.backend = FakeBackend(dict(initial_values))
    runtime.ownership = OwnershipManager()
    runtime._ramps = {}
    runtime._stop_event = threading.Event()
    runtime._drop_target_from_rule_tracking = lambda target: (target, None)[1]
    runtime.stop_ramp = lambda target: (target, None)[1]
    return runtime


def _make_runtime(initial_values: dict[str, float] | None = None) -> ControlRuntime:
    runtime = ControlRuntime.__new__(ControlRuntime)
    runtime.backend = FakeBackend(dict(initial_values or {}))
    runtime.datasource_admin = FakeDatasourceAdmin()
    runtime.ownership = OwnershipManager()
    runtime._ramps = {}
    runtime._rule_states = {}
    runtime._stop_event = threading.Event()
    runtime.rules = []
    runtime.rule_engine = SimpleNamespace(
        prune_rules=lambda _ids: None,
        evaluate=lambda _rule, _values: SimpleNamespace(matched=False),
    )
    return runtime


def test_control_runtime_ramp_interpolates_and_completes(monkeypatch) -> None:
    now = {"t": 100.0}

    def _mono():
        return now["t"]

    monkeypatch.setattr(control_runtime_module.time, "monotonic", _mono)

    runtime = _make_runtime_for_ramps({"reactor.temp.setpoint": 0.0})
    runtime.ownership.request("reactor.temp.setpoint", "tester")

    result = runtime.start_ramp(
        {
            "target": "reactor.temp.setpoint",
            "value": 10.0,
            "duration": 10.0,
            "owner": "tester",
        }
    )
    assert result["ok"] is True

    now["t"] = 105.0
    runtime._tick_ramps()
    assert runtime.backend.values["reactor.temp.setpoint"] == 5.0
    assert "reactor.temp.setpoint" in runtime._ramps

    now["t"] = 111.0
    runtime._tick_ramps()
    assert runtime.backend.values["reactor.temp.setpoint"] == 10.0
    assert "reactor.temp.setpoint" not in runtime._ramps


def test_control_runtime_ramp_stops_when_ownership_is_lost(monkeypatch) -> None:
    now = {"t": 10.0}

    def _mono():
        return now["t"]

    monkeypatch.setattr(control_runtime_module.time, "monotonic", _mono)

    runtime = _make_runtime_for_ramps({"pump.speed": 100.0})
    runtime.ownership.request("pump.speed", "schedule")

    runtime.start_ramp(
        {
            "target": "pump.speed",
            "value": 200.0,
            "duration": 20.0,
            "owner": "schedule",
        }
    )

    runtime.ownership.force_takeover("pump.speed", "operator", reason="manual override")
    now["t"] = 12.0
    runtime._tick_ramps()

    assert "pump.speed" not in runtime._ramps
    assert runtime.backend.values["pump.speed"] == 100.0


def test_manual_release_clears_only_manual_owners() -> None:
    runtime = _make_runtime_for_ramps({"reactor.temp": 20.0, "pump.speed": 100.0})

    manual = runtime.manual_set_parameter("reactor.temp", 32.0)
    runtime.ownership.request("pump.speed", "schedule_service")

    released = runtime.release_manual_controls()

    assert manual["ok"] is True
    assert released == {
        "ok": True,
        "released": ["reactor.temp"],
        "released_count": 1,
        "skipped": ["pump.speed"],
    }
    assert runtime.ownership.get_owner("reactor.temp") is None
    assert runtime.ownership.get_owner("pump.speed") == "schedule_service"


def test_reload_rules_prunes_state_and_calls_rule_engine(monkeypatch) -> None:
    runtime = _make_runtime()
    runtime._rule_states = {
        "keep": ActiveRuleState(active=True, owned_targets={"a"}),
        "drop": ActiveRuleState(active=True, owned_targets={"b"}),
    }
    captured: dict[str, object] = {}

    class FakeRuleEngine:
        def prune_rules(self, rule_ids: set[str]) -> None:
            captured["ids"] = set(rule_ids)

    runtime.rule_engine = FakeRuleEngine()

    monkeypatch.setattr(
        control_runtime_module,
        "load_rules",
        lambda: [{"id": "keep"}, {"id": "new"}, {"enabled": True}],
    )

    runtime.reload_rules()

    assert runtime.rules[0]["id"] == "keep"
    assert "keep" in runtime._rule_states
    assert "drop" not in runtime._rule_states
    assert captured["ids"] == {"keep", "new"}


def test_start_ramp_rejects_invalid_inputs() -> None:
    runtime = _make_runtime({"a": 1.0})

    assert runtime.start_ramp({"value": 1, "duration": 1}) == {
        "ok": False,
        "error": "missing target(s)",
    }
    assert runtime.start_ramp({"target": "a", "duration": 1}) == {
        "ok": False,
        "error": "missing value",
        "targets": ["a"],
    }
    assert runtime.start_ramp({"target": "a", "value": 2}) == {
        "ok": False,
        "error": "missing duration",
        "targets": ["a"],
    }
    assert runtime.start_ramp({"target": "a", "value": 2, "duration": "x"}) == {
        "ok": False,
        "error": "invalid duration",
        "targets": ["a"],
    }
    assert runtime.start_ramp({"target": "a", "value": 2, "duration": 0}) == {
        "ok": False,
        "error": "duration must be > 0",
        "targets": ["a"],
    }


def test_release_rule_targets_if_needed_releases_only_safety_owner() -> None:
    runtime = _make_runtime()
    state = ActiveRuleState(active=True, owned_targets={"safe.target", "operator.target"})
    runtime.ownership.force_takeover("safe.target", "safety")
    runtime.ownership.force_takeover("operator.target", "operator")

    runtime._release_rule_targets_if_needed({"release_when_clear": True}, state)

    assert runtime.ownership.get_owner("safe.target") is None
    assert runtime.ownership.get_owner("operator.target") == "operator"
    assert state.owned_targets == set()


def test_tick_activates_takeover_actions_then_releases_on_clear() -> None:
    runtime = _make_runtime({"sensor.temp": 10.0})
    runtime.reload_rules = lambda: None
    runtime.rules = [
        {
            "id": "rule-1",
            "enabled": True,
            "condition": {"source": "sensor.temp", "operator": ">", "params": {"threshold": 5}},
            "release_when_clear": True,
            "actions": [{"type": "takeover", "target": "reactor.temp", "value": 55.0}],
        }
    ]

    results = [SimpleNamespace(matched=True), SimpleNamespace(matched=False)]

    class FakeRuleEngine:
        def evaluate(self, _rule, _values):
            return results.pop(0)

    runtime.rule_engine = FakeRuleEngine()

    runtime.tick()
    assert runtime.ownership.get_owner("reactor.temp") == "safety"
    assert runtime.backend.values["reactor.temp"] == 55.0
    assert runtime._rule_states["rule-1"].active is True

    runtime.tick()
    assert runtime.ownership.get_owner("reactor.temp") is None
    assert runtime._rule_states["rule-1"].active is False


def test_get_live_snapshot_filters_targets_and_reports_held_rules() -> None:
    runtime = _make_runtime({"a": 1.0, "b": 2.0})
    runtime._ramps = {
        "a": {
            "start": 0.0,
            "end": 10.0,
            "duration": 5.0,
            "start_time": 1.0,
            "owner": "safety",
        },
        "b": {
            "start": 1.0,
            "end": 2.0,
            "duration": 3.0,
            "start_time": 2.0,
            "owner": "operator",
        },
    }
    runtime.ownership.force_takeover("a", "safety", rule_id="rule-1")
    runtime.ownership.force_takeover("b", "operator")
    runtime._rule_states = {
        "rule-1": ActiveRuleState(active=True, owned_targets={"a", "x"}),
        "rule-2": ActiveRuleState(active=True, owned_targets={"b"}),
    }

    snap = runtime.get_live_snapshot(targets=["a"])

    assert set(snap["ownership"]) == {"a"}
    assert set(snap["ramps"]) == {"a"}
    assert set(snap["values"]) == {"a"}
    assert set(snap["active_rules"]) == {"rule-1"}
    assert snap["held_rules"]["rule-1"]["owned_targets"] == ["a"]


def test_get_control_contract_snapshot_resolves_value_owner_and_safety_lock(monkeypatch, tmp_path: Path) -> None:
    runtime = _make_runtime({"reactor.temp": 18.5})
    runtime.ownership.force_takeover("reactor.temp", "safety")

    contract_file = tmp_path / "control_variable_map.json"
    contract_file.write_text(
        """
        {
          "controls": [
            {
              "id": "temp",
              "label": "Temperature",
              "target": "reactor.temp",
              "owner": "bad-config",
              "manual_owner": "bad-config"
            }
          ],
          "groups": []
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(control_runtime_module, "CONTROL_VARIABLE_MAP_FILE", contract_file)

    snap = runtime.get_control_contract_snapshot()

    assert snap["ok"] is True
    assert snap["resolved_controls"][0]["current_value"] == 18.5
    assert snap["resolved_controls"][0]["current_owner"] == "safety"
    assert snap["resolved_controls"][0]["safety_locked"] is True
    assert snap["resolved_controls"][0]["manual_owner"] == "operator"
    assert "owner" not in snap["contract"]["controls"][0]
    assert "manual_owner" not in snap["contract"]["controls"][0]


def test_get_datasource_contract_snapshot_guards_non_dict_inputs_and_non_dict_ui_spec() -> None:
    runtime = _make_runtime()
    runtime.get_control_contract_snapshot = lambda: {"source": "map.json", "resolved_controls": []}
    runtime.backend.describe = lambda: {
        "skip-record": "not-a-dict",
        "bad-meta": {"parameter_type": "fake", "value": 1, "metadata": "bad"},
        "manual": {"parameter_type": "fake", "value": 2, "metadata": {"created_by": "manual"}},
        "source.value": {
            "parameter_type": "fake",
            "value": 3,
            "metadata": {"created_by": "data_source", "owner": "src", "source_type": "demo", "role": "state"},
        },
    }
    runtime.datasource_admin.list_sources = lambda: {
        "bad-source": "not-a-dict",
        "src": {"source_type": "demo", "running": True, "config": {}},
    }
    runtime.datasource_admin.get_source_type_ui = lambda *_a, **_k: "not-a-dict"

    snapshot = runtime.get_datasource_contract_snapshot()

    assert len(snapshot["datasources"]) == 1
    assert snapshot["datasources"][0]["name"] == "src"
    assert snapshot["datasources"][0]["source_control_spec"] == {}
    assert snapshot["datasources"][0]["controls"] == []


def test_get_datasource_contract_snapshot_source_ui_exception_and_control_item_guards() -> None:
    runtime = _make_runtime()
    runtime.get_control_contract_snapshot = lambda: {"source": "map.json", "resolved_controls": []}
    runtime.backend.describe = lambda: {
        "src.value": {
            "parameter_type": "fake",
            "value": 1,
            "metadata": {"created_by": "data_source", "owner": "src", "source_type": "demo", "role": "state"},
        }
    }
    runtime.datasource_admin.list_sources = lambda: {
        "src": {"source_type": "demo", "running": True, "config": {}},
    }

    def raising_ui(*_args, **_kwargs):
        raise RuntimeError("ui failed")

    runtime.datasource_admin.get_source_type_ui = raising_ui
    snapshot = runtime.get_datasource_contract_snapshot()

    assert snapshot["datasources"][0]["source_control_spec_error"] == "ui failed"
    assert snapshot["datasources"][0]["controls"] == []

    runtime.datasource_admin.get_source_type_ui = lambda *_a, **_k: {
        "controls": [
            "bad",
            {"target": "   "},
            {"target": None},
            {"target": "src.value", "value_target": None},
        ]
    }
    snapshot = runtime.get_datasource_contract_snapshot()

    assert snapshot["datasources"][0]["source_control_spec"] == {
        "controls": [
            "bad",
            {"target": "   "},
            {"target": None},
            {"target": "src.value", "value_target": None},
        ]
    }
    controls = snapshot["datasources"][0]["controls"]
    assert len(controls) == 1
    assert controls[0]["target"] == "src.value"
    assert "value_target" not in controls[0]


def test_get_datasource_contract_snapshot_builds_datasource_orphan_and_manual_cards() -> None:
    runtime = _make_runtime()
    runtime.get_control_contract_snapshot = lambda: {
        "source": "map.json",
        "resolved_controls": [
            {
                "id": "mapped-temp",
                "label": "Mapped Temp",
                "group": "A",
                "target": "source.temp",
                "widget": "dial",
                "unit": "C",
                "step": None,
                "min": 0,
                "max": 100,
                "current_value": 20.0,
                "current_owner": None,
                "safety_locked": False,
                "target_exists": True,
            },
            {
                "id": "manual-only",
                "label": "Manual Only",
                "group": "B",
                "target": "manual.target",
                "widget": "slider",
                "unit": "%",
                "min": 0,
                "max": 1,
                "step": 0.1,
                "write": {"kind": "number"},
                "current_value": None,
                "current_owner": None,
                "safety_locked": False,
                "target_exists": False,
            },
        ],
    }
    runtime.backend.describe = lambda: {
        "source.temp": {
            "parameter_type": "fake",
            "value": 19.8,
            "metadata": {
                "created_by": "data_source",
                "owner": "brewtools",
                "source_type": "brewtools_can",
                "role": "command",
                "unit": "C",
            },
        },
        "orphan.param": {
            "parameter_type": "fake",
            "value": 1,
            "metadata": {
                "created_by": "data_source",
                "role": "state",
            },
        },
    }
    runtime.datasource_admin._sources = {
        "brewtools": {
            "source_type": "brewtools_can",
            "running": True,
            "config": {"port": "COM9"},
        }
    }
    runtime.datasource_admin._ui_specs = {
        "brewtools_can": {
            "app": {
                "kind": "sections",
                "version": 1,
                "sections": [
                    {
                        "id": "node-1",
                        "title": "Node 1",
                        "items": [{"kind": "control", "control_id": "source-temp", "action_label": "Apply"}],
                    }
                ],
            },
            "controls": [
                {
                    "id": "source-temp",
                    "target": "source.temp",
                    "widget": "number",
                    "write": {"kind": "number"},
                }
            ]
        }
    }

    snap = runtime.get_datasource_contract_snapshot()

    assert snap["ok"] is True
    assert snap["datasource_backend"]["reachable"] is True
    assert len(snap["datasources"]) == 1
    assert snap["datasources"][0]["name"] == "brewtools"
    assert snap["datasources"][0]["control_count"] == 1
    assert snap["ui_cards"][0]["app"]["kind"] == "sections"
    assert snap["ui_cards"][0]["app"]["sections"][0]["items"][0]["control_id"] == "source-temp"
    assert snap["orphan_parameters"][0]["name"] == "orphan.param"
    assert snap["manual_controls"][0]["target"] == "manual.target"
    manual_card = next(card for card in snap["ui_cards"] if card["kind"] == "manual")
    assert manual_card["app"]["kind"] == "sections"
    assert manual_card["app"]["sections"][0]["items"][0]["control_id"] == manual_card["controls"][0]["id"]


def test_get_datasource_contract_snapshot_marks_backend_unreachable_on_list_failure() -> None:
    runtime = _make_runtime()
    runtime.get_control_contract_snapshot = lambda: {"source": "map.json", "resolved_controls": []}
    runtime.backend.describe = lambda: {}

    def _raise_list_sources():
        raise RuntimeError("offline")

    runtime.datasource_admin.list_sources = _raise_list_sources

    snap = runtime.get_datasource_contract_snapshot()

    assert snap["ok"] is True
    assert snap["datasource_backend"]["reachable"] is False
    assert "offline" in str(snap["datasource_backend"]["error"])


def test_datasource_contract_snapshot_hides_empty_datasource_ui_cards() -> None:
    runtime = _make_runtime()
    runtime.get_control_contract_snapshot = lambda: {"source": "map.json", "resolved_controls": []}
    runtime.backend.describe = lambda: {
        "tilt_hydrometer.temperature": {
            "parameter_type": "float",
            "value": 20.0,
            "metadata": {
                "created_by": "data_source",
                "owner": "tilt",
                "source_type": "tilt_hydrometer",
                "role": "state",
            },
        }
    }
    runtime.datasource_admin._sources = {
        "tilt": {
            "source_type": "tilt_hydrometer",
            "running": True,
            "config": {},
        }
    }
    runtime.datasource_admin._ui_specs = {
        "tilt_hydrometer": {
            "controls": [],
        }
    }

    snap = runtime.get_datasource_contract_snapshot()

    assert len(snap["datasources"]) == 1
    assert snap["datasources"][0]["control_count"] == 0
    assert snap["ui_cards"] == []


def test_datasource_contract_snapshot_builds_fallback_app_for_discovered_controls() -> None:
    runtime = _make_runtime()
    runtime.get_control_contract_snapshot = lambda: {"source": "map.json", "resolved_controls": []}
    runtime.backend.describe = lambda: {
        "brewcan.agitator.0.set_pwm": {
            "parameter_type": "float",
            "value": 42.0,
            "metadata": {
                "created_by": "data_source",
                "owner": "brewtools",
                "source_type": "brewtools",
                "role": "command",
                "node_type": "agitator",
            },
        },
    }
    runtime.datasource_admin._sources = {
        "brewtools": {
            "source_type": "brewtools",
            "running": True,
            "config": {},
        }
    }
    runtime.datasource_admin._ui_specs = {
        "brewtools": {
            "app": {"kind": "sections", "version": 1, "sections": []},
            "controls": [],
        }
    }

    snap = runtime.get_datasource_contract_snapshot()

    card = next(card for card in snap["ui_cards"] if card["source_name"] == "brewtools")
    assert card["controls"]
    assert card["app"]["kind"] == "sections"
    assert card["app"]["sections"]
    assert card["app"]["sections"][0]["items"][0]["kind"] == "control"



def test_collect_sources_handles_nested_conditions_and_non_dict() -> None:
    assert control_runtime_module.collect_sources(["not", "a", "dict"]) == set()

    condition = {
        "source": "root",
        "all": [{"source": "a"}, {"any": [{"source": "b"}, {"not": {"source": "c"}}]}],
    }
    assert control_runtime_module.collect_sources(condition) == {"root", "a", "b", "c"}


def test_control_runtime_basic_ownership_wrappers() -> None:
    runtime = _make_runtime_for_ramps({"x": 1.0})

    req = runtime.request_control("x", "schedule")
    assert req["ok"] is True
    assert req["current_owner"] == "schedule"

    rel = runtime.release_control("x", "schedule")
    assert rel["ok"] is True
    assert rel["current_owner"] is None

    takeover = runtime.force_takeover("x", "operator", reason="manual")
    assert takeover["ok"] is True
    assert takeover["current_owner"] == "operator"


def test_reset_and_clear_all_ownership_paths() -> None:
    runtime = _make_runtime_for_ramps({"a": 1.0, "b": 2.0})
    runtime.ownership.request("a", "owner-a")
    runtime.ownership.request("b", "owner-b")

    reset = runtime.reset_target("a")
    assert reset["ok"] is True
    assert reset["released"] is True
    assert reset["current_owner"] is None

    cleared = runtime.clear_all_ownership()
    assert cleared["ok"] is True
    assert sorted(cleared["cleared"]) == ["b"]


def test_read_and_set_parameter_add_runtime_metadata(monkeypatch) -> None:
    runtime = _make_runtime({"x": 10.0})
    runtime.ownership.request("x", "operator")

    monkeypatch.setattr(control_runtime_module, "read_value", lambda _backend, target, default=None: {"ok": True, "target": target, "value": default})
    monkeypatch.setattr(control_runtime_module, "set_value_checked", lambda _backend, _ownership, target, value, owner: {"ok": True, "target": target, "value": value, "owner": owner})

    read_result = runtime.read_parameter("x", default=5)
    assert read_result["ok"] is True
    assert read_result["current_owner"] == "operator"

    set_result = runtime.set_parameter("x", 99.0, "operator")
    assert set_result["ok"] is True
    assert set_result["backend_value"] == 10.0


def test_control_runtime_init_and_ui_spec_projection(monkeypatch) -> None:
    class FakeRuleEngine:
        def __init__(self):
            self.pruned: set[str] | None = None

        def prune_rules(self, ids: set[str]):
            self.pruned = set(ids)

    fake_rule_engine = FakeRuleEngine()

    monkeypatch.setattr(control_runtime_module, "SignalStoreBackend", lambda host, port: {"host": host, "port": port})
    monkeypatch.setattr(control_runtime_module, "SignalSession", lambda host, port, timeout: SimpleNamespace(host=host, port=port, timeout=timeout))
    monkeypatch.setattr(control_runtime_module, "RuleEngine", lambda: fake_rule_engine)
    monkeypatch.setattr(control_runtime_module, "load_rules", lambda: [{"id": "r1", "enabled": True}])

    runtime = ControlRuntime("127.0.0.1", 8765)

    assert runtime.backend == {"host": "127.0.0.1", "port": 8765}
    assert runtime.datasource_admin.port == control_runtime_module.DATASOURCE_ADMIN_PORT
    assert fake_rule_engine.pruned == {"r1"}

    runtime.get_datasource_contract_snapshot = lambda include_empty_cards=False: {
        "_": include_empty_cards,
        "ok": True,
        "ui_cards": [{"card_id": "x"}],
        "datasource_backend": {"reachable": True},
        "control_map": {"source": "map.json"},
    }
    ui = runtime.get_control_ui_spec()
    assert ui["ok"] is True
    assert ui["manual_owner"] == "operator"
    assert ui["cards"] == [{"card_id": "x"}]


def test_get_control_ui_spec_passes_include_empty_cards_to_snapshot() -> None:
    runtime = _make_runtime()
    calls: list[bool] = []

    def fake_snapshot(include_empty_cards: bool = False):
        calls.append(include_empty_cards)
        return {
            "ok": True,
            "ui_cards": [],
            "datasource_backend": {"reachable": True},
            "control_map": {},
        }

    runtime.get_datasource_contract_snapshot = fake_snapshot

    runtime.get_control_ui_spec()
    runtime.get_control_ui_spec(include_empty_cards=True)

    assert calls == [False, True]


def test_runtime_iter_actions_release_guard_and_run_error_branch(monkeypatch) -> None:
    _ = monkeypatch
    runtime = _make_runtime({"x": 1.0})

    assert runtime._iter_actions({"actions": [{"type": "set"}, "bad"]}) == [{"type": "set"}]
    assert runtime._iter_actions({"action": {"type": "set"}}) == [{"type": "set"}]
    assert runtime._iter_actions({}) == []

    state = ActiveRuleState(active=True, owned_targets={"x"})
    runtime.ownership.request("x", "safety")
    runtime._release_rule_targets_if_needed({"release_when_clear": False}, state)
    assert runtime.ownership.get_owner("x") == "safety"
    assert state.owned_targets == {"x"}

    calls = {"tick": 0}

    def bad_tick():
        calls["tick"] += 1
        # Signal the loop to exit after this one tick.
        runtime._stop_event.set()
        raise RuntimeError("tick failed")

    runtime.tick = bad_tick
    runtime.run(interval=0.01)

    assert calls == {"tick": 1}


def test_load_control_contract_error_paths(monkeypatch, tmp_path: Path) -> None:
    runtime = _make_runtime()

    missing_path = tmp_path / "missing.json"
    monkeypatch.setattr(control_runtime_module, "CONTROL_VARIABLE_MAP_FILE", missing_path)
    assert runtime._load_control_contract()["controls"] == []

    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{bad", encoding="utf-8")
    monkeypatch.setattr(control_runtime_module, "CONTROL_VARIABLE_MAP_FILE", invalid_json)
    assert "error" in runtime._load_control_contract()

    wrong_root = tmp_path / "wrong_root.json"
    wrong_root.write_text("[1,2,3]", encoding="utf-8")
    monkeypatch.setattr(control_runtime_module, "CONTROL_VARIABLE_MAP_FILE", wrong_root)
    assert "error" in runtime._load_control_contract()

    wrong_types = tmp_path / "wrong_types.json"
    wrong_types.write_text('{"controls": "bad", "groups": 1}', encoding="utf-8")
    monkeypatch.setattr(control_runtime_module, "CONTROL_VARIABLE_MAP_FILE", wrong_types)
    payload = runtime._load_control_contract()
    assert payload["controls"] == []
    assert payload["groups"] == []

    mixed_controls = tmp_path / "mixed_controls.json"
    mixed_controls.write_text('{"controls": [{"id": "ok", "target": "x"}, "bad"], "groups": []}', encoding="utf-8")
    monkeypatch.setattr(control_runtime_module, "CONTROL_VARIABLE_MAP_FILE", mixed_controls)
    payload = runtime._load_control_contract()
    assert payload["controls"] == [{"id": "ok", "target": "x"}]


def test_control_contract_and_datasource_contract_guards(monkeypatch) -> None:
    runtime = _make_runtime({"x": 1.0})

    monkeypatch.setattr(
        runtime,
        "_load_control_contract",
        lambda: {
            "controls": [
                {"id": "ok", "target": " x "},
                {"id": "none", "target": None},
                {"id": "blank", "target": "   "},
                "bad",
                123,
            ],
            "groups": [],
        },
    )
    snap = runtime.get_control_contract_snapshot()
    assert len(snap["resolved_controls"]) == 1
    assert snap["resolved_controls"][0]["target"] == "x"

    runtime.get_control_contract_snapshot = lambda: {
        "source": "map.json",
        "resolved_controls": ["bad", {"id": "empty", "target": "   "}],
    }
    runtime.backend.describe = lambda: {}
    runtime.datasource_admin._sources = {}
    ds = runtime.get_datasource_contract_snapshot()
    assert ds["datasources"] == []


def test_manual_set_and_release_filter_and_stop_ramp_paths() -> None:
    runtime = _make_runtime({"safe": 1.0, "taken": 2.0, "a": 3.0, "b": 4.0})
    runtime._drop_target_from_rule_tracking = lambda _target: None

    runtime.ownership.force_takeover("safe", "safety")
    blocked = runtime.manual_set_parameter("safe", 9.0)
    assert blocked["ok"] is False
    assert blocked["blocked"] is True

    runtime.ownership.request("taken", "schedule_service")
    taken = runtime.manual_set_parameter("taken", 8.0)
    assert taken["ok"] is True
    assert taken["takeover"] is True
    assert taken["previous_owner"] == "schedule_service"

    runtime.ownership.request("a", "operator", owner_source="manual")
    runtime.ownership.request("b", "operator", owner_source="manual")
    released = runtime.release_manual_controls(targets=["a"])
    assert released["released"] == ["a"]
    assert runtime.ownership.get_owner("b") == "operator"

    runtime.ownership.request("r", "tester")
    runtime.start_ramp({"target": "r", "value": 10.0, "duration": 2.0, "owner": "tester"})
    assert runtime.stop_ramp("r") is True
    assert runtime.stop_ramp("r") is False


def test_datasource_contract_orphan_and_manual_widget_inference_paths() -> None:
    runtime = _make_runtime()
    runtime.datasource_admin._sources = {
        "dev": {"source_type": "dev_type", "running": True, "config": {}},
    }
    runtime.datasource_admin.get_source_type_ui = lambda *_a, **_k: {}

    runtime.get_control_contract_snapshot = lambda: {
        "source": "map.json",
        "resolved_controls": [
            {"id": "map-state", "label": "Map State", "group": None, "target": "dev.state", "widget": "text", "unit": None,
             "step": None, "min": None, "max": None, "current_value": "ok", "current_owner": None, "safety_locked": False, "target_exists": True},
            {"id": "m-dial", "label": "Dial", "group": None, "target": "manual.dial", "widget": "dial", "unit": None,
             "step": None, "min": 0, "max": 10, "current_value": None, "current_owner": None, "safety_locked": False, "target_exists": False},
            {"id": "m-toggle", "label": "Toggle", "group": None, "target": "manual.toggle", "widget": "toggle", "unit": None,
             "step": None, "min": None, "max": None, "current_value": None, "current_owner": None, "safety_locked": False, "target_exists": False},
            {"id": "m-button", "label": "Button", "group": None, "target": "manual.button", "widget": "button", "unit": None,
             "step": None, "min": None, "max": None, "current_value": None, "current_owner": None, "safety_locked": False, "target_exists": False},
            {"id": "m-write", "label": "Write", "group": None, "target": "manual.write", "widget": "number", "unit": None,
             "step": None, "min": None, "max": None, "write": {"kind": "number", "min": 0}, "current_value": None,
             "current_owner": None, "safety_locked": False, "target_exists": False},
            {"id": "m-text", "label": "Text", "group": None, "target": "manual.text", "widget": "textarea", "unit": None,
             "step": None, "min": None, "max": None, "current_value": None, "current_owner": None, "safety_locked": False, "target_exists": False},
        ],
    }

    runtime.backend.describe = lambda: {
        "dev.state": {
            "parameter_type": "str",
            "value": "ok",
            "metadata": {"created_by": "data_source", "owner": "dev", "source_type": "dev_type", "role": "state"},
        },
        "ghost.temp": {
            "parameter_type": "float",
            "value": 22.0,
            "metadata": {"created_by": "data_source", "owner": "ghost", "source_type": "ghost_type", "role": "state"},
        },
    }

    snapshot = runtime.get_datasource_contract_snapshot()
    assert snapshot["datasources"][0]["controls"][0]["target"] == "dev.state"
    assert snapshot["datasources"][0]["controls"][0]["current_owner"] is None
    assert snapshot["datasources"][0]["controls"][0]["safety_locked"] is False
    assert snapshot["orphan_sources"][0]["name"] == "ghost"

    manual = {item["target"]: item for item in snapshot["manual_controls"]}
    assert manual["manual.dial"]["write"]["kind"] == "number"
    assert manual["manual.toggle"]["write"]["kind"] == "bool"
    assert manual["manual.button"]["write"]["kind"] == "pulse"
    assert manual["manual.write"]["write"] == {"kind": "number", "min": 0}
    assert manual["manual.text"]["write"]["kind"] == "string"


def test_tick_rule_edge_paths_disabled_eval_error_takeover_ramp_generic_and_action_error() -> None:
    runtime = _make_runtime({"x": 0.0, "y": 0.0, "z": 0.0})
    runtime.reload_rules = lambda: None
    runtime._drop_target_from_rule_tracking = lambda _t: None

    class Engine:
        def evaluate(self, rule, _values):
            if rule.get("id") == "eval-error":
                raise RuntimeError("eval failure")
            return SimpleNamespace(matched=True)

    runtime.rule_engine = Engine()

    runtime.rules = [{"id": "disabled", "enabled": False, "actions": []}]
    runtime.tick()

    runtime.rules = [{"id": "eval-error", "enabled": True, "condition": {}, "actions": []}]
    runtime.tick()

    runtime._rule_states.clear()
    runtime.rules = [{"id": "takeover", "enabled": True, "condition": {}, "actions": [{"type": "takeover", "target": "x"}]}]
    runtime.tick()
    assert runtime.ownership.get_owner("x") == "safety"

    runtime._rule_states.clear()
    runtime.ownership.request("y", "safety")
    runtime.rules = [{"id": "ramp", "enabled": True, "condition": {}, "actions": [{"type": "ramp", "target": "y", "value": 5.0, "duration": 1.0}]}]
    runtime.tick()
    assert "y" in runtime._ramps

    runtime._rule_states.clear()
    runtime.rules = [{"id": "set", "enabled": True, "condition": {}, "actions": [{"type": "set", "target": "z", "value": 3.0}]}]
    runtime.tick()
    assert runtime.backend.values["z"] == 3.0

    class BadAction(dict):
        def get(self, key, default=None):
            if key == "type":
                raise RuntimeError("bad action")
            return super().get(key, default)

    runtime._rule_states.clear()
    runtime.rules = [{"id": "bad-action", "enabled": True, "condition": {}, "actions": [BadAction()]}]
    runtime.tick()


def test_datasource_contract_snapshot_discovers_command_and_control_parameters() -> None:
    runtime = _make_runtime()
    runtime.get_control_contract_snapshot = lambda: {
        "source": "map.json",
        "resolved_controls": [
            {
                "id": "mapped-count",
                "label": "Mapped Count",
                "group": "grp",
                "target": "src.count",
                "widget": "slider",
                "unit": "rpm",
                "step": 1,
                "min": 0,
                "max": 100,
                "current_value": 7,
                "current_owner": None,
                "safety_locked": False,
                "target_exists": True,
            },
        ],
    }
    runtime.datasource_admin._sources = {
        "src": {"source_type": "demo", "running": True, "config": {}},
    }
    runtime.datasource_admin.get_source_type_ui = lambda *_args, **_kwargs: {}
    runtime.backend.describe = lambda: {
        "src.flag": {
            "parameter_type": "bool",
            "value": True,
            "metadata": {
                "created_by": "data_source",
                "owner": "src",
                "source_type": "demo",
                "role": "command",
                "unit": None,
            },
        },
        "src.count": {
            "parameter_type": "number",
            "value": 7,
            "metadata": {
                "created_by": "data_source",
                "owner": "src",
                "source_type": "demo",
                "role": "control",
                "unit": "rpm",
            },
        },
        "src.label": {
            "parameter_type": "text",
            "value": "hello",
            "metadata": {
                "created_by": "data_source",
                "owner": "src",
                "source_type": "demo",
                "role": "command",
                "unit": None,
            },
        },
    }

    snapshot = runtime.get_datasource_contract_snapshot()
    controls = {item["target"]: item for item in snapshot["datasources"][0]["controls"]}

    assert controls["src.flag"]["widget"] == "toggle"
    assert controls["src.flag"]["write"] == {"kind": "bool"}
    assert controls["src.count"]["widget"] == "slider"
    assert controls["src.count"]["write"] == {"kind": "number"}
    assert controls["src.count"]["current_owner"] is None
    assert controls["src.count"]["safety_locked"] is False
    assert controls["src.label"]["widget"] == "text"
    assert controls["src.label"]["write"] == {"kind": "string"}


def test_datasource_contract_snapshot_propagates_current_owner_to_datasource_controls() -> None:
    runtime = _make_runtime()
    runtime.get_control_contract_snapshot = lambda: {
        "source": "map.json",
        "resolved_controls": [
            {
                "id": "mapped-temp",
                "label": "Set Temp",
                "group": "grp",
                "target": "src.temp",
                "widget": "number",
                "unit": "C",
                "step": 1,
                "min": 0,
                "max": 100,
                "current_value": 10,
                "current_owner": "scenario_service",
                "safety_locked": False,
                "target_exists": True,
            },
        ],
    }
    runtime.datasource_admin._sources = {
        "src": {"source_type": "demo", "running": True, "config": {}}
    }
    runtime.datasource_admin.get_source_type_ui = lambda *_args, **_kwargs: {}
    runtime.backend.describe = lambda: {
        "src.temp": {
            "parameter_type": "number",
            "value": 10,
            "metadata": {
                "created_by": "data_source",
                "owner": "src",
                "source_type": "demo",
                "role": "control",
                "unit": "C",
            },
        },
    }

    snapshot = runtime.get_datasource_contract_snapshot()
    controls = {item["target"]: item for item in snapshot["datasources"][0]["controls"]}
    assert controls["src.temp"]["current_owner"] == "scenario_service"
    assert controls["src.temp"]["safety_locked"] is False


def test_datasource_contract_snapshot_uses_live_ownership_for_unmapped_sourcedef_controls() -> None:
    runtime = _make_runtime()
    runtime.get_control_contract_snapshot = lambda: {
        "source": "map.json",
        "resolved_controls": [],
    }
    runtime.datasource_admin._sources = {
        "src": {"source_type": "demo", "running": True, "config": {}}
    }
    runtime.datasource_admin.get_source_type_ui = lambda *_args, **_kwargs: {
        "controls": [
            {
                "id": "set-temp",
                "label": "Set Temp",
                "target": "src.temp",
                "widget": "number",
                "write": {"kind": "number"},
            },
        ]
    }
    runtime.backend.describe = lambda: {
        "src.temp": {
            "parameter_type": "number",
            "value": 10,
            "metadata": {
                "created_by": "data_source",
                "owner": "src",
                "source_type": "demo",
                "role": "control",
                "unit": "C",
            },
        },
    }
    runtime.ownership.request("src.temp", "scenario_service")

    snapshot = runtime.get_datasource_contract_snapshot()
    controls = {item["target"]: item for item in snapshot["datasources"][0]["controls"]}
    assert controls["src.temp"]["current_owner"] == "scenario_service"
    assert controls["src.temp"]["safety_locked"] is False


def test_pin_and_unpin_control_parameter_persists_map_and_forces_manual_card(monkeypatch, tmp_path: Path) -> None:
    runtime = _make_runtime({"src.setpoint": 12.5})

    contract_file = tmp_path / "control_variable_map.json"
    monkeypatch.setattr(control_runtime_module, "CONTROL_VARIABLE_MAP_FILE", contract_file)

    bad_pin = runtime.pin_control_parameter(None)
    assert bad_pin["ok"] is False
    assert bad_pin["error"] == "target is required"

    pinned = runtime.pin_control_parameter(
        "src.setpoint",
        label="Source Setpoint",
        pin_scope="manual",
    )
    assert pinned["ok"] is True
    assert pinned["created"] is True

    saved = json.loads(contract_file.read_text(encoding="utf-8"))
    assert saved["controls"][0]["target"] == "src.setpoint"
    assert saved["controls"][0]["pin_scope"] == "manual"

    runtime.backend.describe = lambda: {
        "src.setpoint": {
            "parameter_type": "float",
            "value": 12.5,
            "metadata": {
                "created_by": "data_source",
                "owner": "src",
                "source_type": "demo",
                "role": "command",
            },
        }
    }
    runtime.datasource_admin._sources = {
        "src": {
            "source_type": "demo",
            "running": True,
            "config": {},
        }
    }

    snapshot = runtime.get_datasource_contract_snapshot()
    manual_targets = {item["target"] for item in snapshot["manual_controls"]}
    assert "src.setpoint" in manual_targets

    bad_unpin = runtime.unpin_control_parameter(None)
    assert bad_unpin["ok"] is False
    assert bad_unpin["error"] == "target is required"

    unpinned = runtime.unpin_control_parameter("src.setpoint")
    assert unpinned["ok"] is True
    assert unpinned["removed"] == 1

    saved_after = json.loads(contract_file.read_text(encoding="utf-8"))
    assert saved_after["controls"] == []


def test_tick_uses_ramp_generic_and_error_action_paths(monkeypatch) -> None:
    runtime = _make_runtime({"x": 1.0, "y": 2.0})
    runtime.reload_rules = lambda: None
    runtime._drop_target_from_rule_tracking = lambda _target: None

    class AlwaysMatchEngine:
        def evaluate(self, _rule, _values):
            return SimpleNamespace(matched=True)

    runtime.rule_engine = AlwaysMatchEngine()

    calls: dict[str, object] = {}

    def fake_start_ramp(action, values):
        calls["ramp_action"] = dict(action)
        calls["ramp_values"] = dict(values)
        return {"ok": True, "kind": "ramp"}

    def fake_execute_action(_backend, action):
        action_type = action.get("type")
        if action_type == "explode":
            raise RuntimeError("action failed")
        calls.setdefault("executed", []).append(dict(action))
        return {"ok": True, "kind": action_type}

    runtime.start_ramp = fake_start_ramp
    monkeypatch.setattr(control_runtime_module, "execute_action", fake_execute_action)

    runtime.rules = [
        {
            "id": "combo",
            "enabled": True,
            "condition": {"source": "x"},
            "actions": [
                {"type": "ramp", "target": "x", "value": 4.0, "duration": 1.5},
                {"type": "set", "target": "y", "value": 9.0},
                {"type": "explode", "target": "y"},
            ],
        }
    ]

    runtime.tick()

    assert calls["ramp_action"] == {"type": "ramp", "target": "x", "value": 4.0, "duration": 1.5, "owner": "safety"}
    assert calls["ramp_values"] == {"x": 1.0}
    assert calls["executed"] == [{"type": "set", "target": "y", "value": 9.0}]


def test_tick_matched_active_rule_hits_noop_branch() -> None:
    runtime = _make_runtime({"sensor": 1.0})
    runtime.reload_rules = lambda: None
    runtime.rules = [{"id": "rule-active", "enabled": True, "condition": {"source": "sensor"}, "actions": [{"type": "set", "target": "x", "value": 3.0}]}]
    runtime._rule_states = {"rule-active": ActiveRuleState(active=True, owned_targets=set())}

    class AlwaysMatchedEngine:
        def evaluate(self, _rule, _values):
            return SimpleNamespace(matched=True)

    runtime.rule_engine = AlwaysMatchedEngine()

    runtime.tick()

    assert runtime._rule_states["rule-active"].active is True
    assert "x" not in runtime.backend.values


def test_get_live_snapshot_without_targets_uses_full_snapshot() -> None:
    runtime = _make_runtime({"a": 1.0, "b": 2.0})
    runtime._ramps = {
        "a": {
            "start": 0.0,
            "end": 5.0,
            "duration": 2.0,
            "start_time": 1.0,
            "owner": "safety",
        }
    }
    runtime.ownership.force_takeover("a", "safety", rule_id="rule-1")
    runtime._rule_states = {"rule-1": ActiveRuleState(active=True, owned_targets={"a"})}

    snapshot = runtime.get_live_snapshot()

    assert snapshot["values"] == {"a": 1.0, "b": 2.0}
    assert "rule-1" in snapshot["active_rules"]
    assert "rule-1" in snapshot["held_rules"]
