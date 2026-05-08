from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from Services.parameterDB.parameterdb_core.client import SignalClient
from Services.parameterDB.parameterdb_sources.loader import DataSourceRegistry
from Services.parameterDB.serviceDS import SourceRunner, _builtin_source_root
from Services.parameterDB.sourceDefs.system_time.service import SystemTimeSourceSpec
from tests.integration_helpers import skip_if_parameterdb_unreachable, wait_until


def _source_def_folders() -> list[Path]:
    root = Path(_builtin_source_root())
    return sorted(
        child
        for child in root.iterdir()
        if child.is_dir() and not child.name.startswith("_")
    )


@pytest.mark.parametrize("folder", _source_def_folders(), ids=lambda path: path.name)
def test_builtin_source_def_folder_shape(folder: Path) -> None:
    service_file = folder / "service.py"
    ui_file = folder / "ui.py"

    assert service_file.exists()

    service_tree = ast.parse(service_file.read_text(encoding="utf-8"))
    has_source_symbol = any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SOURCE" for target in node.targets)
        for node in service_tree.body
    )
    assert has_source_symbol

    if ui_file.exists():
        ui_tree = ast.parse(ui_file.read_text(encoding="utf-8"))
        has_ui_entry = any(
            (isinstance(node, ast.FunctionDef) and node.name == "get_ui_spec")
            or (
                isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "UI_SPEC" for target in node.targets)
            )
            for node in ui_tree.body
        )
        assert has_ui_entry


def test_system_time_source_writes_to_live_parameterdb_when_available(tmp_path: Path) -> None:
    skip_if_parameterdb_unreachable()

    registry = DataSourceRegistry()
    registry.register(SystemTimeSourceSpec())

    client = SignalClient("127.0.0.1", 8765, timeout=2.0)
    runner = SourceRunner(client, registry, config_dir=str(tmp_path / "sources"))

    source_name = "it_system_time"
    param_name = f"it.{source_name}.value"

    runner.create_source(
        source_name,
        "system_time",
        config={
            "parameter_name": param_name,
            "parameter_prefix": f"it.{source_name}",
            "update_interval_s": 0.05,
        },
    )

    try:
        def _read_written_value() -> str | None:
            with client.session() as session:
                value = session.get_value(param_name)
            text = str(value).strip() if value is not None else ""
            return text or None

        observed = wait_until(_read_written_value, timeout_s=5.0, label="system_time source update")
        assert isinstance(observed, str)
        assert observed != ""
    finally:
        runner.delete_source(source_name)
        runner.stop_all()


def test_system_time_source_modes_error_path_and_defaults(monkeypatch) -> None:
    from Services.parameterDB.sourceDefs.system_time import (
        service as system_time_module,
    )

    class FakeClient:
        def __init__(self):
            self.calls: list[tuple[str, object]] = []
            self.fail = False

        def create_parameter(self, *_args, **_kwargs):
            return None

        def set_value(self, name: str, value):
            if self.fail and name == "sys.time.value":
                raise RuntimeError("write failed")
            self.calls.append((name, value))

    client = FakeClient()
    source = SystemTimeSourceSpec().create(
        "sys",
        client,
        config={
            "parameter_name": "sys.time.value",
            "parameter_prefix": "sys.time",
            "connected_param": "sys.connected.explicit",
            "last_error_param": "sys.error.explicit",
            "update_interval_s": 0.01,
            "mode": "unix_ms",
        },
    )

    assert source._status_param("connected") == "sys.connected.explicit"

    frozen_now = SimpleNamespace(
        timestamp=lambda: 1234.5,
        isoformat=lambda: "2026-03-29T10:00:00+00:00",
    )
    monkeypatch.setattr(system_time_module, "datetime", SimpleNamespace(now=lambda _tz: frozen_now))

    assert source._current_value() == 1234500
    source.config["mode"] = "unix"
    assert source._current_value() == 1234.5

    state = {"loops": 0}

    def fake_should_stop() -> bool:
        state["loops"] += 1
        return state["loops"] > 1

    source.should_stop = fake_should_stop  # type: ignore[assignment]
    source.sleep = lambda _s: False  # type: ignore[assignment]
    source.run()

    assert any(name == "sys.connected.explicit" and value is True for name, value in client.calls)
    assert any(name == "sys.time.last_sync" for name, _ in client.calls)

    client.calls.clear()
    client.fail = True
    state["loops"] = 0
    source.run()

    assert any(name == "sys.connected.explicit" and value is False for name, value in client.calls)
    assert any(name == "sys.error.explicit" and "write failed" in str(value) for name, value in client.calls)

    defaults = SystemTimeSourceSpec().default_config()
    assert defaults["parameter_name"] == "system.time.iso"
    assert defaults["parameter_prefix"] == "system.time"


@pytest.mark.parametrize(
    ("sender_node_type", "expected_status", "other_status"),
    [
        ("NODE_TYPE_DENSITY_SENSOR", "brewcan.density.1.calibrate_status", "brewcan.pressure.1.calibrate_status"),
        ("NODE_TYPE_PRESSURE_SENSOR", "brewcan.pressure.1.calibrate_status", "brewcan.density.1.calibrate_status"),
    ],
)
def test_brewtools_calibration_ack_updates_only_matching_sensor_status(
    sender_node_type: str,
    expected_status: str,
    other_status: str,
) -> None:
    from Services.parameterDB.sourceDefs.brewtools.brewtools_can import BrewtoolsCanId, Priority
    from Services.parameterDB.sourceDefs.brewtools.brewtools_can.enums import AckType, MsgType, NodeType
    from Services.parameterDB.sourceDefs.brewtools.service import BrewtoolsSource

    class FakeClient:
        def __init__(self):
            self.values: dict[str, object] = {}

        def create_parameter(self, name: str, *_args, value=None, **_kwargs):
            self.values.setdefault(name, value)
            return None

        def update_metadata(self, _name: str, **_changes):
            return True

        def set_value(self, name: str, value):
            self.values[name] = value

        def get_value(self, name: str, default=None):
            return self.values.get(name, default)

    class CalibrationAck:
        def __init__(self, node_id: int, ack_type: int):
            self.node_id = node_id
            self.ack_type = ack_type

    client = FakeClient()
    source = BrewtoolsSource("brewcan", client, config={"parameter_prefix": "brewcan"})
    source._ensure_density_calibrate_params(1)
    source._ensure_pressure_calibrate_params(1)

    frame = SimpleNamespace(
        can_id=BrewtoolsCanId(
            priority=int(Priority.MEDIUM),
            sender_node_type=int(getattr(NodeType, sender_node_type)),
            receiver_node_type=int(NodeType.NODE_TYPE_PLC),
            secondary_node_id=1,
            msg_type=int(MsgType.MSG_TYPE_CALIBRATION_ACK),
        )
    )

    source._handle_event(
        arbitration_id=frame.can_id.to_arbitration_id(),
        data=b"",
        frame=frame,
        obj=CalibrationAck(node_id=1, ack_type=int(AckType.ACK_TYPE_OK)),
    )

    assert client.values[expected_status] == "ok"
    assert client.values[other_status] == ""


def test_brewtools_calibration_ack_unknown_sender_updates_both_statuses() -> None:
    """Fallback: when sender_node_type is 0 (unknown), both density and pressure
    calibrate_status parameters are updated."""
    from Services.parameterDB.sourceDefs.brewtools.brewtools_can import BrewtoolsCanId, Priority
    from Services.parameterDB.sourceDefs.brewtools.brewtools_can.enums import AckType, MsgType, NodeType
    from Services.parameterDB.sourceDefs.brewtools.service import BrewtoolsSource

    class FakeClient:
        def __init__(self):
            self.values: dict[str, object] = {}

        def create_parameter(self, name: str, *_args, value=None, **_kwargs):
            self.values.setdefault(name, value)
            return None

        def update_metadata(self, _name: str, **_changes):
            return True

        def set_value(self, name: str, value):
            self.values[name] = value

        def get_value(self, name: str, default=None):
            return self.values.get(name, default)

    class CalibrationAck:
        def __init__(self, node_id: int, ack_type: int):
            self.node_id = node_id
            self.ack_type = ack_type

    client = FakeClient()
    source = BrewtoolsSource("brewcan", client, config={"parameter_prefix": "brewcan"})
    source._ensure_density_calibrate_params(1)
    source._ensure_pressure_calibrate_params(1)

    # sender_node_type=0 means unknown – neither density nor pressure
    frame = SimpleNamespace(
        can_id=BrewtoolsCanId(
            priority=int(Priority.MEDIUM),
            sender_node_type=0,
            receiver_node_type=int(NodeType.NODE_TYPE_PLC),
            secondary_node_id=1,
            msg_type=int(MsgType.MSG_TYPE_CALIBRATION_ACK),
        )
    )

    source._handle_event(
        arbitration_id=frame.can_id.to_arbitration_id(),
        data=b"",
        frame=frame,
        obj=CalibrationAck(node_id=1, ack_type=int(AckType.ACK_TYPE_OK)),
    )

    assert client.values["brewcan.density.1.calibrate_status"] == "ok"
    assert client.values["brewcan.pressure.1.calibrate_status"] == "ok"


def test_system_time_source_ui_has_parameter_prefix_field() -> None:
    from Services.parameterDB.sourceDefs.system_time.ui import get_ui_spec

    ui = get_ui_spec(mode="create")
    create = ui["create"]
    assert "config.parameter_prefix" in create["required"]
    assert create["defaults"]["config"]["parameter_prefix"] == "system.time"
    assert create["defaults"]["config"]["parameter_name"] == ""


def test_system_time_source_uses_prefix_when_parameter_name_missing() -> None:
    from Services.parameterDB.sourceDefs.system_time.service import SystemTimeSourceSpec

    class FakeClient:
        def __init__(self):
            self.created: list[str] = []

        def create_parameter(self, name: str, *_args, **_kwargs):
            self.created.append(name)
            return None

        def set_value(self, _name: str, _value):
            return None

    client = FakeClient()
    source = SystemTimeSourceSpec().create(
        "clock",
        client,
        config={
            "parameter_prefix": "clock.main",
            "parameter_name": "",
            "update_interval_s": 1.0,
            "mode": "iso",
        },
    )

    source.ensure_parameters()

    assert "clock.main.iso" in client.created


def test_tilt_hydrometer_source_ui_has_color_dropdown() -> None:
    from Services.parameterDB.sourceDefs.tilt_hydrometer.ui import get_ui_spec

    ui = get_ui_spec()
    create_sections = ui["create"]["sections"]
    color_field = next(
        field
        for section in create_sections
        for field in section.get("fields", [])
        if field.get("key") == "config.tilt_color"
    )

    assert color_field["type"] == "enum"
    assert color_field["choices"] == ["Red", "Green", "Black", "Purple", "Orange", "Blue", "Yellow", "Pink"]

    transport_field = next(
        field
        for section in create_sections
        for field in section.get("fields", [])
        if field.get("key") == "config.transport"
    )
    assert transport_field["type"] == "enum"
    assert transport_field["choices"] == ["bridge", "ble"]


def test_all_builtin_source_defs_expose_unified_app_schema() -> None:
    from Services.parameterDB.sourceDefs.brewtools.ui import get_ui_spec as get_brewtools_ui_spec
    from Services.parameterDB.sourceDefs.digital_twin.ui import get_ui_spec as get_twin_ui_spec
    from Services.parameterDB.sourceDefs.labps3005dn.ui import get_ui_spec as get_psu_ui_spec
    from Services.parameterDB.sourceDefs.modbus_relay.ui import get_ui_spec as get_relay_ui_spec
    from Services.parameterDB.sourceDefs.system_time.ui import get_ui_spec as get_system_time_ui_spec
    from Services.parameterDB.sourceDefs.tilt_hydrometer.ui import get_ui_spec as get_tilt_ui_spec

    ui_providers = [
        get_brewtools_ui_spec,
        get_twin_ui_spec,
        get_psu_ui_spec,
        get_relay_ui_spec,
        get_system_time_ui_spec,
        get_tilt_ui_spec,
    ]

    for provider in ui_providers:
        create_ui = provider(mode="create")
        edit_ui = provider(mode="edit")
        control_ui = provider(mode="control")

        assert create_ui["create"]["app"]["kind"] == "sections"
        assert edit_ui["edit"]["app"]["kind"] == "sections"
        assert control_ui["app"]["kind"] == "sections"


def test_command_sources_report_graph_dependencies_from_source_defs() -> None:
    from Services.parameterDB.sourceDefs.brewtools.ui import (
        get_ui_spec as get_brewtools_ui_spec,
    )
    from Services.parameterDB.sourceDefs.digital_twin.ui import (
        get_ui_spec as get_twin_ui_spec,
    )
    from Services.parameterDB.sourceDefs.labps3005dn.ui import (
        get_ui_spec as get_psu_ui_spec,
    )
    from Services.parameterDB.sourceDefs.modbus_relay.ui import (
        get_ui_spec as get_relay_ui_spec,
    )

    relay_ui = get_relay_ui_spec(record={"name": "relay", "config": {"parameter_prefix": "relay", "channel_count": 3}}, mode="edit")
    assert relay_ui["graph"]["depends_on"] == ["relay.ch1", "relay.ch2", "relay.ch3"]

    psu_ui = get_psu_ui_spec(record={"name": "psu", "config": {"parameter_prefix": "psu"}}, mode="edit")
    assert psu_ui["graph"]["depends_on"] == ["psu.set_enable", "psu.set_voltage", "psu.set_current"]

    brewtools_ui = get_brewtools_ui_spec(
        record={"name": "brewcan", "config": {"parameter_prefix": "brewcan", "agitator_nodes": [7, 3, 7]}},
        mode="edit",
    )
    assert brewtools_ui["graph"]["depends_on"] == [
        "brewcan.agitator.3.set_pwm",
        "brewcan.agitator.7.set_pwm",
        "brewcan.density.0.calibrate",
        "brewcan.density.0.calibrate_sg",
        "brewcan.pressure.0.calibrate",
    ]
    assert brewtools_ui["edit"]["app"]["kind"] == "sections"
    assert brewtools_ui["create"]["app"]["kind"] == "sections"
    control_ui = get_brewtools_ui_spec(
        record={
            "name": "brewcan",
            "config": {
                "parameter_prefix": "brewcan",
                "agitator_nodes": [3],
                "density_nodes": [0],
                "pressure_nodes": [0],
            },
        },
        mode="control",
    )
    assert control_ui["app"]["kind"] == "sections"
    assert control_ui["app"]["sections"][0]["title"] == "Node 3"
    assert control_ui["app"]["sections"][0]["items"][0]["control_id"] == "agitator_pwm_3"

    twin_ui = get_twin_ui_spec(
        record={
            "name": "twin",
            "config": {
                "parameter_prefix": "twin",
                "input_bindings": {
                    "in_level": "brewcan.level.0",
                    "in_pressure": "dbc_press_Fermenter_Hi",
                },
                "reset_param": "twin.reset",
            },
        },
        mode="edit",
    )
    assert twin_ui["graph"]["depends_on"] == [
        "brewcan.level.0",
        "dbc_press_Fermenter_Hi",
        "twin.reset",
    ]


def test_modbus_relay_ui_module_uses_zero_input_scan() -> None:
    from Services.parameterDB.sourceDefs.modbus_relay.ui import get_ui_spec

    ui = get_ui_spec(mode="edit")
    module = dict(ui.get("module") or {})
    menu = dict(module.get("menu") or {})
    run = dict(menu.get("run") or {})
    action = dict(menu.get("action") or {})

    assert module.get("replace_form") is True
    assert menu.get("fields") == []
    assert run.get("mode") == "auto"
    assert run.get("cancel_inflight_on_cleanup") is True
    assert action.get("action") == "scan_relays"


def test_modbus_relay_run_ui_action_auto_scan_returns_reachable_only(monkeypatch) -> None:
    from Services.parameterDB.sourceDefs.modbus_relay import ui as relay_ui

    monkeypatch.setattr(relay_ui, "_candidate_hosts", lambda *_args, **_kwargs: ["h1", "h2"])
    monkeypatch.setattr(relay_ui, "_candidate_ports", lambda *_args, **_kwargs: [502, 4196])
    monkeypatch.setattr(relay_ui, "_candidate_unit_ids", lambda *_args, **_kwargs: [1])
    monkeypatch.setattr(
        relay_ui,
        "_discover_open_targets",
        lambda hosts, ports, timeout: [(host, port) for host in hosts for port in ports],
    )

    def _fake_probe(host: str, port: int, unit_id: int, timeout: float):
        _ = (unit_id, timeout)
        if host == "h2" and port == 4196:
            return {
                "host": host,
                "port": port,
                "unit_id": 1,
                "channel_count": 8,
                "reachable": True,
                "error": "",
                "states": [{"channel": 1, "state": True}],
            }
        return {
            "host": host,
            "port": port,
            "unit_id": 1,
            "channel_count": 0,
            "reachable": False,
            "error": "offline",
            "states": [],
        }

    monkeypatch.setattr(relay_ui, "_probe_host_port", _fake_probe)

    result = relay_ui.run_ui_action("scan", payload={})

    assert result["action"] == "scan_relays"
    assert result["scanned"] == 4
    assert result["open_targets"] == 4
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["host"] == "h2"
    assert result["candidates"][0]["port"] == 4196


def test_tilt_hydrometer_source_publishes_selected_color_and_connected_state(monkeypatch) -> None:
    from Services.parameterDB.sourceDefs.tilt_hydrometer.service import (
        TiltHydrometerSourceSpec,
    )

    class FakeClient:
        def __init__(self):
            self.calls: list[tuple[str, object]] = []

        def create_parameter(self, *_args, **_kwargs):
            return None

        def set_value(self, name: str, value):
            self.calls.append((name, value))

    class FakeResponse:
        def __init__(self, payload: bytes):
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    payload = b'[{"Color":"Red","SG":1048,"Temp":68,"RSSI":-70,"WeeksOnBattery":12}]'
    missing_payload = b'[{"Color":"Blue","SG":1030,"Temp":66}]'
    state = {"count": 0}

    def fake_urlopen(_req, timeout=0):
        _ = timeout
        state["count"] += 1
        if state["count"] == 1:
            return FakeResponse(payload)
        return FakeResponse(missing_payload)

    client = FakeClient()
    source = TiltHydrometerSourceSpec().create(
        "tilt_red",
        client,
        config={
            "transport": "bridge",
            "bridge_url": "http://tiltbridge.local/json",
            "tilt_color": "Red",
            "parameter_prefix": "tilt",
            "update_interval_s": 0.01,
        },
    )

    from Services.parameterDB.sourceDefs.tilt_hydrometer import service as tilt_module

    monkeypatch.setattr(tilt_module, "urlopen", fake_urlopen)

    loop_state = {"loops": 0}

    def fake_should_stop() -> bool:
        loop_state["loops"] += 1
        return loop_state["loops"] > 1

    source.should_stop = fake_should_stop  # type: ignore[assignment]
    source.sleep = lambda _s: False  # type: ignore[assignment]
    source.run()

    assert any(name == "tilt.connected" and value is True for name, value in client.calls)
    assert any(name == "tilt.gravity" and abs(float(value) - 1.048) < 1e-9 for name, value in client.calls if value is not None)
    assert any(name == "tilt.temperature_f" and float(value) == 68.0 for name, value in client.calls if value is not None)

    client.calls.clear()
    loop_state["loops"] = 0
    source.run()

    assert any(name == "tilt.connected" and value is False for name, value in client.calls)
    assert any(name == "tilt.last_error" and "not present" in str(value) for name, value in client.calls)

    defaults = TiltHydrometerSourceSpec().default_config()
    assert defaults["transport"] == "bridge"
    assert defaults["tilt_color"] == "Red"
    assert defaults["ble_idle_s"] == 0.0
    assert defaults["ble_stale_after_s"] == 20.0


def test_tilt_hydrometer_source_ble_transport_connected_and_missing(monkeypatch) -> None:
    _ = monkeypatch
    from Services.parameterDB.sourceDefs.tilt_hydrometer.service import (
        TiltHydrometerSourceSpec,
    )

    class FakeClient:
        def __init__(self):
            self.calls: list[tuple[str, object]] = []

        def create_parameter(self, *_args, **_kwargs):
            return None

        def set_value(self, name: str, value):
            self.calls.append((name, value))

    client = FakeClient()
    source = TiltHydrometerSourceSpec().create(
        "tilt_ble",
        client,
        config={
            "transport": "ble",
            "tilt_color": "Blue",
            "parameter_prefix": "tilt.ble",
            "update_interval_s": 0.01,
            "ble_stale_after_s": 0.0,
        },
    )

    state = {"count": 0}

    def fake_fetch_ble_selected():
        state["count"] += 1
        if state["count"] == 1:
            return {"Color": "Blue", "SG": 1042, "Temp": 67, "RSSI": -66}
        return None

    source._fetch_ble_selected = fake_fetch_ble_selected  # type: ignore[method-assign]

    loop_state = {"loops": 0}

    def fake_should_stop() -> bool:
        loop_state["loops"] += 1
        return loop_state["loops"] > 1

    source.should_stop = fake_should_stop  # type: ignore[assignment]
    source.sleep = lambda _s: False  # type: ignore[assignment]
    source.run()

    assert any(name == "tilt.ble.connected" and value is True for name, value in client.calls)
    assert any(name == "tilt.ble.gravity" and abs(float(value) - 1.042) < 1e-9 for name, value in client.calls if value is not None)

    client.calls.clear()
    loop_state["loops"] = 0
    source.run()
    assert any(name == "tilt.ble.connected" and value is False for name, value in client.calls)
    assert any(name == "tilt.ble.last_error" and "not seen over BLE" in str(value) for name, value in client.calls)


def test_tilt_hydrometer_ui_module_scan_metadata() -> None:
    from Services.parameterDB.sourceDefs.tilt_hydrometer.ui import get_ui_spec

    ui = get_ui_spec(mode="edit")
    module = dict(ui.get("module") or {})
    menu = dict(module.get("menu") or {})
    run = dict(menu.get("run") or {})
    action = dict(menu.get("action") or {})

    assert module.get("id") == "tiltDiscovery"
    assert run.get("mode") == "auto"
    assert run.get("poll_interval_s") == 3.0
    assert run.get("cancel_inflight_on_cleanup") is True
    assert menu.get("preserve_results") is True
    assert action.get("action") == "scan_tilts"
    assert isinstance(menu.get("fields"), list)


def test_tilt_hydrometer_run_ui_action_scans_bridge_and_ble(monkeypatch) -> None:
    from Services.parameterDB.sourceDefs.tilt_hydrometer import ui as tilt_ui

    monkeypatch.setattr(
        tilt_ui,
        "_scan_bridge_tilts",
        lambda payload, record: (
            [
                {
                    "source": "bridge",
                    "tilt_color": "Red",
                    "transport": "bridge",
                    "ble_device_address": "",
                    "bridge_url": "http://tiltbridge.local/json",
                    "selectable": True,
                }
            ],
            "",
        ),
    )
    monkeypatch.setattr(
        tilt_ui,
        "_scan_ble_tilts",
        lambda payload: (
            [
                {
                    "source": "ble",
                    "tilt_color": "Blue",
                    "transport": "ble",
                    "ble_device_address": "AA:BB:CC:DD:EE:FF",
                    "bridge_url": "",
                    "selectable": True,
                }
            ],
            "",
        ),
    )

    result = tilt_ui.run_ui_action("scan_tilts", payload={})

    assert result["ok"] is True
    assert result["action"] == "scan_tilts"
    assert len(result["candidates"]) == 2
    assert {item["source"] for item in result["candidates"]} == {"bridge", "ble"}


def test_tilt_hydrometer_run_ui_action_falls_back_to_manual_colors(monkeypatch) -> None:
    from Services.parameterDB.sourceDefs.tilt_hydrometer import ui as tilt_ui

    monkeypatch.setattr(tilt_ui, "_scan_bridge_tilts", lambda payload, record: ([], "timed out"))
    monkeypatch.setattr(tilt_ui, "_scan_ble_tilts", lambda payload: ([], ""))

    result = tilt_ui.run_ui_action("scan_tilts", payload={})

    assert result["ok"] is True
    assert result["action"] == "scan_tilts"
    assert result["candidates"] == []
    assert any("bridge: timed out" in warning for warning in result["warnings"])


def test_tilt_bridge_scan_rejects_unsupported_url_schemes(monkeypatch) -> None:
    from Services.parameterDB.sourceDefs.tilt_hydrometer import ui as tilt_ui

    calls = {"count": 0}

    def fake_urlopen(*_args, **_kwargs):
        calls["count"] += 1
        raise AssertionError("urlopen should not be reached for invalid schemes")

    monkeypatch.setattr(tilt_ui, "urlopen", fake_urlopen)

    candidates, error = tilt_ui._scan_bridge_tilts({"bridge_url": "file:///tmp/tilt.json"}, None)

    assert candidates == []
    assert calls["count"] == 0
    assert "http" in error.lower()


def test_tilt_bridge_scan_defaults_to_documented_timeout(monkeypatch) -> None:
    from Services.parameterDB.sourceDefs.tilt_hydrometer import ui as tilt_ui

    observed: dict[str, float] = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"tilts": []}'

    def fake_urlopen(req, timeout):
        observed["url"] = req.full_url
        observed["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(tilt_ui, "urlopen", fake_urlopen)

    candidates, error = tilt_ui._scan_bridge_tilts({}, None)

    assert candidates == []
    assert error == ""
    assert observed["url"] == "http://tiltbridge.local/json"
    assert observed["timeout"] == 3.0


def test_tilt_ble_decode_accepts_standard_ibeacon_payload_length() -> None:
    from Services.parameterDB.sourceDefs.tilt_hydrometer.service import (
        TiltHydrometerSource,
    )

    uuid_bytes = bytes.fromhex("a495bb20c5b14b44b5121370f02d74de")
    major_temp_f = (68).to_bytes(2, byteorder="big", signed=False)
    minor_sg = (1048).to_bytes(2, byteorder="big", signed=False)
    tx_power = bytes([0xC5])
    payload = bytes([0x02, 0x15]) + uuid_bytes + major_temp_f + minor_sg + tx_power

    decoded = TiltHydrometerSource._decode_tilt_from_manufacturer_data({0x004C: payload}, "a495bb20c5b14b44b5121370f02d74de")
    assert decoded is not None
    assert float(decoded["Temp"]) == 68.0
    assert float(decoded["SG"]) == 1048.0


def test_tilt_hydrometer_normalizes_tilt_pro_ranges() -> None:
    from Services.parameterDB.sourceDefs.tilt_hydrometer.service import (
        TiltHydrometerSource,
    )

    # Tilt Pro style encoding represented as integer fields.
    item = {"Temp": 543, "SG": 10722}
    assert TiltHydrometerSource._normalize_temp_f(item) == 54.3
    assert TiltHydrometerSource._normalize_gravity(item) == 1.0722


def test_tilt_invalid_color_reports_clear_error() -> None:
    from Services.parameterDB.sourceDefs.tilt_hydrometer.service import (
        TiltHydrometerSourceSpec,
    )

    class FakeClient:
        def create_parameter(self, *_args, **_kwargs):
            return None

        def set_value(self, _name: str, _value):
            return None

    source = TiltHydrometerSourceSpec().create(
        "tilt_bad",
        FakeClient(),
        config={"tilt_color": "Teal"},
    )

    with pytest.raises(ValueError, match="Unsupported Tilt color"):
        source._selected_color()


def test_tilt_ble_missing_packet_within_stale_window_keeps_connected_true() -> None:
    from Services.parameterDB.sourceDefs.tilt_hydrometer.service import (
        TiltHydrometerSourceSpec,
    )

    class FakeClient:
        def __init__(self):
            self.calls: list[tuple[str, object]] = []

        def create_parameter(self, *_args, **_kwargs):
            return None

        def set_value(self, name: str, value):
            self.calls.append((name, value))

    client = FakeClient()
    source = TiltHydrometerSourceSpec().create(
        "tilt_ble",
        client,
        config={
            "transport": "ble",
            "tilt_color": "Green",
            "parameter_prefix": "tilt",
            "ble_stale_after_s": 60.0,
            "update_interval_s": 0.01,
        },
    )

    state = {"count": 0}

    def fake_fetch_ble_selected():
        state["count"] += 1
        if state["count"] == 1:
            return {"Color": "Green", "SG": 1042, "Temp": 67, "RSSI": -66}
        return None

    source._fetch_ble_selected = fake_fetch_ble_selected  # type: ignore[method-assign]

    loop_state = {"loops": 0}

    def fake_should_stop() -> bool:
        loop_state["loops"] += 1
        return loop_state["loops"] > 1

    source.should_stop = fake_should_stop  # type: ignore[assignment]
    source.sleep = lambda _s: False  # type: ignore[assignment]

    source.run()
    client.calls.clear()
    loop_state["loops"] = 0
    source.run()

    assert any(name == "tilt.connected" and value is True for name, value in client.calls)
    assert not any(name == "tilt.last_error" and "not seen over BLE" in str(value) for name, value in client.calls)


def test_tilt_battery_weeks_persists_last_known_value_when_missing() -> None:
    from Services.parameterDB.sourceDefs.tilt_hydrometer.service import (
        TiltHydrometerSourceSpec,
    )

    class FakeClient:
        def __init__(self):
            self.calls: list[tuple[str, object]] = []

        def create_parameter(self, *_args, **_kwargs):
            return None

        def set_value(self, name: str, value):
            self.calls.append((name, value))

    client = FakeClient()
    source = TiltHydrometerSourceSpec().create("tilt", client, config={"parameter_prefix": "tilt"})
    source._publish_selected({"Color": "Green", "SG": 1048, "Temp": 68, "WeeksOnBattery": 12, "RSSI": -60})
    source._publish_selected({"Color": "Green", "SG": 1047, "Temp": 67, "RSSI": -61})

    battery_values = [value for name, value in client.calls if name == "tilt.battery_weeks"]
    assert battery_values[-2:] == [12.0, 12.0]


# ---------------------------------------------------------------------------
# PAPAGO Meteo ETH
# ---------------------------------------------------------------------------

def test_papago_meteo_register_decode() -> None:
    import struct
    from Services.parameterDB.sourceDefs.papago_meteo.service import (
        _u16,
        _i16,
        _float32,
        _decode_ntp_time,
        _decode_quantity,
        QuantitySpec,
    )

    regs = [0] * 20
    regs[0] = 0xABCD
    assert _u16(regs, 0) == 0xABCD

    regs[1] = 0x8000
    assert _i16(regs, 1) == -32768
    regs[2] = 0x7FFF
    assert _i16(regs, 2) == 32767

    # IEEE 754 float: 1.5 = 0x3FC00000 → hi=0x3FC0, lo=0x0000
    regs[5] = 0x3FC0
    regs[6] = 0x0000
    assert abs(_float32(regs, 5) - 1.5) < 1e-6

    # NTP timestamp: 0 → empty string
    assert _decode_ntp_time([0] * 20, 0) == ""

    # NTP: seconds since 1900-01-01 for 2000-01-01T00:00:00Z = 3155673600
    ntp_val = 3155673600
    regs[10] = (ntp_val >> 16) & 0xFFFF
    regs[11] = ntp_val & 0xFFFF
    ts = _decode_ntp_time(regs, 10)
    assert ts.startswith("2000-01-01")
    assert ts.endswith("Z")

    # _decode_quantity: status=0 (ok), int_x10=150 → value=15.0
    spec = QuantitySpec(
        key="test",
        status_register=0,
        int_x10_register=1,
        float_register=None,
        unit_register=None,
        default_unit="C",
        label="Test",
    )
    regs[0] = 0   # status ok
    regs[1] = 150
    result = _decode_quantity(regs, spec)
    assert result["value"] == 15.0
    assert result["quality"] == "ok"
    assert result["unit"] == "C"

    # status=2 (overflow) → value is None
    regs[0] = 2
    result = _decode_quantity(regs, spec)
    assert result["value"] is None
    assert result["quality"] == "overflow"


def test_papago_meteo_source_ensure_parameters_creates_expected_params() -> None:
    from Services.parameterDB.sourceDefs.papago_meteo.service import PapagoMeteoSource

    created: list[str] = []

    class FakeClient:
        def create_parameter(self, name: str, *_args, **_kwargs):
            created.append(name)
        def update_config(self, *_a, **_kw): pass
        def update_metadata(self, *_a, **_kw): pass
        def set_value(self, *_a, **_kw): pass

    source = PapagoMeteoSource(
        "meteo",
        FakeClient(),
        config={"host": "127.0.0.1", "parameter_prefix": "wx"},
    )
    source.ensure_parameters()

    # default-enabled quantities: sensor_a_value_1/2/3, wind_direction_deg, wind_speed_m_s
    assert "wx.sensor_a.value_1" in created
    assert "wx.sensor_a.value_2" in created
    assert "wx.sensor_a.value_3" in created
    assert "wx.wind.direction_deg" in created
    assert "wx.wind.speed_m_s" in created
    # quality params alongside each measurement
    assert "wx.sensor_a.value_1.quality" in created
    # status params
    assert "wx.connected" in created
    assert "wx.last_error" in created
    assert "wx.last_sync" in created
    assert "wx.device_time" in created
    # sensor_b disabled by default — not created
    assert "wx.sensor_b.value_1" not in created


def test_papago_meteo_source_publish_snapshot_writes_values() -> None:
    from Services.parameterDB.sourceDefs.papago_meteo.service import PapagoMeteoSource

    written: dict[str, object] = {}

    class FakeClient:
        def create_parameter(self, *_a, **_kw): pass
        def update_config(self, *_a, **_kw): pass
        def update_metadata(self, *_a, **_kw): pass
        def set_value(self, name: str, value): written[name] = value

    source = PapagoMeteoSource(
        "meteo",
        FakeClient(),
        config={"host": "127.0.0.1", "parameter_prefix": "wx"},
    )

    snapshot = {
        "device_time": "2026-01-01T00:00:00Z",
        "sensor_a_status": "measuring",
        "sensor_a_type": "temperature_ds",
        "sensor_b_status": "not_used",
        "sensor_b_type": "none",
        "wind_sensor_status": "measuring",
        "quantities": {
            "sensor_a_value_1": {"value": 21.3, "quality": "ok", "unit": "C", "unit_code": 0, "label": "Sensor A Value 1"},
            "sensor_a_value_2": {"value": None, "quality": "invalid", "unit": "native", "unit_code": 0, "label": "Sensor A Value 2"},
            "sensor_a_value_3": {"value": 55.0, "quality": "ok", "unit": "native", "unit_code": 0, "label": "Sensor A Value 3"},
            "sensor_b_value_1": {"value": 1.0, "quality": "ok", "unit": "native", "unit_code": 0, "label": "Sensor B Value 1"},
            "sensor_b_value_2": {"value": 2.0, "quality": "ok", "unit": "native", "unit_code": 0, "label": "Sensor B Value 2"},
            "sensor_b_value_3": {"value": 3.0, "quality": "ok", "unit": "native", "unit_code": 0, "label": "Sensor B Value 3"},
            "wind_direction_deg": {"value": 270.0, "quality": "ok", "unit": "deg", "unit_code": 0, "label": "Wind Direction"},
            "wind_speed_m_s": {"value": 5.1, "quality": "ok", "unit": "m/s", "unit_code": 0, "label": "Wind Speed"},
        },
    }

    source._publish_snapshot(snapshot)

    assert written["wx.sensor_a.value_1"] == 21.3
    assert written["wx.sensor_a.value_1.quality"] == "ok"
    assert written["wx.sensor_a.value_2"] is None
    assert written["wx.wind.direction_deg"] == 270.0
    assert written["wx.wind.speed_m_s"] == 5.1
    assert written["wx.device_time"] == "2026-01-01T00:00:00Z"
    assert written["wx.sensor_a_status"] == "measuring"
    assert written["wx.wind_sensor_status"] == "measuring"
    assert written["wx.connected"] is True
    assert written["wx.last_error"] == ""
    # sensor_b disabled — should not be published
    assert "wx.sensor_b.value_1" not in written


def test_papago_meteo_ui_module_spec_structure() -> None:
    from Services.parameterDB.sourceDefs.papago_meteo.ui import get_ui_spec

    ui = get_ui_spec()
    module = dict(ui.get("module") or {})
    menu = dict(module.get("menu") or {})
    run = dict(menu.get("run") or {})
    action = dict(menu.get("action") or {})

    assert ui["source_type"] == "papago_meteo"
    assert module.get("replace_form") is True
    assert menu.get("fields") == []
    assert run.get("mode") == "auto"
    assert run.get("cancel_inflight_on_cleanup") is True
    assert action.get("action") == "scan_papago_meteo"

    # create/edit sections present
    create_sections = [s["title"] for s in ui["create"]["sections"]]
    assert "Identity" in create_sections
    assert "Connection" in create_sections
    assert "Publishing" in create_sections

    edit_sections = [s["title"] for s in ui["edit"]["sections"]]
    assert "Status Parameters" in edit_sections


def test_papago_meteo_run_ui_action_returns_reachable_only(monkeypatch) -> None:
    from Services.parameterDB.sourceDefs.papago_meteo import ui as papago_ui

    monkeypatch.setattr(papago_ui, "_candidate_hosts", lambda *_a, **_kw: ["192.168.1.10", "192.168.1.20"])
    monkeypatch.setattr(papago_ui, "_candidate_ports", lambda *_a, **_kw: [502])
    monkeypatch.setattr(papago_ui, "_candidate_unit_ids", lambda *_a, **_kw: [1])
    monkeypatch.setattr(
        papago_ui,
        "_discover_open_targets",
        lambda hosts, ports, timeout: [(host, port) for host in hosts for port in ports],
    )

    def _fake_probe(host: str, port: int, unit_id: int, timeout: float):
        if host == "192.168.1.10":
            return {
                "host": host, "port": port, "unit_id": unit_id,
                "reachable": True, "error": "",
                "sensor_a_status": "measuring", "sensor_a_type": "temperature_ds",
                "sensor_b_status": "not_used", "sensor_b_type": "none",
                "wind_sensor_status": "measuring",
                "quantities": [{"quantity": "wind_speed_m_s", "value": 3.2, "quality": "ok", "unit": "m/s", "label": "Wind Speed"}],
            }
        return {"host": host, "port": port, "unit_id": unit_id, "reachable": False, "error": "timeout", "quantities": []}

    monkeypatch.setattr(papago_ui, "_probe_host_port", _fake_probe)

    result = papago_ui.run_ui_action("scan", payload={})

    assert result["ok"] is True
    assert result["action"] == "scan_papago_meteo"
    assert result["scanned"] == 2
    assert result["open_targets"] == 2
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["host"] == "192.168.1.10"
    assert result["candidates"][0]["reachable"] is True


def test_papago_meteo_run_ui_action_rejects_unknown_action() -> None:
    from Services.parameterDB.sourceDefs.papago_meteo.ui import run_ui_action

    with pytest.raises(ValueError, match="Unsupported papago_meteo UI action"):
        run_ui_action("unknown_action", payload={})


def test_papago_meteo_get_ui_spec_control_mode_returns_empty_controls() -> None:
    from Services.parameterDB.sourceDefs.papago_meteo.ui import get_ui_spec

    spec = get_ui_spec(mode="control")
    assert spec["source_type"] == "papago_meteo"
    assert spec["controls"] == []
