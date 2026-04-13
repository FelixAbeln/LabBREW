from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from ipaddress import ip_network
from typing import Any

from .service import RelayBoard, RelayError


def _int_value(payload: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(payload.get(key, default))
    except Exception:
        return int(default)


def _float_value(payload: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(payload.get(key, default))
    except Exception:
        return float(default)


def _local_ipv4_addresses() -> list[str]:
    found: list[str] = []

    def _add(ip: str) -> None:
        raw = str(ip or "").strip()
        if not raw:
            return
        if raw.startswith("127."):
            return
        if raw in found:
            return
        found.append(raw)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            _add(sock.getsockname()[0])
    except Exception:
        pass

    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        for info in infos:
            addr = info[4][0] if len(info) > 4 and info[4] else ""
            _add(addr)
    except Exception:
        pass

    return found


def _candidate_ports(payload: dict[str, Any], record: dict[str, Any] | None) -> list[int]:
    ports: list[int] = []

    def _add(value: Any) -> None:
        try:
            port = int(value)
        except Exception:
            return
        if port <= 0 or port > 65535:
            return
        if port not in ports:
            ports.append(port)

    raw_ports = payload.get("ports")
    if isinstance(raw_ports, list):
        for item in raw_ports:
            _add(item)

    if not ports:
        _add(payload.get("port"))

    if isinstance(record, dict):
        cfg = record.get("config")
        if isinstance(cfg, dict):
            _add(cfg.get("port"))

    for common in (4196, 502):
        _add(common)

    return ports or [502]


def _candidate_unit_ids(
    payload: dict[str, Any], record: dict[str, Any] | None
) -> list[int]:
    _ = (payload, record)
    # Waveshare Modbus POE ETH relay uses slave/unit id 1 by default.
    return [1]


def _tcp_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _discover_open_targets(
    hosts: list[str], ports: list[int], *, timeout: float
) -> list[tuple[str, int]]:
    targets = [(host, int(port)) for host in hosts for port in ports]
    if not targets:
        return []

    open_targets: list[tuple[str, int]] = []
    workers = max(8, min(128, len(targets)))
    check_timeout = max(0.03, min(0.08, timeout))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {
            pool.submit(_tcp_open, host, port, check_timeout): (host, port)
            for host, port in targets
        }
        for future in as_completed(future_map):
            host, port = future_map[future]
            try:
                if future.result():
                    open_targets.append((host, port))
            except Exception:
                pass
    return open_targets


def _candidate_hosts(payload: dict[str, Any], record: dict[str, Any] | None) -> list[str]:
    _ = record
    raw_hosts = payload.get("hosts")
    if isinstance(raw_hosts, list):
        hosts = [str(item).strip() for item in raw_hosts if str(item).strip()]
        if hosts:
            return hosts

    host = str(payload.get("host") or "").strip()
    if host:
        return [host]

    raw_cidr = str(payload.get("cidr") or "").strip()
    if raw_cidr:
        max_hosts = max(1, min(256, _int_value(payload, "max_hosts", 64)))
        try:
            network = ip_network(raw_cidr, strict=False)
            result = []
            for addr in network.hosts():
                result.append(str(addr))
                if len(result) >= max_hosts:
                    break
            if result:
                return result
        except Exception:
            pass

    auto_hosts: list[str] = ["127.0.0.1"]
    max_hosts = max(1, min(512, _int_value(payload, "max_hosts", 256)))
    for base_ip in _local_ipv4_addresses():
        try:
            network = ip_network(f"{base_ip}/24", strict=False)
        except Exception:
            continue
        for addr in network.hosts():
            host = str(addr)
            if host == base_ip:
                continue
            if host not in auto_hosts:
                auto_hosts.append(host)
            if len(auto_hosts) >= max_hosts:
                return auto_hosts
    return auto_hosts


def _probe_channel_count(
    host: str,
    port: int,
    unit_id: int,
    timeout: float,
) -> tuple[int | None, list[dict[str, Any]], str]:
    last_error = ""
    for count in (32, 16, 8, 4, 2, 1):
        board = RelayBoard(
            host=host,
            port=port,
            unit_id=unit_id,
            channel_count=count,
            timeout=timeout,
        )
        try:
            states = board.all_states()
            return (
                count,
                [
                    {"channel": channel, "state": bool(state)}
                    for channel, state in sorted(states.items())
                ],
                "",
            )
        except RelayError as exc:
            last_error = str(exc)
            lowered = last_error.lower()
            if "network error" in lowered or "connection closed" in lowered:
                break
        except Exception as exc:
            last_error = str(exc)
            break
        finally:
            board.close()
    return None, [], last_error or "No relay response"


def _probe_host_port(host: str, port: int, unit_id: int, timeout: float) -> dict[str, Any]:
    channel_count, states, error = _probe_channel_count(host, port, unit_id, timeout)
    return {
        "host": host,
        "port": port,
        "unit_id": unit_id,
        "channel_count": int(channel_count or 0),
        "reachable": bool(channel_count),
        "error": "" if channel_count else error,
        "states": states,
    }


def _get_control_spec(record: dict | None = None) -> dict:
    record = dict(record or {})
    config = dict(record.get("config") or {})
    source_name = str(record.get("name") or "").strip() or "modbus_relay"
    prefix = str(config.get("parameter_prefix") or source_name).strip() or source_name
    try:
        channel_count = max(1, int(config.get("channel_count", 8)))
    except Exception:
        channel_count = 8

    controls = [
        {
            "id": f"relay_ch{channel}",
            "label": f"Relay Channel {channel}",
            "target": f"{prefix}.ch{channel}",
            "widget": "toggle",
            "write": {"kind": "bool"},
            "role": "command",
        }
        for channel in range(1, channel_count + 1)
    ]

    return {
        "spec_version": 1,
        "source_type": "modbus_relay",
        "display_name": "Modbus Relay Board",
        "description": "Writable relay channel commands.",
        "controls": controls,
    }


def _get_graph_spec(record: dict | None = None) -> dict:
    controls = _get_control_spec(record).get("controls", [])
    depends_on = []
    seen = set()

    for control in controls:
        target = str(control.get("target") or "").strip()
        if target and target not in seen:
            depends_on.append(target)
            seen.add(target)

    return {"depends_on": depends_on}


def get_ui_spec(record: dict | None = None, mode: str | None = None) -> dict:
    if mode == "control":
        return _get_control_spec(record)
    return {
        "source_type": "modbus_relay",
        "display_name": "Modbus Relay Board",
        "description": (
            "Mirrors relay channel booleans to a Modbus-TCP relay board "
            "and republishes actual relay states."
        ),
        "module": {
            "id": "modbusRelayDiscovery",
            "display_name": "Relay Discovery",
            "description": "Auto-scan network relays, detect port/channels, then select.",
            "replace_form": True,
            "menu": {
                "fields": [],
                "run": {
                    "mode": "auto",
                    "cancel_inflight_on_cleanup": True,
                },
                "action": {
                    "id": "scan",
                    "action": "scan_relays",
                    "label": "Scan Network",
                },
                "result": {
                    "list_key": "candidates",
                    "title_key": "host",
                    "subtitle_keys": ["port", "unit_id", "channel_count"],
                    "status_key": "reachable",
                    "error_key": "error",
                    "apply_label": "Use This Board",
                    "apply_map": {
                        "host": "host",
                        "port": "port",
                        "unit_id": "unit_id",
                        "channel_count": "channel_count",
                    },
                },
            },
        },
        "graph": _get_graph_spec(record),
        "create": {
            "required": ["name", "config.host"],
            "defaults": {
                "config": {
                    "host": "127.0.0.1",
                    "port": 502,
                    "unit_id": 1,
                    "channel_count": 8,
                    "timeout": 1.5,
                    "update_interval_s": 0.25,
                    "reconnect_delay_s": 2.0,
                    "parameter_prefix": "relay",
                }
            },
            "sections": [
                {
                    "title": "Identity",
                    "fields": [
                        {
                            "key": "name",
                            "label": "Source Name",
                            "type": "string",
                            "required": True,
                        },
                        {
                            "key": "config.parameter_prefix",
                            "label": "Parameter Prefix",
                            "type": "string",
                            "required": True,
                            "help": (
                                "Creates relay state params like "
                                "relay.ch1, relay.ch2, ..."
                            ),
                        },
                    ],
                },
                {
                    "title": "Connection",
                    "fields": [
                        {
                            "key": "config.host",
                            "label": "Host",
                            "type": "string",
                            "required": True,
                        },
                        {
                            "key": "config.port",
                            "label": "TCP Port",
                            "type": "int",
                            "required": True,
                        },
                        {
                            "key": "config.unit_id",
                            "label": "Unit ID",
                            "type": "int",
                            "required": True,
                        },
                        {
                            "key": "config.timeout",
                            "label": "Timeout (s)",
                            "type": "float",
                            "required": True,
                        },
                    ],
                },
                {
                    "title": "Channels",
                    "fields": [
                        {
                            "key": "config.channel_count",
                            "label": "Channel Count",
                            "type": "int",
                            "required": True,
                        },
                        {
                            "key": "config.update_interval_s",
                            "label": "Poll Interval (s)",
                            "type": "float",
                            "required": True,
                        },
                        {
                            "key": "config.reconnect_delay_s",
                            "label": "Reconnect Delay (s)",
                            "type": "float",
                            "required": True,
                        },
                    ],
                },
            ],
        },
        "edit": {
            "sections": [
                {
                    "title": "Identity",
                    "fields": [
                        {
                            "key": "name",
                            "label": "Source Name",
                            "type": "string",
                            "required": True,
                        },
                        {
                            "key": "config.parameter_prefix",
                            "label": "Parameter Prefix",
                            "type": "string",
                            "required": True,
                        },
                    ],
                },
                {
                    "title": "Connection",
                    "fields": [
                        {
                            "key": "config.host",
                            "label": "Host",
                            "type": "string",
                            "required": True,
                        },
                        {
                            "key": "config.port",
                            "label": "TCP Port",
                            "type": "int",
                            "required": True,
                        },
                        {
                            "key": "config.unit_id",
                            "label": "Unit ID",
                            "type": "int",
                            "required": True,
                        },
                        {
                            "key": "config.timeout",
                            "label": "Timeout (s)",
                            "type": "float",
                            "required": True,
                        },
                    ],
                },
                {
                    "title": "Channels",
                    "fields": [
                        {
                            "key": "config.channel_count",
                            "label": "Channel Count",
                            "type": "int",
                            "required": True,
                        },
                        {
                            "key": "config.update_interval_s",
                            "label": "Poll Interval (s)",
                            "type": "float",
                            "required": True,
                        },
                        {
                            "key": "config.reconnect_delay_s",
                            "label": "Reconnect Delay (s)",
                            "type": "float",
                            "required": True,
                        },
                    ],
                },
                {
                    "title": "Parameters",
                    "fields": [
                        {
                            "key": "config.connected_param",
                            "label": "Connected Param",
                            "type": "string",
                            "required": False,
                        },
                        {
                            "key": "config.last_error_param",
                            "label": "Last Error Param",
                            "type": "string",
                            "required": False,
                        },
                        {
                            "key": "config.last_sync_param",
                            "label": "Last Sync Param",
                            "type": "string",
                            "required": False,
                        },
                    ],
                },
            ]
        },
    }


def run_ui_action(
    action: str,
    payload: dict[str, Any] | None = None,
    record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action_name = str(action or "").strip().lower()
    request = dict(payload or {})
    if action_name not in {"scan_relays", "scan"}:
        raise ValueError(f"Unsupported modbus_relay UI action: {action}")

    timeout = max(0.06, _float_value(request, "timeout", 0.1))
    hosts = _candidate_hosts(request, record)
    ports = _candidate_ports(request, record)
    unit_ids = _candidate_unit_ids(request, record)
    open_targets = _discover_open_targets(hosts, ports, timeout=timeout)

    futures = []
    boards: list[dict[str, Any]] = []
    worker_count = max(4, min(64, len(open_targets) * max(1, len(unit_ids))))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        for host, port in open_targets:
            for unit_id in unit_ids:
                futures.append(
                    pool.submit(_probe_host_port, host, int(port), int(unit_id), timeout)
                )
        for future in as_completed(futures):
            try:
                boards.append(future.result())
            except Exception as exc:
                boards.append(
                    {
                        "host": "unknown",
                        "port": 0,
                        "unit_id": 0,
                        "channel_count": 0,
                        "reachable": False,
                        "error": str(exc),
                        "states": [],
                    }
                )

    boards.sort(
        key=lambda item: (
            0 if item.get("reachable") else 1,
            str(item.get("host") or ""),
            int(item.get("port") or 0),
        )
    )
    reachable = [item for item in boards if item.get("reachable")]

    return {
        "ok": True,
        "action": "scan_relays",
        "candidates": reachable,
        "scanned": len(hosts) * len(ports),
        "open_targets": len(open_targets),
    }
