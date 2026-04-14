from .._ui_schema import build_control_app, build_section_app


def _get_control_spec(_record: dict | None = None) -> dict:
    controls = []
    return {
        "spec_version": 1,
        "source_type": "system_time",
        "display_name": "System Time",
        "description": "This datasource has no writable control parameters.",
        "controls": controls,
        "app": build_control_app(controls, title="Controls"),
    }


def get_ui_spec(_record: dict | None = None, mode: str | None = None) -> dict:
    if mode == "control":
        return _get_control_spec()
    ui = {
        "source_type": "system_time",
        "display_name": "System Time",
        "description": "Publishes the runner machine time into a single hold parameter.",
        "create": {
            "required": ["name", "config.parameter_prefix"],
            "defaults": {
                "config": {
                    "parameter_prefix": "system.time",
                    "parameter_name": "",
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
                            "key": "config.parameter_prefix",
                            "label": "Parameter Prefix",
                            "type": "string",
                            "required": True,
                        },
                        {
                            "key": "config.parameter_name",
                            "label": "Timestamp Parameter Name (optional override)",
                            "type": "string",
                            "required": False,
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
                            "key": "config.parameter_prefix",
                            "label": "Parameter Prefix",
                            "type": "string",
                            "required": True,
                        },
                        {
                            "key": "config.parameter_name",
                            "label": "Timestamp Parameter Name (optional override)",
                            "type": "string",
                            "required": False,
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
    for mode_key in ("create", "edit"):
        mode_spec = ui.get(mode_key)
        if isinstance(mode_spec, dict) and "app" not in mode_spec:
            mode_spec["app"] = build_section_app(mode_spec.get("sections", []))
    return ui
