def get_ui_spec() -> dict:
    return {
        "parameter_type": "math",
        "display_name": "Math Expression",
        "description": (
            "Evaluates an equation using other parameters and can "
            "mirror the result to other parameters."
        ),
        "create": {
            "required": ["name", "config.equation"],
            "defaults": {
                "value": 0.0,
                "config": {
                    "equation": "",
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
                            "help": (
                                "Unique parameter name that stores the "
                                "expression output."
                            ),
                        },
                    ],
                },
                {
                    "title": "Equation",
                    "fields": [
                        {
                            "key": "config.equation",
                            "label": "Equation",
                            "type": "string",
                            "required": True,
                            "help": (
                                "Arithmetic expression like "
                                "'density * 2 / 2'. Symbols refer to "
                                "other parameter names."
                            ),
                        },
                        {
                            "key": "config.enable_param",
                            "label": "Enable Parameter",
                            "type": "parameter_ref",
                            "help": (
                                "Optional boolean-like parameter used to "
                                "enable or disable evaluation."
                            ),
                        },
                        {
                            "key": "config.output_params",
                            "label": "Mirror Output To",
                            "type": "parameter_ref",
                            "help": (
                                "Optional parameters that should receive "
                                "the same output value as this math "
                                "parameter."
                            ),
                        },
                    ],
                },
                {
                    "title": "Initial Value",
                    "fields": [
                        {
                            "key": "value",
                            "label": "Initial Output",
                            "type": "float",
                            "help": (
                                "Stored output used before the first "
                                "successful evaluation."
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
                            "help": (
                                "Live expression output from the latest "
                                "scan cycle."
                            ),
                        },
                    ],
                },
                {
                    "title": "Equation",
                    "fields": [
                        {
                            "key": "config.equation",
                            "label": "Equation",
                            "type": "string",
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
                    "title": "State",
                    "fields": [
                        {
                            "key": "state.symbols",
                            "label": "Resolved Symbols",
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
