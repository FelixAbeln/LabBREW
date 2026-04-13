from __future__ import annotations

import asyncio
from typing import Annotated, Any

import requests
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from .models import FermenterView
from .schedule_import.parser import (
    collect_workbook_parameter_references,
    parse_schedule_workbook,
)
from .schedule_import.validator import validate_schedule_payload


def _read_json_response(
    proxy: Any,
    *,
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    data_body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    try:
        return proxy.request(
            method=method,
            url=url,
            params=params,
            json_body=json_body,
            data_body=data_body,
            headers=headers,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502, detail=f"Upstream request failed: {exc}"
        ) from exc


def _read_raw_response(
    proxy: Any,
    *,
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    data_body: bytes | None = None,
    headers: dict[str, str] | None = None,
    stream: bool = False,
):
    try:
        return proxy.request_raw(
            method=method,
            url=url,
            params=params,
            json_body=json_body,
            data_body=data_body,
            headers=headers,
            stream=stream,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502, detail=f"Upstream request failed: {exc}"
        ) from exc


def _read_best_effort(
    proxy: Any,
    *,
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    data_body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int | None, Any]:
    try:
        return proxy.request(
            method=method,
            url=url,
            params=params,
            json_body=json_body,
            data_body=data_body,
            headers=headers,
        )
    except requests.RequestException as exc:
        return None, {"ok": False, "detail": str(exc)}


def _to_view(node: Any) -> FermenterView:
    return FermenterView(
        id=node.id,
        name=node.name,
        address=node.address,
        host=node.host,
        online=node.online,
        agent_base_url=node.agent_base_url,
        services_hint=node.services_hint,
        services=node.services,
        summary=node.summary,
        last_error=node.last_error,
    )


def _build_agent_proxy_url(node: Any, suffix: str) -> str:
    suffix = suffix if suffix.startswith("/") else f"/{suffix}"
    return f"{node.agent_base_url}{suffix}"


def _build_service_proxy_url(node: Any, service_name: str, suffix: str = "") -> str:
    suffix = suffix.lstrip("/")
    service_agents = getattr(node, "service_agents", {}) or {}
    agent_base_url = service_agents.get(service_name) or node.agent_base_url
    url = f"{agent_base_url}/proxy/{service_name}"
    if suffix:
        url += f"/{suffix}"
    return url


def _get_service_node(registry: Any, fermenter_id: str, service_name: str):
    if hasattr(registry, "get_node_for_service"):
        return registry.get_node_for_service(fermenter_id, service_name)
    return registry.get_node(fermenter_id)


def _get_fermenter_nodes(registry: Any, fermenter_id: str) -> list[Any]:
    if hasattr(registry, "snapshot"):
        return [
            node
            for node in registry.snapshot()
            if str(getattr(node, "id", "")) == str(fermenter_id)
        ]
    node = registry.get_node(fermenter_id)
    return [node] if node is not None else []


def _find_node_by_agent_base_url(registry: Any, fermenter_id: str, agent_base_url: str):
    target = str(agent_base_url or "").strip().rstrip("/")
    if not target:
        return None
    for node in _get_fermenter_nodes(registry, fermenter_id):
        base = str(getattr(node, "agent_base_url", "") or "").strip().rstrip("/")
        if base and base == target:
            return node
    return None


def _get_datasource_node(registry: Any, fermenter_id: str):
    # Prefer datasource-service nodes in split topologies so uploaded
    # FMUs land where datasource runtimes execute.
    for service_name in (
        "ParameterDB_DataSource",
        "parameterdb_datasource",
        "parameterdb",
    ):
        node = _get_service_node(registry, fermenter_id, service_name)
        if node is not None:
            return node
    return registry.get_node(fermenter_id)


def _get_available_backend_parameters(
    proxy: Any, node: Any
) -> tuple[set[str] | None, dict[str, Any] | None]:
    status_code, payload = _read_best_effort(
        proxy,
        method="GET",
        url=_build_service_proxy_url(node, "control_service", "system/snapshot"),
    )
    if status_code is None:
        return None, {
            "level": "error",
            "code": "BACKEND_UNREACHABLE",
            "path": "backend.control_service.system/snapshot",
            "message": "Could not reach control backend for parameter validation",
            "detail": payload.get("detail")
            if isinstance(payload, dict)
            else str(payload),
        }
    if not (200 <= status_code < 300) or not isinstance(payload, dict):
        return None, {
            "level": "error",
            "code": "BACKEND_VALIDATION_REQUEST_FAILED",
            "path": "backend.control_service.system/snapshot",
            "message": "Control backend rejected parameter validation request",
            "status_code": status_code,
            "detail": payload,
        }

    values = payload.get("values")
    if not isinstance(values, dict):
        return None, {
            "level": "error",
            "code": "BACKEND_SNAPSHOT_INVALID",
            "path": "backend.control_service.system/snapshot.values",
            "message": "Control backend snapshot does not contain a values object",
        }

    return {str(name) for name in values}, None


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"ok": "true"}

    @router.get("/fermenters", response_model=list[FermenterView])
    def list_fermenters(request: Request):
        registry = request.app.state.registry
        return [_to_view(node) for node in registry.snapshot()]

    @router.get("/fermenters/{fermenter_id}", response_model=FermenterView)
    def get_fermenter(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")
        return _to_view(node)

    @router.get("/fermenters/{fermenter_id}/agent/info")
    def get_agent_info(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")
        status_code, payload = _read_json_response(
            proxy, method="GET", url=_build_agent_proxy_url(node, "/agent/info")
        )
        return JSONResponse(status_code=status_code, content=payload)

    @router.get("/fermenters/{fermenter_id}/agent/services")
    def get_agent_services(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")
        status_code, payload = _read_json_response(
            proxy, method="GET", url=_build_agent_proxy_url(node, "/agent/services")
        )
        return JSONResponse(status_code=status_code, content=payload)

    @router.get("/fermenters/{fermenter_id}/summary")
    def get_summary(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")
        status_code, payload = _read_json_response(
            proxy, method="GET", url=_build_agent_proxy_url(node, "/agent/summary")
        )
        return JSONResponse(status_code=status_code, content=payload)

    @router.get("/fermenters/{fermenter_id}/agents/storage")
    def list_agent_storage(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        nodes = _get_fermenter_nodes(registry, fermenter_id)
        if not nodes:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        agents: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for node in nodes:
            base = str(getattr(node, "agent_base_url", "") or "").strip()
            if not base:
                continue
            key = base.rstrip("/").lower()
            if key in seen_urls:
                continue
            seen_urls.add(key)

            status_code, payload = _read_best_effort(
                proxy,
                method="GET",
                url=_build_agent_proxy_url(node, "/agent/storage/roots"),
            )
            healthy = (
                status_code is not None
                and 200 <= status_code < 300
                and isinstance(payload, dict)
            )
            agents.append(
                {
                    "node_id": getattr(node, "id", ""),
                    "node_name": getattr(node, "name", ""),
                    "agent_base_url": base,
                    "services_hint": list(getattr(node, "services_hint", []) or []),
                    "storage": payload if healthy else None,
                    "reachable": bool(healthy),
                    "error": None
                    if healthy
                    else (
                        payload.get("detail")
                        if isinstance(payload, dict)
                        else str(payload)
                    ),
                }
            )

        return {
            "ok": True,
            "fermenter_id": fermenter_id,
            "agents": agents,
        }

    async def _proxy_agent_storage_action(
        request: Request, fermenter_id: str, action: str
    ):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Body must be a JSON object")
        agent_base_url = str(body.get("agent_base_url") or "").strip()
        node = _find_node_by_agent_base_url(registry, fermenter_id, agent_base_url)
        if node is None:
            raise HTTPException(
                status_code=404, detail="Target agent not found for fermenter"
            )

        forwarded = {k: v for k, v in body.items() if k != "agent_base_url"}
        status_code, payload = await asyncio.to_thread(
            _read_json_response,
            proxy,
            method="POST",
            url=_build_agent_proxy_url(node, f"/agent/storage/{action}"),
            json_body=forwarded,
        )
        return JSONResponse(status_code=status_code, content=payload)

    @router.post("/fermenters/{fermenter_id}/agents/storage/list")
    async def list_agent_storage_entries(fermenter_id: str, request: Request):
        return await _proxy_agent_storage_action(request, fermenter_id, "list")

    @router.post("/fermenters/{fermenter_id}/agents/storage/mkdir")
    async def mkdir_agent_storage(fermenter_id: str, request: Request):
        return await _proxy_agent_storage_action(request, fermenter_id, "mkdir")

    @router.post("/fermenters/{fermenter_id}/agents/storage/move")
    async def move_agent_storage(fermenter_id: str, request: Request):
        return await _proxy_agent_storage_action(request, fermenter_id, "move")

    @router.post("/fermenters/{fermenter_id}/agents/storage/delete")
    async def delete_agent_storage(fermenter_id: str, request: Request):
        return await _proxy_agent_storage_action(request, fermenter_id, "delete")

    @router.post("/fermenters/{fermenter_id}/agents/storage/read-file")
    async def read_agent_storage_file(fermenter_id: str, request: Request):
        return await _proxy_agent_storage_action(request, fermenter_id, "read-file")

    @router.post("/fermenters/{fermenter_id}/agents/storage/write-file")
    async def write_agent_storage_file(fermenter_id: str, request: Request):
        return await _proxy_agent_storage_action(request, fermenter_id, "write-file")

    @router.get("/fermenters/{fermenter_id}/agents/storage/download")
    def download_agent_storage_file(
        fermenter_id: str,
        request: Request,
        agent_base_url: str,
        root: str,
        path: str,
    ):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = _find_node_by_agent_base_url(registry, fermenter_id, agent_base_url)
        if node is None:
            raise HTTPException(
                status_code=404, detail="Target agent not found for fermenter"
            )

        response = _read_raw_response(
            proxy,
            method="GET",
            url=_build_agent_proxy_url(node, "/agent/storage/download"),
            params={"root": root, "path": path},
            stream=True,
        )
        content_type = response.headers.get("content-type", "application/octet-stream")
        passthrough_headers = {}
        content_disposition = response.headers.get("content-disposition")
        if content_disposition:
            passthrough_headers["content-disposition"] = content_disposition
        content_length = response.headers.get("content-length")
        if content_length:
            passthrough_headers["content-length"] = content_length
        return StreamingResponse(
            response.iter_content(chunk_size=64 * 1024),
            status_code=response.status_code,
            media_type=content_type,
            headers=passthrough_headers,
            background=BackgroundTask(response.close),
        )

    @router.post("/fermenters/{fermenter_id}/agents/storage/network-drive")
    async def add_network_drive_to_agents(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Body must be a JSON object")

        name = str(body.get("name") or "").strip()
        path_text = str(body.get("path") or "").strip()
        if not name or not path_text:
            raise HTTPException(
                status_code=400, detail="Both name and path are required"
            )

        nodes = _get_fermenter_nodes(registry, fermenter_id)
        if not nodes:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        results: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        overall_ok = True
        for node in nodes:
            base = str(getattr(node, "agent_base_url", "") or "").strip()
            if not base:
                continue
            key = base.rstrip("/").lower()
            if key in seen_urls:
                continue
            seen_urls.add(key)
            status_code, payload = _read_best_effort(
                proxy,
                method="POST",
                url=_build_agent_proxy_url(node, "/agent/storage/network-drive"),
                json_body={"name": name, "path": path_text},
            )
            ok = (
                status_code is not None
                and 200 <= status_code < 300
                and isinstance(payload, dict)
                and bool(payload.get("ok", True))
            )
            overall_ok = overall_ok and ok
            results.append(
                {
                    "agent_base_url": base,
                    "node_id": getattr(node, "id", ""),
                    "node_name": getattr(node, "name", ""),
                    "ok": ok,
                    "status_code": status_code,
                    "result": payload,
                }
            )

        status = 200 if overall_ok else 207
        return JSONResponse(
            status_code=status,
            content={
                "ok": overall_ok,
                "name": name,
                "path": path_text,
                "results": results,
            },
        )

    @router.get("/fermenters/{fermenter_id}/agent/repo/status")
    def get_agent_repo_status(fermenter_id: str, request: Request, force: bool = False):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")
        status_code, payload = _read_json_response(
            proxy,
            method="GET",
            url=_build_agent_proxy_url(node, "/agent/repo/status"),
            params={"force": "1" if force else "0"},
        )
        return JSONResponse(status_code=status_code, content=payload)

    @router.post("/fermenters/{fermenter_id}/agent/repo/update")
    def post_agent_repo_update(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")
        status_code, payload = _read_json_response(
            proxy,
            method="POST",
            url=_build_agent_proxy_url(node, "/agent/repo/update"),
        )
        return JSONResponse(status_code=status_code, content=payload)

    async def _proxy_via_agent(
        request: Request, fermenter_id: str, service_name: str, service_path: str = ""
    ):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = _get_service_node(registry, fermenter_id, service_name)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")
        raw_body = b""
        headers = None
        if request.method in {"POST", "PUT", "PATCH"}:
            raw_body = await request.body()
            headers = {
                key: value
                for key, value in request.headers.items()
                if key.lower() in {"content-type", "accept"}
            }
        status_code, payload = await asyncio.to_thread(
            _read_json_response,
            proxy,
            method=request.method,
            url=_build_service_proxy_url(node, service_name, service_path),
            params=dict(request.query_params),
            data_body=raw_body if raw_body else None,
            headers=headers,
        )
        return JSONResponse(status_code=status_code, content=payload)

    async def _proxy_agent_path(request: Request, fermenter_id: str, agent_path: str):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")
        raw_body = b""
        headers = None
        if request.method in {"POST", "PUT", "PATCH"}:
            raw_body = await request.body()
            headers = {
                key: value
                for key, value in request.headers.items()
                if key.lower() in {"content-type", "accept"}
            }
        status_code, payload = await asyncio.to_thread(
            _read_json_response,
            proxy,
            method=request.method,
            url=_build_agent_proxy_url(node, f"/parameterdb/{agent_path.lstrip('/')}"),
            params=dict(request.query_params),
            data_body=raw_body if raw_body else None,
            headers=headers,
        )
        return JSONResponse(status_code=status_code, content=payload)

    @router.put("/fermenters/{fermenter_id}/schedule/validate-import")
    async def validate_schedule_import(
        fermenter_id: str, request: Request, file: Annotated[UploadFile, File(...)]
    ):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        file_bytes = await file.read()
        payload = parse_schedule_workbook(
            file_bytes, filename=file.filename or "schedule.xlsx"
        )
        refs = collect_workbook_parameter_references(file_bytes)
        available_parameters, backend_issue = _get_available_backend_parameters(
            proxy, node
        )
        result = validate_schedule_payload(
            payload,
            available_parameters=available_parameters,
            extra_parameter_references=refs,
        )
        if backend_issue is not None:
            result["valid"] = False
            result["issues"].append(backend_issue)
            result["errors"].append(backend_issue["message"])
            result["error_codes"] = sorted(
                {*result.get("error_codes", []), str(backend_issue["code"])}
            )

        return {
            "ok": result["valid"],
            "valid": result["valid"],
            "errors": result["errors"],
            "warnings": result["warnings"],
            "error_codes": result.get("error_codes", []),
            "warning_codes": result.get("warning_codes", []),
            "issues": result.get("issues", []),
            "schedule": payload,
            "summary": {
                "setup_step_count": len(payload.get("setup_steps", [])),
                "plan_step_count": len(payload.get("plan_steps", [])),
            },
        }

    @router.put("/fermenters/{fermenter_id}/schedule/import")
    async def import_schedule(
        fermenter_id: str, request: Request, file: Annotated[UploadFile, File(...)]
    ):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        file_bytes = await file.read()
        payload = parse_schedule_workbook(
            file_bytes, filename=file.filename or "schedule.xlsx"
        )
        refs = collect_workbook_parameter_references(file_bytes)
        available_parameters, backend_issue = _get_available_backend_parameters(
            proxy, node
        )
        result = validate_schedule_payload(
            payload,
            available_parameters=available_parameters,
            extra_parameter_references=refs,
        )
        if backend_issue is not None:
            result["valid"] = False
            result["issues"].append(backend_issue)
            result["errors"].append(backend_issue["message"])
            result["error_codes"] = sorted(
                {*result.get("error_codes", []), str(backend_issue["code"])}
            )

        if not result["valid"]:
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "valid": False,
                    "errors": result["errors"],
                    "warnings": result["warnings"],
                    "error_codes": result.get("error_codes", []),
                    "warning_codes": result.get("warning_codes", []),
                    "issues": result.get("issues", []),
                    "schedule": payload,
                },
            )

        status_code, forwarded = _read_json_response(
            proxy,
            method="PUT",
            url=_build_service_proxy_url(node, "schedule_service", "schedule"),
            json_body=payload,
        )
        return JSONResponse(
            status_code=status_code,
            content={
                "ok": 200 <= status_code < 300,
                "valid": True,
                "errors": [],
                "warnings": result["warnings"],
                "error_codes": [],
                "warning_codes": result.get("warning_codes", []),
                "issues": [
                    item
                    for item in result.get("issues", [])
                    if item.get("level") == "warning"
                ],
                "schedule": payload,
                "forwarded": forwarded,
            },
        )

    @router.get("/fermenters/{fermenter_id}/dashboard")
    def get_dashboard(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        status_code, schedule_status = _read_best_effort(
            proxy,
            method="GET",
            url=_build_service_proxy_url(node, "schedule_service", "schedule/status"),
        )
        schedule = (
            schedule_status
            if status_code
            and 200 <= status_code < 300
            and isinstance(schedule_status, dict)
            else None
        )

        schedule_definition: Any = None
        status_code, schedule_payload = _read_best_effort(
            proxy,
            method="GET",
            url=_build_service_proxy_url(node, "schedule_service", "schedule"),
        )
        if (
            status_code
            and 200 <= status_code < 300
            and isinstance(schedule_payload, dict)
        ):
            schedule_definition = schedule_payload.get("schedule")

        owned_target_values: list[dict[str, Any]] = []
        for target in (
            schedule.get("owned_targets", []) if isinstance(schedule, dict) else []
        ):
            target_status, target_payload = _read_best_effort(
                proxy,
                method="GET",
                url=_build_service_proxy_url(
                    node, "control_service", f"control/read/{target}"
                ),
            )
            if (
                target_status
                and 200 <= target_status < 300
                and isinstance(target_payload, dict)
            ):
                owned_target_values.append(
                    {
                        "target": target,
                        "ok": bool(target_payload.get("ok")),
                        "value": target_payload.get("value", "-"),
                        "owner": target_payload.get("current_owner"),
                    }
                )
            else:
                detail = (
                    target_payload.get("detail")
                    if isinstance(target_payload, dict)
                    else None
                )
                owned_target_values.append(
                    {
                        "target": target,
                        "ok": False,
                        "value": "read failed",
                        "owner": None,
                        "detail": detail,
                    }
                )

        return {
            "fermenter": _to_view(node).model_dump(),
            "schedule": schedule,
            "schedule_definition": schedule_definition,
            "owned_target_values": owned_target_values,
        }

    @router.get("/fermenters/{fermenter_id}/datasource-files/fmu")
    def list_datasource_fmu_files(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = _get_datasource_node(registry, fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")
        status_code, payload = _read_json_response(
            proxy,
            method="GET",
            url=_build_agent_proxy_url(node, "/parameterdb/fmu-files"),
        )
        return JSONResponse(status_code=status_code, content=payload)

    @router.post("/fermenters/{fermenter_id}/datasource-files/fmu")
    async def upload_datasource_fmu_file(
        fermenter_id: str, request: Request, file: Annotated[UploadFile, File(...)]
    ):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = _get_datasource_node(registry, fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Uploaded FMU is empty")

        status_code, payload = _read_json_response(
            proxy,
            method="POST",
            url=_build_agent_proxy_url(node, "/parameterdb/fmu-files"),
            data_body=file_bytes,
            headers={
                "content-type": file.content_type or "application/octet-stream",
                "x-filename": file.filename or "upload.fmu",
            },
        )
        return JSONResponse(status_code=status_code, content=payload)

    @router.delete("/fermenters/{fermenter_id}/datasource-files/fmu/{filename:path}")
    def delete_datasource_fmu_file(fermenter_id: str, filename: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = _get_datasource_node(registry, fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        status_code, payload = _read_json_response(
            proxy,
            method="DELETE",
            url=_build_agent_proxy_url(node, f"/parameterdb/fmu-files/{filename}"),
        )
        return JSONResponse(status_code=status_code, content=payload)

    @router.get(
        "/fermenters/{fermenter_id}/datasource-files/fmu/{filename:path}/download"
    )
    def download_datasource_fmu_file(
        fermenter_id: str, filename: str, request: Request
    ):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = _get_datasource_node(registry, fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        response = _read_raw_response(
            proxy,
            method="GET",
            url=_build_agent_proxy_url(
                node, f"/parameterdb/fmu-files/{filename}/download"
            ),
            params=dict(request.query_params),
            stream=True,
        )
        content_type = response.headers.get("content-type", "application/octet-stream")
        passthrough_headers = {}
        content_disposition = response.headers.get("content-disposition")
        if content_disposition:
            passthrough_headers["content-disposition"] = content_disposition
        content_length = response.headers.get("content-length")
        if content_length:
            passthrough_headers["content-length"] = content_length
        return StreamingResponse(
            response.iter_content(chunk_size=64 * 1024),
            status_code=response.status_code,
            media_type=content_type,
            headers=passthrough_headers,
            background=BackgroundTask(response.close),
        )

    @router.api_route(
        "/fermenters/{fermenter_id}/services/{service_name}/{service_path:path}",
        methods=["GET", "POST", "PUT", "DELETE"],
    )
    @router.api_route(
        "/fermenters/{fermenter_id}/services/{service_name}",
        methods=["GET", "POST", "PUT", "DELETE"],
    )
    async def proxy_service(
        fermenter_id: str, service_name: str, request: Request, service_path: str = ""
    ):
        return await _proxy_via_agent(request, fermenter_id, service_name, service_path)

    @router.api_route(
        "/fermenters/{fermenter_id}/schedule/{service_path:path}",
        methods=["GET", "POST", "PUT", "DELETE"],
    )
    @router.api_route(
        "/fermenters/{fermenter_id}/schedule", methods=["GET", "POST", "PUT", "DELETE"]
    )
    async def proxy_schedule(
        fermenter_id: str, request: Request, service_path: str = ""
    ):
        return await _proxy_via_agent(
            request,
            fermenter_id,
            "schedule_service",
            f"schedule/{service_path}".rstrip("/"),
        )

    @router.api_route(
        "/fermenters/{fermenter_id}/control/{service_path:path}",
        methods=["GET", "POST", "PUT", "DELETE"],
    )
    @router.api_route(
        "/fermenters/{fermenter_id}/control", methods=["GET", "POST", "PUT", "DELETE"]
    )
    async def proxy_control(
        fermenter_id: str, request: Request, service_path: str = ""
    ):
        return await _proxy_via_agent(
            request,
            fermenter_id,
            "control_service",
            f"control/{service_path}".rstrip("/"),
        )

    @router.api_route(
        "/fermenters/{fermenter_id}/rules/{service_path:path}",
        methods=["GET", "POST", "PUT", "DELETE"],
    )
    @router.api_route(
        "/fermenters/{fermenter_id}/rules", methods=["GET", "POST", "PUT", "DELETE"]
    )
    async def proxy_rules(fermenter_id: str, request: Request, service_path: str = ""):
        return await _proxy_via_agent(
            request,
            fermenter_id,
            "control_service",
            f"rules/{service_path}".rstrip("/"),
        )

    @router.api_route(
        "/fermenters/{fermenter_id}/system/{service_path:path}",
        methods=["GET", "POST", "PUT", "DELETE"],
    )
    @router.api_route(
        "/fermenters/{fermenter_id}/system", methods=["GET", "POST", "PUT", "DELETE"]
    )
    async def proxy_system(fermenter_id: str, request: Request, service_path: str = ""):
        return await _proxy_via_agent(
            request,
            fermenter_id,
            "control_service",
            f"system/{service_path}".rstrip("/"),
        )

    @router.get("/fermenters/{fermenter_id}/data/archives/download/{archive_name}")
    def download_data_archive(fermenter_id: str, archive_name: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = _get_service_node(registry, fermenter_id, "data_service")
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        response = _read_raw_response(
            proxy,
            method="GET",
            url=_build_service_proxy_url(
                node, "data_service", f"archives/download/{archive_name}"
            ),
            params=dict(request.query_params),
            stream=True,
        )
        content_type = response.headers.get("content-type", "application/octet-stream")
        passthrough_headers = {}
        content_disposition = response.headers.get("content-disposition")
        if content_disposition:
            passthrough_headers["content-disposition"] = content_disposition
        content_length = response.headers.get("content-length")
        if content_length:
            passthrough_headers["content-length"] = content_length
        return StreamingResponse(
            response.iter_content(chunk_size=64 * 1024),
            status_code=response.status_code,
            media_type=content_type,
            headers=passthrough_headers,
            background=BackgroundTask(response.close),
        )

    @router.api_route(
        "/fermenters/{fermenter_id}/data/{service_path:path}",
        methods=["GET", "POST", "PUT", "DELETE"],
    )
    @router.api_route(
        "/fermenters/{fermenter_id}/data", methods=["GET", "POST", "PUT", "DELETE"]
    )
    async def proxy_data(fermenter_id: str, request: Request, service_path: str = ""):
        return await _proxy_via_agent(
            request, fermenter_id, "data_service", service_path.rstrip("/")
        )

    @router.api_route(
        "/fermenters/{fermenter_id}/ws/{service_path:path}",
        methods=["GET", "POST", "PUT", "DELETE"],
    )
    @router.api_route(
        "/fermenters/{fermenter_id}/ws", methods=["GET", "POST", "PUT", "DELETE"]
    )
    async def proxy_ws(fermenter_id: str, request: Request, service_path: str = ""):
        return await _proxy_via_agent(
            request, fermenter_id, "control_service", f"ws/{service_path}".rstrip("/")
        )

    @router.api_route(
        "/fermenters/{fermenter_id}/parameterdb/{service_path:path}",
        methods=["GET", "POST", "PUT", "DELETE"],
    )
    @router.api_route(
        "/fermenters/{fermenter_id}/parameterdb",
        methods=["GET", "POST", "PUT", "DELETE"],
    )
    async def proxy_parameterdb(
        fermenter_id: str, request: Request, service_path: str = ""
    ):
        return await _proxy_agent_path(request, fermenter_id, service_path)

    return router
