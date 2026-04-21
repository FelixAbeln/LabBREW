def get_ui_spec() -> dict:
    return {
        "parameter_type": "deadband",
        "display_name": "Deadband Controller",
        "description": (
            "Boolean hysteresis controller with separate on and off "
            "offsets. Its output can also be mirrored to one or "
            "more other parameters."
        ),
        "create": {
            "required": [
                "name",
                "config.pv",
                "config.sp",
                "config.on_offset",
                "config.off_offset",
            ],
            "defaults": {
                "value": False,
                "config": {
                    "pv": "",
                    "sp": "",
                    "on_offset": 1.0,
                    "off_offset": 1.0,
                    "direction": "below",
                    "enable_param": "",
                },
                "metadata": {},
            },
            "sections": [
                {
                    "title": "Identity",
                    "fields": [
                        {
                            "key": "name",
                            "label": "Name",
                            "type": "string",
                            "required": True,
                            "help": (
                                "Unique parameter name for the boolean "
                                "controller output."
                            ),
                        },
                        {
                            "key": "value",
                            "label": "Initial Output",
                            "type": "bool",
                            "help": (
                                "Starting boolean output used until "
                                "the first decisive scan."
                            ),
                        },
                    ],
                },
                {
                    "title": "Inputs",
                    "fields": [
                        {
                            "key": "config.pv",
                            "label": "Process Value",
                            "type": "parameter_ref",
                            "required": True,
                            "help": "Parameter providing the measured value.",
                        },
                        {
                            "key": "config.sp",
                            "label": "Setpoint",
                            "type": "parameter_ref",
                            "required": True,
                            "help": "Parameter providing the switching center.",
                        },
                        {
                            "key": "config.enable_param",
                            "label": "Enable Parameter",
                            "type": "parameter_ref",
                            "help": (
                                "Optional boolean-like parameter used to "
                                "enable or disable updates."
                            ),
                        },
                    ],
                },
                {
                    "title": "Behavior",
                    "fields": [
                        {
                            "key": "config.direction",
                            "label": "Active When",
                            "type": "enum",
                            "options": ["below", "above"],
                            "help": (
                                "Use 'below' for the low-side controller "
                                "and 'above' for the high-side controller."
                            ),
                        },
                        {
                            "key": "config.on_offset",
                            "label": "On Offset",
                            "type": "float",
                            "required": True,
                            "help": (
                                "Distance from setpoint before this "
                                "controller turns on. For a 'below' "
                                "controller that means below SP; for an "
                                "'above' controller it means above SP."
                            ),
                        },
                        {
                            "key": "config.off_offset",
                            "label": "Off Offset",
                            "type": "float",
                            "required": True,
                            "help": (
                                "Distance across the setpoint before this "
                                "controller turns back off, creating the "
                                "dead zone and preventing chatter."
                            ),
                        },
                    ],
                },
            ],
        },
        "edit": {
            "allow_rename": False,
            "sections": [
                {
                    "title": "Identity",
                    "fields": [
                        {
                            "key": "name",
                            "label": "Name",
                            "type": "string",
                            "readonly": True,
                        },
                        {
                            "key": "value",
                            "label": "Current Output",
                            "type": "readonly",
                            "help": "Live boolean output after hysteresis logic.",
                        },
                    ],
                },
                {
                    "title": "Inputs",
                    "fields": [
                        {
                            "key": "config.pv",
                            "label": "Process Value",
                            "type": "parameter_ref",
                            "required": True,
                        },
                        {
                            "key": "config.sp",
                            "label": "Setpoint",
                            "type": "parameter_ref",
                            "required": True,
                        },
                        {
                            "key": "config.enable_param",
                            "label": "Enable Parameter",
                            "type": "parameter_ref",
                        },
                    ],
                },
                {
                    "title": "Behavior",
                    "fields": [
                        {
                            "key": "config.direction",
                            "label": "Active When",
                            "type": "enum",
                            "options": ["below", "above"],
                        },
                        {
                            "key": "config.on_offset",
                            "label": "On Offset",
                            "type": "float",
                            "required": True,
                        },
                        {
                            "key": "config.off_offset",
                            "label": "Off Offset",
                            "type": "float",
                            "required": True,
                        },
                    ],
                },
                {
                    "title": "State",
                    "fields": [
                        {"key": "state.pv", "label": "PV", "type": "readonly"},
                        {"key": "state.sp", "label": "SP", "type": "readonly"},
                        {
                            "key": "state.on_threshold",
                            "label": "On Threshold",
                            "type": "readonly",
                        },
                        {
                            "key": "state.off_threshold",
                            "label": "Off Threshold",
                            "type": "readonly",
                        },
                        {
                            "key": "state.on_offset",
                            "label": "On Offset",
                            "type": "readonly",
                        },
                        {
                            "key": "state.off_offset",
                            "label": "Off Offset",
                            "type": "readonly",
                        },
                        {
                            "key": "state.direction",
                            "label": "Direction",
                            "type": "readonly",
                        },
                        {
                            "key": "state.output_targets",
                            "label": "Output Targets",
                            "type": "readonly",
                        },
                        {
                            "key": "state.missing_output_targets",
                            "label": "Missing Targets",
                            "type": "readonly",
                        },
                        {
                            "key": "state.last_error",
                            "label": "Last Error",
                            "type": "readonly",
                        },
                    ],
                },
            ],
        },
    }
