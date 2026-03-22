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
                "fields": ["target|targets", "owner", "reason", "value"],
                "required": ["owner"],
            },
            "ramp": {
                "fields": ["target|targets", "value", "duration", "owner"],
                "required": ["value", "duration", "owner"],
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
