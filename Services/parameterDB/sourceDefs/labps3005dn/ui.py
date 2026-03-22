def get_ui_spec() -> dict:
    return {
        "source_type": "labps3005dn",
        "display_name": "LABPS3005DN PSU",
        "description": "Mirrors static setpoint parameters to a serial bench PSU and publishes measured readbacks.",
        "create": {
            "required": ["name", "config.port"],
            "defaults": {
                "config": {
                    "port": "COM5",
                    "baudrate": 9600,
                    "timeout": 1.0,
                    "settle_time": 0.08,
                    "update_interval_s": 0.25,
                    "reconnect_delay_s": 2.0,
                    "parameter_prefix": "psu",
                    "initial_voltage": 0.0,
                    "initial_current": 0.0,
                }
            },
            "sections": [
                {
                    "title": "Identity",
                    "fields": [
                        {"key": "name", "label": "Source Name", "type": "string", "required": True},
                        {"key": "config.parameter_prefix", "label": "Parameter Prefix", "type": "string", "required": True, "help": "Base name for setpoint and readback parameters."},
                    ],
                },
                {
                    "title": "Connection",
                    "fields": [
                        {"key": "config.port", "label": "Serial Port", "type": "string", "required": True},
                        {"key": "config.baudrate", "label": "Baudrate", "type": "int", "required": True},
                        {"key": "config.timeout", "label": "Serial Timeout (s)", "type": "float", "required": True},
                        {"key": "config.settle_time", "label": "Command Settle Time (s)", "type": "float", "required": True},
                    ],
                },
                {
                    "title": "Polling",
                    "fields": [
                        {"key": "config.update_interval_s", "label": "Poll Interval (s)", "type": "float", "required": True},
                        {"key": "config.reconnect_delay_s", "label": "Reconnect Delay (s)", "type": "float", "required": True},
                        {"key": "config.initial_voltage", "label": "Initial Voltage Setpoint", "type": "float", "required": False},
                        {"key": "config.initial_current", "label": "Initial Current Setpoint", "type": "float", "required": False},
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
                        {"key": "config.port", "label": "Serial Port", "type": "string", "required": True},
                        {"key": "config.baudrate", "label": "Baudrate", "type": "int", "required": True},
                        {"key": "config.timeout", "label": "Serial Timeout (s)", "type": "float", "required": True},
                        {"key": "config.settle_time", "label": "Command Settle Time (s)", "type": "float", "required": True},
                    ],
                },
                {
                    "title": "Polling",
                    "fields": [
                        {"key": "config.update_interval_s", "label": "Poll Interval (s)", "type": "float", "required": True},
                        {"key": "config.reconnect_delay_s", "label": "Reconnect Delay (s)", "type": "float", "required": True},
                        {"key": "config.initial_voltage", "label": "Initial Voltage Setpoint", "type": "float", "required": False},
                        {"key": "config.initial_current", "label": "Initial Current Setpoint", "type": "float", "required": False},
                    ],
                },
                {
                    "title": "Parameters",
                    "fields": [
                        {"key": "config.set_enable_param", "label": "Set Enable Param", "type": "string", "required": False},
                        {"key": "config.set_voltage_param", "label": "Set Voltage Param", "type": "string", "required": False},
                        {"key": "config.set_current_param", "label": "Set Current Param", "type": "string", "required": False},
                        {"key": "config.voltage_meas_param", "label": "Voltage Measured Param", "type": "string", "required": False},
                        {"key": "config.current_meas_param", "label": "Current Measured Param", "type": "string", "required": False},
                        {"key": "config.output_state_param", "label": "Output State Param", "type": "string", "required": False},
                        {"key": "config.mode_param", "label": "Mode Param", "type": "string", "required": False},
                        {"key": "config.protection_param", "label": "Protection Param", "type": "string", "required": False},
                        {"key": "config.status_raw_param", "label": "Raw Status Param", "type": "string", "required": False},
                        {"key": "config.connected_param", "label": "Connected Param", "type": "string", "required": False},
                        {"key": "config.last_error_param", "label": "Last Error Param", "type": "string", "required": False},
                        {"key": "config.idn_param", "label": "IDN Param", "type": "string", "required": False},
                    ],
                },
            ]
        },
    }
