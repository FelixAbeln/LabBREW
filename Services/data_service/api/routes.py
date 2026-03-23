"""API routes for the data service."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter()
_runtime = None


def set_runtime(runtime):
    """Set the runtime instance for API routes."""
    global _runtime
    _runtime = runtime


class SetupMeasurementRequest(BaseModel):
    """Request model for setup_measurement endpoint."""
    parameters: List[str]
    hz: float = 10.0
    output_dir: str = "data/measurements"
    output_format: str = "parquet"
    session_name: Optional[str] = None


class TakeLoadstepRequest(BaseModel):
    """Request model for take_loadstep endpoint."""
    duration_seconds: float = 30.0
    loadstep_name: Optional[str] = None
    parameters: Optional[List[str]] = None


@router.post("/measurement/setup")
async def setup_measurement(request: SetupMeasurementRequest):
    """Setup a measurement session.
    
    Configure which parameters to record, the sampling rate, output format, etc.
    """
    if _runtime is None:
        raise HTTPException(status_code=500, detail="Runtime not initialized")

    result = _runtime.setup_measurement(
        parameters=request.parameters,
        hz=request.hz,
        output_dir=request.output_dir,
        output_format=request.output_format,
        session_name=request.session_name or ""
    )

    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))

    return result


@router.post("/measurement/start")
async def measure_start():
    """Start recording measurements.
    
    Begins recording the configured parameters at the specified Hz.
    A measurement session must be configured first via /measurement/setup.
    """
    if _runtime is None:
        raise HTTPException(status_code=500, detail="Runtime not initialized")

    result = _runtime.measure_start()

    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))

    return result


@router.post("/measurement/stop")
async def measure_stop():
    """Stop recording measurements.
    
    Finalizes the data file and returns a summary of the recording session.
    """
    if _runtime is None:
        raise HTTPException(status_code=500, detail="Runtime not initialized")

    result = _runtime.measure_stop()

    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))

    return result


@router.post("/loadstep/take")
async def take_loadstep(request: TakeLoadstepRequest):
    """Start recording a loadstep.
    
    Records averaged data over a specified duration.
    A measurement session must be active via /measurement/start.
    """
    if _runtime is None:
        raise HTTPException(status_code=500, detail="Runtime not initialized")

    result = _runtime.take_loadstep(
        duration_seconds=request.duration_seconds,
        loadstep_name=request.loadstep_name or "",
        parameters=request.parameters
    )

    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))

    return result


@router.get("/status")
async def get_status():
    """Get the current status of the data service.
    
    Returns information about the backend connection, recording state, and loaded configuration.
    """
    if _runtime is None:
        raise HTTPException(status_code=500, detail="Runtime not initialized")

    return _runtime.get_status()


@router.get("/health")
async def health():
    """Health check endpoint."""
    if _runtime is None:
        return {"status": "unhealthy", "reason": "Runtime not initialized"}

    status = _runtime.get_status()
    if status["backend_connected"]:
        return {"status": "healthy", "details": status}
    else:
        return {"status": "unhealthy", "reason": "Backend not connected", "details": status}
