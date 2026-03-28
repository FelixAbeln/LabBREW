from fastapi import APIRouter, HTTPException

from ..._shared.operator_engine.loader import load_registry
from ..rules.storage import get_rule_dir

router = APIRouter(prefix="/system")


def _require_runtime():
    from .routes_control import _runtime as control_runtime
    if control_runtime is None:
        raise HTTPException(status_code=503, detail="Control runtime not initialized")
    return control_runtime


def _normalize_targets(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    targets = [part.strip() for part in raw.split(",") if part.strip()]
    return targets or None



@router.get("/health")
def health():
    return {"ok": True}


@router.get("/operators")
def list_operators():
    registry = load_registry()
    return registry.list_metadata()


@router.get("/rule-dir")
def rule_dir():
    return {"rule_dir": str(get_rule_dir())}


@router.get("/schema")
def schema():
    return {
        "actions": {
            "set": {
                "fields": ["target|targets", "value"],
                "required": ["value"],
            },
            "takeover": {
                "fields": ["target|targets", "reason", "value"],
                "required": [],
            },
            "ramp": {
                "fields": ["target|targets", "value", "duration"],
                "required": ["value", "duration"],
            },
        },
        "multi_target_supported": True,
        "rule_fields": ["id", "enabled", "condition", "actions", "release_when_clear"],
        "snapshot": {
            "path": "/system/snapshot",
            "query": {
                "targets": "optional comma-separated target names"
            },
            "fields": ["ownership", "ramps", "active_rules", "held_rules", "values"]
        },
        "control_contract": {
            "path": "/system/control-contract",
            "fields": ["contract", "resolved_controls", "available_targets"],
        },
        "datasource_contract": {
            "path": "/system/datasource-contract",
            "fields": ["datasources", "orphan_sources", "orphan_parameters"],
        },
        "control_ui_spec": {
            "path": "/system/control-ui-spec",
            "fields": ["cards", "write_path", "release_path", "manual_owner"],
        },
        "manual_control": {
            "write_path": "/control/manual-write",
            "release_path": "/control/release-manual",
            "manual_owner": "operator",
            "protected_owner": "safety",
        },
        "websocket": {
            "path": "/ws/live",
            "query": {
                "targets": "optional comma-separated target names",
                "interval": "optional seconds between snapshots, minimum 0.1"
            }
        },
    }


@router.get("/snapshot")
def snapshot(targets: str | None = None):
    runtime = _require_runtime()
    return runtime.get_live_snapshot(targets=_normalize_targets(targets))


@router.get("/control-contract")
def control_contract():
    runtime = _require_runtime()
    return runtime.get_control_contract_snapshot()


@router.get("/datasource-contract")
def datasource_contract():
    runtime = _require_runtime()
    return runtime.get_datasource_contract_snapshot()


@router.get("/control-ui-spec")
def control_ui_spec():
    runtime = _require_runtime()
    return runtime.get_control_ui_spec()
