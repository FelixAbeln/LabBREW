from __future__ import annotations

import struct

import pytest

from Services.parameterDB.sourceDefs.brewtools.ui import get_ui_spec as get_brewtools_ui_spec
from Services.parameterDB.sourceDefs.brewtools.service import BrewtoolsSourceSpec
from Services.parameterDB.sourceDefs.brewtools.transports.base import TransportDiscoveryCandidate
from Services.parameterDB.sourceDefs.brewtools.transports.pcan_gateway import (
    TYPE_CLASSIC_CRC,
    discover_peak_gateways,
    parse_gateway_packet,
)


def test_brewtools_ui_transport_choices_and_graph_dependencies() -> None:
    ui = get_brewtools_ui_spec(
        record={
            "name": "brewcan",
            "config": {
                "parameter_prefix": "brewcan",
                "agitator_nodes": [7, 3, 7],
                "density_nodes": [2],
                "pressure_nodes": [1],
            },
        },
        mode="edit",
    )
    transport_field = next(
        field
        for section in ui["edit"]["sections"]
        for field in section.get("fields", [])
        if field.get("key") == "config.transport"
    )
    assert transport_field["type"] == "enum"
    assert transport_field["choices"] == ["kvaser", "pcan_gateway_udp"]
    assert ui["graph"]["depends_on"] == [
        "brewcan.agitator.3.set_pwm",
        "brewcan.agitator.7.set_pwm",
        "brewcan.density.2.calibrate",
        "brewcan.density.2.calibrate_sg",
        "brewcan.pressure.1.calibrate",
    ]


def test_brewtools_graph_uses_fallback_command_targets_when_nodes_unset() -> None:
    ui = get_brewtools_ui_spec(
        record={"name": "Brewtools_Kvaser_Sim", "config": {"parameter_prefix": "brewcan"}},
        mode="edit",
    )
    assert ui["graph"]["depends_on"] == [
        "brewcan.agitator.0.set_pwm",
        "brewcan.density.0.calibrate",
        "brewcan.density.0.calibrate_sg",
        "brewcan.pressure.0.calibrate",
    ]


def test_brewtools_ui_transport_fields_are_adaptive() -> None:
    ui = get_brewtools_ui_spec(record={"name": "brewcan", "config": {}}, mode="edit")
    fields = [
        field
        for section in ui["edit"]["sections"]
        for field in section.get("fields", [])
    ]

    interface = next(field for field in fields if field.get("key") == "config.interface")
    channel = next(field for field in fields if field.get("key") == "config.channel")
    bitrate = next(field for field in fields if field.get("key") == "config.bitrate")
    gateway_host = next(field for field in fields if field.get("key") == "config.gateway_host")
    gateway_tx = next(field for field in fields if field.get("key") == "config.gateway_tx_port")
    gateway_rx = next(field for field in fields if field.get("key") == "config.gateway_rx_port")
    gateway_bind = next(field for field in fields if field.get("key") == "config.gateway_bind_host")

    assert interface.get("visible_when") == {"config.transport": "kvaser"}
    assert channel.get("visible_when") == {"config.transport": ["kvaser", "pcan_gateway_udp"]}
    assert bitrate.get("visible_when") == {"config.transport": "kvaser"}
    assert gateway_host.get("visible_when") == {"config.transport": "pcan_gateway_udp"}
    assert gateway_tx.get("visible_when") == {"config.transport": "pcan_gateway_udp"}
    assert gateway_rx.get("visible_when") == {"config.transport": "pcan_gateway_udp"}
    assert gateway_bind.get("visible_when") == {"config.transport": "pcan_gateway_udp"}


def test_brewtools_default_config_exposes_both_transport_families() -> None:
    config = BrewtoolsSourceSpec().default_config()
    assert config["transport"] == "kvaser"
    assert config["interface"] == "kvaser"
    assert config["channel"] == 0
    assert config["gateway_host"] == "192.168.0.30"
    assert config["gateway_tx_port"] == 55002
    assert config["gateway_rx_port"] == 55001


def test_brewtools_ui_shows_channel_for_peak_and_kvaser() -> None:
    ui = get_brewtools_ui_spec(record={"name": "brewcan", "config": {}}, mode="edit")
    sections = list(ui.get("edit", {}).get("sections") or [])
    transport = next(section for section in sections if section.get("title") == "Transport")
    channel = next(field for field in transport.get("fields", []) if field.get("key") == "config.channel")

    assert channel.get("label") == "Bus / Channel"
    assert channel.get("visible_when") == {"config.transport": ["kvaser", "pcan_gateway_udp"]}


def test_brewtools_ui_module_scan_metadata() -> None:
    ui = get_brewtools_ui_spec(record={"name": "brewcan", "config": {}}, mode="edit")
    module = dict(ui.get("module") or {})
    menu = dict(module.get("menu") or {})
    run = dict(menu.get("run") or {})
    action = dict(menu.get("action") or {})

    assert module.get("id") == "brewtoolsCanDiscovery"
    assert module.get("replace_form") is True
    assert menu.get("fields") == []
    assert run.get("mode") == "auto"
    assert run.get("cancel_inflight_on_cleanup") is True
    assert action.get("action") == "scan_channels"


def test_brewtools_run_ui_action_scans_kvaser_and_peak(monkeypatch) -> None:
    from Services.parameterDB.sourceDefs.brewtools import ui as brewtools_ui

    monkeypatch.setattr(
        brewtools_ui,
        "discover_transport_candidates",
        lambda payload, record: (
            [
                TransportDiscoveryCandidate(
                    title="kvaser:0",
                    subtitle="Kvaser channel",
                    source="kvaser",
                    transport="kvaser",
                    interface="kvaser",
                    channel=0,
                    bitrate=500000,
                    selectable=True,
                ).as_dict(),
                TransportDiscoveryCandidate(
                    title="pcan:192.168.0.30",
                    subtitle="UDP 55002/55001",
                    source="pcan_gateway_udp",
                    transport="pcan_gateway_udp",
                    gateway_host="192.168.0.30",
                    selectable=True,
                ).as_dict(),
            ],
            [],
        ),
    )

    result = brewtools_ui.run_ui_action("scan_channels", payload={})

    assert result["ok"] is True
    assert result["action"] == "scan_channels"
    assert len(result["channels"]) == 2
    assert {item["source"] for item in result["channels"]} == {"kvaser", "pcan_gateway_udp"}


def test_brewtools_run_ui_action_filters_unreachable_peak_candidates(monkeypatch) -> None:
    from Services.parameterDB.sourceDefs.brewtools import ui as brewtools_ui

    monkeypatch.setattr(brewtools_ui, "discover_transport_candidates", lambda payload, record: ([], []))

    result = brewtools_ui.run_ui_action("scan_channels", payload={})

    assert result["ok"] is True
    assert result["channels"] == []


def test_transport_discovery_candidate_as_dict_preserves_extra_fields() -> None:
    candidate = TransportDiscoveryCandidate(
        title="pcan:192.168.5.31",
        subtitle="CAN 0 · PCAN-Ethernet Gateway DR · SN:26869 · UDP 55002/55001",
        source="pcan_gateway_udp",
        transport="pcan_gateway_udp",
        gateway_host="192.168.5.31",
        selectable=True,
        extra={"identity_serial_no": "26869"},
    )

    result = candidate.as_dict()

    assert result["title"] == "pcan:192.168.5.31"
    assert result["identity_serial_no"] == "26869"


def test_discover_peak_gateways_emits_one_candidate_per_can_bus(monkeypatch) -> None:
    monkeypatch.setattr(
        "Services.parameterDB.sourceDefs.brewtools.transports.pcan_gateway._gateway_hosts",
        lambda _payload, _record: ["192.168.5.36"],
    )
    monkeypatch.setattr(
        "Services.parameterDB.sourceDefs.brewtools.transports.pcan_gateway._arp_mac_table",
        lambda: {"192.168.5.36": "00-11-22-33-44-55"},
    )
    monkeypatch.setattr(
        "Services.parameterDB.sourceDefs.brewtools.transports.pcan_gateway._json_device_identity",
        lambda _host, timeout_s: (
            True,
            "PCAN-Ethernet Gateway DR",
            "SN:26869",
            {
                "identity_product_name": "PCAN-Ethernet Gateway DR",
                "identity_order_no": "IPEH-004010",
                "identity_serial_no": "26869",
                "identity_source": "json_device",
                "identity_can_count": 2,
            },
            "",
        ),
    )

    result, error = discover_peak_gateways({}, None)

    assert error == ""
    assert [item.title for item in result] == [
        "pcan:192.168.5.36:can0",
        "pcan:192.168.5.36:can1",
    ]
    assert [item.channel for item in result] == [0, 1]
    assert all(item.gateway_host == "192.168.5.36" for item in result)
    assert all(item.selectable is True for item in result)


def test_parse_gateway_packet_rejects_crc_frame_shorter_than_header_plus_crc() -> None:
    packet = bytearray(31)
    struct.pack_into(">H", packet, 0, 31)
    struct.pack_into(">H", packet, 2, TYPE_CLASSIC_CRC)

    with pytest.raises(ValueError, match="CRC gateway frame length"):
        parse_gateway_packet(bytes(packet))


def test_parse_gateway_packet_rejects_crc_frame_with_truncated_payload() -> None:
    # length=32 includes 28-byte header + 4-byte CRC, so no payload bytes remain.
    # With dlc=8 this must fail fast instead of slicing an empty/truncated payload.
    packet = bytearray(32)
    struct.pack_into(">H", packet, 0, 32)
    struct.pack_into(">H", packet, 2, TYPE_CLASSIC_CRC)
    packet[21] = 8

    with pytest.raises(ValueError, match="payload overruns"):
        parse_gateway_packet(bytes(packet))


def test_discover_kvaser_channels_subtitle_includes_device_name_and_serial(monkeypatch) -> None:
    """discover_kvaser_channels should build a subtitle from device_name, serial, and dongle_channel."""
    _ = monkeypatch
    import types

    fake_can = types.ModuleType("can")
    fake_can.detect_available_configs = lambda interfaces: [
        {
            "interface": "kvaser",
            "channel": 0,
            "device_name": "Kvaser Leaf Light v2",
            "serial": 12345,
            "dongle_channel": 1,
        },
        {
            "interface": "kvaser",
            "channel": 1,
            "device_name": "Kvaser Leaf Light v2",
            "serial": 12345,
            "dongle_channel": 2,
        },
    ]
    import sys
    old_can = sys.modules.get("can")
    sys.modules["can"] = fake_can
    try:
        from Services.parameterDB.sourceDefs.brewtools.transports.kvaser import discover_kvaser_channels
        result, _ = discover_kvaser_channels()
    finally:
        if old_can is None:
            del sys.modules["can"]
        else:
            sys.modules["can"] = old_can

    assert len(result) == 2
    assert result[0].title == "kvaser:0"
    assert result[0].subtitle.startswith("ch1 · ")
    assert "Kvaser Leaf Light v2" in result[0].subtitle
    assert "SN:12345" in result[0].subtitle
    assert result[1].title == "kvaser:1"
    assert result[1].subtitle.startswith("ch2 · ")


def test_discover_kvaser_channels_subtitle_serial_zero_shows_virtual(monkeypatch) -> None:
    """When serial is 0, the subtitle should say SN:virtual."""
    import sys
    import types

    fake_can = types.ModuleType("can")
    fake_can.detect_available_configs = lambda interfaces: [
        {
            "interface": "kvaser",
            "channel": 0,
            "device_name": "Kvaser Virtual CAN Driver",
            "serial": 0,
            "dongle_channel": 1,
        },
    ]
    missing = object()
    previous_can = sys.modules.get("can", missing)
    sys.modules["can"] = fake_can
    try:
        from Services.parameterDB.sourceDefs.brewtools.transports.kvaser import discover_kvaser_channels
        result, _ = discover_kvaser_channels()
    finally:
        if previous_can is missing:
            sys.modules.pop("can", None)
        else:
            sys.modules["can"] = previous_can

    assert len(result) == 1
    assert "SN:virtual" in result[0].subtitle
