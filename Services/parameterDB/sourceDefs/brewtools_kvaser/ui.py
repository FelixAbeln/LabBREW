def get_ui_spec() -> dict:
    return {
        "source_type": "brewtools_kvaser",
        "display_name": "Brewtools CAN (Kvaser)",
        "description": "Receives Brewtools CAN measurements over Kvaser and mirrors them into parameters, with optional agitator PWM commands and density polling.",
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
