from __future__ import annotations

import struct

import pytest

from Services.parameterDB.sourceDefs.brewtools.ui import get_ui_spec as get_brewtools_ui_spec
from Services.parameterDB.sourceDefs.brewtools.service import BrewtoolsSourceSpec
from Services.parameterDB.sourceDefs.brewtools.transports.base import TransportDiscoveryCandidate
from Services.parameterDB.sourceDefs.brewtools.transports.pcan_gateway import (
    TYPE_CLASSIC_CRC,
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
    assert channel.get("visible_when") == {"config.transport": "kvaser"}
    assert bitrate.get("visible_when") == {"config.transport": "kvaser"}
    assert gateway_host.get("visible_when") == {"config.transport": "pcan_gateway_udp"}
    assert gateway_tx.get("visible_when") == {"config.transport": "pcan_gateway_udp"}
    assert gateway_rx.get("visible_when") == {"config.transport": "pcan_gateway_udp"}
    assert gateway_bind.get("visible_when") == {"config.transport": "pcan_gateway_udp"}


def test_brewtools_default_config_exposes_both_transport_families() -> None:
    config = BrewtoolsSourceSpec().default_config()
    assert config["transport"] == "kvaser"
    assert config["interface"] == "kvaser"
    assert config["gateway_host"] == "192.168.0.30"
    assert config["gateway_tx_port"] == 55002
    assert config["gateway_rx_port"] == 55001


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
        subtitle="UDP 55002/55001 · PCAN-Ethernet Gateway DR (SN:26869)",
        source="pcan_gateway_udp",
        transport="pcan_gateway_udp",
        gateway_host="192.168.5.31",
        selectable=True,
        extra={"identity_serial_no": "26869"},
    )

    result = candidate.as_dict()

    assert result["title"] == "pcan:192.168.5.31"
    assert result["identity_serial_no"] == "26869"


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
