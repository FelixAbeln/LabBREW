def get_ui_spec() -> dict:
    return {
        "parameter_type": "script",
        "display_name": "Script",
        "description": "Computes its own value from an expression every scan.",
        "create": {
            "required": ["name", "config.expr"],
            "defaults": {
                "value": None,
                "config": {
                    "expr": "value",
                    "depends_on": [],
                },
                "metadata": {},
            },
        },
        "edit": {
            "allow_rename": False,
            "sections": [
                {
                    "title": "Definition",
                    "fields": [
                        {"key": "name", "label": "Name", "type": "string", "readonly": True},
                        {"key": "config.expr", "label": "Expression", "type": "code", "required": True},
                        {"key": "config.depends_on", "label": "Dependencies", "type": "parameter_ref_list"},
                    ],
                },
                {
                    "title": "Runtime",
                    "fields": [
                        {"key": "value", "label": "Current Value", "type": "readonly"},
                        {"key": "state.last_error", "label": "Last Error", "type": "readonly"},
                    ],
                },
            ],
        },
    }
