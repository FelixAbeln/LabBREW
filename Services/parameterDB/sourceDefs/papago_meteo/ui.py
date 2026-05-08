from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from ipaddress import ip_network
from typing import Any

from .service import PapagoMeteoDevice, PapagoMeteoError, QUANTITIES
from .._ui_schema import build_control_app, build_section_app


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
        if not raw or raw.startswith("127.") or raw in found:
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
        if 0 < port <= 65535 and port not in ports:
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
    _add(502)
    return ports or [502]


def _candidate_unit_ids(payload: dict[str, Any], record: dict[str, Any] | None) -> list[int]:
    unit_ids: list[int] = []

    def _add(value: Any) -> None:
        try:
            unit_id = int(value)
        except Exception:
            return
        if 0 <= unit_id <= 247 and unit_id not in unit_ids:
            unit_ids.append(unit_id)

    raw_unit_ids = payload.get("unit_ids")
    if isinstance(raw_unit_ids, list):
        for item in raw_unit_ids:
            _add(item)
    _add(payload.get("unit_id"))
    if isinstance(record, dict):
        cfg = record.get("config")
        if isinstance(cfg, dict):
            _add(cfg.get("unit_id"))
    _add(1)
    return unit_ids or [1]


def _tcp_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _discover_open_targets(hosts: list[str], ports: list[int], *, timeout: float) -> list[tuple[str, int]]:
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
        max_hosts = max(1, min(512, _int_value(payload, "max_hosts", 256)))
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


def _probe_host_port(host: str, port: int, unit_id: int, timeout: float) -> dict[str, Any]:
    device = PapagoMeteoDevice(host=host, port=port, unit_id=unit_id, timeout=timeout)
    try:
        snapshot = device.read_snapshot()
        quantities = []
        for key, value in snapshot.get("quantities", {}).items():
            quantities.append(
                {
                    "quantity": key,
                    "label": QUANTITIES[key].label if key in QUANTITIES else key,
                    "value": value.get("value"),
                    "quality": value.get("quality"),
                    "unit": value.get("unit"),
                }
            )
        return {
            "host": host,
            "port": port,
            "unit_id": unit_id,
            "reachable": True,
            "error": "",
            "sensor_a_status": snapshot.get("sensor_a_status", ""),
            "sensor_a_type": snapshot.get("sensor_a_type", ""),
            "sensor_b_status": snapshot.get("sensor_b_status", ""),
            "sensor_b_type": snapshot.get("sensor_b_type", ""),
            "wind_sensor_status": snapshot.get("wind_sensor_status", ""),
            "quantities": quantities,
        }
    except PapagoMeteoError as exc:
        return {
            "host": host,
            "port": port,
            "unit_id": unit_id,
            "reachable": False,
            "error": str(exc),
            "quantities": [],
        }
    except Exception as exc:
        return {
            "host": host,
            "port": port,
            "unit_id": unit_id,
            "reachable": False,
            "error": str(exc),
            "quantities": [],
        }
    finally:
        device.close()


def _default_quantities(prefix: str) -> dict[str, dict[str, Any]]:
    return {
        "sensor_a_value_1": {"enabled": True, "parameter": f"{prefix}.sensor_a.value_1", "publish_quality": True},
        "sensor_a_value_2": {"enabled": True, "parameter": f"{prefix}.sensor_a.value_2", "publish_quality": True},
        "sensor_a_value_3": {"enabled": True, "parameter": f"{prefix}.sensor_a.value_3", "publish_quality": True},
        "sensor_b_value_1": {"enabled": False, "parameter": f"{prefix}.sensor_b.value_1", "publish_quality": True},
        "sensor_b_value_2": {"enabled": False, "parameter": f"{prefix}.sensor_b.value_2", "publish_quality": True},
        "sensor_b_value_3": {"enabled": False, "parameter": f"{prefix}.sensor_b.value_3", "publish_quality": True},
        "wind_direction_deg": {"enabled": True, "parameter": f"{prefix}.wind.direction_deg", "publish_quality": True},
        "wind_speed_m_s": {"enabled": True, "parameter": f"{prefix}.wind.speed_m_s", "publish_quality": True},
    }


def _get_graph_spec(record: dict | None = None) -> dict:
    record = dict(record or {})
    config = dict(record.get("config") or {})
    source_name = str(record.get("name") or "").strip() or "papago"
    prefix = str(config.get("parameter_prefix") or source_name).strip() or source_name
    quantities = config.get("quantities")
    if not isinstance(quantities, dict) or not quantities:
        quantities = _default_quantities(prefix)

    depends_on: list[str] = []
    seen: set[str] = set()

    def add(target: str) -> None:
        target = str(target or "").strip()
        if target and target not in seen:
            seen.add(target)
            depends_on.append(target)

    for key, item in quantities.items():
        if key not in QUANTITIES or not isinstance(item, dict):
            continue
        if not bool(item.get("enabled", True)):
            continue
        add(str(item.get("parameter") or f"{prefix}.{key}"))
        if bool(item.get("publish_quality", True)):
            add(str(item.get("quality_parameter") or f"{str(item.get('parameter') or f'{prefix}.{key}')}.quality"))

    for status_key in ("connected", "last_error", "last_sync", "device_time"):
        add(str(config.get(f"{status_key}_param") or f"{prefix}.{status_key}"))

    return {"depends_on": depends_on}


def _get_control_spec(record: dict | None = None) -> dict:
    _ = record
    controls = []
    return {
        "spec_version": 1,
        "source_type": "papago_meteo",
        "display_name": "PAPAGO Meteo ETH",
        "description": "This datasource publishes weather-station measurements and has no writable controls.",
        "controls": controls,
        "app": build_control_app(controls, title="PAPAGO Meteo"),
    }


def _identity_section() -> dict:
    return {
        "title": "Identity",
        "fields": [
            {"key": "name", "label": "Source Name", "type": "string", "required": True},
            {"key": "config.parameter_prefix", "label": "Parameter Prefix", "type": "string", "required": True},
        ],
    }


def _connection_section() -> dict:
    return {
        "title": "Connection",
        "fields": [
            {"key": "config.host", "label": "Host", "type": "string", "required": True},
            {"key": "config.port", "label": "TCP Port", "type": "int", "required": True},
            {"key": "config.unit_id", "label": "Unit ID", "type": "int", "required": True},
            {"key": "config.timeout", "label": "Timeout (s)", "type": "float", "required": True},
        ],
    }


def _publishing_section() -> dict:
    return {
        "title": "Publishing",
        "fields": [
            {"key": "config.update_interval_s", "label": "Poll Interval (s)", "type": "float", "required": True},
            {"key": "config.reconnect_delay_s", "label": "Reconnect Delay (s)", "type": "float", "required": True},
            {"key": "config.prefer_float", "label": "Prefer IEEE754 Float Registers", "type": "bool", "required": False},
            {
                "key": "config.quantities",
                "label": "Quantity Mapping JSON",
                "type": "json",
                "required": False,
                "help": "Map PAPAGO quantities to ParameterDB parameters. Leave empty for default Sensor A + wind parameters.",
            },
        ],
    }


def _status_section() -> dict:
    return {
        "title": "Status Parameters",
        "fields": [
            {"key": "config.connected_param", "label": "Connected Param", "type": "string", "required": False},
            {"key": "config.last_error_param", "label": "Last Error Param", "type": "string", "required": False},
            {"key": "config.last_sync_param", "label": "Last Sync Param", "type": "string", "required": False},
            {"key": "config.device_time_param", "label": "Device Time Param", "type": "string", "required": False},
        ],
    }


def get_ui_spec(record: dict | None = None, mode: str | None = None) -> dict:
    if mode == "control":
        return _get_control_spec(record)

    ui = {
        "source_type": "papago_meteo",
        "display_name": "PAPAGO Meteo ETH",
        "description": "Reads PAPAGO Meteo ETH weather-station measurements over Modbus TCP input registers.",
        "module": {
            "id": "papagoMeteoDiscovery",
            "display_name": "PAPAGO Meteo Discovery",
            "description": "Auto-scan the local network for PAPAGO Meteo ETH devices on Modbus TCP.",
            "replace_form": True,
            "menu": {
                "fields": [],
                "run": {
                    "mode": "auto",
                    "cancel_inflight_on_cleanup": True,
                    "request_timeout_s": 8.0,
                },
                "action": {
                    "id": "scan",
                    "action": "scan_papago_meteo",
                    "label": "Scan Network",
                },
                "result": {
                    "list_key": "candidates",
                    "key_fields": ["host", "port", "unit_id"],
                    "title_key": "host",
                    "subtitle_keys": ["port", "unit_id", "sensor_a_type", "wind_sensor_status"],
                    "status_key": "reachable",
                    "error_key": "error",
                    "apply_label": "Use This Station",
                    "empty_message": "No PAPAGO Meteo stations found.",
                    "apply_map": {
                        "host": "host",
                        "port": "port",
                        "unit_id": "unit_id",
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
                    "timeout": 1.5,
                    "update_interval_s": 2.0,
                    "reconnect_delay_s": 2.0,
                    "parameter_prefix": "papago",
                    "prefer_float": False,
                    "quantities": {},
                }
            },
            "sections": [_identity_section(), _connection_section(), _publishing_section()],
        },
        "edit": {
            "sections": [
                _identity_section(),
                _connection_section(),
                _publishing_section(),
                _status_section(),
            ]
        },
    }
    for mode_key in ("create", "edit"):
        mode_spec = ui.get(mode_key)
        if isinstance(mode_spec, dict) and "app" not in mode_spec:
            mode_spec["app"] = build_section_app(mode_spec.get("sections", []))
    return ui


def run_ui_action(
    action: str,
    payload: dict[str, Any] | None = None,
    record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action_name = str(action or "").strip().lower()
    request = dict(payload or {})
    if action_name not in {"scan_papago_meteo", "scan"}:
        raise ValueError(f"Unsupported papago_meteo UI action: {action}")

    timeout = max(0.06, _float_value(request, "timeout", 0.1))
    hosts = _candidate_hosts(request, record)
    ports = _candidate_ports(request, record)
    unit_ids = _candidate_unit_ids(request, record)
    open_targets = _discover_open_targets(hosts, ports, timeout=timeout)

    candidates: list[dict[str, Any]] = []
    worker_count = max(4, min(64, len(open_targets) * max(1, len(unit_ids))))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [
            pool.submit(_probe_host_port, host, int(port), int(unit_id), timeout)
            for host, port in open_targets
            for unit_id in unit_ids
        ]
        for future in as_completed(futures):
            try:
                candidates.append(future.result())
            except Exception as exc:
                candidates.append(
                    {
                        "host": "unknown",
                        "port": 0,
                        "unit_id": 0,
                        "reachable": False,
                        "error": str(exc),
                        "quantities": [],
                    }
                )

    candidates.sort(
        key=lambda item: (
            0 if item.get("reachable") else 1,
            str(item.get("host") or ""),
            int(item.get("port") or 0),
        )
    )
    reachable = [item for item in candidates if item.get("reachable")]

    return {
        "ok": True,
        "action": "scan_papago_meteo",
        "candidates": reachable,
        "scanned": len(hosts) * len(ports),
        "open_targets": len(open_targets),
    }
