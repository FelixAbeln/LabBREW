from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

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
        return self._ui_specs.get(source_type, {})


def _make_runtime_for_ramps(initial_values: dict[str, float]) -> ControlRuntime:
    runtime = ControlRuntime.__new__(ControlRuntime)
    runtime.backend = FakeBackend(dict(initial_values))
    runtime.ownership = OwnershipManager()
    runtime._ramps = {}
    runtime._drop_target_from_rule_tracking = lambda target: None
    runtime.stop_ramp = lambda target: None
    return runtime


def _make_runtime(initial_values: dict[str, float] | None = None) -> ControlRuntime:
    runtime = ControlRuntime.__new__(ControlRuntime)
    runtime.backend = FakeBackend(dict(initial_values or {}))
    runtime.datasource_admin = FakeDatasourceAdmin()
    runtime.ownership = OwnershipManager()
    runtime._ramps = {}
    runtime._rule_states = {}
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
    assert snap["orphan_parameters"][0]["name"] == "orphan.param"
    assert snap["manual_controls"][0]["target"] == "manual.target"
    assert any(card["kind"] == "manual" for card in snap["ui_cards"])


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

    runtime.get_datasource_contract_snapshot = lambda: {
        "ok": True,
        "ui_cards": [{"card_id": "x"}],
        "datasource_backend": {"reachable": True},
        "control_map": {"source": "map.json"},
    }
    ui = runtime.get_control_ui_spec()
    assert ui["ok"] is True
    assert ui["manual_owner"] == "operator"
    assert ui["cards"] == [{"card_id": "x"}]


def test_runtime_iter_actions_release_guard_and_run_error_branch(monkeypatch) -> None:
    runtime = _make_runtime({"x": 1.0})

    assert runtime._iter_actions({"actions": [{"type": "set"}, "bad"]}) == [{"type": "set"}]
    assert runtime._iter_actions({"action": {"type": "set"}}) == [{"type": "set"}]
    assert runtime._iter_actions({}) == []

    state = ActiveRuleState(active=True, owned_targets={"x"})
    runtime.ownership.request("x", "safety")
    runtime._release_rule_targets_if_needed({"release_when_clear": False}, state)
    assert runtime.ownership.get_owner("x") == "safety"
    assert state.owned_targets == {"x"}

    calls = {"tick": 0, "sleep": 0}

    def bad_tick():
        calls["tick"] += 1
        raise RuntimeError("tick failed")

    def stop_sleep(_interval: float):
        calls["sleep"] += 1
        raise StopIteration()

    runtime.tick = bad_tick
    monkeypatch.setattr(control_runtime_module.time, "sleep", stop_sleep)

    with pytest.raises(StopIteration):
        runtime.run(interval=0.01)

    assert calls == {"tick": 1, "sleep": 1}
