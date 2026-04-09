def _get_control_spec(_record: dict | None = None) -> dict:
    return {
        "spec_version": 1,
        "source_type": "system_time",
        "display_name": "System Time",
        "description": "This datasource has no writable control parameters.",
        "controls": [],
    }


def get_ui_spec(_record: dict | None = None, mode: str | None = None) -> dict:
    if mode == "control":
        return _get_control_spec()
    return {
        "source_type": "system_time",
        "display_name": "System Time",
        "description": "Publishes the runner machine time into one hold parameter.",
        "create": {
            "required": ["name", "config.parameter_name"],
            "defaults": {
                "config": {
                    "parameter_name": "system.time.iso",
                    "update_interval_s": 1.0,
                    "mode": "iso",
                }
            },
            "sections": [
                {
                    "title": "Identity",
                    "fields": [
                        {
                            "key": "name",
                            "label": "Source Name",
                            "type": "string",
                            "required": True,
                        },
                        {
                            "key": "config.parameter_name",
                            "label": "Parameter Name",
                            "type": "string",
                            "required": True,
                        },
                    ],
                },
                {
                    "title": "Publishing",
                    "fields": [
                        {
                            "key": "config.update_interval_s",
                            "label": "Update Interval (s)",
                            "type": "float",
                            "required": True,
                        },
                        {
                            "key": "config.mode",
                            "label": "Format",
                            "type": "enum",
                            "required": True,
                            "choices": ["iso", "unix", "unix_ms"],
                        },
                    ],
                },
            ],
        },
        "edit": {
            "sections": [
                {
                    "title": "Identity",
                    "fields": [
                        {
                            "key": "name",
                            "label": "Source Name",
                            "type": "string",
                            "required": True,
                        },
                        {
                            "key": "config.parameter_name",
                            "label": "Parameter Name",
                            "type": "string",
                            "required": True,
                        },
                    ],
                },
                {
                    "title": "Publishing",
                    "fields": [
                        {
                            "key": "config.update_interval_s",
                            "label": "Update Interval (s)",
                            "type": "float",
                            "required": True,
                            "default": 1.0,
                        },
                        {
                            "key": "config.mode",
                            "label": "Format",
                            "type": "enum",
                            "required": True,
                            "choices": ["iso", "unix", "unix_ms"],
                        },
                    ],
                },
            ]
        },
    }
