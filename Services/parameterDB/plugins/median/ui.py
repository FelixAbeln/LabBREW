def get_ui_spec() -> dict:
    return {
        "parameter_type": "median",
        "display_name": "Median Filter",
        "description": "Smooths a source parameter using a rolling median.",
        "create": {
            "required": ["name", "config.source"],
            "defaults": {
                "value": 0.0,
                "config": {
                    "source": "",
                    "enable_param": "",
                    "window": 5,
                    "output_params": [],
                },
                "metadata": {},
            },
            "sections": [
                {
                    "title": "Identity",
                    "fields": [
                        {"key": "name", "label": "Name", "type": "string", "required": True, "help": "Unique parameter name that stores the filtered output."},
                        {"key": "value", "label": "Initial Value", "type": "float", "help": "Stored output before the first successful scan."},
                    ],
                },
                {
                    "title": "Inputs",
                    "fields": [
                        {"key": "config.source", "label": "Source Parameter", "type": "parameter_ref", "required": True, "help": "Parameter whose value should be median filtered."},
                        {"key": "config.enable_param", "label": "Enable Parameter", "type": "parameter_ref", "help": "Optional boolean-like parameter used to enable or disable filtering."},
                        {"key": "config.output_params", "label": "Mirror Output To", "type": "parameter_ref", "help": "Optional parameters that should receive the same filtered value."},
                    ],
                },
                {
                    "title": "Behavior",
                    "fields": [
                        {"key": "config.window", "label": "Window Size", "type": "int", "required": True, "help": "Number of most recent samples included in the rolling median."},
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
                        {"key": "name", "label": "Name", "type": "string", "readonly": True},
                        {"key": "value", "label": "Current Output", "type": "readonly"},
                    ],
                },
                {
                    "title": "Inputs",
                    "fields": [
                        {"key": "config.source", "label": "Source Parameter", "type": "parameter_ref", "required": True},
                        {"key": "config.enable_param", "label": "Enable Parameter", "type": "parameter_ref"},
                        {"key": "config.output_params", "label": "Mirror Output To", "type": "parameter_ref"},
                    ],
                },
                {
                    "title": "Behavior",
                    "fields": [
                        {"key": "config.window", "label": "Window Size", "type": "int", "required": True},
                    ],
                },
                {
                    "title": "State",
                    "fields": [
                        {"key": "state.source", "label": "Source", "type": "readonly"},
                        {"key": "state.input", "label": "Input", "type": "readonly"},
                        {"key": "state.window", "label": "Window", "type": "readonly"},
                        {"key": "state.sample_count", "label": "Sample Count", "type": "readonly"},
                        {"key": "state.samples", "label": "Samples", "type": "readonly"},
                        {"key": "state.output_targets", "label": "Output Targets", "type": "readonly"},
                        {"key": "state.missing_output_targets", "label": "Missing Targets", "type": "readonly"},
                        {"key": "state.last_error", "label": "Last Error", "type": "readonly"},
                    ],
                },
            ],
        },
    }
