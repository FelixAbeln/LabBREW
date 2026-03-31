def get_ui_spec() -> dict:
    return {
        "parameter_type": "condition",
        "display_name": "Condition",
        "description": "Evaluates shared wait-expression logic like cond:..., elapsed:..., all(...), and any(...), then stores the resulting boolean.",
        "create": {
            "required": ["name", "config.condition"],
            "defaults": {
                "value": False,
                "config": {
                    "condition": "",
                    "enable_param": "",
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
                            "help": "Unique parameter name that stores the boolean condition result.",
                        }
                    ],
                },
                {
                    "title": "Logic",
                    "fields": [
                        {
                            "key": "config.condition",
                            "label": "Logic Expression",
                            "type": "text",
                            "required": True,
                            "help": "Use the shared syntax: cond:source:operator:threshold[:for_seconds], elapsed:seconds, all(expr1;expr2), or any(expr1;expr2). Example: all(elapsed:900;cond:brewcan.density.0:<=:1.012:120).",
                        },
                        {
                            "key": "config.enable_param",
                            "label": "Enable Parameter",
                            "type": "parameter_ref",
                            "help": "Optional boolean-like parameter used to enable or disable condition evaluation.",
                        },
                        {
                            "key": "config.output_params",
                            "label": "Mirror Output To",
                            "type": "parameter_ref",
                            "help": "Optional parameters that should receive the same boolean value as this condition.",
                        },
                    ],
                },
                {
                    "title": "Initial Value",
                    "fields": [
                        {
                            "key": "value",
                            "label": "Initial Value",
                            "type": "bool",
                            "help": "Stored boolean value before the first successful evaluation.",
                        }
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
                        {
                            "key": "value",
                            "label": "Current Value",
                            "type": "readonly",
                            "help": "Final boolean result from the latest condition evaluation.",
                        },
                    ],
                },
                {
                    "title": "Logic",
                    "fields": [
                        {"key": "config.condition", "label": "Logic Expression", "type": "text", "required": True},
                        {"key": "config.enable_param", "label": "Enable Parameter", "type": "parameter_ref"},
                        {"key": "config.output_params", "label": "Mirror Output To", "type": "parameter_ref"},
                    ],
                },
                {
                    "title": "State",
                    "fields": [
                        {"key": "state.expression", "label": "Expression", "type": "readonly"},
                        {"key": "state.logic_kind", "label": "Logic Kind", "type": "readonly"},
                        {"key": "state.condition_kind", "label": "Condition Kind", "type": "readonly"},
                        {"key": "state.source", "label": "Source", "type": "readonly"},
                        {"key": "state.operator", "label": "Operator", "type": "readonly"},
                        {"key": "state.params", "label": "Params", "type": "readonly"},
                        {"key": "state.sources", "label": "Resolved Sources", "type": "readonly"},
                        {"key": "state.matched", "label": "Matched", "type": "readonly"},
                        {"key": "state.elapsed_s", "label": "Elapsed Since Start (s)", "type": "readonly"},
                        {"key": "state.required_for_s", "label": "Required Hold (s)", "type": "readonly"},
                        {"key": "state.observed_values", "label": "Observed Values", "type": "readonly"},
                        {"key": "state.message", "label": "Message", "type": "readonly"},
                        {"key": "state.output_targets", "label": "Output Targets", "type": "readonly"},
                        {"key": "state.missing_output_targets", "label": "Missing Targets", "type": "readonly"},
                        {"key": "state.last_error", "label": "Last Error", "type": "readonly"},
                    ],
                },
            ],
        },
    }