from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.request import Request, urlopen

from .service import _APPLE_COMPANY_ID, _TILT_COLOR_UUIDS
from .._ui_schema import build_control_app, build_section_app


_TILT_COLORS = [
    "Red",
    "Green",
    "Black",
    "Purple",
    "Orange",
    "Blue",
    "Yellow",
    "Pink",
]

_TILT_COLOR_CANONICAL = {name.lower(): name for name in _TILT_COLORS}
_UUID_TO_COLOR = {uuid.lower(): color for color, uuid in _TILT_COLOR_UUIDS.items()}


def _canonical_color(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    return _TILT_COLOR_CANONICAL.get(raw)


def _bridge_url(payload: dict[str, Any], record: dict[str, Any] | None) -> str:
    requested = str(payload.get("bridge_url") or "").strip()
    if requested:
        return requested
    if isinstance(record, dict):
        cfg = record.get("config")
        if isinstance(cfg, dict):
            configured = str(cfg.get("bridge_url") or "").strip()
            if configured:
                return configured
    return "http://tiltbridge.local/json"


def _parse_bridge_payload(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("tilts"), list):
        return [item for item in data["tilts"] if isinstance(item, dict)]
    return []


def _scan_bridge_tilts(
    payload: dict[str, Any], record: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], str]:
    try:
        bridge_url = _bridge_url(payload, record)
        timeout_s = float(payload.get("request_timeout_s") or 1.0)
        req = Request(
            bridge_url,
            headers={"Accept": "application/json", "User-Agent": "LabBREW-TiltScan/1.0"},
        )
        with urlopen(req, timeout=timeout_s) as resp:  # nosec: B310
            body = resp.read().decode("utf-8", errors="replace")
        parsed = _parse_bridge_payload(json.loads(body))
    except Exception as exc:
        return [], str(exc)

    out: list[dict[str, Any]] = []
    seen_colors: set[str] = set()
    for item in parsed:
        color = _canonical_color(item.get("color", item.get("Color")))
        if not color or color in seen_colors:
            continue
        seen_colors.add(color)
        out.append(
            {
                "source": "bridge",
                "tilt_color": color,
                "transport": "bridge",
                "ble_device_address": "",
                "bridge_url": bridge_url,
                "selectable": True,
            }
        )
    return out, ""


def _decode_tilt_color_from_adv(manufacturer_data: dict[int, bytes]) -> str | None:
    blob = manufacturer_data.get(_APPLE_COMPANY_ID)
    if not blob:
        return None
    # Some adapters include the Apple company ID bytes (0x4C00) in the blob.
    if len(blob) >= 25 and blob[0] == 0x4C and blob[1] == 0x00:
        blob = blob[2:]
    if len(blob) < 23:
        return None
    if blob[0] != 0x02 or blob[1] != 0x15:
        return None
    uuid_hex = blob[2:18].hex().lower()
    return _UUID_TO_COLOR.get(uuid_hex)


async def _scan_ble_tilts_async(scan_timeout_s: float) -> list[dict[str, Any]]:
    from bleak import BleakScanner

    found: dict[tuple[str, str], dict[str, Any]] = {}

    def _collect(device: Any, adv_data: Any) -> None:
        color = _decode_tilt_color_from_adv(
            getattr(adv_data, "manufacturer_data", {}) or {}
        )
        if not color:
            return
        address = str(getattr(device, "address", "") or "").strip()
        key = (color, address)
        if key in found:
            return
        found[key] = {
            "source": "ble",
            "tilt_color": color,
            "transport": "ble",
            "ble_device_address": address,
            "bridge_url": "",
            "selectable": True,
        }

    def _on_detection(device: Any, adv_data: Any) -> None:
        _collect(device, adv_data)

    scanner = BleakScanner(detection_callback=_on_detection)
    await scanner.start()
    try:
        await asyncio.sleep(max(0.5, scan_timeout_s))
    finally:
        await scanner.stop()
    return sorted(found.values(), key=lambda item: (item["tilt_color"], item["ble_device_address"]))


def _scan_ble_tilts(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    scan_timeout_s = float(payload.get("ble_scan_timeout_s") or 4.0)
    try:
        return asyncio.run(_scan_ble_tilts_async(scan_timeout_s)), ""
    except ModuleNotFoundError:
        return [], "BLE scan unavailable: bleak is not installed"
    except Exception as exc:
        return [], str(exc)


def _get_control_spec(_record: dict | None = None) -> dict:
    controls: list[dict[str, Any]] = []
    return {
        "spec_version": 1,
        "source_type": "tilt_hydrometer",
        "display_name": "Tilt Hydrometer",
        "description": "This datasource has no writable control parameters.",
        "controls": controls,
        "app": build_control_app(controls, title="Controls"),
    }


def get_ui_spec(_record: dict | None = None, mode: str | None = None) -> dict:
    if mode == "control":
        return _get_control_spec()
    ui = {
        "source_type": "tilt_hydrometer",
        "display_name": "Tilt Hydrometer",
        "description": (
            "Reads Tilt Bridge JSON and publishes one Tilt hydrometer "
            "by color."
        ),
        "module": {
            "id": "tiltDiscovery",
            "display_name": "Tilt Discovery",
            "description": "Scan TiltBridge and BLE, then select a discovered Tilt.",
            "replace_form": True,
            "menu": {
                "fields": [],
                "run": {
                    "mode": "auto",
                    "poll_interval_s": 3.0,
                    "cancel_inflight_on_cleanup": True,
                },
                "preserve_results": True,
                "suppress_warnings": True,
                "action": {
                    "id": "scan",
                    "action": "scan_tilts",
                    "label": "Scan Bridge + BLE",
                },
                "result": {
                    "list_key": "candidates",
                    "key_fields": ["transport", "tilt_color", "ble_device_address", "bridge_url"],
                    "title_key": "tilt_color",
                    "subtitle_keys": ["source", "ble_device_address"],
                    "status_key": "selectable",
                    "error_key": "error",
                    "apply_label": "Use This Tilt",
                    "empty_message": "No Tilt discovered. Verify BLE adapter or TiltBridge availability and retry.",
                    "apply_map": {
                        "transport": "transport",
                        "tilt_color": "tilt_color",
                        "ble_device_address": "ble_device_address",
                        "bridge_url": "bridge_url",
                    },
                },
            },
        },
        "create": {
            "required": ["name", "config.transport", "config.tilt_color"],
            "defaults": {
                "config": {
                    "transport": "bridge",
                    "bridge_url": "http://tiltbridge.local/json",
                    "tilt_color": "Red",
                    "parameter_prefix": "tilt",
                    "update_interval_s": 2.0,
                    "request_timeout_s": 3.0,
                    "ble_scan_timeout_s": 4.0,
                    "ble_device_address": "",
                    "ble_idle_s": 0.0,
                    "ble_stale_after_s": 20.0,
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
                        },
                    ],
                },
                {
                    "title": "Transport",
                    "fields": [
                        {
                            "key": "config.transport",
                            "label": "Transport",
                            "type": "enum",
                            "required": True,
                            "choices": ["bridge", "ble"],
                            "help": (
                                "bridge uses TiltBridge HTTP JSON; ble "
                                "scans local Bluetooth advertisements."
                            ),
                        },
                        {
                            "key": "config.tilt_color",
                            "label": "Tilt Color",
                            "type": "enum",
                            "required": True,
                            "choices": _TILT_COLORS,
                        },
                        {
                            "key": "config.bridge_url",
                            "label": "Bridge URL",
                            "type": "string",
                            "required": False,
                            "help": "Used only for transport=bridge. Example: http://tiltbridge.local/json",
                            "visible_when": {"config.transport": "bridge"},
                        },
                        {
                            "key": "config.ble_scan_timeout_s",
                            "label": "BLE Scan Timeout (s)",
                            "type": "float",
                            "required": False,
                            "help": "Used only for transport=ble.",
                            "visible_when": {"config.transport": "ble"},
                        },
                        {
                            "key": "config.ble_idle_s",
                            "label": "BLE Idle Gap (s)",
                            "type": "float",
                            "required": False,
                            "help": (
                                "Extra delay between BLE scans. Set 0 "
                                "for continuous scanning."
                            ),
                            "visible_when": {"config.transport": "ble"},
                        },
                        {
                            "key": "config.ble_stale_after_s",
                            "label": "BLE Stale Timeout (s)",
                            "type": "float",
                            "required": False,
                            "help": (
                                "Keep connected true this long after "
                                "last seen Tilt packet to avoid short "
                                "advertising gaps."
                            ),
                            "visible_when": {"config.transport": "ble"},
                        },
                        {
                            "key": "config.ble_device_address",
                            "label": "BLE Device Address",
                            "type": "string",
                            "required": False,
                            "help": (
                                "Optional BLE MAC/address to lock to "
                                "one Tilt. Used only for transport=ble."
                            ),
                            "visible_when": {"config.transport": "ble"},
                        },
                        {
                            "key": "config.request_timeout_s",
                            "label": "HTTP Timeout (s)",
                            "type": "float",
                            "required": True,
                            "visible_when": {"config.transport": "bridge"},
                        },
                        {
                            "key": "config.update_interval_s",
                            "label": "Poll Interval (s)",
                            "type": "float",
                            "required": True,
                            "help": (
                                "Used only for transport=bridge. BLE "
                                "pacing uses ble_idle_s and "
                                "ble_scan_timeout_s."
                            ),
                            "visible_when": {"config.transport": "bridge"},
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
                    "title": "Transport",
                    "fields": [
                        {
                            "key": "config.transport",
                            "label": "Transport",
                            "type": "enum",
                            "required": True,
                            "choices": ["bridge", "ble"],
                        },
                        {
                            "key": "config.tilt_color",
                            "label": "Tilt Color",
                            "type": "enum",
                            "required": True,
                            "choices": _TILT_COLORS,
                        },
                        {
                            "key": "config.bridge_url",
                            "label": "Bridge URL",
                            "type": "string",
                            "required": False,
                            "help": "Used only for transport=bridge.",
                            "visible_when": {"config.transport": "bridge"},
                        },
                        {
                            "key": "config.ble_scan_timeout_s",
                            "label": "BLE Scan Timeout (s)",
                            "type": "float",
                            "required": False,
                            "help": "Used only for transport=ble.",
                            "visible_when": {"config.transport": "ble"},
                        },
                        {
                            "key": "config.ble_idle_s",
                            "label": "BLE Idle Gap (s)",
                            "type": "float",
                            "required": False,
                            "help": (
                                "Extra delay between BLE scans. Set 0 "
                                "for continuous scanning."
                            ),
                            "visible_when": {"config.transport": "ble"},
                        },
                        {
                            "key": "config.ble_stale_after_s",
                            "label": "BLE Stale Timeout (s)",
                            "type": "float",
                            "required": False,
                            "help": (
                                "Keep connected true this long after "
                                "last seen Tilt packet to avoid short "
                                "advertising gaps."
                            ),
                            "visible_when": {"config.transport": "ble"},
                        },
                        {
                            "key": "config.ble_device_address",
                            "label": "BLE Device Address",
                            "type": "string",
                            "required": False,
                            "help": "Optional BLE MAC/address to lock to one Tilt.",
                            "visible_when": {"config.transport": "ble"},
                        },
                        {
                            "key": "config.request_timeout_s",
                            "label": "HTTP Timeout (s)",
                            "type": "float",
                            "required": True,
                            "visible_when": {"config.transport": "bridge"},
                        },
                        {
                            "key": "config.update_interval_s",
                            "label": "Poll Interval (s)",
                            "type": "float",
                            "required": True,
                        },
                    ],
                },
                {
                    "title": "Parameter Overrides",
                    "fields": [
                        {
                            "key": "config.gravity_param",
                            "label": "Gravity Parameter",
                            "type": "string",
                            "required": False,
                        },
                        {
                            "key": "config.temperature_f_param",
                            "label": "Temperature F Parameter",
                            "type": "string",
                            "required": False,
                        },
                        {
                            "key": "config.temperature_c_param",
                            "label": "Temperature C Parameter",
                            "type": "string",
                            "required": False,
                        },
                        {
                            "key": "config.rssi_param",
                            "label": "RSSI Parameter",
                            "type": "string",
                            "required": False,
                        },
                        {
                            "key": "config.battery_weeks_param",
                            "label": "Battery Weeks Parameter",
                            "type": "string",
                            "required": False,
                        },
                        {
                            "key": "config.raw_param",
                            "label": "Raw Payload Parameter",
                            "type": "string",
                            "required": False,
                        },
                        {
                            "key": "config.connected_param",
                            "label": "Connected Parameter",
                            "type": "string",
                            "required": False,
                        },
                        {
                            "key": "config.last_error_param",
                            "label": "Last Error Parameter",
                            "type": "string",
                            "required": False,
                        },
                        {
                            "key": "config.last_sync_param",
                            "label": "Last Sync Parameter",
                            "type": "string",
                            "required": False,
                        },
                    ],
                },
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
    if action_name not in {"scan_tilts", "scan"}:
        raise ValueError(f"Unsupported tilt_hydrometer UI action: {action}")

    candidates: list[dict[str, Any]] = []
    warnings: list[str] = []

    bridge_items, bridge_error = _scan_bridge_tilts(request, record)
    ble_items, ble_error = _scan_ble_tilts(request)

    if bridge_error:
        warnings.append(f"bridge: {bridge_error}")
    if ble_error:
        warnings.append(f"ble: {ble_error}")

    candidates.extend(bridge_items)
    candidates.extend(ble_items)

    return {
        "ok": True,
        "action": "scan_tilts",
        "candidates": candidates,
        "scanned": len(candidates),
        "warnings": warnings,
    }
