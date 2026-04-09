from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from typing import Any

import requests
import uvicorn
import yaml
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from requests.adapters import HTTPAdapter
from starlette.background import BackgroundTask

from Services._shared.storage_paths import (
    add_network_drive_to_topology,
    configured_network_drives,
    storage_subdir,
)
from Services.parameterDB.parameterdb_core.client import SignalClient


class CreateParamBody(BaseModel):
    name: str
    parameter_type: str
    value: Any = None
    config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SetValueBody(BaseModel):
    value: Any


class UpdateConfigBody(BaseModel):
    config: dict[str, Any]


class UpdateMetadataBody(BaseModel):
    metadata: dict[str, Any]


class CreateSourceBody(BaseModel):
    name: str
    source_type: str
    config: dict[str, Any] = Field(default_factory=dict)


class ImportSnapshotBody(BaseModel):
    snapshot: dict[str, Any]
    replace_existing: bool = True
    save_to_disk: bool = True


class AgentStorageListBody(BaseModel):
    root: str
    path: str = ""


class AgentStorageMkdirBody(BaseModel):
    root: str
    path: str = ""
    name: str


class AgentStorageMoveBody(BaseModel):
    root: str
    src_path: str
    dst_path: str


class AgentStorageDeleteBody(BaseModel):
    root: str
    path: str
    recursive: bool = False


class AgentStorageNetworkDriveBody(BaseModel):
    name: str
    path: str


class AgentStorageFileBody(BaseModel):
    root: str
    path: str


class AgentStorageWriteFileBody(BaseModel):
    root: str
    path: str
    content: str


_EDITABLE_TEXT_EXTENSIONS = {
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".log",
    ".csv",
    ".ini",
    ".cfg",
    ".conf",
    ".py",
    ".toml",
    ".xml",
}
_MAX_EDITABLE_FILE_BYTES = 1_000_000


def _build_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=32, pool_maxsize=64, max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def build_agent_app(
    *,
    node_id: str,
    node_name: str,
    service_map: Callable[[], dict[str, dict[str, Any]]],
    summary_provider: Callable[[], dict[str, Any]],
    proxy_session: requests.Session,
    update_status_provider: Callable[[bool], dict[str, Any]] | None = None,
    apply_update_action: Callable[[], dict[str, Any]] | None = None,
) -> FastAPI:
    app = FastAPI(title=f"Fermenter Agent {node_name}")

    db_host = "127.0.0.1"
    db_port = 8765
    ds_port = 8766
    db_timeout = 5.0

    def _db() -> SignalClient:
        return SignalClient(db_host, db_port, timeout=db_timeout)

    def _ds() -> SignalClient:
        return SignalClient(db_host, ds_port, timeout=db_timeout)

    def _wrap(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    def _build_graph_payload() -> dict[str, Any]:
        graph = dict(_db().graph_info() or {})
        try:
            raw_sources = _ds().list_sources() or {}
        except Exception:
            raw_sources = {}

        sources: dict[str, dict[str, Any]] = {}
        for source_name, source_record in raw_sources.items():
            record = dict(source_record or {})
            source_type = str(record.get("source_type") or "").strip()
            graph_meta: dict[str, Any] = {}
            if source_type:
                try:
                    ui_spec = (
                        _ds().get_source_type_ui(
                            source_type, name=source_name, mode="edit"
                        )
                        or {}
                    )
                    graph_meta = dict(ui_spec.get("graph") or {})
                except Exception:
                    graph_meta = {}
            sources[source_name] = {
                **record,
                "graph": graph_meta,
            }

        graph["sources"] = sources
        return graph

    def _fmu_storage_dir() -> Path:
        folder = storage_subdir("datasource_files") / "fmu"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _sanitize_file_name(filename: str) -> str:
        raw = Path(str(filename or "")).name.strip()
        if not raw:
            raise HTTPException(status_code=400, detail="Missing FMU filename")
        safe = "".join(
            ch if ch.isalnum() or ch in {".", "_", "-"} else "_" for ch in raw
        )
        safe = safe.strip(" ._")
        if not safe:
            raise HTTPException(status_code=400, detail="Invalid FMU filename")
        if Path(safe).suffix.lower() != ".fmu":
            raise HTTPException(status_code=400, detail="Only .fmu files are allowed")
        return safe

    def _fmu_file_path(filename: str) -> Path:
        folder = _fmu_storage_dir().resolve()
        candidate = (folder / _sanitize_file_name(filename)).resolve()
        try:
            candidate.relative_to(folder)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid FMU path") from exc
        return candidate

    def _fmu_entry(path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "name": path.name,
            "size_bytes": stat.st_size,
            "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
            "local_path": str(path.resolve()),
        }

    def _storage_roots() -> dict[str, Path]:
        base = storage_subdir("").resolve()
        base.mkdir(parents=True, exist_ok=True)
        roots = {
            "data": base,
        }
        for item in configured_network_drives():
            drive_name = str(item.get("name") or "").strip()
            drive_path = str(item.get("path") or "").strip()
            if not drive_name or not drive_path:
                continue
            key = f"drive:{drive_name}"
            roots[key] = Path(drive_path).expanduser().resolve(strict=False)
        return roots

    def _storage_root_for_key(root_key: str) -> Path:
        key = str(root_key or "").strip()
        roots = _storage_roots()
        root = roots.get(key)
        if root is None:
            raise HTTPException(status_code=400, detail=f"Unknown storage root '{key}'")
        return root.resolve()

    def _resolve_storage_path(
        root_key: str, rel_path: str = ""
    ) -> tuple[Path, Path, str]:
        root = _storage_root_for_key(root_key)
        cleaned = str(rel_path or "").strip().replace("\\", "/").strip("/")
        target = (root / cleaned).resolve() if cleaned else root
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid storage path") from exc
        relative = (
            "" if target == root else str(target.relative_to(root)).replace("\\", "/")
        )
        return root, target, relative

    def _storage_entry(path: Path, root: Path) -> dict[str, Any]:
        stat = path.stat()
        suffix = path.suffix.lower()
        editable = (
            path.is_file()
            and suffix in _EDITABLE_TEXT_EXTENSIONS
            and stat.st_size <= _MAX_EDITABLE_FILE_BYTES
        )
        return {
            "name": path.name,
            "kind": "directory" if path.is_dir() else "file",
            "size_bytes": None if path.is_dir() else stat.st_size,
            "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
            "path": ""
            if path == root
            else str(path.relative_to(root)).replace("\\", "/"),
            "editable_text": editable,
        }

    def _resolve_storage_file(root_key: str, rel_path: str) -> tuple[Path, Path, str]:
        root, target, relative = _resolve_storage_path(root_key, rel_path)
        if relative == "":
            raise HTTPException(status_code=400, detail="Storage root is not a file")
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return root, target, relative

    def _read_text_storage_file(
        root_key: str, rel_path: str
    ) -> tuple[Path, Path, str, str]:
        root, target, relative = _resolve_storage_file(root_key, rel_path)
        if target.stat().st_size > _MAX_EDITABLE_FILE_BYTES:
            raise HTTPException(
                status_code=413, detail="File is too large to edit in browser"
            )
        if target.suffix.lower() not in _EDITABLE_TEXT_EXTENSIONS:
            raise HTTPException(
                status_code=415, detail="Only text-like files can be edited in browser"
            )
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=415, detail="File is not valid UTF-8 text"
            ) from exc
        return root, target, relative, content

    def _storage_roots_payload() -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for key, root in _storage_roots().items():
            try:
                usage = shutil.disk_usage(root)
                disk = {
                    "total_bytes": usage.total,
                    "used_bytes": usage.used,
                    "free_bytes": usage.free,
                }
            except OSError:
                disk = {
                    "total_bytes": None,
                    "used_bytes": None,
                    "free_bytes": None,
                }
            display_name = (
                key.removeprefix("drive:") if key.startswith("drive:") else key
            )
            payload.append(
                {
                    "key": key,
                    "display_name": display_name,
                    "path": str(root),
                    "disk": disk,
                }
            )
        return payload

    def _join_bridge_path(prefix: str, suffix: str = "") -> str:
        suffix = suffix.strip("/")
        if not suffix:
            return prefix.strip("/")
        return f"{prefix.strip('/')}/{suffix}"

    async def _proxy_to_service(
        request: Request, service_name: str, service_path: str = ""
    ):
        upgrade = str(request.headers.get("upgrade") or "").lower()
        connection = str(request.headers.get("connection") or "").lower()
        if upgrade == "websocket" or "upgrade" in connection:
            raise HTTPException(
                status_code=501,
                detail=(
                    "WebSocket upgrade is not supported by the HTTP "
                    "service proxy; use a direct WebSocket-capable endpoint"
                ),
            )

        services = service_map()
        target = services.get(service_name)
        if not target or not target.get("healthy"):
            raise HTTPException(
                status_code=404, detail=f"service {service_name!r} not available"
            )

        base_url = str(target["base_url"]).rstrip("/")
        url = f"{base_url}/{service_path.lstrip('/')}" if service_path else base_url
        body = await request.body()
        headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
        try:
            resp = proxy_session.request(
                method=request.method,
                url=url,
                params=request.query_params,
                data=body,
                headers=headers,
                timeout=10,
                stream=True,
            )
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        content_type = resp.headers.get("content-type", "application/json")
        if "application/json" in content_type:
            try:
                return JSONResponse(status_code=resp.status_code, content=resp.json())
            finally:
                resp.close()

        passthrough_headers = {}
        content_disposition = resp.headers.get("content-disposition")
        if content_disposition:
            passthrough_headers["content-disposition"] = content_disposition
        content_length = resp.headers.get("content-length")
        if content_length:
            passthrough_headers["content-length"] = content_length
        return StreamingResponse(
            resp.iter_content(chunk_size=64 * 1024),
            status_code=resp.status_code,
            media_type=content_type,
            headers=passthrough_headers,
            background=BackgroundTask(resp.close),
        )

    @app.get("/agent/info")
    def agent_info() -> dict[str, Any]:
        return {
            "node_id": node_id,
            "node_name": node_name,
            "services": service_map(),
        }

    @app.get("/agent/services")
    def agent_services() -> dict[str, Any]:
        return service_map()

    @app.get("/agent/summary")
    def agent_summary() -> dict[str, Any]:
        return summary_provider()

    @app.get("/agent/repo/status")
    def agent_repo_status(force: bool = False) -> dict[str, Any]:
        if update_status_provider is None:
            raise HTTPException(
                status_code=501, detail="Repo status provider is not configured"
            )
        return {
            "ok": True,
            "status": update_status_provider(bool(force)),
        }

    @app.post("/agent/repo/update")
    def agent_repo_update() -> dict[str, Any]:
        if apply_update_action is None:
            raise HTTPException(
                status_code=501, detail="Repo update action is not configured"
            )
        result = apply_update_action()
        if not bool(result.get("ok")):
            raise HTTPException(status_code=500, detail=result)
        return {
            "ok": True,
            **result,
        }

    @app.get("/parameterdb/params")
    def list_params() -> dict[str, Any]:
        return {"ok": True, "params": _wrap(lambda: _db().describe())}

    @app.get("/parameterdb/graph")
    def get_graph() -> dict[str, Any]:
        return {"ok": True, "graph": _wrap(_build_graph_payload)}

    @app.get("/parameterdb/stats")
    def get_stats() -> dict[str, Any]:
        return {"ok": True, "stats": _wrap(lambda: _db().stats())}

    @app.get("/parameterdb/snapshot-file")
    def export_snapshot() -> dict[str, Any]:
        exported = _wrap(lambda: _db().export_snapshot())
        return {"ok": True, **exported}

    @app.post("/parameterdb/snapshot-file")
    def import_snapshot(body: ImportSnapshotBody) -> dict[str, Any]:
        imported = _wrap(
            lambda: _db().import_snapshot(
                body.snapshot,
                replace_existing=body.replace_existing,
                save_to_disk=body.save_to_disk,
            )
        )
        return {"ok": True, **imported}

    @app.get("/parameterdb/param-types")
    def list_param_types() -> dict[str, Any]:
        return {"ok": True, "types": _wrap(lambda: _db().list_parameter_type_ui())}

    @app.get("/parameterdb/param-types/{parameter_type}/ui")
    def get_param_type_ui(parameter_type: str) -> dict[str, Any]:
        return {
            "ok": True,
            "ui": _wrap(lambda: _db().get_parameter_type_ui(parameter_type)),
        }

    @app.post("/parameterdb/params")
    def create_param(body: CreateParamBody) -> dict[str, Any]:
        ok = _wrap(
            lambda: _db().create_parameter(
                body.name,
                body.parameter_type,
                value=body.value,
                config=body.config,
                metadata=body.metadata,
            )
        )
        if not ok:
            raise HTTPException(
                status_code=400, detail="create_parameter returned False"
            )
        return {"ok": True}

    @app.put("/parameterdb/params/{name:path}/value")
    def set_value(name: str, body: SetValueBody) -> dict[str, Any]:
        return {"ok": bool(_wrap(lambda: _db().set_value(name, body.value)))}

    @app.put("/parameterdb/params/{name:path}/config")
    def update_config(name: str, body: UpdateConfigBody) -> dict[str, Any]:
        return {"ok": bool(_wrap(lambda: _db().update_config(name, **body.config)))}

    @app.put("/parameterdb/params/{name:path}/metadata")
    def update_metadata(name: str, body: UpdateMetadataBody) -> dict[str, Any]:
        return {"ok": bool(_wrap(lambda: _db().update_metadata(name, **body.metadata)))}

    @app.delete("/parameterdb/params/{name:path}")
    def delete_param(name: str) -> dict[str, Any]:
        return {"ok": bool(_wrap(lambda: _db().delete_parameter(name)))}

    @app.get("/parameterdb/source-types")
    def list_source_types() -> dict[str, Any]:
        return {"ok": True, "types": _wrap(lambda: _ds().list_source_types_ui())}

    @app.get("/parameterdb/source-types/{source_type}/ui")
    def get_source_type_ui(
        source_type: str, name: str | None = None, mode: str | None = None
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "ui": _wrap(
                lambda: _ds().get_source_type_ui(source_type, name=name, mode=mode)
            ),
        }

    @app.get("/parameterdb/sources")
    def list_sources() -> dict[str, Any]:
        return {"ok": True, "sources": _wrap(lambda: _ds().list_sources())}

    @app.post("/parameterdb/sources")
    def create_source(body: CreateSourceBody) -> dict[str, Any]:
        _wrap(
            lambda: _ds().create_source(body.name, body.source_type, config=body.config)
        )
        return {"ok": True}

    @app.put("/parameterdb/sources/{name}")
    def update_source(name: str, body: UpdateConfigBody) -> dict[str, Any]:
        _wrap(lambda: _ds().update_source(name, config=body.config))
        return {"ok": True}

    @app.delete("/parameterdb/sources/{name}")
    def delete_source(name: str) -> dict[str, Any]:
        _wrap(lambda: _ds().delete_source(name))
        return {"ok": True}

    @app.get("/parameterdb/fmu-files")
    def list_fmu_files() -> dict[str, Any]:
        folder = _fmu_storage_dir()
        files = [
            _fmu_entry(path)
            for path in sorted(folder.glob("*.fmu"), key=lambda item: item.name.lower())
            if path.is_file()
        ]
        return {
            "ok": True,
            "folder": str(folder.resolve()),
            "files": files,
        }

    @app.post("/parameterdb/fmu-files")
    async def upload_fmu_file(
        request: Request,
        file: UploadFile | None = File(default=None),  # noqa: B008
    ) -> dict[str, Any]:
        payload = b""
        filename = ""
        if file is not None:
            filename = file.filename or ""
            payload = await file.read()
        else:
            filename = str(request.headers.get("x-filename") or "").strip()
            payload = await request.body()

        filename = _sanitize_file_name(filename)
        target = _fmu_file_path(filename)
        if not payload:
            raise HTTPException(status_code=400, detail="Uploaded FMU is empty")
        target.write_bytes(payload)
        return {
            "ok": True,
            "folder": str(_fmu_storage_dir().resolve()),
            "file": _fmu_entry(target),
        }

    @app.delete("/parameterdb/fmu-files/{filename:path}")
    def delete_fmu_file(filename: str) -> dict[str, Any]:
        target = _fmu_file_path(filename)
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="FMU file not found")
        try:
            target.unlink()
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to delete FMU file: {exc}"
            ) from exc
        return {"ok": True}

    @app.get("/parameterdb/fmu-files/{filename:path}/download")
    def download_fmu_file(filename: str):
        target = _fmu_file_path(filename)
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="FMU file not found")
        return FileResponse(
            path=str(target),
            filename=target.name,
            media_type="application/octet-stream",
        )

    @app.get("/agent/storage/roots")
    def list_storage_roots() -> dict[str, Any]:
        return {
            "ok": True,
            "roots": _storage_roots_payload(),
        }

    @app.post("/agent/storage/list")
    def list_storage_folder(body: AgentStorageListBody) -> dict[str, Any]:
        root, folder, relative = _resolve_storage_path(body.root, body.path)
        if not folder.exists() or not folder.is_dir():
            raise HTTPException(status_code=404, detail="Storage folder not found")
        entries = [
            _storage_entry(child, root)
            for child in sorted(
                folder.iterdir(),
                key=lambda item: (not item.is_dir(), item.name.lower()),
            )
        ]
        return {
            "ok": True,
            "root": body.root,
            "root_path": str(root),
            "path": relative,
            "entries": entries,
        }

    @app.post("/agent/storage/mkdir")
    def mkdir_storage_folder(body: AgentStorageMkdirBody) -> dict[str, Any]:
        if not str(body.name or "").strip():
            raise HTTPException(status_code=400, detail="Folder name is required")
        _root, parent, _relative = _resolve_storage_path(body.root, body.path)
        if not parent.exists() or not parent.is_dir():
            raise HTTPException(status_code=404, detail="Parent folder not found")
        folder_name = Path(str(body.name).strip()).name
        if folder_name in {".", ".."} or not folder_name:
            raise HTTPException(status_code=400, detail="Invalid folder name")
        target = (parent / folder_name).resolve()
        try:
            target.relative_to(_root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid folder path") from exc
        if target.exists():
            raise HTTPException(status_code=409, detail="Folder already exists")
        target.mkdir(parents=False, exist_ok=False)
        return {"ok": True}

    @app.post("/agent/storage/move")
    def move_storage_entry(body: AgentStorageMoveBody) -> dict[str, Any]:
        root, src, _ = _resolve_storage_path(body.root, body.src_path)
        _root2, dst, _ = _resolve_storage_path(body.root, body.dst_path)
        if not src.exists():
            raise HTTPException(status_code=404, detail="Source path not found")
        if dst.exists():
            raise HTTPException(status_code=409, detail="Destination already exists")
        if not dst.parent.exists() or not dst.parent.is_dir():
            raise HTTPException(
                status_code=404, detail="Destination parent does not exist"
            )
        try:
            src.replace(dst)
        except OSError:
            shutil.move(str(src), str(dst))
        return {
            "ok": True,
            "from": ""
            if src == root
            else str(src.relative_to(root)).replace("\\", "/"),
            "to": "" if dst == root else str(dst.relative_to(root)).replace("\\", "/"),
        }

    @app.post("/agent/storage/delete")
    def delete_storage_entry(body: AgentStorageDeleteBody) -> dict[str, Any]:
        _root, target, relative = _resolve_storage_path(body.root, body.path)
        if relative == "":
            raise HTTPException(status_code=400, detail="Cannot delete storage root")
        if not target.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        if target.is_dir():
            if any(target.iterdir()) and not body.recursive:
                raise HTTPException(
                    status_code=400,
                    detail="Directory is not empty; use recursive=true to delete",
                )
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"ok": True}

    @app.post("/agent/storage/read-file")
    def read_storage_file(body: AgentStorageFileBody) -> dict[str, Any]:
        _root, target, relative, content = _read_text_storage_file(body.root, body.path)
        return {
            "ok": True,
            "root": body.root,
            "path": relative,
            "name": target.name,
            "content": content,
        }

    @app.post("/agent/storage/write-file")
    def write_storage_file(body: AgentStorageWriteFileBody) -> dict[str, Any]:
        _root, target, relative, _content = _read_text_storage_file(
            body.root, body.path
        )
        content = str(body.content)
        if target.suffix.lower() in {".yaml", ".yml"}:
            try:
                parsed = yaml.safe_load(content)
            except yaml.YAMLError as exc:
                raise HTTPException(
                    status_code=400, detail=f"Invalid YAML: {exc}"
                ) from exc
            content = yaml.safe_dump(parsed, sort_keys=False, allow_unicode=False)
        target.write_text(content, encoding="utf-8", newline="\n")
        return {
            "ok": True,
            "path": relative,
            "content": content,
        }

    @app.get("/agent/storage/download")
    def download_storage_file(root: str = Query(...), path: str = Query(...)):
        _root, target, _relative = _resolve_storage_file(root, path)
        return FileResponse(
            path=str(target),
            filename=target.name,
            media_type="application/octet-stream",
        )

    @app.post("/agent/storage/network-drive")
    def add_storage_network_drive(body: AgentStorageNetworkDriveBody) -> dict[str, Any]:
        record = add_network_drive_to_topology(body.name, body.path)
        return {
            "ok": True,
            "network_drive": record,
        }

    @app.api_route(
        "/proxy/{service_name}/{service_path:path}",
        methods=["GET", "POST", "PUT", "DELETE"],
    )
    @app.api_route("/proxy/{service_name}", methods=["GET", "POST", "PUT", "DELETE"])
    async def proxy(service_name: str, request: Request, service_path: str = ""):
        return await _proxy_to_service(request, service_name, service_path)

    @app.api_route(
        "/control/{service_path:path}", methods=["GET", "POST", "PUT", "DELETE"]
    )
    @app.api_route("/control", methods=["GET", "POST", "PUT", "DELETE"])
    async def proxy_control(request: Request, service_path: str = ""):
        return await _proxy_to_service(
            request, "control_service", _join_bridge_path("control", service_path)
        )

    @app.api_route(
        "/schedule/{service_path:path}", methods=["GET", "POST", "PUT", "DELETE"]
    )
    @app.api_route("/schedule", methods=["GET", "POST", "PUT", "DELETE"])
    async def proxy_schedule(request: Request, service_path: str = ""):
        return await _proxy_to_service(
            request, "schedule_service", _join_bridge_path("schedule", service_path)
        )

    @app.api_route(
        "/rules/{service_path:path}", methods=["GET", "POST", "PUT", "DELETE"]
    )
    @app.api_route("/rules", methods=["GET", "POST", "PUT", "DELETE"])
    async def proxy_rules(request: Request, service_path: str = ""):
        return await _proxy_to_service(
            request, "control_service", _join_bridge_path("rules", service_path)
        )

    @app.api_route(
        "/system/{service_path:path}", methods=["GET", "POST", "PUT", "DELETE"]
    )
    @app.api_route("/system", methods=["GET", "POST", "PUT", "DELETE"])
    async def proxy_system(request: Request, service_path: str = ""):
        return await _proxy_to_service(
            request, "control_service", _join_bridge_path("system", service_path)
        )

    @app.api_route("/ws/{service_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    @app.api_route("/ws", methods=["GET", "POST", "PUT", "DELETE"])
    async def proxy_ws(request: Request, service_path: str = ""):
        return await _proxy_to_service(
            request, "control_service", _join_bridge_path("ws", service_path)
        )

    @app.api_route(
        "/data/{service_path:path}", methods=["GET", "POST", "PUT", "DELETE"]
    )
    @app.api_route("/data", methods=["GET", "POST", "PUT", "DELETE"])
    async def proxy_data(request: Request, service_path: str = ""):
        return await _proxy_to_service(request, "data_service", service_path.strip("/"))

    return app


class AgentApiServer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        node_id: str,
        node_name: str,
        service_map: Callable[[], dict[str, dict[str, Any]]],
        summary_provider: Callable[[], dict[str, Any]],
        update_status_provider: Callable[[bool], dict[str, Any]] | None = None,
        apply_update_action: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._proxy_session = _build_session()
        self.app = build_agent_app(
            node_id=node_id,
            node_name=node_name,
            service_map=service_map,
            summary_provider=summary_provider,
            proxy_session=self._proxy_session,
            update_status_provider=update_status_provider,
            apply_update_action=apply_update_action,
        )
        self._server = uvicorn.Server(
            uvicorn.Config(self.app, host=self.host, port=self.port, log_level="info")
        )
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(target=self._server.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._server.should_exit = True
        self._thread.join(timeout=5)
        self._thread = None
        self._proxy_session.close()
