from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from ipaddress import ip_network
from typing import Any

from .transports import PeakGatewayUdpTransport, RawCanFrame


def _local_ipv4_addresses() -> list[str]:
    hosts: list[str] = []
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET)
    except Exception:
        infos = []
    for info in infos:
        addr = str(info[4][0] or "").strip()
        if not addr or addr.startswith("127."):
            continue
        if addr not in hosts:
            hosts.append(addr)
    return hosts


def _scan_kvaser_channels(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    _ = payload
    try:
        import can
    except ModuleNotFoundError:
        return [], "python-can is not installed"
    except Exception as exc:
        return [], str(exc)

    try:
        configs = can.detect_available_configs(interfaces=["kvaser"])
    except TypeError:
        try:
            configs = [
                cfg
                for cfg in (can.detect_available_configs() or [])
                if str((cfg or {}).get("interface", "")).strip().lower() == "kvaser"
            ]
        except Exception as exc:
            return [], str(exc)
    except Exception as exc:
        return [], str(exc)

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for cfg in configs or []:
        if not isinstance(cfg, dict):
            continue
        channel_value = cfg.get("channel", 0)
        channel_text = str(channel_value).strip() or "0"
        key = ("kvaser", channel_text)
        if key in seen:
            continue
        seen.add(key)
        try:
            channel = int(channel_value)
        except Exception:
            channel = 0
        bitrate = int(cfg.get("bitrate") or 500000)
        out.append(
            {
                "title": f"kvaser:{channel_text}",
                "subtitle": "Kvaser channel",
                "source": "kvaser",
                "transport": "kvaser",
                "interface": "kvaser",
                "channel": channel,
                "bitrate": bitrate,
                "gateway_host": "",
                "gateway_tx_port": 55002,
                "gateway_rx_port": 55001,
                "gateway_bind_host": "0.0.0.0",
                "selectable": True,
                "error": "",
            }
        )
    return out, ""


def _gateway_hosts(payload: dict[str, Any], record: dict[str, Any] | None) -> list[str]:
    out: list[str] = []

    def _add(host: Any) -> None:
        text = str(host or "").strip()
        if text and text not in out:
            out.append(text)

    raw_hosts = payload.get("gateway_hosts")
    if isinstance(raw_hosts, list):
        for host in raw_hosts:
            _add(host)

    _add(payload.get("gateway_host"))
    if isinstance(record, dict):
        cfg = record.get("config")
        if isinstance(cfg, dict):
            _add(cfg.get("gateway_host"))

    _add("192.168.0.30")
    max_hosts = max(1, min(256, int(payload.get("max_gateway_hosts") or 128)))
    for local in _local_ipv4_addresses():
        parts = local.split(".")
        if len(parts) == 4:
            _add(".".join(parts[:3] + ["30"]))
        try:
            subnet = ip_network(f"{local}/24", strict=False)
        except Exception:
            continue
        for host in subnet.hosts():
            text = str(host)
            if text == local:
                continue
            _add(text)
            if len(out) >= max_hosts:
                return out
    return out


def _scan_peak_gateways(
    payload: dict[str, Any],
    record: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str]:
    tx_port = int(payload.get("gateway_tx_port") or 55002)
    rx_port = int(payload.get("gateway_rx_port") or 55001)
    bind_host = str(payload.get("gateway_bind_host") or "0.0.0.0").strip() or "0.0.0.0"
    timeout_s = float(payload.get("probe_timeout_s") or 0.08)
    worker_count = max(1, min(64, int(payload.get("probe_workers") or 32)))

    hosts = _gateway_hosts(payload, record)
    out: list[dict[str, Any]] = []

    def _probe_host(host: str) -> dict[str, Any] | None:
        reachable = False
        transport = None
        try:
            transport = PeakGatewayUdpTransport(
                remote_host=host,
                remote_port=tx_port,
                local_host=bind_host,
                local_port=0,
                socket_timeout=timeout_s,
            )
            transport.send_frame(
                RawCanFrame(
                    arbitration_id=0x1FFFFFFF,
                    data=b"",
                    is_extended_id=True,
                    is_remote_frame=True,
                )
            )
            frames = transport.recv_frames(timeout=timeout_s)
            reachable = bool(frames)
        except Exception:
            reachable = False
        finally:
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass
        if not reachable:
            return None

        return {
            "title": f"pcan:{host}",
            "subtitle": f"UDP {tx_port}/{rx_port}",
            "source": "pcan_gateway_udp",
            "transport": "pcan_gateway_udp",
            "interface": "",
            "channel": 0,
            "bitrate": 500000,
            "gateway_host": host,
            "gateway_tx_port": tx_port,
            "gateway_rx_port": rx_port,
            "gateway_bind_host": bind_host,
            "selectable": True,
            "error": "",
        }

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(_probe_host, host) for host in hosts]
        for future in as_completed(futures):
            try:
                item = future.result()
            except Exception:
                item = None
            if item is not None:
                out.append(item)

    return out, ""


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

    return {
        "spec_version": 1,
        "source_type": "brewtools",
        "display_name": "Brewtools CAN",
        "description": (
            "Writable agitator PWM controls, density calibration triggers, "
            "and pressure sensor zeroing controls."
        ),
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
            {"key": "config.gateway_host", "label": "PCAN Gateway Host", "type": "string", "required": False, "hint": "Used when transport = pcan_gateway_udp.", "visible_when": {"config.transport": "pcan_gateway_udp"}},
            {"key": "config.gateway_tx_port", "label": "PCAN Gateway TX Port", "type": "int", "required": False, "visible_when": {"config.transport": "pcan_gateway_udp"}},
            {"key": "config.gateway_rx_port", "label": "PCAN Gateway RX Port", "type": "int", "required": False, "visible_when": {"config.transport": "pcan_gateway_udp"}},
            {"key": "config.gateway_bind_host", "label": "PCAN Bind Host", "type": "string", "required": False, "visible_when": {"config.transport": "pcan_gateway_udp"}},
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
                    "subtitle_keys": ["subtitle", "source"],
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
            "sections": sections,
        },
        "edit": {"sections": edit_sections},
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

    candidates: list[dict[str, Any]] = []
    warnings: list[str] = []

    kvaser_items, kvaser_error = _scan_kvaser_channels(request)
    if kvaser_error:
        warnings.append(f"kvaser: {kvaser_error}")
    candidates.extend(kvaser_items)

    pcan_items, pcan_error = _scan_peak_gateways(request, record)
    if pcan_error:
        warnings.append(f"pcan_gateway_udp: {pcan_error}")
    candidates.extend(pcan_items)

    return {
        "ok": True,
        "action": "scan_channels",
        "channels": candidates,
        "scanned": len(candidates),
        "warnings": warnings,
    }
