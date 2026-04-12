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
