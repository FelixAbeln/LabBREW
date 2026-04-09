def get_ui_spec() -> dict:
    return {
        "parameter_type": "lowpass",
        "display_name": "Lowpass Filter",
        "description": "Smooths a source parameter with a first-order lowpass filter.",
        "create": {
            "required": ["name", "config.source"],
            "defaults": {
                "value": 0.0,
                "config": {
                    "source": "",
                    "enable_param": "",
                    "tau_s": 1.0,
                    "output_params": [],
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
                                "Unique parameter name that stores "
                                "the filtered output."
                            ),
                        },
                        {
                            "key": "value",
                            "label": "Initial Value",
                            "type": "float",
                            "help": (
                                "Stored output before the first successful "
                                "scan. First scan snaps to source."
                            ),
                        },
                    ],
                },
                {
                    "title": "Inputs",
                    "fields": [
                        {
                            "key": "config.source",
                            "label": "Source Parameter",
                            "type": "parameter_ref",
                            "required": True,
                            "help": "Parameter whose value should be lowpass filtered.",
                        },
                        {
                            "key": "config.enable_param",
                            "label": "Enable Parameter",
                            "type": "parameter_ref",
                            "help": (
                                "Optional boolean-like parameter used to "
                                "enable or disable filtering."
                            ),
                        },
                        {
                            "key": "config.output_params",
                            "label": "Mirror Output To",
                            "type": "parameter_ref",
                            "help": (
                                "Optional parameters that should receive "
                                "the same filtered value."
                            ),
                        },
                    ],
                },
                {
                    "title": "Behavior",
                    "fields": [
                        {
                            "key": "config.tau_s",
                            "label": "Time Constant (s)",
                            "type": "float",
                            "required": True,
                            "help": (
                                "Larger values smooth more aggressively. "
                                "Zero means pass-through."
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
                        {"key": "value", "label": "Current Output", "type": "readonly"},
                    ],
                },
                {
                    "title": "Inputs",
                    "fields": [
                        {
                            "key": "config.source",
                            "label": "Source Parameter",
                            "type": "parameter_ref",
                            "required": True,
                        },
                        {
                            "key": "config.enable_param",
                            "label": "Enable Parameter",
                            "type": "parameter_ref",
                        },
                        {
                            "key": "config.output_params",
                            "label": "Mirror Output To",
                            "type": "parameter_ref",
                        },
                    ],
                },
                {
                    "title": "Behavior",
                    "fields": [
                        {
                            "key": "config.tau_s",
                            "label": "Time Constant (s)",
                            "type": "float",
                            "required": True,
                        },
                    ],
                },
                {
                    "title": "State",
                    "fields": [
                        {"key": "state.source", "label": "Source", "type": "readonly"},
                        {"key": "state.input", "label": "Input", "type": "readonly"},
                        {
                            "key": "state.tau_s",
                            "label": "Time Constant",
                            "type": "readonly",
                        },
                        {"key": "state.dt", "label": "dt", "type": "readonly"},
                        {"key": "state.alpha", "label": "Alpha", "type": "readonly"},
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
