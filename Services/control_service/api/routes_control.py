from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/control")
_runtime = None


def set_runtime(runtime):
    global _runtime
    _runtime = runtime


def _require_runtime():
    if _runtime is None:
        raise HTTPException(status_code=503, detail="Control runtime not initialized")
    return _runtime


@router.get("/ownership")
def ownership():
    runtime = _require_runtime()
    return runtime.ownership.snapshot()


@router.post("/request")
def request(data: dict):
    runtime = _require_runtime()
    return runtime.request_control(data["target"], data["owner"])


@router.post("/release")
def release(data: dict):
    runtime = _require_runtime()
    return runtime.release_control(data["target"], data["owner"])


@router.post("/force-takeover")
def force_takeover(data: dict):
    runtime = _require_runtime()
    return runtime.force_takeover(
        data["target"],
        data["owner"],
        reason=data.get("reason", ""),
    )


@router.post("/reset")
def reset_target(data: dict):
    runtime = _require_runtime()
    return runtime.reset_target(data["target"])


@router.post("/clear-ownership")
def clear_ownership():
    runtime = _require_runtime()
    return runtime.clear_all_ownership()


@router.get("/read/{target}")
def read_target(target: str):
    runtime = _require_runtime()
    return runtime.read_parameter(target)


@router.post("/write")
def write_target(data: dict):
    runtime = _require_runtime()
    return runtime.set_parameter(
        target=data["target"],
        value=data["value"],
        owner=data["owner"],
    )


@router.post("/manual-write")
def manual_write_target(data: dict):
    runtime = _require_runtime()
    return runtime.manual_set_parameter(
        target=data["target"],
        value=data["value"],
        owner=data.get("owner", "operator"),
        reason=data.get("reason", "manual override"),
    )


@router.post("/release-manual")
def release_manual_controls(data: dict | None = None):
    runtime = _require_runtime()
    payload = data or {}
    targets = payload.get("targets")
    if isinstance(targets, list):
        targets = [str(target).strip() for target in targets if str(target).strip()]
    else:
        targets = None
    return runtime.release_manual_controls(targets=targets)


@router.post("/ramp")
def start_ramp(data: dict):
    runtime = _require_runtime()
    targets = data.get("targets") or [data.get("target")]
    owner = data.get("owner")

    if not owner:
        return {"ok": False, "error": "owner required"}

    if not targets or targets == [None]:
        return {"ok": False, "error": "target or targets required"}

    values = runtime.backend.snapshot([t for t in targets if t is not None])

    for target in targets:
        current = runtime.ownership.get_owner(target)
        if current not in (None, owner):
            return {"ok": False, "error": f"{target} owned by {current}"}
        runtime.ownership.request(target, owner)

    return runtime.start_ramp(data, values=values)
