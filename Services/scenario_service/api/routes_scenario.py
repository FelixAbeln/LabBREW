from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/scenario")
_runtime = None


def set_runtime(runtime) -> None:
    global _runtime
    _runtime = runtime


def _require_runtime():
    if _runtime is None:
        raise HTTPException(status_code=503, detail="Scenario runtime not initialized")
    return _runtime


@router.get("/package")
def get_package():
    return _require_runtime().get_package()


@router.put("/package")
def put_package(payload: dict):
    return _require_runtime().load_package(payload)


@router.post("/package/tune")
def tune_package(payload: dict):
    return _require_runtime().tune_package(payload)


@router.delete("/package")
def delete_package():
    return _require_runtime().clear_package()


@router.post("/compile")
def compile_package(payload: dict):
    return _require_runtime().compile_package(payload)


@router.post("/run/start")
def start_run():
    return _require_runtime().start_run()


@router.post("/run/pause")
def pause_run():
    return _require_runtime().pause_run()


@router.post("/run/resume")
def resume_run():
    return _require_runtime().resume_run()


@router.post("/run/stop")
def stop_run():
    return _require_runtime().stop_run()


@router.post("/run/next")
def next_step():
    return _require_runtime().next_step()


@router.post("/run/previous")
def previous_step():
    return _require_runtime().previous_step()


@router.get("/run/status")
def get_run_status():
    return _require_runtime().status()
