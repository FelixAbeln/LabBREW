def get_ui_spec() -> dict:
    return {
        "parameter_type": "static",
        "display_name": "Static Value",
        "description": "Passive retained value changed by external apps or operators.",
        "create": {
            "required": ["name"],
            "defaults": {
                "value": 0,
                "config": {},
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
                                "Unique parameter name used by the runtime "
                                "and other plugins."
                            ),
                        },
                    ],
                },
                {
                    "title": "Initial Value",
                    "fields": [
                        {
                            "key": "value",
                            "label": "Initial Value",
                            "type": "json",
                            "help": (
                                "Seed value to create the retained "
                                "parameter with. Any JSON-compatible "
                                "value is allowed."
                            ),
                        },
                    ],
                },
                {
                    "title": "Metadata",
                    "fields": [
                        {
                            "key": "metadata.unit",
                            "label": "Unit",
                            "type": "string",
                            "help": "Optional engineering unit shown in the monitor.",
                        },
                        {
                            "key": "metadata.comment",
                            "label": "Comment",
                            "type": "text",
                            "help": "Optional operator or development note.",
                        },
                    ],
                },
            ],
        },
        "edit": {
            "allow_rename": False,
            "sections": [
                {
                    "title": "Value",
                    "fields": [
                        {
                            "key": "name",
                            "label": "Name",
                            "type": "string",
                            "required": True,
                            "readonly": True,
                        },
                        {
                            "key": "value",
                            "label": "Value",
                            "type": "json",
                            "help": (
                                "Live retained value. Use this for quick "
                                "manual forcing and tuning during "
                                "development."
                            ),
                        },
                    ],
                },
                {
                    "title": "Metadata",
                    "fields": [
                        {"key": "metadata.unit", "label": "Unit", "type": "string"},
                        {"key": "metadata.comment", "label": "Comment", "type": "text"},
                    ],
                },
            ],
        },
    }
