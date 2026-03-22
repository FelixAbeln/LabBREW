
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix='/schedule')
_runtime = None


def set_runtime(runtime):
    global _runtime
    _runtime = runtime


def _require_runtime():
    if _runtime is None:
        raise HTTPException(status_code=503, detail='Schedule runtime not initialized')
    return _runtime


@router.get('')
def get_schedule():
    return _require_runtime().get_schedule()


@router.put('')
def put_schedule(payload: dict):
    return _require_runtime().load_schedule(payload)


@router.delete('')
def delete_schedule():
    return _require_runtime().clear_schedule()


@router.post('/start')
def start_run():
    return _require_runtime().start_run()


@router.post('/pause')
def pause_run():
    return _require_runtime().pause_run()


@router.post('/resume')
def resume_run():
    return _require_runtime().resume_run()


@router.post('/stop')
def stop_run():
    return _require_runtime().stop_run()


@router.post('/next')
def next_step():
    return _require_runtime().next_step()


@router.post('/previous')
def previous_step():
    return _require_runtime().previous_step()


@router.get('/status')
def status():
    return _require_runtime().status()
