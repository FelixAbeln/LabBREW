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
    return {
        "depends_on": [
            str(control.get("target"))
            for control in controls
            if str(control.get("target") or "").strip()
        ]
    }


def get_ui_spec(record: dict | None = None, mode: str | None = None) -> dict:
    if mode == "control":
        return _get_control_spec(record)
    return {
        "source_type": "modbus_relay",
        "display_name": "Modbus Relay Board",
        "description": "Mirrors relay channel booleans to a Modbus-TCP relay board and republishes actual relay states.",
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
                        {"key": "name", "label": "Source Name", "type": "string", "required": True},
                        {"key": "config.parameter_prefix", "label": "Parameter Prefix", "type": "string", "required": True, "help": "Creates relay state params like relay.ch1, relay.ch2, ..."},
                    ],
                },
                {
                    "title": "Connection",
                    "fields": [
                        {"key": "config.host", "label": "Host", "type": "string", "required": True},
                        {"key": "config.port", "label": "TCP Port", "type": "int", "required": True},
                        {"key": "config.unit_id", "label": "Unit ID", "type": "int", "required": True},
                        {"key": "config.timeout", "label": "Timeout (s)", "type": "float", "required": True},
                    ],
                },
                {
                    "title": "Channels",
                    "fields": [
                        {"key": "config.channel_count", "label": "Channel Count", "type": "int", "required": True},
                        {"key": "config.update_interval_s", "label": "Poll Interval (s)", "type": "float", "required": True},
                        {"key": "config.reconnect_delay_s", "label": "Reconnect Delay (s)", "type": "float", "required": True},
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
                    "title": "Connection",
                    "fields": [
                        {"key": "config.host", "label": "Host", "type": "string", "required": True},
                        {"key": "config.port", "label": "TCP Port", "type": "int", "required": True},
                        {"key": "config.unit_id", "label": "Unit ID", "type": "int", "required": True},
                        {"key": "config.timeout", "label": "Timeout (s)", "type": "float", "required": True},
                    ],
                },
                {
                    "title": "Channels",
                    "fields": [
                        {"key": "config.channel_count", "label": "Channel Count", "type": "int", "required": True},
                        {"key": "config.update_interval_s", "label": "Poll Interval (s)", "type": "float", "required": True},
                        {"key": "config.reconnect_delay_s", "label": "Reconnect Delay (s)", "type": "float", "required": True},
                    ],
                },
                {
                    "title": "Parameters",
                    "fields": [
                        {"key": "config.connected_param", "label": "Connected Param", "type": "string", "required": False},
                        {"key": "config.last_error_param", "label": "Last Error Param", "type": "string", "required": False},
                        {"key": "config.last_sync_param", "label": "Last Sync Param", "type": "string", "required": False},
                    ],
                },
            ]
        },
    }
