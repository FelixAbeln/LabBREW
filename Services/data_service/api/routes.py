"""API routes for the data service."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter()
_runtime = None


def set_runtime(runtime):
    """Set the runtime instance for API routes."""
    global _runtime
    _runtime = runtime


class SetupMeasurementRequest(BaseModel):
    """Request model for setup_measurement endpoint."""

    parameters: list[str]
    hz: float = 10.0
    output_dir: str = "data/measurements"
    output_format: str = "parquet"
    session_name: str | None = None
    include_files: list[str] | None = None


class TakeLoadstepRequest(BaseModel):
    """Request model for take_loadstep endpoint."""

    duration_seconds: float = 30.0
    loadstep_name: str | None = None
    parameters: list[str] | None = None


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
        session_name=request.session_name or "",
        include_files=request.include_files,
    )

    if not result.get("ok"):
        raise HTTPException(
            status_code=400, detail=result.get("error", "Unknown error")
        )

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
        raise HTTPException(
            status_code=400, detail=result.get("error", "Unknown error")
        )

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
        raise HTTPException(
            status_code=400, detail=result.get("error", "Unknown error")
        )

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
        parameters=request.parameters,
    )

    if not result.get("ok"):
        raise HTTPException(
            status_code=400, detail=result.get("error", "Unknown error")
        )

    return result


@router.get("/status")
async def get_status():
    """Get the current status of the data service.

    Returns information about backend connection, recording state,
    and loaded configuration.
    """
    if _runtime is None:
        raise HTTPException(status_code=500, detail="Runtime not initialized")

    return _runtime.get_status()


@router.get("/archives")
async def list_archives(output_dir: str | None = None, limit: int = 200):
    """List archive files and disk usage for the archive directory."""
    if _runtime is None:
        raise HTTPException(status_code=500, detail="Runtime not initialized")

    result = _runtime.list_archives(output_dir=output_dir, limit=limit)
    if not result.get("ok"):
        raise HTTPException(
            status_code=400, detail=result.get("error", "Unknown error")
        )
    return result


@router.get("/archives/view/{archive_name}")
async def view_archive(
    archive_name: str, output_dir: str | None = None, max_points: int = 1500
):
    """Inspect an archive and return parsed measurement/loadstep data for UI preview."""
    if _runtime is None:
        raise HTTPException(status_code=500, detail="Runtime not initialized")

    result = _runtime.view_archive(
        archive_name=archive_name,
        output_dir=output_dir,
        max_points=max_points,
    )
    if not result.get("ok"):
        error_text = str(result.get("error", "Unknown error"))
        error_code = result.get("error_code")
        status_code = result.get("status_code")

        if not isinstance(status_code, int):
            text = error_text.lower()
            is_not_found = error_code == "not_found" or "not found" in text or "missing archive" in text
            status_code = 404 if is_not_found else 400
        raise HTTPException(status_code=status_code, detail=error_text)
    return result


@router.delete("/archives/{archive_name}")
async def delete_archive(archive_name: str, output_dir: str | None = None):
    """Delete one archive file by name."""
    if _runtime is None:
        raise HTTPException(status_code=500, detail="Runtime not initialized")

    result = _runtime.delete_archive(archive_name=archive_name, output_dir=output_dir)
    if not result.get("ok"):
        raise HTTPException(
            status_code=404, detail=result.get("error", "Unknown error")
        )
    return result


@router.get("/archives/download/{archive_name}")
async def download_archive(archive_name: str, output_dir: str | None = None):
    """Download an archive file by name."""
    if _runtime is None:
        raise HTTPException(status_code=500, detail="Runtime not initialized")

    resolved = _runtime.resolve_archive_path(
        archive_name=archive_name, output_dir=output_dir
    )
    if not resolved.get("ok"):
        raise HTTPException(
            status_code=404, detail=resolved.get("error", "Archive not found")
        )

    path = resolved["path"]
    return FileResponse(
        path=path, filename=resolved["name"], media_type="application/zip"
    )


@router.get("/health")
async def health():
    """Health check endpoint."""
    if _runtime is None:
        return {"status": "unhealthy", "reason": "Runtime not initialized"}

    status = _runtime.get_status()
    if status["backend_connected"]:
        return {"status": "healthy", "details": status}
    return {
        "status": "unhealthy",
        "reason": "Backend not connected",
        "details": status,
    }
