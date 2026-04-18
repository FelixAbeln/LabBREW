from __future__ import annotations

from typing import Any

from .transports import discover_transport_candidates


def _nodes(config: dict, key: str) -> list[int]:
    raw = config.get(key) or []
    nodes: list[int] = []
    if isinstance(raw, list):
        for value in raw:
            try:
                node_id = int(value)
            except Exception:
                continue
            if node_id >= 0:
                nodes.append(node_id)
    return sorted(set(nodes))


def _get_control_spec(record: dict | None = None) -> dict:
    record = dict(record or {})
    config = dict(record.get("config") or {})
    source_name = str(record.get("name") or "").strip() or "brewcan"
    prefix = str(config.get("parameter_prefix") or source_name).strip() or source_name

    nodes = _nodes(config, "agitator_nodes")
    density_nodes = _nodes(config, "density_nodes")
    pressure_nodes = _nodes(config, "pressure_nodes")

    controls = (
        [
            {
                "id": f"agitator_pwm_{node_id}",
                "label": f"Agitator PWM Node {node_id}",
                "target": f"{prefix}.agitator.{node_id}.set_pwm",
                "widget": "number",
                "unit": "%",
                "write": {"kind": "number", "min": 0.0, "max": 100.0, "step": 1.0},
                "role": "command",
                "node_id": node_id,
            }
            for node_id in nodes
        ]
        + [
            {
                "id": f"density_calibrate_{node_id}",
                "label": f"Calibrate Density Node {node_id}",
                "target": f"{prefix}.density.{node_id}.calibrate",
                "value_target": f"{prefix}.density.{node_id}.calibrate_sg",
                "widget": "number_button",
                "unit": "SG",
                "write": {"kind": "pulse", "value": True},
                "value_write": {"kind": "number", "min": 0.900, "max": 1.200, "step": 0.001},
                "role": "command",
                "node_id": node_id,
            }
            for node_id in density_nodes
        ]
        + [
            {
                "id": f"pressure_calibrate_{node_id}",
                "label": f"Zero Pressure Sensor (Node {node_id})",
                "target": f"{prefix}.pressure.{node_id}.calibrate",
                "widget": "button",
                "write": {"kind": "pulse", "value": True},
                "role": "command",
                "node_id": node_id,
                "hint": "Ensure sensor is at atmospheric pressure before zeroing.",
            }
            for node_id in pressure_nodes
        ]
    )

    card_sections: list[dict[str, Any]] = []
    seen_node_ids: list[int] = []
    for node_id in nodes + density_nodes + pressure_nodes:
        if node_id not in seen_node_ids:
            seen_node_ids.append(node_id)
    for node_id in seen_node_ids:
        items: list[dict[str, Any]] = []
        if node_id in nodes:
            items.append(
                {
                    "kind": "control",
                    "control_id": f"agitator_pwm_{node_id}",
                    "action_label": "Apply PWM",
                }
            )
        if node_id in density_nodes:
            items.append(
                {
                    "kind": "control",
                    "control_id": f"density_calibrate_{node_id}",
                    "action_label": "Calibrate",
                }
            )
        if node_id in pressure_nodes:
            items.append(
                {
                    "kind": "control",
                    "control_id": f"pressure_calibrate_{node_id}",
                    "action_label": "Zero Sensor",
                }
            )
        if items:
            card_sections.append(
                {
                    "id": f"node-{node_id}",
                    "title": f"Node {node_id}",
                    "items": items,
                }
            )

    return {
        "spec_version": 1,
        "source_type": "brewtools",
        "display_name": "Brewtools CAN",
        "description": (
            "Writable agitator PWM controls, density calibration triggers, "
            "and pressure sensor zeroing controls."
        ),
        "app": {
            "kind": "sections",
            "version": 1,
            "sections": card_sections,
        },
        "controls": controls,
        "discovery": {
            "fallback_roles": ["command"],
            "metadata_filters": {"node_type": "agitator"},
            "hint": (
                "If no node lists are configured, controls can still be "
                "discovered from live datasource metadata."
            ),
        },
    }


def _section_app_from_fields(sections: list[dict[str, Any]]) -> dict[str, Any]:
    app_sections: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        fields = [
            {"kind": "field", "field": dict(field)}
            for field in section.get("fields", [])
            if isinstance(field, dict)
        ]
        app_sections.append(
            {
                "id": section.get("id") or f"section-{index + 1}",
                "title": section.get("title"),
                "items": fields,
            }
        )
    return {"kind": "sections", "version": 1, "sections": app_sections}


def _get_graph_spec(record: dict | None = None) -> dict:
    record = dict(record or {})
    config = dict(record.get("config") or {})
    source_name = str(record.get("name") or "").strip() or "brewcan"
    prefix = str(config.get("parameter_prefix") or source_name).strip() or source_name

    agitator_nodes = _nodes(config, "agitator_nodes")
    density_nodes = _nodes(config, "density_nodes")
    pressure_nodes = _nodes(config, "pressure_nodes")

    # If nodes are not configured yet, expose node 0 command parameters so
    # operator graph/order remains meaningful once runtime discovery starts.
    if not agitator_nodes:
        agitator_nodes = [0]
    if not density_nodes:
        density_nodes = [0]
    if not pressure_nodes:
        pressure_nodes = [0]

    depends_on: list[str] = []
    seen: set[str] = set()

    def add(target: str) -> None:
        target = str(target or "").strip()
        if target and target not in seen:
            seen.add(target)
            depends_on.append(target)

    for node_id in agitator_nodes:
        add(f"{prefix}.agitator.{node_id}.set_pwm")
    for node_id in density_nodes:
        add(f"{prefix}.density.{node_id}.calibrate")
        add(f"{prefix}.density.{node_id}.calibrate_sg")
    for node_id in pressure_nodes:
        add(f"{prefix}.pressure.{node_id}.calibrate")

    return {"depends_on": depends_on}


def _identity_section() -> dict:
    return {
        "title": "Identity",
        "fields": [
            {"key": "name", "label": "Source Name", "type": "string", "required": True},
            {"key": "config.parameter_prefix", "label": "Parameter Prefix", "type": "string", "required": True},
        ],
    }


def _transport_section() -> dict:
    return {
        "title": "Transport",
        "fields": [
            {"key": "config.transport", "label": "Transport", "type": "enum", "required": True, "choices": ["kvaser", "pcan_gateway_udp"]},
            {"key": "config.interface", "label": "Interface", "type": "enum", "required": False, "choices": ["kvaser"], "hint": "Used when transport = kvaser.", "visible_when": {"config.transport": "kvaser"}},
            {"key": "config.channel", "label": "Channel", "type": "int", "required": False, "hint": "Used when transport = kvaser.", "visible_when": {"config.transport": "kvaser"}},
            {"key": "config.bitrate", "label": "Bitrate", "type": "int", "required": False, "hint": "Used when transport = kvaser.", "visible_when": {"config.transport": "kvaser"}},
            {"key": "config.gateway_host", "label": "PCAN Gateway Host", "type": "string", "required": False, "hint": "IP address of PCAN gateway (used when transport = pcan_gateway_udp).", "visible_when": {"config.transport": "pcan_gateway_udp"}},
            {"key": "config.gateway_tx_port", "label": "PCAN Gateway TX Port", "type": "int", "required": True, "hint": "TX port for sending commands (typically 55002, check gateway config).", "visible_when": {"config.transport": "pcan_gateway_udp"}},
            {"key": "config.gateway_rx_port", "label": "PCAN Gateway RX Port", "type": "int", "required": True, "hint": "RX port for receiving data (typically 55001, check gateway config).", "visible_when": {"config.transport": "pcan_gateway_udp"}},
            {"key": "config.gateway_bind_host", "label": "PCAN Bind Host", "type": "string", "required": False, "hint": "Local bind address (0.0.0.0 for all interfaces)", "visible_when": {"config.transport": "pcan_gateway_udp"}},
            {"key": "config.recv_timeout_s", "label": "Receive Timeout (s)", "type": "float", "required": True},
            {"key": "config.reconnect_delay_s", "label": "Reconnect Delay (s)", "type": "float", "required": True},
        ],
    }


def _optional_outputs_section() -> dict:
    return {
        "title": "Optional Outputs",
        "fields": [
            {"key": "config.initial_pwm", "label": "Initial PWM", "type": "float", "required": False},
            {"key": "config.density_request_interval_s", "label": "Density Request Interval (s)", "type": "float", "required": True},
        ],
    }


def _nodes_section() -> dict:
    return {
        "title": "Device Nodes",
        "fields": [
            {"key": "config.agitator_nodes", "label": "Agitator Node IDs (optional allowlist)", "type": "json", "required": False, "hint": "Use [0, 1] to limit nodes, or [] to allow/discover all."},
            {"key": "config.density_nodes", "label": "Density Sensor Node IDs (optional allowlist)", "type": "json", "required": False, "hint": "Use [0] to limit nodes, or [] to allow/discover all."},
            {"key": "config.pressure_nodes", "label": "Pressure Sensor Node IDs (optional allowlist)", "type": "json", "required": False, "hint": "Use [0] to limit nodes, or [] to allow/discover all."},
        ],
    }


def _overrides_section() -> dict:
    return {
        "title": "Overrides",
        "fields": [
            {"key": "config.measurement_params", "label": "Measurement Param Overrides", "type": "json", "required": False},
            {"key": "config.connected_param", "label": "Connected Param", "type": "string", "required": False},
            {"key": "config.last_error_param", "label": "Last Error Param", "type": "string", "required": False},
            {"key": "config.last_frame_utc_param", "label": "Last Frame UTC Param", "type": "string", "required": False},
            {"key": "config.last_can_id_param", "label": "Last CAN ID Param", "type": "string", "required": False},
            {"key": "config.last_msg_type_param", "label": "Last Msg Type Param", "type": "string", "required": False},
            {"key": "config.last_node_id_param", "label": "Last Node ID Param", "type": "string", "required": False},
        ],
    }


def get_ui_spec(record: dict | None = None, mode: str | None = None) -> dict:
    if mode == "control":
        return _get_control_spec(record)

    sections = [_identity_section(), _transport_section(), _optional_outputs_section(), _nodes_section()]
    edit_sections = sections + [_overrides_section()]

    return {
        "source_type": "brewtools",
        "display_name": "Brewtools CAN",
        "description": (
            "Receives Brewtools CAN measurements over Kvaser or a PCAN UDP gateway "
            "and mirrors them into parameters, with optional agitator PWM commands and density polling."
        ),
        "module": {
            "id": "brewtoolsCanDiscovery",
            "display_name": "CAN Bus Discovery",
            "description": "Scan discovered CAN channels/devices (Kvaser and PCAN UDP gateways), then select one.",
            "replace_form": True,
            "menu": {
                "fields": [],
                "run": {
                    "mode": "auto",
                    "cancel_inflight_on_cleanup": True,
                },
                "action": {
                    "id": "scan",
                    "action": "scan_channels",
                    "label": "Scan CAN Channels",
                },
                "result": {
                    "list_key": "channels",
                    "title_key": "title",
                    "subtitle_keys": ["subtitle"],
                    "status_key": "selectable",
                    "error_key": "error",
                    "apply_label": "Use This Channel",
                    "empty_message": "No CAN channels/devices discovered.",
                    "apply_map": {
                        "transport": "transport",
                        "interface": "interface",
                        "channel": "channel",
                        "bitrate": "bitrate",
                        "gateway_host": "gateway_host",
                        "gateway_tx_port": "gateway_tx_port",
                        "gateway_rx_port": "gateway_rx_port",
                        "gateway_bind_host": "gateway_bind_host",
                    },
                },
            },
        },
        "graph": _get_graph_spec(record),
        "create": {
            "required": ["name", "config.transport", "config.parameter_prefix"],
            "defaults": {
                "config": {
                    "transport": "kvaser",
                    "interface": "kvaser",
                    "channel": 0,
                    "bitrate": 500000,
                    "recv_timeout_s": 0.1,
                    "reconnect_delay_s": 2.0,
                    "density_request_interval_s": 2.0,
                    "parameter_prefix": "brewcan",
                    "density_nodes": [],
                    "pressure_nodes": [],
                    "agitator_nodes": [],
                    "initial_pwm": 0.0,
                    "gateway_host": "192.168.0.30",
                    "gateway_tx_port": 55002,
                    "gateway_rx_port": 55001,
                    "gateway_bind_host": "0.0.0.0",
                }
            },
            "app": _section_app_from_fields(sections),
            "sections": sections,
        },
        "edit": {
            "app": _section_app_from_fields(edit_sections),
            "sections": edit_sections,
        },
    }


def run_ui_action(
    action: str,
    payload: dict[str, Any] | None = None,
    record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action_name = str(action or "").strip().lower()
    request = dict(payload or {})
    if action_name not in {"scan_channels", "scan"}:
        raise ValueError(f"Unsupported brewtools UI action: {action}")

    candidates, warnings = discover_transport_candidates(request, record)

    return {
        "ok": True,
        "action": "scan_channels",
        "channels": candidates,
        "scanned": len(candidates),
        "warnings": warnings,
    }
