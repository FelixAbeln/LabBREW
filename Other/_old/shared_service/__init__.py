"""Shared building blocks for scheduler-style services."""

from .cli import build_common_service_parser
from .operators import OperatorDef, OperatorRegistry, build_default_operator_registry
from .rule_store import JsonRuleStore
from .styles import AppPalette, button_role_stylesheet, build_main_window_stylesheet, build_status_banner_stylesheet

__all__ = [
    "AppPalette",
    "OperatorDef",
    "OperatorRegistry",
    "JsonRuleStore",
    "build_common_service_parser",
    "build_default_operator_registry",
    "build_main_window_stylesheet",
    "build_status_banner_stylesheet",
    "button_role_stylesheet",
]

from .condition_spec import ConditionSpec, condition_from_rule, condition_from_schedule_step

from .http_client import ApiClient
