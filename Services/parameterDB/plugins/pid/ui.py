def get_ui_spec() -> dict:
    return {
        "parameter_type": "pid",
        "display_name": "PID Controller",
        "description": (
            "Reads PV and SP from other parameters and can mirror its "
            "output to one or more other parameters."
        ),
        "create": {
            "required": [
                "name",
                "config.pv",
                "config.sp",
                "config.kp",
                "config.ki",
                "config.kd",
                "config.out_min",
                "config.out_max",
            ],
            "defaults": {
                "value": 0.0,
                "config": {
                    "pv": "",
                    "sp": "",
                    "enable_param": "",
                    "mode_param": "",
                    "manual_out_param": "",
                    "kp": 1.0,
                    "ki": 0.0,
                    "kd": 0.0,
                    "bias": 0.0,
                    "out_min": 0.0,
                    "out_max": 100.0,
                    "manual_out": 0.0,
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
                            "help": "Unique parameter name for the controller output.",
                        },
                    ],
                },
                {
                    "title": "Process Links",
                    "fields": [
                        {
                            "key": "config.pv",
                            "label": "Process Value",
                            "type": "parameter_ref",
                            "required": True,
                            "help": (
                                "Parameter that provides the measured "
                                "process value."
                            ),
                        },
                        {
                            "key": "config.sp",
                            "label": "Setpoint",
                            "type": "parameter_ref",
                            "required": True,
                            "help": "Parameter that provides the active setpoint.",
                        },
                        {
                            "key": "config.enable_param",
                            "label": "Enable Parameter",
                            "type": "parameter_ref",
                            "help": (
                                "Optional boolean-like parameter used to "
                                "enable or disable controller action."
                            ),
                        },
                        {
                            "key": "config.mode_param",
                            "label": "Mode Parameter",
                            "type": "parameter_ref",
                            "help": (
                                "Optional parameter that selects auto/manual "
                                "mode externally."
                            ),
                        },
                        {
                            "key": "config.manual_out_param",
                            "label": "Manual Output Parameter",
                            "type": "parameter_ref",
                            "help": (
                                "Optional parameter providing manual output "
                                "when the controller is not in auto."
                            ),
                        },
                        {
                            "key": "config.output_params",
                            "label": "Mirror Output To",
                            "type": "parameter_ref",
                            "help": (
                                "Optional parameters that should receive the "
                                "same output value as this PID controller."
                            ),
                        },
                    ],
                },
                {
                    "title": "Tuning",
                    "fields": [
                        {
                            "key": "config.kp",
                            "label": "Kp",
                            "type": "float",
                            "required": True,
                            "help": "Proportional gain.",
                        },
                        {
                            "key": "config.ki",
                            "label": "Ki",
                            "type": "float",
                            "required": True,
                            "help": "Integral gain per scan.",
                        },
                        {
                            "key": "config.kd",
                            "label": "Kd",
                            "type": "float",
                            "required": True,
                            "help": "Derivative gain.",
                        },
                        {
                            "key": "config.bias",
                            "label": "Bias",
                            "type": "float",
                            "help": "Constant output bias added before clamping.",
                        },
                        {
                            "key": "config.out_min",
                            "label": "Output Min",
                            "type": "float",
                            "required": True,
                            "help": "Lower output clamp.",
                        },
                        {
                            "key": "config.out_max",
                            "label": "Output Max",
                            "type": "float",
                            "required": True,
                            "help": "Upper output clamp.",
                        },
                    ],
                },
                {
                    "title": "Manual / Startup",
                    "fields": [
                        {
                            "key": "value",
                            "label": "Initial Output",
                            "type": "float",
                            "help": (
                                "Initial stored controller output before the "
                                "first useful scan."
                            ),
                        },
                        {
                            "key": "config.manual_out",
                            "label": "Manual Output",
                            "type": "float",
                            "help": (
                                "Fallback manual output when no manual "
                                "output parameter is wired."
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
                            "help": "Live controller output written by the scan cycle.",
                        },
                    ],
                },
                {
                    "title": "Links",
                    "fields": [
                        {
                            "key": "config.pv",
                            "label": "Process Value",
                            "type": "parameter_ref",
                            "required": True,
                        },
                        {
                            "key": "config.sp",
                            "label": "Setpoint",
                            "type": "parameter_ref",
                            "required": True,
                        },
                        {
                            "key": "config.enable_param",
                            "label": "Enable Parameter",
                            "type": "parameter_ref",
                        },
                        {
                            "key": "config.mode_param",
                            "label": "Mode Parameter",
                            "type": "parameter_ref",
                        },
                        {
                            "key": "config.manual_out_param",
                            "label": "Manual Output Parameter",
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
                    "title": "Tuning",
                    "fields": [
                        {
                            "key": "config.kp",
                            "label": "Kp",
                            "type": "float",
                            "required": True,
                        },
                        {
                            "key": "config.ki",
                            "label": "Ki",
                            "type": "float",
                            "required": True,
                        },
                        {
                            "key": "config.kd",
                            "label": "Kd",
                            "type": "float",
                            "required": True,
                        },
                        {"key": "config.bias", "label": "Bias", "type": "float"},
                        {
                            "key": "config.out_min",
                            "label": "Output Min",
                            "type": "float",
                            "required": True,
                        },
                        {
                            "key": "config.out_max",
                            "label": "Output Max",
                            "type": "float",
                            "required": True,
                        },
                        {
                            "key": "config.manual_out",
                            "label": "Manual Output",
                            "type": "float",
                        },
                    ],
                },
                {
                    "title": "State",
                    "fields": [
                        {
                            "key": "state.integral",
                            "label": "Integral",
                            "type": "readonly",
                        },
                        {
                            "key": "state.prev_error",
                            "label": "Previous Error",
                            "type": "readonly",
                        },
                        {"key": "state.error", "label": "Error", "type": "readonly"},
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
