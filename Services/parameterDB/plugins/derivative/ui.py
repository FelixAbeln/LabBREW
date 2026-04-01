def get_ui_spec() -> dict:
    return {
        "parameter_type": "derivative",
        "display_name": "Derivative",
        "description": "Computes rate-of-change from one source parameter using scan dt.",
        "create": {
            "required": ["name", "config.source"],
            "defaults": {
                "value": 0.0,
                "config": {
                    "source": "",
                    "enable_param": "",
                    "mode": "continuous",
                    "window_s": 2.0,
                    "scale": 1.0,
                    "min_dt": 1e-6,
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
                            "help": "Unique parameter name used by the runtime and other plugins.",
                        },
                        {
                            "key": "value",
                            "label": "Initial Value",
                            "type": "float",
                            "help": "Starting output value before the first derivative sample.",
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
                            "help": "Parameter whose rate-of-change should be computed.",
                        },
                        {
                            "key": "config.enable_param",
                            "label": "Enable Parameter",
                            "type": "parameter_ref",
                            "help": "Optional boolean-like parameter to enable or disable updates.",
                        },
                        {
                            "key": "config.output_params",
                            "label": "Mirror Output To",
                            "type": "parameter_ref",
                            "help": "Optional parameters that should receive the same derivative output.",
                        },
                    ],
                },
                {
                    "title": "Behavior",
                    "fields": [
                        {
                            "key": "config.mode",
                            "label": "Derivative Mode",
                            "type": "enum",
                            "options": ["continuous", "window"],
                            "help": "Use 'continuous' for time since last detected source change. Use 'window' for derivative over a fixed trailing time window.",
                        },
                        {
                            "key": "config.window_s",
                            "label": "Window (s)",
                            "type": "float",
                            "visible_when": {"config.mode": "window"},
                            "help": "Used when mode is 'window'. Example: 2.0 gives a two-second trailing derivative.",
                        },
                        {
                            "key": "config.scale",
                            "label": "Scale",
                            "type": "float",
                            "help": "Multiplier applied to the raw derivative.",
                        },
                        {
                            "key": "config.min_dt",
                            "label": "Minimum dt (s)",
                            "type": "float",
                            "visible_when": {"config.mode": "continuous"},
                            "help": "Lower bound used for dt to avoid divide-by-zero spikes.",
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
                        {"key": "name", "label": "Name", "type": "string", "readonly": True},
                        {"key": "value", "label": "Current Value", "type": "readonly"},
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
                        {"key": "config.mode", "label": "Derivative Mode", "type": "enum", "options": ["continuous", "window"]},
                        {"key": "config.window_s", "label": "Window (s)", "type": "float", "visible_when": {"config.mode": "window"}},
                        {"key": "config.scale", "label": "Scale", "type": "float"},
                        {"key": "config.min_dt", "label": "Minimum dt (s)", "type": "float", "visible_when": {"config.mode": "continuous"}},
                    ],
                },
                {
                    "title": "State",
                    "fields": [
                        {"key": "state.mode", "label": "Mode", "type": "readonly"},
                        {"key": "state.window_s", "label": "Window", "type": "readonly", "visible_when": {"state.mode": "window"}},
                        {"key": "state.source", "label": "Source", "type": "readonly"},
                        {"key": "state.input", "label": "Input", "type": "readonly"},
                        {"key": "state.delta", "label": "Delta", "type": "readonly"},
                        {"key": "state.raw_derivative", "label": "Raw Derivative", "type": "readonly"},
                        {"key": "state.updated_on_change", "label": "Updated On Change", "type": "readonly"},
                        {"key": "state.scale", "label": "Scale", "type": "readonly"},
                        {"key": "state.dt", "label": "dt", "type": "readonly"},
                        {"key": "state.effective_dt", "label": "Effective dt", "type": "readonly"},
                        {"key": "state.elapsed_since_change_s", "label": "Elapsed Since Change", "type": "readonly", "visible_when": {"state.mode": "continuous"}},
                        {"key": "state.history_sample_count", "label": "History Samples", "type": "readonly", "visible_when": {"state.mode": "window"}},
                        {"key": "state.history_span_s", "label": "History Span", "type": "readonly", "visible_when": {"state.mode": "window"}},
                        {"key": "state.output_targets", "label": "Output Targets", "type": "readonly"},
                        {"key": "state.missing_output_targets", "label": "Missing Targets", "type": "readonly"},
                        {"key": "state.last_error", "label": "Last Error", "type": "readonly"},
                    ],
                },
            ],
        },
    }
