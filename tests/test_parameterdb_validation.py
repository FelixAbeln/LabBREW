from __future__ import annotations

from pathlib import Path

import pytest

from Services.parameterDB.parameterdb_core.errors import ValidationError
from Services.parameterDB.parameterdb_service.api.validation import (
    optional_bool,
    optional_int,
    optional_list_of_str,
    optional_path_str,
    optional_str,
    require_dict,
    require_str,
    validate_create_parameter,
    validate_delete_parameter,
    validate_empty_ok,
    validate_get_parameter_type_ui,
    validate_get_value,
    validate_load_parameter_type_folder,
    validate_set_value,
    validate_snapshot_names,
    validate_subscribe,
    validate_update_changes,
)


def test_basic_required_and_optional_validation_helpers() -> None:
    payload = {
        "obj": {"a": 1},
        "name": " alpha ",
        "opt": "value",
        "flag": True,
        "names": ["a", "b"],
        "folder": "nested/dir",
        "count": 7,
    }

    assert require_dict(payload, "obj") == {"a": 1}
    assert require_str(payload, "name") == " alpha "
    assert optional_str(payload, "opt") == "value"
    assert optional_str({"opt": ""}, "opt") is None
    assert optional_str({}, "opt") is None
    assert optional_bool(payload, "flag") is True
    assert optional_bool({}, "flag", default=True) is True
    assert optional_list_of_str(payload, "names") == ["a", "b"]
    assert optional_list_of_str({}, "names") == []
    assert optional_path_str(payload, "folder") == str(Path("nested/dir"))
    assert optional_path_str({}, "folder") is None
    assert optional_int(payload, "count", default=3) == 7
    assert optional_int({}, "count", default=3) == 3


def test_validation_helpers_reject_invalid_input_types() -> None:
    with pytest.raises(ValidationError, match="Field 'obj' must be an object"):
        require_dict({"obj": []}, "obj")
    with pytest.raises(ValidationError, match="Field 'name' must be a non-empty string"):
        require_str({"name": "   "}, "name")
    with pytest.raises(ValidationError, match="Field 'opt' must be a string"):
        optional_str({"opt": 1}, "opt")
    with pytest.raises(ValidationError, match="Field 'flag' must be a boolean"):
        optional_bool({"flag": "yes"}, "flag")
    with pytest.raises(ValidationError, match="Field 'names' must be a list of strings"):
        optional_list_of_str({"names": ["ok", 1]}, "names")
    with pytest.raises(ValidationError, match="Field 'count' must be an integer"):
        optional_int({"count": "7"}, "count", default=0)


def test_payload_validators_accept_expected_shapes() -> None:
    assert validate_empty_ok({"ok": True}) == {"ok": True}
    assert validate_get_parameter_type_ui({"parameter_type": "fake"}) == {"parameter_type": "fake"}
    assert validate_create_parameter(
        {
            "name": "alpha",
            "parameter_type": "fake",
            "value": 10,
            "config": {"unit": "C"},
            "metadata": {"owner": "pytest"},
        }
    ) == {
        "name": "alpha",
        "parameter_type": "fake",
        "value": 10,
        "config": {"unit": "C"},
        "metadata": {"owner": "pytest"},
    }
    assert validate_delete_parameter({"name": "alpha"}) == {"name": "alpha"}
    assert validate_get_value({"name": "alpha", "default": 7}) == {"name": "alpha", "default": 7}
    assert validate_set_value({"name": "alpha", "value": 9}) == {"name": "alpha", "value": 9}
    assert validate_update_changes({"name": "alpha", "changes": {"unit": "C"}}) == {
        "name": "alpha",
        "changes": {"unit": "C"},
    }
    assert validate_load_parameter_type_folder({"folder": "plugins"}) == {"folder": "plugins"}
    assert validate_subscribe({"names": ["a"], "send_initial": False, "max_queue": 0}) == {
        "names": ["a"],
        "send_initial": False,
        "max_queue": 1,
    }


def test_payload_validators_reject_invalid_shapes() -> None:
    with pytest.raises(ValidationError, match="Payload must be an object"):
        validate_empty_ok([])  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="Field 'config' must be an object"):
        validate_create_parameter({"name": "alpha", "parameter_type": "fake", "config": []})
    with pytest.raises(ValidationError, match="Field 'metadata' must be an object"):
        validate_create_parameter({"name": "alpha", "parameter_type": "fake", "metadata": []})
    with pytest.raises(ValidationError, match="Field 'folder' must be a non-empty string"):
        validate_load_parameter_type_folder({"folder": ""})
    with pytest.raises(ValidationError, match="Field 'names' must be a list of strings"):
        validate_subscribe({"names": ["a", 2]})
    with pytest.raises(ValidationError, match="Field 'send_initial' must be a boolean"):
        validate_subscribe({"send_initial": "yes"})
    with pytest.raises(ValidationError, match="Field 'max_queue' must be an integer"):
        validate_subscribe({"max_queue": "large"})


def test_validate_snapshot_names_accepts_valid_input() -> None:
    assert validate_snapshot_names({"names": ["param1"]}) == {"names": ["param1"]}
    assert validate_snapshot_names({"names": ["param1", "param2", "param3"]}) == {
        "names": ["param1", "param2", "param3"]
    }


def test_validate_snapshot_names_rejects_invalid_input() -> None:
    # Empty list
    with pytest.raises(ValidationError, match="Field 'names' must be a non-empty list"):
        validate_snapshot_names({"names": []})
    # Not a list
    with pytest.raises(ValidationError, match="Field 'names' must be a list of non-empty strings"):
        validate_snapshot_names({"names": "param1"})
    # List with non-strings
    with pytest.raises(ValidationError, match="Field 'names' must be a list of non-empty strings"):
        validate_snapshot_names({"names": ["param1", 2]})
    # List with blank strings
    with pytest.raises(ValidationError, match="Field 'names' must be a list of non-empty strings"):
        validate_snapshot_names({"names": ["param1", ""]})
    with pytest.raises(ValidationError, match="Field 'names' must be a list of non-empty strings"):
        validate_snapshot_names({"names": ["param1", "   "]})
