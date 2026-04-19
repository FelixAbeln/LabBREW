from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(prefix="/scenario")
_runtime = None


def set_runtime(runtime) -> None:
    global _runtime
    _runtime = runtime


def _require_runtime():
    if _runtime is None:
        raise HTTPException(status_code=503, detail="Scenario runtime not initialized")
    return _runtime


def _json_result(result: tuple[int, dict]):
    status_code, payload = result
    return JSONResponse(status_code=status_code, content=payload)


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


@router.put("/validate-import")
async def validate_import_package(file: Annotated[UploadFile, File(...)]):
    runtime = _require_runtime()
    package_bytes = await file.read()
    return _json_result(
        runtime.package_repository.validate_import_upload(
            package_bytes,
            filename=file.filename or "scenario.package.msgpack",
        )
    )


@router.put("/import")
async def import_package(file: Annotated[UploadFile, File(...)]):
    runtime = _require_runtime()
    package_bytes = await file.read()
    return _json_result(
        runtime.package_repository.import_upload(
            package_bytes,
            filename=file.filename or "scenario.package.msgpack",
        )
    )


@router.get("/repository")
def list_repository(q: str | None = None, tag: str | None = None):
    runtime = _require_runtime()
    return _json_result(runtime.package_repository.list_packages(q=q, tag=tag))


@router.post("/repository/save")
def save_repository_package(payload: dict):
    runtime = _require_runtime()
    return _json_result(runtime.package_repository.save_package(payload))


@router.post("/repository/copy")
def copy_repository_package(payload: dict):
    runtime = _require_runtime()
    return _json_result(runtime.package_repository.copy_package(payload))


@router.get("/repository/templates")
def list_repository_templates():
    runtime = _require_runtime()
    return _json_result(runtime.package_repository.list_templates())


@router.post("/repository/create-from-template")
def create_repository_from_template(payload: dict):
    runtime = _require_runtime()
    return _json_result(runtime.package_repository.create_from_template(payload))


@router.post("/repository/import")
def import_repository_package(payload: dict):
    runtime = _require_runtime()
    return _json_result(runtime.package_repository.import_package(payload))


@router.post("/repository/metadata")
def update_repository_metadata(payload: dict):
    runtime = _require_runtime()
    return _json_result(runtime.package_repository.update_metadata(payload))


@router.post("/repository/rename")
def rename_repository_package(payload: dict):
    runtime = _require_runtime()
    return _json_result(runtime.package_repository.rename_package(payload))


@router.delete("/repository/{filename}")
def delete_repository_package(filename: str):
    runtime = _require_runtime()
    return _json_result(runtime.package_repository.delete_package(filename))


@router.get("/repository/download/{filename}")
def download_repository_package(filename: str):
    runtime = _require_runtime()
    target = runtime.package_repository.download_package_path(filename)
    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type="application/octet-stream",
    )


@router.get("/repository/read/{filename}")
def read_repository_package(filename: str):
    runtime = _require_runtime()
    return _json_result(runtime.package_repository.read_package(filename))


@router.post("/repository/upload-package")
async def upload_repository_package(
    request: Request,
    file: Annotated[UploadFile, File(...)],
):
    runtime = _require_runtime()
    package_bytes = await file.read()
    requested_filename = str(request.query_params.get("filename") or "").strip() or None
    return _json_result(
        runtime.package_repository.upload_package(
            package_bytes,
            upload_filename=file.filename or "package.lbpkg",
            requested_filename=requested_filename,
        )
    )


@router.post("/repository/package-file-action")
@router.post("/repository/convert-excel")
async def repository_package_file_action(
    request: Request,
    file: Annotated[UploadFile, File(...)],
):
    runtime = _require_runtime()
    workbook_bytes = await file.read()
    return _json_result(
        runtime.package_repository.package_file_action(
            workbook_bytes,
            workbook_filename=file.filename or "workbook.xlsx",
            options=dict(request.query_params),
        )
    )


@router.post("/run/start")
def start_run(payload: dict | None = None):
    start_index = None
    if isinstance(payload, dict):
        run_index = payload.get("run_index")
        if run_index is not None:
            try:
                start_index = max(0, int(run_index) - 1)
            except (TypeError, ValueError):
                start_index = None
        else:
            requested_start_index = payload.get("start_index")
            if requested_start_index is not None:
                try:
                    start_index = int(requested_start_index)
                except (TypeError, ValueError):
                    start_index = None
    return _require_runtime().start_run(start_index=start_index)


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


# ------------------------------------------------------------------ queue

@router.get("/queue")
def get_queue():
    return _require_runtime().get_queue()


@router.put("/queue")
def set_queue(payload: dict):
    entries = payload.get("entries") if isinstance(payload, dict) else []
    advance_on_stop = payload.get("advance_on_stop") if isinstance(payload, dict) else None
    enabled = payload.get("enabled") if isinstance(payload, dict) else None
    return _require_runtime().set_queue(
        entries or [],
        advance_on_stop=advance_on_stop,
        enabled=enabled,
    )


@router.post("/queue/enqueue")
def enqueue(payload: dict):
    advance_on_stop = payload.get("advance_on_stop") if isinstance(payload, dict) else None
    queue_enabled = payload.get("queue_enabled") if isinstance(payload, dict) else None
    return _require_runtime().enqueue(
        payload,
        advance_on_stop=advance_on_stop,
        queue_enabled=queue_enabled,
    )


@router.delete("/queue/{index}")
def dequeue(index: int):
    return _require_runtime().dequeue(index)


@router.post("/queue/clear")
def clear_queue():
    return _require_runtime().clear_queue()


@router.post("/queue/run-next")
def run_next_queued():
    return _require_runtime().start_next_queued()
