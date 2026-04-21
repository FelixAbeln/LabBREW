def get_ui_spec() -> dict:
    return {
        "parameter_type": "moving_average",
        "display_name": "Moving Average",
        "description": "Smooths a source parameter using a rolling arithmetic mean.",
        "create": {
            "required": ["name", "config.source"],
            "defaults": {
                "value": 0.0,
                "config": {
                    "source": "",
                    "enable_param": "",
                    "window": 5,
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
                            "help": "Stored output before the first successful scan.",
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
                            "help": "Parameter whose value should be averaged.",
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
                    ],
                },
                {
                    "title": "Behavior",
                    "fields": [
                        {
                            "key": "config.window",
                            "label": "Window Size",
                            "type": "int",
                            "required": True,
                            "help": (
                                "Number of most recent samples included "
                                "in the average."
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
                    ],
                },
                {
                    "title": "Behavior",
                    "fields": [
                        {
                            "key": "config.window",
                            "label": "Window Size",
                            "type": "int",
                            "required": True,
                        },
                    ],
                },
                {
                    "title": "State",
                    "fields": [
                        {"key": "state.source", "label": "Source", "type": "readonly"},
                        {"key": "state.input", "label": "Input", "type": "readonly"},
                        {"key": "state.window", "label": "Window", "type": "readonly"},
                        {
                            "key": "state.sample_count",
                            "label": "Sample Count",
                            "type": "readonly",
                        },
                        {
                            "key": "state.samples",
                            "label": "Samples",
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
