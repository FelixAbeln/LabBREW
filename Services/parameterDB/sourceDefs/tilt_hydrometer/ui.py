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


def _get_control_spec(record: dict | None = None) -> dict:
    return {
        "spec_version": 1,
        "source_type": "tilt_hydrometer",
        "display_name": "Tilt Hydrometer",
        "description": "This datasource has no writable control parameters.",
        "controls": [],
    }


def get_ui_spec(record: dict | None = None, mode: str | None = None) -> dict:
    if mode == "control":
        return _get_control_spec(record)
    return {
        "source_type": "tilt_hydrometer",
        "display_name": "Tilt Hydrometer",
        "description": "Reads Tilt Bridge JSON and publishes one Tilt hydrometer by color.",
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
                        {"key": "name", "label": "Source Name", "type": "string", "required": True},
                        {"key": "config.parameter_prefix", "label": "Parameter Prefix", "type": "string", "required": True},
                    ],
                },
                {
                    "title": "Transport",
                    "fields": [
                        {"key": "config.transport", "label": "Transport", "type": "enum", "required": True, "choices": ["bridge", "ble"], "help": "bridge uses TiltBridge HTTP JSON; ble scans local Bluetooth advertisements."},
                        {"key": "config.tilt_color", "label": "Tilt Color", "type": "enum", "required": True, "choices": _TILT_COLORS},
                        {"key": "config.bridge_url", "label": "Bridge URL", "type": "string", "required": False, "help": "Used only for transport=bridge. Example: http://tiltbridge.local/json", "visible_when": {"config.transport": "bridge"}},
                        {"key": "config.ble_scan_timeout_s", "label": "BLE Scan Timeout (s)", "type": "float", "required": False, "help": "Used only for transport=ble.", "visible_when": {"config.transport": "ble"}},
                        {"key": "config.ble_idle_s", "label": "BLE Idle Gap (s)", "type": "float", "required": False, "help": "Extra delay between BLE scans. Set 0 for continuous scanning.", "visible_when": {"config.transport": "ble"}},
                        {"key": "config.ble_stale_after_s", "label": "BLE Stale Timeout (s)", "type": "float", "required": False, "help": "Keep connected true this long after last seen Tilt packet to avoid short advertising gaps.", "visible_when": {"config.transport": "ble"}},
                        {"key": "config.ble_device_address", "label": "BLE Device Address", "type": "string", "required": False, "help": "Optional BLE MAC/address to lock to one Tilt. Used only for transport=ble.", "visible_when": {"config.transport": "ble"}},
                        {"key": "config.request_timeout_s", "label": "HTTP Timeout (s)", "type": "float", "required": True, "visible_when": {"config.transport": "bridge"}},
                        {"key": "config.update_interval_s", "label": "Poll Interval (s)", "type": "float", "required": True},
                    ],
                },
            ],
        },
        "edit": {
            "sections": [
                {
                    "title": "Identity",
                    "fields": [
                        {"key": "name", "label": "Source Name", "type": "string", "required": True},
                        {"key": "config.parameter_prefix", "label": "Parameter Prefix", "type": "string", "required": True},
                    ],
                },
                {
                    "title": "Transport",
                    "fields": [
                        {"key": "config.transport", "label": "Transport", "type": "enum", "required": True, "choices": ["bridge", "ble"]},
                        {"key": "config.tilt_color", "label": "Tilt Color", "type": "enum", "required": True, "choices": _TILT_COLORS},
                        {"key": "config.bridge_url", "label": "Bridge URL", "type": "string", "required": False, "help": "Used only for transport=bridge.", "visible_when": {"config.transport": "bridge"}},
                        {"key": "config.ble_scan_timeout_s", "label": "BLE Scan Timeout (s)", "type": "float", "required": False, "help": "Used only for transport=ble.", "visible_when": {"config.transport": "ble"}},
                        {"key": "config.ble_idle_s", "label": "BLE Idle Gap (s)", "type": "float", "required": False, "help": "Extra delay between BLE scans. Set 0 for continuous scanning.", "visible_when": {"config.transport": "ble"}},
                        {"key": "config.ble_stale_after_s", "label": "BLE Stale Timeout (s)", "type": "float", "required": False, "help": "Keep connected true this long after last seen Tilt packet to avoid short advertising gaps.", "visible_when": {"config.transport": "ble"}},
                        {"key": "config.ble_device_address", "label": "BLE Device Address", "type": "string", "required": False, "help": "Optional BLE MAC/address to lock to one Tilt.", "visible_when": {"config.transport": "ble"}},
                        {"key": "config.request_timeout_s", "label": "HTTP Timeout (s)", "type": "float", "required": True, "visible_when": {"config.transport": "bridge"}},
                        {"key": "config.update_interval_s", "label": "Poll Interval (s)", "type": "float", "required": True},
                    ],
                },
                {
                    "title": "Parameter Overrides",
                    "fields": [
                        {"key": "config.gravity_param", "label": "Gravity Parameter", "type": "string", "required": False},
                        {"key": "config.temperature_f_param", "label": "Temperature F Parameter", "type": "string", "required": False},
                        {"key": "config.temperature_c_param", "label": "Temperature C Parameter", "type": "string", "required": False},
                        {"key": "config.rssi_param", "label": "RSSI Parameter", "type": "string", "required": False},
                        {"key": "config.battery_weeks_param", "label": "Battery Weeks Parameter", "type": "string", "required": False},
                        {"key": "config.raw_param", "label": "Raw Payload Parameter", "type": "string", "required": False},
                        {"key": "config.connected_param", "label": "Connected Parameter", "type": "string", "required": False},
                        {"key": "config.last_error_param", "label": "Last Error Parameter", "type": "string", "required": False},
                        {"key": "config.last_sync_param", "label": "Last Sync Parameter", "type": "string", "required": False},
                    ],
                },
            ]
        },
    }
