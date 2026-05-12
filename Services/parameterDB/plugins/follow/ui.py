def get_ui_spec() -> dict:
    return {
        "parameter_type": "follow",
        "display_name": "Follow",
        "description": "Mirrors a source parameter and can hold the last good value while the source is invalid.",
        "create": {
            "required": ["name", "config.source"],
            "defaults": {
                "value": 0.0,
                "config": {
                    "source": "",
                    "latch_on_invalid": True,
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
                            "help": "Unique parameter name that stores the followed output.",
                        },
                        {
                            "key": "value",
                            "label": "Initial Value",
                            "type": "float",
                            "help": "Seed value used until the first valid source value is observed.",
                        },
                    ],
                },
                {
                    "title": "Source",
                    "fields": [
                        {
                            "key": "config.source",
                            "label": "Source Parameter",
                            "type": "parameter_ref",
                            "required": True,
                            "help": "Parameter to mirror while it remains valid.",
                        },
                        {
                            "key": "config.latch_on_invalid",
                            "label": "Latch On Invalid",
                            "type": "bool",
                            "required": True,
                            "help": "Keep the last good value when the source parameter is marked invalid.",
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
                        },
                    ],
                },
                {
                    "title": "Source",
                    "fields": [
                        {
                            "key": "config.source",
                            "label": "Source Parameter",
                            "type": "parameter_ref",
                            "required": True,
                        },
                        {
                            "key": "config.latch_on_invalid",
                            "label": "Latch On Invalid",
                            "type": "bool",
                            "required": True,
                        },
                    ],
                },
                {
                    "title": "State",
                    "fields": [
                        {"key": "state.source", "label": "Source", "type": "readonly"},
                        {"key": "state.input", "label": "Input", "type": "readonly"},
                        {"key": "state.source_invalid", "label": "Source Invalid", "type": "readonly"},
                        {"key": "state.source_invalid_reasons", "label": "Invalid Reasons", "type": "readonly"},
                        {"key": "state.latched", "label": "Latched", "type": "readonly"},
                        {"key": "state.last_error", "label": "Last Error", "type": "readonly"},
                    ],
                },
            ],
        },
    }