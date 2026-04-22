from __future__ import annotations

from Services.parameterDB.parameterdb_core.plugin_ui.paths import (
    deep_copy_payload,
    get_by_path,
    patch_from_flat_fields,
    set_by_path,
)
from Services.parameterDB.parameterdb_core.plugin_ui.spec import normalize_ui_spec


def test_normalize_ui_spec_applies_defaults_and_field_normalization() -> None:
    spec = {
        "display_name": "PID",
        "create": {
            "required": ["name", "config.kp"],
            "defaults": {
                "value": 0,
                "config": {"kp": 1.0},
            },
            "sections": [
                {
                    "fields": [
                        {"key": "name"},
                        {"key": "config.kp", "type": "number"},
                    ]
                }
            ],
        },
        "edit": {
            "allow_rename": True,
            "sections": [
                {
                    "title": "Runtime",
                    "fields": [{"key": "value"}],
                }
            ],
        },
    }

    normalized = normalize_ui_spec("pid", spec, display_name="PID Plugin", description="Controller")

    assert normalized["parameter_type"] == "pid"
    assert normalized["display_name"] == "PID"
    assert normalized["create"]["defaults"]["config"]["kp"] == 1.0
    assert normalized["create"]["defaults"]["config"]["mirror_to"] == []
    assert normalized["create"]["defaults"]["config"]["timeshift"] == 0.0
    assert normalized["create"]["defaults"]["config"]["calibration_equation"] == ""
    assert normalized["create"]["defaults"]["config"]["force_invalid"] is False
    assert normalized["create"]["defaults"]["config"]["force_invalid_reason"] == ""
    assert normalized["create"]["defaults"]["metadata"] == {}
    assert normalized["create"]["sections"][0]["title"] == "Section 1"
    assert normalized["create"]["sections"][0]["fields"][0]["label"] == "name"
    assert normalized["create"]["sections"][0]["fields"][0]["required"] is False
    assert normalized["create"]["sections"][1]["title"] == "Database Output Pipeline"
    assert normalized["edit"]["allow_rename"] is True
    assert normalized["edit"]["sections"][0]["fields"][0]["label"] == "value"
    assert normalized["edit"]["sections"][1]["title"] == "Database Output Pipeline"
    create_db_fields = {
        field["key"]: field
        for field in normalized["create"]["sections"][1]["fields"]
    }
    assert create_db_fields["config.transducer_id"]["type"] == "transducer_ref"



def test_normalize_ui_spec_without_input_uses_global_defaults() -> None:
    normalized = normalize_ui_spec("static", None, display_name="Static", description="desc")

    assert normalized["parameter_type"] == "static"
    assert normalized["display_name"] == "Static"
    assert normalized["description"] == "desc"
    assert normalized["create"]["required"] == ["name"]
    assert normalized["create"]["defaults"]["config"]["mirror_to"] == []
    assert normalized["create"]["defaults"]["config"]["timeshift"] == 0.0
    assert normalized["create"]["defaults"]["config"]["calibration_equation"] == ""
    assert normalized["create"]["defaults"]["config"]["force_invalid"] is False
    assert normalized["create"]["defaults"]["config"]["force_invalid_reason"] == ""
    assert normalized["edit"]["sections"][0]["title"] == "Database Output Pipeline"



def test_plugin_ui_paths_helpers_for_nested_get_set_and_patch() -> None:
    payload = {"config": {"pid": {"kp": 1.0}}}

    copied = deep_copy_payload(payload)
    copied["config"]["pid"]["kp"] = 2.0

    assert payload["config"]["pid"]["kp"] == 1.0
    assert get_by_path(payload, "config.pid.kp") == 1.0
    assert get_by_path(payload, "config.pid.ki", default="missing") == "missing"
    assert get_by_path(payload, "", default="empty") == "empty"

    set_by_path(payload, "config.pid.ki", 0.2)
    assert payload["config"]["pid"]["ki"] == 0.2

    patch = patch_from_flat_fields(
        {
            "name": "reactor.pid",
            "config.pid.kd": 0.05,
            "metadata.owner": "pytest",
        }
    )

    assert patch == {
        "name": "reactor.pid",
        "config": {"pid": {"kd": 0.05}},
        "metadata": {"owner": "pytest"},
    }
