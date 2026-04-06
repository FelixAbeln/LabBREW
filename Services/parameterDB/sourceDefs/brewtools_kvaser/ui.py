def _get_control_spec(record: dict | None = None) -> dict:
    record = dict(record or {})
    config = dict(record.get("config") or {})
    source_name = str(record.get("name") or "").strip() or "brewcan"
    prefix = str(config.get("parameter_prefix") or source_name).strip() or source_name

    raw_nodes = config.get("agitator_nodes") or []
    nodes: list[int] = []
    if isinstance(raw_nodes, list):
        for value in raw_nodes:
            try:
                node_id = int(value)
            except Exception:
                continue
            if node_id >= 0:
                nodes.append(node_id)
    nodes = sorted(set(nodes))

    raw_density_nodes = config.get("density_nodes") or []
    density_nodes: list[int] = []
    if isinstance(raw_density_nodes, list):
        for value in raw_density_nodes:
            try:
                node_id = int(value)
            except Exception:
                continue
            if node_id >= 0:
                density_nodes.append(node_id)
    density_nodes = sorted(set(density_nodes))

    raw_pressure_nodes = config.get("pressure_nodes") or []
    pressure_nodes: list[int] = []
    if isinstance(raw_pressure_nodes, list):
        for value in raw_pressure_nodes:
            try:
                node_id = int(value)
            except Exception:
                continue
            if node_id >= 0:
                pressure_nodes.append(node_id)
    pressure_nodes = sorted(set(pressure_nodes))

    controls = [
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
    ] + [
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
    ] + [
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

    return {
        "spec_version": 1,
        "source_type": "brewtools_kvaser",
        "display_name": "Brewtools CAN (Kvaser)",
        "description": "Writable agitator PWM controls and density calibration triggers.",
        "controls": controls,
        "discovery": {
            "fallback_roles": ["command"],
            "metadata_filters": {"node_type": "agitator"},
            "hint": "If no agitator_nodes are configured, controls can still be discovered from live datasource metadata.",
        },
    }


def _get_graph_spec(record: dict | None = None) -> dict:
    controls = _get_control_spec(record).get("controls", [])
    seen: set[str] = set()
    depends_on: list[str] = []
    for control in controls:
        target = str(control.get("target") or "").strip()
        if not target or target in seen:
            continue
        seen.add(target)
        depends_on.append(target)
    return {"depends_on": depends_on}


def get_ui_spec(record: dict | None = None, mode: str | None = None) -> dict:
    if mode == "control":
        return _get_control_spec(record)
    return {
        "source_type": "brewtools_kvaser",
        "display_name": "Brewtools CAN (Kvaser)",
        "description": "Receives Brewtools CAN measurements over Kvaser and mirrors them into parameters, with optional agitator PWM commands and density polling.",
        "graph": _get_graph_spec(record),
        "create": {
            "required": ["name", "config.channel", "config.bitrate"],
            "defaults": {
                "config": {
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
                    "title": "CAN Bus",
                    "fields": [
                        {"key": "config.interface", "label": "Interface", "type": "enum", "required": True, "options": ["kvaser"]},
                        {"key": "config.channel", "label": "Channel", "type": "int", "required": True},
                        {"key": "config.bitrate", "label": "Bitrate", "type": "int", "required": True},
                        {"key": "config.recv_timeout_s", "label": "Receive Timeout (s)", "type": "float", "required": True},
                        {"key": "config.reconnect_delay_s", "label": "Reconnect Delay (s)", "type": "float", "required": True},
                    ],
                },
                {
                    "title": "Optional Outputs",
                    "fields": [
                        {"key": "config.initial_pwm", "label": "Initial PWM", "type": "float", "required": False},
                        {"key": "config.density_request_interval_s", "label": "Density Request Interval (s)", "type": "float", "required": True},
                    ],
                },
                {
                    "title": "Device Nodes",
                    "fields": [
                        {"key": "config.agitator_nodes", "label": "Agitator Node IDs", "type": "json", "required": False, "hint": "e.g. [0, 1]"},
                        {"key": "config.density_nodes", "label": "Density Sensor Node IDs", "type": "json", "required": False, "hint": "e.g. [0]"},
                        {"key": "config.pressure_nodes", "label": "Pressure Sensor Node IDs", "type": "json", "required": False, "hint": "e.g. [0]"},
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
                    "title": "CAN Bus",
                    "fields": [
                        {"key": "config.interface", "label": "Interface", "type": "enum", "required": True, "options": ["kvaser"]},
                        {"key": "config.channel", "label": "Channel", "type": "int", "required": True},
                        {"key": "config.bitrate", "label": "Bitrate", "type": "int", "required": True},
                        {"key": "config.recv_timeout_s", "label": "Receive Timeout (s)", "type": "float", "required": True},
                        {"key": "config.reconnect_delay_s", "label": "Reconnect Delay (s)", "type": "float", "required": True},
                    ],
                },
                {
                    "title": "Optional Outputs",
                    "fields": [
                        {"key": "config.initial_pwm", "label": "Initial PWM", "type": "float", "required": False},
                        {"key": "config.density_request_interval_s", "label": "Density Request Interval (s)", "type": "float", "required": True},
                    ],
                },
                {
                    "title": "Device Nodes",
                    "fields": [
                        {"key": "config.agitator_nodes", "label": "Agitator Node IDs", "type": "json", "required": False, "hint": "e.g. [0, 1]"},
                        {"key": "config.density_nodes", "label": "Density Sensor Node IDs", "type": "json", "required": False, "hint": "e.g. [0]"},
                        {"key": "config.pressure_nodes", "label": "Pressure Sensor Node IDs", "type": "json", "required": False, "hint": "e.g. [0]"},
                    ],
                },
                {
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
                },
            ],
        },
    }
