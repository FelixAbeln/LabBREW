from __future__ import annotations

import asyncio
import base64
import io
import json
import mimetypes
import threading
import zipfile

import msgpack
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import requests
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from Services._shared.json_persistence import atomic_write_json
from Services._shared.storage_paths import storage_path
from BrewSupervisor.api.schedule_import.parser import parse_schedule_workbook

from .models import FermenterView


def _scenario_package_repo_dir() -> Path:
    repo_dir = Path(storage_path("scenario_packages"))
    repo_dir.mkdir(parents=True, exist_ok=True)
    return repo_dir


def _scenario_repo_index_path() -> Path:
    return _scenario_package_repo_dir() / "repository_index.json"


def _load_scenario_repo_index() -> dict[str, Any]:
    index_path = _scenario_repo_index_path()
    if not index_path.exists() or not index_path.is_file():
        return {"packages": {}}
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return {"packages": {}}
    if not isinstance(payload, dict):
        return {"packages": {}}
    packages = payload.get("packages")
    if not isinstance(packages, dict):
        payload["packages"] = {}
    return payload


def _save_scenario_repo_index(index_payload: dict[str, Any]) -> None:
    payload = dict(index_payload or {})
    packages = payload.get("packages")
    if not isinstance(packages, dict):
        payload["packages"] = {}
    atomic_write_json(_scenario_repo_index_path(), payload)


def _read_excel_runner_source() -> str:
    root_dir = Path(__file__).resolve().parents[2]
    runner_path = root_dir / "Other" / "Builders" / "demo_sources" / "excel_program_runner.py"
    return runner_path.read_text(encoding="utf-8")


def _read_excel_conversion_script_source() -> str:
    root_dir = Path(__file__).resolve().parents[2]
    script_path = root_dir / "Other" / "Builders" / "convert_excel_to_scenario_package.py"
    return script_path.read_text(encoding="utf-8")


def _default_editor_spec_payload() -> dict[str, Any]:
    return {
        "type": "labbrew.editor-spec",
        "version": "1.0",
        "sections": [
            {
                "id": "identity",
                "title": "Identity",
                "fields": ["id", "name", "version", "description"],
            },
            {
                "id": "metadata",
                "title": "Metadata",
                "fields": ["metadata"],
            },
        ],
        "file_upload_actions": [
            {
                "id": "replace_excel",
                "label": "Replace Excel source",
                "description": "Upload a new Excel workbook to rebuild this package.",
                "accept": ".xlsx",
                "endpoint": "repository/convert-excel",
                "query": {
                    "filename": "${package.id}.lbpkg",
                    "import_now": "true",
                },
            }
        ],
        "repository_save": {
            "filename_template": "${package.id}.lbpkg",
            "tags_path": "metadata.tags",
            "version_notes_path": "metadata.version_notes",
            "notes_path": "metadata.notes",
        },
    }


def _default_validation_payload() -> dict[str, Any]:
    return {
        "type": "labbrew.validation-spec",
        "version": "1.0",
        "required_fields": [
            "id",
            "name",
            "runner",
            "interface",
            "validation",
            "editor_spec",
            "endpoint_code",
            "artifacts",
        ],
        "rules": [
            {
                "code": "entrypoint_present",
                "message": "endpoint_code.entrypoint must exist in package artifacts",
            },
            {
                "code": "program_present",
                "message": "data/program.json must be included in package artifacts",
            },
        ],
    }


def _build_package_payload_from_program(
    *,
    package_id: str,
    package_name: str,
    version: str,
    description: str,
    tags: list[str],
    version_notes: str,
    source: str,
    program_payload: dict[str, Any],
    source_workbook_bytes: bytes | None = None,
    source_workbook_name: str | None = None,
) -> dict[str, Any]:
    entrypoint_artifact = "bin/excel_program_runner.py"
    program_artifact = "data/program.json"
    validation_artifact = "validation/validation.json"
    editor_spec_artifact = "editor/spec.json"
    converter_script_artifact = "tools/convert_excel_to_scenario_package.py"

    runner_source = _read_excel_runner_source()
    program_json = json.dumps(program_payload, ensure_ascii=False, indent=2)
    validation_json = json.dumps(_default_validation_payload(), ensure_ascii=False, indent=2)
    editor_spec_json = json.dumps(_default_editor_spec_payload(), ensure_ascii=False, indent=2)

    artifacts = [
        {
            "path": entrypoint_artifact,
            "encoding": "base64",
            "content_b64": base64.b64encode(runner_source.encode("utf-8")).decode("ascii"),
            "size": len(runner_source.encode("utf-8")),
            "media_type": "text/x-python",
        },
        {
            "path": program_artifact,
            "encoding": "base64",
            "content_b64": base64.b64encode(program_json.encode("utf-8")).decode("ascii"),
            "size": len(program_json.encode("utf-8")),
            "media_type": "application/json",
        },
        {
            "path": validation_artifact,
            "encoding": "base64",
            "content_b64": base64.b64encode(validation_json.encode("utf-8")).decode("ascii"),
            "size": len(validation_json.encode("utf-8")),
            "media_type": "application/json",
        },
        {
            "path": editor_spec_artifact,
            "encoding": "base64",
            "content_b64": base64.b64encode(editor_spec_json.encode("utf-8")).decode("ascii"),
            "size": len(editor_spec_json.encode("utf-8")),
            "media_type": "application/json",
        },
    ]

    source_artifact_path = None
    converter_script_artifact_path = None
    if source_workbook_bytes:
        workbook_name = Path(str(source_workbook_name or "workbook.xlsx")).name or "workbook.xlsx"
        source_artifact_path = f"source/{workbook_name}"
        artifacts.append(
            {
                "path": source_artifact_path,
                "encoding": "base64",
                "content_b64": base64.b64encode(source_workbook_bytes).decode("ascii"),
                "size": len(source_workbook_bytes),
                "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        )

        conversion_manifest = {
            "type": "labbrew.excel-conversion",
            "version": "1.0",
            "source_workbook_artifact": source_artifact_path,
            "parser": "BrewSupervisor.api.schedule_import.parser.parse_schedule_workbook",
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        conversion_manifest_json = json.dumps(conversion_manifest, ensure_ascii=False, indent=2)
        artifacts.append(
            {
                "path": "source/conversion_manifest.json",
                "encoding": "base64",
                "content_b64": base64.b64encode(conversion_manifest_json.encode("utf-8")).decode("ascii"),
                "size": len(conversion_manifest_json.encode("utf-8")),
                "media_type": "application/json",
            }
        )

        converter_script_source = _read_excel_conversion_script_source()
        converter_script_artifact_path = converter_script_artifact
        artifacts.append(
            {
                "path": converter_script_artifact_path,
                "encoding": "base64",
                "content_b64": base64.b64encode(converter_script_source.encode("utf-8")).decode("ascii"),
                "size": len(converter_script_source.encode("utf-8")),
                "media_type": "text/x-python",
            }
        )

        conversion_manifest["converter_script_artifact"] = converter_script_artifact_path
        conversion_manifest_json = json.dumps(conversion_manifest, ensure_ascii=False, indent=2)
        artifacts[-2] = {
            "path": "source/conversion_manifest.json",
            "encoding": "base64",
            "content_b64": base64.b64encode(conversion_manifest_json.encode("utf-8")).decode("ascii"),
            "size": len(conversion_manifest_json.encode("utf-8")),
            "media_type": "application/json",
        }

    return {
        "id": package_id,
        "name": package_name,
        "version": version,
        "description": description,
        "interface": {
            "kind": "labbrew.scenario-package",
            "version": "1.0",
            "status_endpoint": "/scenario/run/status",
            "run_endpoints": {
                "start": "/scenario/run/start",
                "pause": "/scenario/run/pause",
                "resume": "/scenario/run/resume",
                "stop": "/scenario/run/stop",
                "next": "/scenario/run/next",
                "previous": "/scenario/run/previous",
            },
        },
        "validation": {
            "artifact": validation_artifact,
            "required_fields": _default_validation_payload()["required_fields"],
        },
        "editor_spec": {
            "artifact": editor_spec_artifact,
            "version": "1.0",
        },
        "endpoint_code": {
            "language": "python",
            "entrypoint": entrypoint_artifact,
            "interface_contract": "labbrew.scenario-package@1.0",
        },
        "runner": {
            "kind": "scripted",
            "entrypoint": "scripted.run",
            "config": {},
        },
        "program": program_payload,
        "artifacts": artifacts,
        "metadata": {
            "tags": tags,
            "version_notes": version_notes,
            "packaging": "self-contained",
            "import_source": source,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source_workbook_artifact": source_artifact_path,
            "converter_script_artifact": converter_script_artifact_path,
        },
    }


def _safe_scenario_repo_filename(filename: str, *, default_name: str = "package") -> str:
    raw = Path(str(filename or "").strip()).name
    if not raw:
        raw = default_name
    if not raw:
        return ""
    if not raw.lower().endswith(".lbpkg"):
        raw = f"{raw}.lbpkg"
    return raw


def _build_scenario_package_archive_bytes(package_payload: dict[str, Any]) -> bytes:
    manifest = dict(package_payload or {})
    artifacts = list(manifest.pop("artifacts", []) or [])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("scenario.package.msgpack", msgpack.packb(manifest, use_bin_type=True))
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            content_b64 = str(item.get("content_b64") or "").strip()
            if not path or not content_b64:
                continue
            try:
                archive.writestr(path, base64.b64decode(content_b64))
            except Exception:
                continue
    return buf.getvalue()


def _normalize_to_self_contained_package(package_payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    payload = dict(package_payload or {})

    package_id = str(payload.get("id") or payload.get("name") or "scenario-package").strip() or "scenario-package"
    package_name = str(payload.get("name") or package_id).strip() or package_id
    package_version = str(payload.get("version") or "0.1.0").strip() or "0.1.0"
    package_description = str(payload.get("description") or "")

    interface_payload = payload.get("interface")
    if not isinstance(interface_payload, dict):
        interface_payload = {
            "kind": "labbrew.scenario-package",
            "version": "1.0",
        }

    endpoint_code = payload.get("endpoint_code")
    if not isinstance(endpoint_code, dict):
        endpoint_code = {}
    entrypoint = str(endpoint_code.get("entrypoint") or "bin/excel_program_runner.py").strip() or "bin/excel_program_runner.py"

    runner_payload = payload.get("runner")
    if not isinstance(runner_payload, dict):
        runner_payload = {"kind": "scripted", "entrypoint": "scripted.run", "config": {}}

    program_payload = payload.get("program")
    if not isinstance(program_payload, dict):
        program_payload = {
            "setup_steps": [],
            "plan_steps": [],
            "measurement_config": {
                "hz": 10,
                "output_format": "parquet",
                "output_dir": "data/measurements",
            },
        }

    existing_artifacts = payload.get("artifacts")
    artifacts_by_path: dict[str, dict[str, Any]] = {}
    if isinstance(existing_artifacts, list):
        for item in existing_artifacts:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            content_b64 = str(item.get("content_b64") or "").strip()
            if not path or not content_b64:
                continue
            artifacts_by_path[path] = dict(item)

    def _put_artifact(path: str, text_payload: str, media_type: str) -> None:
        raw = text_payload.encode("utf-8")
        artifacts_by_path[path] = {
            "path": path,
            "media_type": media_type,
            "encoding": "base64",
            "content_b64": base64.b64encode(raw).decode("ascii"),
            "size": len(raw),
        }

    validation_payload = payload.get("validation")
    if not isinstance(validation_payload, dict):
        validation_payload = {}
    validation_artifact = str(validation_payload.get("artifact") or "validation/validation.json").strip() or "validation/validation.json"

    editor_spec_payload = payload.get("editor_spec")
    if not isinstance(editor_spec_payload, dict):
        editor_spec_payload = {}
    editor_spec_artifact = str(editor_spec_payload.get("artifact") or editor_spec_payload.get("schema_artifact") or "editor/spec.json").strip() or "editor/spec.json"

    if entrypoint not in artifacts_by_path:
        _put_artifact(entrypoint, _read_excel_runner_source(), "text/x-python")
    if "data/program.json" not in artifacts_by_path:
        _put_artifact("data/program.json", json.dumps(program_payload, ensure_ascii=False, indent=2), "application/json")
    if validation_artifact not in artifacts_by_path:
        _put_artifact(validation_artifact, json.dumps(_default_validation_payload(), ensure_ascii=False, indent=2), "application/json")
    if editor_spec_artifact not in artifacts_by_path:
        _put_artifact(editor_spec_artifact, json.dumps(_default_editor_spec_payload(), ensure_ascii=False, indent=2), "application/json")

    metadata_payload = payload.get("metadata")
    if not isinstance(metadata_payload, dict):
        metadata_payload = {}
    metadata_payload["packaging"] = "self-contained"
    metadata_payload.setdefault("import_source", source)
    metadata_payload.setdefault("normalized_at", datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    return {
        **payload,
        "id": package_id,
        "name": package_name,
        "version": package_version,
        "description": package_description,
        "interface": interface_payload,
        "validation": {
            **validation_payload,
            "artifact": validation_artifact,
            "required_fields": _default_validation_payload()["required_fields"],
        },
        "editor_spec": {
            **editor_spec_payload,
            "artifact": editor_spec_artifact,
            "version": str(editor_spec_payload.get("version") or "1.0"),
        },
        "endpoint_code": {
            **endpoint_code,
            "language": str(endpoint_code.get("language") or "python"),
            "entrypoint": entrypoint,
            "interface_contract": str(endpoint_code.get("interface_contract") or "labbrew.scenario-package@1.0"),
        },
        "runner": {
            "kind": str(runner_payload.get("kind") or "scripted"),
            "entrypoint": str(runner_payload.get("entrypoint") or "scripted.run"),
            "config": runner_payload.get("config") if isinstance(runner_payload.get("config"), dict) else {},
        },
        "program": program_payload,
        "artifacts": list(artifacts_by_path.values()),
        "metadata": metadata_payload,
    }


def _validate_self_contained_scenario_package(
    package_payload: dict[str, Any],
    *,
    require_full_contract: bool,
) -> list[dict[str, str]]:
    payload = package_payload if isinstance(package_payload, dict) else {}
    errors: list[dict[str, str]] = []

    if require_full_contract:
        required_fields = [
            "id",
            "name",
            "runner",
            "interface",
            "validation",
            "editor_spec",
            "endpoint_code",
            "artifacts",
        ]
        for field in required_fields:
            if field not in payload:
                errors.append(
                    {
                        "code": "missing_required_field",
                        "message": f"Package is missing required field '{field}'",
                        "path": field,
                    }
                )

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        errors.append(
            {
                "code": "missing_artifacts",
                "message": "Package must include embedded artifacts for runner/editor/validation",
                "path": "artifacts",
            }
        )
        return errors

    artifact_paths = {
        str(item.get("path") or "").strip()
        for item in artifacts
        if isinstance(item, dict)
    }

    endpoint_code = payload.get("endpoint_code")
    if isinstance(endpoint_code, dict):
        entrypoint = str(endpoint_code.get("entrypoint") or "").strip()
        if not entrypoint:
            errors.append(
                {
                    "code": "missing_endpoint_entrypoint",
                    "message": "endpoint_code.entrypoint is required",
                    "path": "endpoint_code.entrypoint",
                }
            )
        elif entrypoint not in artifact_paths:
            errors.append(
                {
                    "code": "missing_endpoint_artifact",
                    "message": "endpoint_code.entrypoint must exist in artifacts",
                    "path": "endpoint_code.entrypoint",
                }
            )

    validation = payload.get("validation")
    if isinstance(validation, dict):
        validation_artifact = str(validation.get("artifact") or "").strip()
        if validation_artifact and validation_artifact not in artifact_paths:
            errors.append(
                {
                    "code": "missing_validation_artifact",
                    "message": "validation.artifact must exist in artifacts",
                    "path": "validation.artifact",
                }
            )
    elif require_full_contract:
        errors.append(
            {
                "code": "missing_validation_contract",
                "message": "validation section is required for repository-grade packages",
                "path": "validation",
            }
        )

    editor_spec = payload.get("editor_spec")
    if isinstance(editor_spec, dict):
        editor_artifact = str(editor_spec.get("artifact") or editor_spec.get("schema_artifact") or "").strip()
        if not editor_artifact:
            errors.append(
                {
                    "code": "missing_editor_spec_artifact",
                    "message": "editor_spec.artifact (or schema_artifact) is required",
                    "path": "editor_spec.artifact",
                }
            )
        elif editor_artifact not in artifact_paths:
            errors.append(
                {
                    "code": "missing_editor_spec_artifact_payload",
                    "message": "editor_spec artifact must exist in artifacts",
                    "path": "editor_spec.artifact",
                }
            )

        # Allow package-defined editor runtime hooks; if referenced they must be embedded.
        for key, value in editor_spec.items():
            if not isinstance(key, str):
                continue
            if not key.endswith("_artifact"):
                continue
            artifact_ref = str(value or "").strip()
            if artifact_ref and artifact_ref not in artifact_paths:
                errors.append(
                    {
                        "code": "missing_editor_runtime_artifact",
                        "message": f"editor_spec.{key} must exist in artifacts",
                        "path": f"editor_spec.{key}",
                    }
                )
    elif require_full_contract:
        errors.append(
            {
                "code": "missing_editor_spec_contract",
                "message": "editor_spec section is required for repository-grade packages",
                "path": "editor_spec",
            }
        )

    runner = payload.get("runner")
    runner_kind = str((runner or {}).get("kind") or "").strip().lower() if isinstance(runner, dict) else ""
    if require_full_contract and runner_kind == "scripted" and "data/program.json" not in artifact_paths:
        errors.append(
            {
                "code": "missing_program_artifact",
                "message": "Scripted package must embed data/program.json",
                "path": "artifacts",
            }
        )

    return errors


def _parse_uploaded_scenario_package(file_bytes: bytes, filename: str) -> dict[str, Any]:
    suffix = Path(filename or "").suffix.lower()

    def _read_msgpack_payload(raw: bytes) -> dict[str, Any]:
        try:
            payload = msgpack.unpackb(raw, raw=False)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid scenario package MessagePack manifest: {exc}",
            ) from exc
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=422,
                detail="Scenario package manifest root must be a map/object",
            )
        return payload

    if suffix in {".zip", ".lbpkg"}:
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as archive:
                candidates = (
                    "scenario.package.msgpack",
                    "scenario-package.msgpack",
                    "package.msgpack",
                    "scenario.package.mpk",
                    "scenario-package.mpk",
                    "package.mpk",
                )
                manifest_name = None
                for candidate in candidates:
                    if candidate in archive.namelist():
                        manifest_name = candidate
                        break
                if manifest_name is None:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "Scenario package archive must contain one of: "
                            "scenario.package.msgpack, scenario-package.msgpack, package.msgpack"
                        ),
                    )

                payload = _read_msgpack_payload(archive.read(manifest_name))
                artifacts: list[dict[str, Any]] = []
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    item_name = str(info.filename or "").strip()
                    if not item_name or item_name == manifest_name:
                        continue
                    blob = archive.read(item_name)
                    media_type, _ = mimetypes.guess_type(item_name)
                    artifacts.append(
                        {
                            "path": item_name,
                            "media_type": media_type or "application/octet-stream",
                            "encoding": "base64",
                            "content_b64": base64.b64encode(blob).decode("ascii"),
                            "size": len(blob),
                        }
                    )

                payload["artifacts"] = artifacts
                payload.setdefault("metadata", {})
                if isinstance(payload.get("metadata"), dict):
                    payload["metadata"]["archive_filename"] = filename
                return payload
        except zipfile.BadZipFile as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid scenario package archive: {exc}",
            ) from exc

    raise HTTPException(
        status_code=415,
        detail=(
            "Unsupported scenario package format. "
            "Use .zip or .lbpkg"
        ),
    )


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


_WORKSPACE_LAYOUT_STORE_LOCK = threading.RLock()


def _workspace_layout_store_path() -> Path:
    path = storage_path("supervisor_workspace_layouts.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_workspace_layout_store() -> dict[str, Any]:
    with _WORKSPACE_LAYOUT_STORE_LOCK:
        path = _workspace_layout_store_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}


def _save_workspace_layout_store(store: dict[str, Any]) -> None:
    with _WORKSPACE_LAYOUT_STORE_LOCK:
        path = _workspace_layout_store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, store, indent=2, sort_keys=True, ensure_ascii=False)


def _update_workspace_layout_store(fermenter_id: str, layout: dict[str, Any]) -> None:
    with _WORKSPACE_LAYOUT_STORE_LOCK:
        store = _load_workspace_layout_store()
        store[str(fermenter_id)] = layout
        _save_workspace_layout_store(store)


def _normalize_workspace_layout_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    tabs = raw.get("tabs")
    if not isinstance(tabs, list) or not tabs:
        raise HTTPException(status_code=400, detail="Body must include a non-empty tabs list")

    try:
        normalized_tabs = json.loads(json.dumps(tabs))
    except TypeError as exc:
        raise HTTPException(status_code=400, detail="Workspace tabs must be JSON serializable") from exc

    encoded_tabs = json.dumps(normalized_tabs, separators=(",", ":"))
    if len(encoded_tabs.encode("utf-8")) > 500_000:
        raise HTTPException(status_code=413, detail="Workspace layout payload is too large")

    control_card_order_raw = raw.get("control_card_order")
    control_card_order = []
    if isinstance(control_card_order_raw, list):
        control_card_order = [
            str(item).strip() for item in control_card_order_raw if str(item).strip()
        ]

    active_tab = str(raw.get("active_tab") or "").strip() or None

    return {
        "tabs": normalized_tabs,
        "active_tab": active_tab,
        "control_card_order": control_card_order,
        "updated_at": datetime.now(tz=UTC).isoformat(),
    }


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

    @router.get("/fermenters/{fermenter_id}/agent/persistence")
    def get_agent_persistence(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")
        status_code, payload = _read_json_response(
            proxy, method="GET", url=_build_agent_proxy_url(node, "/agent/persistence")
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

    @router.get("/fermenters/{fermenter_id}/workspace-layouts")
    def get_workspace_layouts(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        store = _load_workspace_layout_store()
        layout = store.get(str(fermenter_id))
        if not isinstance(layout, dict):
            layout = None

        return {
            "ok": True,
            "fermenter_id": fermenter_id,
            "workspace_layout": layout,
        }

    @router.put("/fermenters/{fermenter_id}/workspace-layouts")
    async def put_workspace_layouts(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

        layout = _normalize_workspace_layout_payload(body)
        layout["fermenter_name"] = str(getattr(node, "name", "") or fermenter_id)

        await asyncio.to_thread(
            _update_workspace_layout_store, fermenter_id, layout
        )

        return {
            "ok": True,
            "fermenter_id": fermenter_id,
            "workspace_layout": layout,
        }

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

    @router.put("/fermenters/{fermenter_id}/scenario/validate-import")
    async def validate_scenario_import(
        fermenter_id: str,
        request: Request,
        file: Annotated[UploadFile, File(...)],
    ):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        file_bytes = await file.read()
        package_payload = _parse_uploaded_scenario_package(
            file_bytes,
            file.filename or "scenario.package.msgpack",
        )

        self_contained_errors = _validate_self_contained_scenario_package(
            package_payload,
            require_full_contract=True,
        )
        if self_contained_errors:
            return {
                "ok": False,
                "valid": False,
                "errors": self_contained_errors,
                "warnings": [],
                "scenario_package": package_payload,
                "compile": {"ok": False, "errors": self_contained_errors, "warnings": []},
                "summary": {
                    "filename": file.filename or "scenario.package.msgpack",
                    "runner": str((package_payload.get("runner") or {}).get("kind", "unknown")),
                },
            }

        status_code, compile_result = _read_json_response(
            proxy,
            method="POST",
            url=_build_service_proxy_url(node, "scenario_service", "scenario/compile"),
            json_body=package_payload,
        )

        compile_ok = bool(
            status_code and 200 <= status_code < 300 and isinstance(compile_result, dict)
            and compile_result.get("ok")
        )
        compile_errors = (
            compile_result.get("errors", [])
            if isinstance(compile_result, dict)
            else []
        )
        compile_warnings = (
            compile_result.get("warnings", [])
            if isinstance(compile_result, dict)
            else []
        )

        return {
            "ok": compile_ok,
            "valid": compile_ok,
            "errors": compile_errors,
            "warnings": compile_warnings,
            "scenario_package": package_payload,
            "compile": compile_result,
            "summary": {
                "filename": file.filename or "scenario.package.msgpack",
                "runner": str(
                    (package_payload.get("runner") or {}).get("kind", "unknown")
                ),
            },
        }

    @router.put("/fermenters/{fermenter_id}/scenario/import")
    async def import_scenario(
        fermenter_id: str,
        request: Request,
        file: Annotated[UploadFile, File(...)],
    ):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        file_bytes = await file.read()
        package_payload = _parse_uploaded_scenario_package(
            file_bytes,
            file.filename or "scenario.package.msgpack",
        )

        self_contained_errors = _validate_self_contained_scenario_package(
            package_payload,
            require_full_contract=True,
        )
        if self_contained_errors:
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "valid": False,
                    "errors": self_contained_errors,
                    "warnings": [],
                    "scenario_package": package_payload,
                    "compile": {"ok": False, "errors": self_contained_errors, "warnings": []},
                },
            )

        compile_status, compile_result = _read_json_response(
            proxy,
            method="POST",
            url=_build_service_proxy_url(node, "scenario_service", "scenario/compile"),
            json_body=package_payload,
        )

        compile_ok = bool(
            compile_status and 200 <= compile_status < 300 and isinstance(compile_result, dict)
            and compile_result.get("ok")
        )

        if not compile_ok:
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "valid": False,
                    "errors": (
                        compile_result.get("errors", [])
                        if isinstance(compile_result, dict)
                        else [{"code": "compile_failed", "message": "Compile failed"}]
                    ),
                    "warnings": (
                        compile_result.get("warnings", [])
                        if isinstance(compile_result, dict)
                        else []
                    ),
                    "scenario_package": package_payload,
                    "compile": compile_result,
                },
            )

        status_code, forwarded = _read_json_response(
            proxy,
            method="PUT",
            url=_build_service_proxy_url(node, "scenario_service", "scenario/package"),
            json_body=package_payload,
        )

        service_accepts_package = bool(
            200 <= status_code < 300
            and not (
                isinstance(forwarded, dict)
                and forwarded.get("ok") is False
            )
        )

        if not service_accepts_package:
            forwarded_errors = (
                forwarded.get("errors", [])
                if isinstance(forwarded, dict)
                else []
            )
            fallback_error = {
                "code": "service_rejected_package",
                "message": (
                    str(forwarded.get("error") or "")
                    if isinstance(forwarded, dict)
                    else "Scenario service rejected package"
                ) or "Scenario service rejected package",
            }
            return JSONResponse(
                status_code=status_code if status_code >= 400 else 422,
                content={
                    "ok": False,
                    "valid": True,
                    "errors": forwarded_errors or [fallback_error],
                    "warnings": (
                        compile_result.get("warnings", [])
                        if isinstance(compile_result, dict)
                        else []
                    ),
                    "scenario_package": package_payload,
                    "compile": compile_result,
                    "forwarded": forwarded,
                    "summary": {"filename": filename, "repository_import": True},
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "ok": True,
                "valid": True,
                "errors": [],
                "warnings": (
                    compile_result.get("warnings", [])
                    if isinstance(compile_result, dict)
                    else []
                ),
                "scenario_package": package_payload,
                "compile": compile_result,
                "forwarded": forwarded,
            },
        )

    @router.get("/fermenters/{fermenter_id}/scenario/repository")
    async def list_scenario_repository(
        fermenter_id: str,
        request: Request,
        q: str | None = None,
        tag: str | None = None,
    ):
        registry = request.app.state.registry
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        repo_dir = _scenario_package_repo_dir()
        index_payload = _load_scenario_repo_index()
        index_packages = index_payload.get("packages") if isinstance(index_payload, dict) else {}
        index_packages = index_packages if isinstance(index_packages, dict) else {}

        search_term = str(q or "").strip().lower()
        tag_term = str(tag or "").strip().lower()
        packages = []
        for path in sorted(repo_dir.glob("*.lbpkg"), key=lambda p: p.name.lower()):
            stat = path.stat()
            meta = index_packages.get(path.name)
            meta = meta if isinstance(meta, dict) else {}
            tags = [
                str(item).strip()
                for item in (meta.get("tags") or [])
                if str(item).strip()
            ]
            version_notes = str(meta.get("version_notes") or "")
            notes = str(meta.get("notes") or "")

            haystack = f"{path.name} {' '.join(tags)} {version_notes} {notes}".lower()
            if search_term and search_term not in haystack:
                continue
            if tag_term and tag_term not in [item.lower() for item in tags]:
                continue

            packages.append(
                {
                    "name": path.name,
                    "size": int(stat.st_size),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat().replace("+00:00", "Z"),
                    "tags": tags,
                    "version_notes": version_notes,
                    "notes": notes,
                }
            )

        return {
            "ok": True,
            "repository_dir": str(repo_dir),
            "packages": packages,
        }

    @router.post("/fermenters/{fermenter_id}/scenario/repository/save")
    async def save_scenario_to_repository(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}

        package_payload = payload.get("package")
        if not isinstance(package_payload, dict):
            package_status, package_response = _read_json_response(
                proxy,
                method="GET",
                url=_build_service_proxy_url(node, "scenario_service", "scenario/package"),
            )
            if not (200 <= package_status < 300 and isinstance(package_response, dict)):
                return JSONResponse(
                    status_code=package_status,
                    content={"ok": False, "error": "Failed to read current scenario package"},
                )
            package_payload = package_response.get("package")

        if not isinstance(package_payload, dict):
            return JSONResponse(status_code=400, content={"ok": False, "error": "No scenario package available to save"})

        package_payload = _normalize_to_self_contained_package(
            package_payload,
            source="repository-save",
        )
        self_contained_errors = _validate_self_contained_scenario_package(
            package_payload,
            require_full_contract=True,
        )
        if self_contained_errors:
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "error": "Package is not self-contained",
                    "errors": self_contained_errors,
                },
            )

        suggested = str(payload.get("filename") or package_payload.get("name") or package_payload.get("id") or "package")
        filename = _safe_scenario_repo_filename(suggested, default_name="package")
        repo_dir = _scenario_package_repo_dir()
        target = repo_dir / filename
        target.write_bytes(_build_scenario_package_archive_bytes(package_payload))

        tags = [
            str(item).strip()
            for item in (payload.get("tags") or package_payload.get("metadata", {}).get("tags") or [])
            if str(item).strip()
        ]
        version_notes = str(
            payload.get("version_notes")
            or package_payload.get("metadata", {}).get("version_notes")
            or ""
        )
        notes = str(payload.get("notes") or "")
        index_payload = _load_scenario_repo_index()
        index_packages = index_payload.setdefault("packages", {})
        if isinstance(index_packages, dict):
            index_packages[filename] = {
                "tags": tags,
                "version_notes": version_notes,
                "notes": notes,
            }
            _save_scenario_repo_index(index_payload)

        stat = target.stat()
        return {
            "ok": True,
            "saved": {
                "name": target.name,
                "size": int(stat.st_size),
                "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat().replace("+00:00", "Z"),
                "tags": tags,
                "version_notes": version_notes,
                "notes": notes,
            },
        }

    @router.post("/fermenters/{fermenter_id}/scenario/repository/copy")
    async def copy_scenario_repository_package(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}

        source_name = _safe_scenario_repo_filename(str(payload.get("source_filename") or ""), default_name="")
        target_name = _safe_scenario_repo_filename(str(payload.get("target_filename") or ""), default_name="")
        if not source_name or not target_name:
            return JSONResponse(status_code=400, content={"ok": False, "error": "source_filename and target_filename are required"})

        repo_dir = _scenario_package_repo_dir()
        source_path = repo_dir / source_name
        target_path = repo_dir / target_name
        if not source_path.exists() or not source_path.is_file():
            return JSONResponse(status_code=404, content={"ok": False, "error": "Source package not found"})

        target_path.write_bytes(source_path.read_bytes())
        index_payload = _load_scenario_repo_index()
        index_packages = index_payload.setdefault("packages", {})
        if isinstance(index_packages, dict) and source_name in index_packages:
            copied = dict(index_packages.get(source_name) or {})
            index_packages[target_name] = copied
            _save_scenario_repo_index(index_payload)
        stat = target_path.stat()
        return {
            "ok": True,
            "copied": {
                "name": target_path.name,
                "size": int(stat.st_size),
                "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat().replace("+00:00", "Z"),
            },
        }

    @router.post("/fermenters/{fermenter_id}/scenario/repository/import")
    async def import_scenario_from_repository(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}

        filename = _safe_scenario_repo_filename(str(payload.get("filename") or ""), default_name="")
        if not filename:
            return JSONResponse(status_code=400, content={"ok": False, "error": "filename is required"})

        repo_dir = _scenario_package_repo_dir()
        package_path = repo_dir / filename
        if not package_path.exists() or not package_path.is_file():
            return JSONResponse(status_code=404, content={"ok": False, "error": "Package not found in repository"})

        package_payload = _parse_uploaded_scenario_package(package_path.read_bytes(), filename)

        self_contained_errors = _validate_self_contained_scenario_package(
            package_payload,
            require_full_contract=True,
        )
        if self_contained_errors:
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "valid": False,
                    "errors": self_contained_errors,
                    "warnings": [],
                    "scenario_package": package_payload,
                    "compile": {"ok": False, "errors": self_contained_errors, "warnings": []},
                    "summary": {"filename": filename, "repository_import": True},
                },
            )

        compile_status, compile_result = _read_json_response(
            proxy,
            method="POST",
            url=_build_service_proxy_url(node, "scenario_service", "scenario/compile"),
            json_body=package_payload,
        )

        compile_ok = bool(
            compile_status and 200 <= compile_status < 300 and isinstance(compile_result, dict)
            and compile_result.get("ok")
        )
        if not compile_ok:
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "valid": False,
                    "errors": (
                        compile_result.get("errors", [])
                        if isinstance(compile_result, dict)
                        else [{"code": "compile_failed", "message": "Compile failed"}]
                    ),
                    "warnings": (
                        compile_result.get("warnings", [])
                        if isinstance(compile_result, dict)
                        else []
                    ),
                    "scenario_package": package_payload,
                    "compile": compile_result,
                    "summary": {"filename": filename, "repository_import": True},
                },
            )

        status_code, forwarded = _read_json_response(
            proxy,
            method="PUT",
            url=_build_service_proxy_url(node, "scenario_service", "scenario/package"),
            json_body=package_payload,
        )
        return JSONResponse(
            status_code=status_code,
            content={
                "ok": 200 <= status_code < 300,
                "valid": True,
                "errors": [],
                "warnings": (
                    compile_result.get("warnings", [])
                    if isinstance(compile_result, dict)
                    else []
                ),
                "scenario_package": package_payload,
                "compile": compile_result,
                "forwarded": forwarded,
                "summary": {"filename": filename, "repository_import": True},
            },
        )

    @router.post("/fermenters/{fermenter_id}/scenario/repository/metadata")
    async def update_scenario_repository_metadata(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}

        filename = _safe_scenario_repo_filename(str(payload.get("filename") or ""), default_name="")
        if not filename:
            return JSONResponse(status_code=400, content={"ok": False, "error": "filename is required"})

        repo_dir = _scenario_package_repo_dir()
        package_path = repo_dir / filename
        if not package_path.exists() or not package_path.is_file():
            return JSONResponse(status_code=404, content={"ok": False, "error": "Package not found"})

        tags = [str(item).strip() for item in (payload.get("tags") or []) if str(item).strip()]
        version_notes = str(payload.get("version_notes") or "")
        notes = str(payload.get("notes") or "")

        index_payload = _load_scenario_repo_index()
        index_packages = index_payload.setdefault("packages", {})
        if isinstance(index_packages, dict):
            index_packages[filename] = {
                "tags": tags,
                "version_notes": version_notes,
                "notes": notes,
            }
            _save_scenario_repo_index(index_payload)

        return {
            "ok": True,
            "updated": {
                "name": filename,
                "tags": tags,
                "version_notes": version_notes,
                "notes": notes,
            },
        }

    @router.post("/fermenters/{fermenter_id}/scenario/repository/rename")
    async def rename_scenario_repository_package(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}

        source_name = _safe_scenario_repo_filename(str(payload.get("source_filename") or ""), default_name="")
        target_name = _safe_scenario_repo_filename(str(payload.get("target_filename") or ""), default_name="")
        if not source_name or not target_name:
            return JSONResponse(status_code=400, content={"ok": False, "error": "source_filename and target_filename are required"})

        repo_dir = _scenario_package_repo_dir()
        source_path = repo_dir / source_name
        target_path = repo_dir / target_name
        if not source_path.exists() or not source_path.is_file():
            return JSONResponse(status_code=404, content={"ok": False, "error": "Source package not found"})
        if target_path.exists():
            return JSONResponse(status_code=409, content={"ok": False, "error": "Target package already exists"})

        source_path.replace(target_path)

        index_payload = _load_scenario_repo_index()
        index_packages = index_payload.setdefault("packages", {})
        if isinstance(index_packages, dict) and source_name in index_packages:
            index_packages[target_name] = dict(index_packages.pop(source_name) or {})
            _save_scenario_repo_index(index_payload)

        stat = target_path.stat()
        return {
            "ok": True,
            "renamed": {
                "name": target_name,
                "size": int(stat.st_size),
                "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat().replace("+00:00", "Z"),
            },
        }

    @router.delete("/fermenters/{fermenter_id}/scenario/repository/{filename}")
    async def delete_scenario_repository_package(fermenter_id: str, request: Request, filename: str):
        registry = request.app.state.registry
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        safe_name = _safe_scenario_repo_filename(filename, default_name="")
        if not safe_name:
            return JSONResponse(status_code=400, content={"ok": False, "error": "filename is required"})

        repo_dir = _scenario_package_repo_dir()
        target = repo_dir / safe_name
        if not target.exists() or not target.is_file():
            return JSONResponse(status_code=404, content={"ok": False, "error": "Package not found"})

        target.unlink()
        index_payload = _load_scenario_repo_index()
        index_packages = index_payload.setdefault("packages", {})
        if isinstance(index_packages, dict) and safe_name in index_packages:
            index_packages.pop(safe_name, None)
            _save_scenario_repo_index(index_payload)

        return {"ok": True, "deleted": safe_name}

    @router.get("/fermenters/{fermenter_id}/scenario/repository/download/{filename}")
    async def download_scenario_repository_package(fermenter_id: str, request: Request, filename: str):
        registry = request.app.state.registry
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        safe_name = _safe_scenario_repo_filename(filename, default_name="")
        if not safe_name:
            raise HTTPException(status_code=400, detail="filename is required")

        repo_dir = _scenario_package_repo_dir()
        target = repo_dir / safe_name
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="Package not found")

        stream = target.open("rb")
        headers = {"content-disposition": f'attachment; filename="{safe_name}"'}
        return StreamingResponse(
            stream,
            media_type="application/octet-stream",
            headers=headers,
            background=BackgroundTask(stream.close),
        )

    @router.get("/fermenters/{fermenter_id}/scenario/repository/read/{filename}")
    async def read_scenario_repository_package(fermenter_id: str, request: Request, filename: str):
        registry = request.app.state.registry
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        safe_name = _safe_scenario_repo_filename(filename, default_name="")
        if not safe_name:
            return JSONResponse(status_code=400, content={"ok": False, "error": "filename is required"})

        repo_dir = _scenario_package_repo_dir()
        package_path = repo_dir / safe_name
        if not package_path.exists() or not package_path.is_file():
            return JSONResponse(status_code=404, content={"ok": False, "error": "Package not found"})

        package_payload = _parse_uploaded_scenario_package(package_path.read_bytes(), safe_name)
        return {
            "ok": True,
            "filename": safe_name,
            "scenario_package": package_payload,
        }

    @router.post("/fermenters/{fermenter_id}/scenario/repository/upload-package")
    async def upload_scenario_repository_package(
        fermenter_id: str,
        request: Request,
        file: Annotated[UploadFile, File(...)],
    ):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        package_bytes = await file.read()
        if not package_bytes:
            return JSONResponse(status_code=400, content={"ok": False, "error": "Uploaded package file is empty"})

        try:
            package_payload = _parse_uploaded_scenario_package(package_bytes, file.filename or "package.lbpkg")
        except Exception as exc:
            return JSONResponse(status_code=400, content={"ok": False, "error": f"Invalid package file: {exc}"})

        package_payload = _normalize_to_self_contained_package(package_payload, source="repository-upload")
        self_contained_errors = _validate_self_contained_scenario_package(
            package_payload,
            require_full_contract=True,
        )
        if self_contained_errors:
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "valid": False,
                    "errors": self_contained_errors,
                    "warnings": [],
                    "scenario_package": package_payload,
                    "compile": {"ok": False, "errors": self_contained_errors, "warnings": []},
                },
            )

        compile_status, compile_result = _read_json_response(
            proxy,
            method="POST",
            url=_build_service_proxy_url(node, "scenario_service", "scenario/compile"),
            json_body=package_payload,
        )
        compile_ok = bool(
            compile_status and 200 <= compile_status < 300 and isinstance(compile_result, dict)
            and compile_result.get("ok")
        )
        if not compile_ok:
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "valid": False,
                    "errors": (
                        compile_result.get("errors", [])
                        if isinstance(compile_result, dict)
                        else [{"code": "compile_failed", "message": "Compile failed"}]
                    ),
                    "warnings": (
                        compile_result.get("warnings", [])
                        if isinstance(compile_result, dict)
                        else []
                    ),
                    "scenario_package": package_payload,
                    "compile": compile_result,
                },
            )

        suggested = str(
            request.query_params.get("filename")
            or file.filename
            or package_payload.get("id")
            or package_payload.get("name")
            or "uploaded-package"
        )
        filename = _safe_scenario_repo_filename(suggested, default_name="uploaded-package")
        repo_dir = _scenario_package_repo_dir()
        target = repo_dir / filename
        target.write_bytes(_build_scenario_package_archive_bytes(package_payload))

        metadata_payload = package_payload.get("metadata")
        metadata_payload = metadata_payload if isinstance(metadata_payload, dict) else {}
        tags = [
            str(item).strip()
            for item in (metadata_payload.get("tags") or [])
            if str(item).strip()
        ]
        version_notes = str(metadata_payload.get("version_notes") or "")
        notes = str(metadata_payload.get("notes") or package_payload.get("description") or "")

        index_payload = _load_scenario_repo_index()
        index_packages = index_payload.setdefault("packages", {})
        if isinstance(index_packages, dict):
            index_packages[filename] = {
                "tags": tags,
                "version_notes": version_notes,
                "notes": notes,
            }
            _save_scenario_repo_index(index_payload)

        stat = target.stat()
        return {
            "ok": True,
            "valid": True,
            "saved": {
                "name": target.name,
                "size": int(stat.st_size),
                "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat().replace("+00:00", "Z"),
                "tags": tags,
                "version_notes": version_notes,
                "notes": notes,
            },
            "scenario_package": package_payload,
            "compile": compile_result,
        }

    @router.post("/fermenters/{fermenter_id}/scenario/repository/convert-excel")
    async def convert_excel_to_repository_package(
        fermenter_id: str,
        request: Request,
        file: Annotated[UploadFile, File(...)],
    ):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Fermenter not found")

        workbook_bytes = await file.read()
        if not workbook_bytes:
            return JSONResponse(status_code=400, content={"ok": False, "error": "Uploaded Excel file is empty"})

        payload_raw = {
            "filename": request.query_params.get("filename") or file.filename or "excel-converted",
            "name": request.query_params.get("name") or "",
            "id": request.query_params.get("id") or "",
            "version": request.query_params.get("version") or "",
            "description": request.query_params.get("description") or "",
            "version_notes": request.query_params.get("version_notes") or "",
            "tags": [item for item in str(request.query_params.get("tags") or "").split(",") if item.strip()],
        }

        program_payload = parse_schedule_workbook(workbook_bytes, filename=file.filename or "workbook.xlsx")
        package_defaults = program_payload.get("package_defaults") if isinstance(program_payload, dict) else {}
        package_defaults = package_defaults if isinstance(package_defaults, dict) else {}

        resolved_id = str(
            payload_raw["id"]
            or package_defaults.get("id")
            or program_payload.get("id")
            or Path(file.filename or "scenario").stem.replace(" ", "-").lower()
            or "scenario-package"
        )
        resolved_name = str(
            payload_raw["name"]
            or package_defaults.get("name")
            or program_payload.get("name")
            or Path(file.filename or "Scenario").stem
            or "Scenario Package"
        )
        resolved_version = str(payload_raw["version"] or package_defaults.get("version") or "0.1.0")
        resolved_description = str(
            payload_raw["description"]
            or package_defaults.get("description")
            or f"Excel-converted package from {file.filename or 'workbook.xlsx'}"
        )

        meta_tags = [
            str(item).strip()
            for item in (package_defaults.get("tags") or [])
            if str(item).strip()
        ]
        resolved_tags = [
            str(item).strip()
            for item in (payload_raw["tags"] or meta_tags)
            if str(item).strip()
        ]

        package_payload = _build_package_payload_from_program(
            package_id=resolved_id,
            package_name=resolved_name,
            version=resolved_version,
            description=resolved_description,
            tags=resolved_tags,
            version_notes=str(payload_raw["version_notes"] or ""),
            source="excel",
            program_payload=dict(program_payload or {}),
            source_workbook_bytes=workbook_bytes,
            source_workbook_name=file.filename or "workbook.xlsx",
        )

        compile_status, compile_result = _read_json_response(
            proxy,
            method="POST",
            url=_build_service_proxy_url(node, "scenario_service", "scenario/compile"),
            json_body=package_payload,
        )
        compile_ok = bool(
            compile_status and 200 <= compile_status < 300 and isinstance(compile_result, dict)
            and compile_result.get("ok")
        )
        if not compile_ok:
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "valid": False,
                    "errors": compile_result.get("errors", []) if isinstance(compile_result, dict) else [{"code": "compile_failed", "message": "Compile failed"}],
                    "warnings": compile_result.get("warnings", []) if isinstance(compile_result, dict) else [],
                    "scenario_package": package_payload,
                    "compile": compile_result,
                },
            )

        suggested = str(payload_raw["filename"] or package_payload.get("name") or package_payload.get("id") or "excel-package")
        filename = _safe_scenario_repo_filename(suggested, default_name="excel-package")
        repo_dir = _scenario_package_repo_dir()
        target = repo_dir / filename
        target.write_bytes(_build_scenario_package_archive_bytes(package_payload))

        index_payload = _load_scenario_repo_index()
        index_packages = index_payload.setdefault("packages", {})
        tags = [str(item).strip() for item in resolved_tags if str(item).strip()]
        version_notes = str(payload_raw["version_notes"] or "")
        if isinstance(index_packages, dict):
            index_packages[filename] = {
                "tags": tags,
                "version_notes": version_notes,
                "notes": f"Converted from {file.filename or 'Excel workbook'}",
            }
            _save_scenario_repo_index(index_payload)

        import_now = str(request.query_params.get("import_now") or "false").lower() in {"1", "true", "yes", "on"}
        imported = None
        if import_now:
            status_code, forwarded = _read_json_response(
                proxy,
                method="PUT",
                url=_build_service_proxy_url(node, "scenario_service", "scenario/package"),
                json_body=package_payload,
            )
            imported = {"ok": 200 <= status_code < 300, "status_code": status_code, "forwarded": forwarded}

        stat = target.stat()
        return {
            "ok": True,
            "valid": True,
            "saved": {
                "name": target.name,
                "size": int(stat.st_size),
                "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat().replace("+00:00", "Z"),
                "tags": tags,
                "version_notes": version_notes,
            },
            "scenario_package": package_payload,
            "compile": compile_result,
            "imported": imported,
        }

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
            url=_build_service_proxy_url(node, "scenario_service", "scenario/run/status"),
        )
        runner_status = None
        if (
            status_code
            and 200 <= status_code < 300
            and isinstance(schedule_status, dict)
        ):
            runner_status = schedule_status.get("runner_status")
        schedule = runner_status if isinstance(runner_status, dict) else None

        schedule_definition: Any = None
        scenario_package: Any = None
        status_code, schedule_payload = _read_best_effort(
            proxy,
            method="GET",
            url=_build_service_proxy_url(node, "scenario_service", "scenario/package"),
        )
        if (
            status_code
            and 200 <= status_code < 300
            and isinstance(schedule_payload, dict)
        ):
            package = schedule_payload.get("package")
            if isinstance(package, dict):
                scenario_package = package
                candidate = package.get("program")
                if isinstance(candidate, dict):
                    schedule_definition = candidate

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
            "scenario_package": scenario_package,
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
        "/fermenters/{fermenter_id}/scenario/{service_path:path}",
        methods=["GET", "POST", "PUT", "DELETE"],
    )
    @router.api_route(
        "/fermenters/{fermenter_id}/scenario", methods=["GET", "POST", "PUT", "DELETE"]
    )
    async def proxy_scenario(
        fermenter_id: str, request: Request, service_path: str = ""
    ):
        return await _proxy_via_agent(
            request,
            fermenter_id,
            "scenario_service",
            f"scenario/{service_path}".rstrip("/"),
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
