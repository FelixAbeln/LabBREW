from __future__ import annotations

import base64
import io
import json
import mimetypes
import zipfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import msgpack
from fastapi import HTTPException

from Services._shared.json_persistence import atomic_write_json
from Services._shared.storage_paths import default_measurements_dir, storage_path


def _scenario_package_repo_dir() -> Path:
    repo_dir = Path(storage_path("scenario_packages"))
    repo_dir.mkdir(parents=True, exist_ok=True)
    return repo_dir


def _scenario_template_dir() -> Path:
    template_dir = Path(storage_path("scenario_templates"))
    template_dir.mkdir(parents=True, exist_ok=True)
    return template_dir


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


def _read_package_artifact_text(package_path: Path, artifact_path: str) -> str:
    if not package_path.is_file():
        raise FileNotFoundError(f"Missing required package: {package_path}")
    with zipfile.ZipFile(package_path, "r") as archive:
        if artifact_path not in archive.namelist():
            raise FileNotFoundError(
                f"Package artifact '{artifact_path}' not found in {package_path.name}"
            )
        return archive.read(artifact_path).decode("utf-8")


def _read_excel_runner_source(package_path: Path, runner_artifact: str) -> str:
    return _read_package_artifact_text(package_path, runner_artifact)


def _read_excel_conversion_script_source(
    package_path: Path, converter_artifact: str
) -> str:
    return _read_package_artifact_text(package_path, converter_artifact)


def _resolve_package_runner_artifact(package_payload: dict[str, Any]) -> str:
    endpoint_code = (
        package_payload.get("endpoint_code") if isinstance(package_payload, dict) else None
    )
    endpoint_code = endpoint_code if isinstance(endpoint_code, dict) else {}
    runner_artifact = str(endpoint_code.get("entrypoint") or "").strip()
    if not runner_artifact:
        raise RuntimeError("Source package must declare endpoint_code.entrypoint")
    return runner_artifact


def _resolve_package_converter_artifact(package_payload: dict[str, Any]) -> str:
    metadata = package_payload.get("metadata") if isinstance(package_payload, dict) else None
    metadata = metadata if isinstance(metadata, dict) else {}
    converter_artifact = str(metadata.get("converter_script_artifact") or "").strip()
    if not converter_artifact:
        raise RuntimeError("Source package must declare metadata.converter_script_artifact")
    return converter_artifact


def _resolve_converter_source_package(*, target_filename: str) -> Path:
    repo_dir = _scenario_package_repo_dir()

    if target_filename:
        existing_repo_pkg = repo_dir / target_filename
        if existing_repo_pkg.is_file():
            return existing_repo_pkg

    raise FileNotFoundError(
        "No converter source package selected. Replace an existing repository package file so its embedded converter is used."
    )


def _parse_program_with_package_converter(
    workbook_bytes: bytes,
    *,
    package_path: Path,
    converter_artifact: str,
    filename: str,
) -> dict[str, Any]:
    converter_src = _read_excel_conversion_script_source(package_path, converter_artifact)
    namespace: dict[str, Any] = {}
    exec(compile(converter_src, converter_artifact, "exec"), namespace)  # noqa: S102
    parse_workbook = namespace.get("parse_workbook")
    if not callable(parse_workbook):
        raise RuntimeError(
            f"Converter artifact '{converter_artifact}' must define parse_workbook(...)"
        )
    return parse_workbook(
        workbook_bytes,
        filename=filename,
        default_measurements_output_dir=default_measurements_dir(),
    )


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
        "file_upload_actions": [],
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


def _exec_package_converter(
    *,
    package_path: Path,
    runner_artifact: str,
    converter_artifact: str,
    package_id: str,
    package_name: str,
    version: str,
    description: str,
    tags: list[str],
    version_notes: str,
    program_payload: dict[str, Any],
    source_workbook_bytes: bytes | None = None,
    source_workbook_name: str | None = None,
) -> dict[str, Any]:
    converter_src = _read_excel_conversion_script_source(package_path, converter_artifact)
    runner_src = _read_excel_runner_source(package_path, runner_artifact)
    namespace: dict[str, Any] = {}
    exec(compile(converter_src, converter_artifact, "exec"), namespace)  # noqa: S102
    build_package = namespace["build_package"]
    return build_package(
        dict(program_payload or {}),
        runner_source=runner_src,
        converter_source=converter_src,
        source_name=str(source_workbook_name or "workbook.xlsx"),
        package_id=package_id,
        package_name=package_name,
        version=version,
        description=description,
        tags=list(tags or []),
        version_notes=version_notes,
        source_workbook_bytes=source_workbook_bytes,
    )


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


def _normalize_to_self_contained_package(
    package_payload: dict[str, Any], *, source: str
) -> dict[str, Any]:
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
    editor_spec_artifact = str(
        editor_spec_payload.get("artifact")
        or editor_spec_payload.get("schema_artifact")
        or "editor/spec.json"
    ).strip() or "editor/spec.json"

    if "data/program.json" not in artifacts_by_path:
        _put_artifact(
            "data/program.json",
            json.dumps(program_payload, ensure_ascii=False, indent=2),
            "application/json",
        )
    if validation_artifact not in artifacts_by_path:
        _put_artifact(
            validation_artifact,
            json.dumps(_default_validation_payload(), ensure_ascii=False, indent=2),
            "application/json",
        )
    if editor_spec_artifact not in artifacts_by_path:
        _put_artifact(
            editor_spec_artifact,
            json.dumps(_default_editor_spec_payload(), ensure_ascii=False, indent=2),
            "application/json",
        )

    try:
        editor_artifact_item = artifacts_by_path.get(editor_spec_artifact)
        editor_content_b64 = str((editor_artifact_item or {}).get("content_b64") or "").strip()
        if editor_content_b64:
            editor_spec_embedded = json.loads(base64.b64decode(editor_content_b64).decode("utf-8"))
            if isinstance(editor_spec_embedded, dict):
                file_upload_actions = editor_spec_embedded.get("file_upload_actions")
                changed = False
                if isinstance(file_upload_actions, list):
                    for action in file_upload_actions:
                        if not isinstance(action, dict):
                            continue
                        endpoint = str(action.get("endpoint") or "").strip()
                        if endpoint == "repository/convert-excel":
                            action["endpoint"] = "repository/package-file-action"
                            changed = True
                if changed:
                    _put_artifact(
                        editor_spec_artifact,
                        json.dumps(editor_spec_embedded, ensure_ascii=False, indent=2),
                        "application/json",
                    )
    except Exception:
        pass

    metadata_payload = payload.get("metadata")
    if not isinstance(metadata_payload, dict):
        metadata_payload = {}
    metadata_payload["packaging"] = "self-contained"
    metadata_payload.setdefault("import_source", source)
    metadata_payload.setdefault(
        "normalized_at",
        datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )

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
            "interface_contract": str(
                endpoint_code.get("interface_contract") or "labbrew.scenario-package@1.0"
            ),
        },
        "runner": {
            "kind": str(runner_payload.get("kind") or "scripted"),
            "entrypoint": str(runner_payload.get("entrypoint") or "scripted.run"),
            "config": runner_payload.get("config")
            if isinstance(runner_payload.get("config"), dict)
            else {},
        },
        "program": program_payload,
        "artifacts": list(artifacts_by_path.values()),
        "metadata": metadata_payload,
    }


def _infer_converter_artifact_from_package(package_payload: dict[str, Any]) -> str:
    artifacts = package_payload.get("artifacts") if isinstance(package_payload, dict) else None
    if not isinstance(artifacts, list):
        return ""

    candidate_paths: list[str] = []
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        lower = path.lower()
        if not path or not lower.endswith(".py"):
            continue
        if "converter" not in lower:
            continue
        candidate_paths.append(path)

    if not candidate_paths:
        return ""
    if len(candidate_paths) == 1:
        return candidate_paths[0]

    preferred = [path for path in candidate_paths if path.lower().startswith("bin/")]
    if len(preferred) == 1:
        return preferred[0]

    exact_preferred = [
        path for path in candidate_paths if path.lower() == "bin/excel_package_converter.py"
    ]
    if len(exact_preferred) == 1:
        return exact_preferred[0]

    return ""


def _ensure_converter_contract_metadata(package_payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(package_payload or {})
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    converter_artifact = str(metadata.get("converter_script_artifact") or "").strip()
    if not converter_artifact:
        inferred = _infer_converter_artifact_from_package(payload)
        if inferred:
            metadata["converter_script_artifact"] = inferred
    payload["metadata"] = metadata
    return payload


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
    elif require_full_contract:
        errors.append(
            {
                "code": "missing_endpoint_code_contract",
                "message": "endpoint_code section is required for repository-grade packages",
                "path": "endpoint_code",
            }
        )

    metadata_payload = payload.get("metadata")
    if isinstance(metadata_payload, dict):
        converter_artifact = str(metadata_payload.get("converter_script_artifact") or "").strip()
        if require_full_contract and not converter_artifact:
            errors.append(
                {
                    "code": "missing_converter_artifact_reference",
                    "message": "metadata.converter_script_artifact is required for package-owned conversion",
                    "path": "metadata.converter_script_artifact",
                }
            )
        elif converter_artifact and converter_artifact not in artifact_paths:
            errors.append(
                {
                    "code": "missing_converter_artifact_payload",
                    "message": "metadata.converter_script_artifact must exist in artifacts",
                    "path": "metadata.converter_script_artifact",
                }
            )
    elif require_full_contract:
        errors.append(
            {
                "code": "missing_metadata_contract",
                "message": "metadata section is required for repository-grade packages",
                "path": "metadata",
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
        editor_artifact = str(
            editor_spec.get("artifact") or editor_spec.get("schema_artifact") or ""
        ).strip()
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

        for key, value in editor_spec.items():
            if not isinstance(key, str) or not key.endswith("_artifact"):
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
        detail="Unsupported scenario package format. Use .zip or .lbpkg",
    )


class ScenarioPackageRepository:
    def __init__(
        self,
        *,
        compile_package: Callable[[dict[str, Any]], dict[str, Any]],
        load_package: Callable[[dict[str, Any]], dict[str, Any]],
        get_current_package_payload: Callable[[], dict[str, Any] | None],
    ) -> None:
        self._compile_package = compile_package
        self._load_package = load_package
        self._get_current_package_payload = get_current_package_payload

    def _validate_import_payload(
        self,
        package_bytes: bytes,
        *,
        filename: str,
    ) -> tuple[int, dict[str, Any], dict[str, Any] | None]:
        package_payload = _parse_uploaded_scenario_package(package_bytes, filename)
        package_payload = _ensure_converter_contract_metadata(package_payload)
        self_contained_errors = _validate_self_contained_scenario_package(
            package_payload,
            require_full_contract=True,
        )
        if self_contained_errors:
            return (
                422,
                {
                    "ok": False,
                    "valid": False,
                    "errors": self_contained_errors,
                    "warnings": [],
                    "scenario_package": package_payload,
                    "compile": {"ok": False, "errors": self_contained_errors, "warnings": []},
                    "summary": {
                        "filename": filename,
                        "runner": str((package_payload.get("runner") or {}).get("kind", "unknown")),
                    },
                },
                package_payload,
            )

        compile_result = self._compile_package(package_payload)
        compile_ok = bool(compile_result.get("ok"))
        status_code = 200 if compile_ok else 422
        payload = {
            "ok": compile_ok,
            "valid": compile_ok,
            "errors": (
                compile_result.get("errors", [])
                if isinstance(compile_result, dict)
                else []
            ),
            "warnings": (
                compile_result.get("warnings", [])
                if isinstance(compile_result, dict)
                else []
            ),
            "scenario_package": package_payload,
            "compile": compile_result,
            "summary": {
                "filename": filename,
                "runner": str((package_payload.get("runner") or {}).get("kind", "unknown")),
            },
        }
        return status_code, payload, package_payload

    def validate_import_upload(
        self,
        package_bytes: bytes,
        *,
        filename: str,
    ) -> tuple[int, dict[str, Any]]:
        status_code, payload, _package_payload = self._validate_import_payload(
            package_bytes,
            filename=filename,
        )
        return status_code, payload

    def import_upload(
        self,
        package_bytes: bytes,
        *,
        filename: str,
    ) -> tuple[int, dict[str, Any]]:
        status_code, payload, package_payload = self._validate_import_payload(
            package_bytes,
            filename=filename,
        )
        if status_code != 200 or not isinstance(package_payload, dict):
            return status_code, payload

        forwarded = self._load_package(package_payload)
        forwarded_ok = bool(forwarded.get("ok"))
        return (200 if forwarded_ok else 422), {
            "ok": forwarded_ok,
            "valid": forwarded_ok,
            "errors": forwarded.get("errors", []),
            "warnings": payload.get("warnings", []),
            "scenario_package": package_payload,
            "compile": payload.get("compile"),
            "forwarded": forwarded,
        }

    def list_packages(self, *, q: str | None = None, tag: str | None = None) -> tuple[int, dict[str, Any]]:
        repo_dir = _scenario_package_repo_dir()
        index_payload = _load_scenario_repo_index()
        index_packages = index_payload.get("packages") if isinstance(index_payload, dict) else {}
        index_packages = index_packages if isinstance(index_packages, dict) else {}

        search_term = str(q or "").strip().lower()
        tag_term = str(tag or "").strip().lower()
        packages = []
        for path in sorted(repo_dir.glob("*.lbpkg"), key=lambda item: item.name.lower()):
            stat = path.stat()
            meta = index_packages.get(path.name)
            meta = meta if isinstance(meta, dict) else {}
            tags = [str(item).strip() for item in (meta.get("tags") or []) if str(item).strip()]
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
        return 200, {"ok": True, "repository_dir": str(repo_dir), "packages": packages}

    def save_package(self, payload: Any) -> tuple[int, dict[str, Any]]:
        raw = payload if isinstance(payload, dict) else {}
        package_payload = raw.get("package") if isinstance(raw.get("package"), dict) else None
        if not isinstance(package_payload, dict):
            package_payload = self._get_current_package_payload()
        if not isinstance(package_payload, dict):
            return 400, {"ok": False, "error": "No scenario package available to save"}

        package_payload = _normalize_to_self_contained_package(package_payload, source="repository-save")
        package_payload = _ensure_converter_contract_metadata(package_payload)
        self_contained_errors = _validate_self_contained_scenario_package(
            package_payload,
            require_full_contract=True,
        )
        if self_contained_errors:
            return 422, {
                "ok": False,
                "error": "Package is not self-contained",
                "errors": self_contained_errors,
            }

        suggested = str(raw.get("filename") or package_payload.get("name") or package_payload.get("id") or "package")
        filename = _safe_scenario_repo_filename(suggested, default_name="package")
        target = _scenario_package_repo_dir() / filename
        target.write_bytes(_build_scenario_package_archive_bytes(package_payload))

        tags = [
            str(item).strip()
            for item in (raw.get("tags") or package_payload.get("metadata", {}).get("tags") or [])
            if str(item).strip()
        ]
        version_notes = str(raw.get("version_notes") or package_payload.get("metadata", {}).get("version_notes") or "")
        notes = str(raw.get("notes") or "")
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
        return 200, {
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

    def copy_package(self, payload: Any) -> tuple[int, dict[str, Any]]:
        raw = payload if isinstance(payload, dict) else {}
        source_name = _safe_scenario_repo_filename(str(raw.get("source_filename") or ""), default_name="")
        target_name = _safe_scenario_repo_filename(str(raw.get("target_filename") or ""), default_name="")
        if not source_name or not target_name:
            return 400, {"ok": False, "error": "source_filename and target_filename are required"}

        repo_dir = _scenario_package_repo_dir()
        source_path = repo_dir / source_name
        target_path = repo_dir / target_name
        if not source_path.exists() or not source_path.is_file():
            return 404, {"ok": False, "error": "Source package not found"}

        target_path.write_bytes(source_path.read_bytes())
        index_payload = _load_scenario_repo_index()
        index_packages = index_payload.setdefault("packages", {})
        if isinstance(index_packages, dict) and source_name in index_packages:
            index_packages[target_name] = dict(index_packages.get(source_name) or {})
            _save_scenario_repo_index(index_payload)
        stat = target_path.stat()
        return 200, {
            "ok": True,
            "copied": {
                "name": target_path.name,
                "size": int(stat.st_size),
                "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat().replace("+00:00", "Z"),
            },
        }

    def list_templates(self) -> tuple[int, dict[str, Any]]:
        template_dir = _scenario_template_dir()
        templates = []
        for path in sorted(template_dir.glob("*.lbpkg"), key=lambda item: item.name.lower()):
            stat = path.stat()
            templates.append(
                {
                    "name": path.name,
                    "size": int(stat.st_size),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat().replace("+00:00", "Z"),
                }
            )
        return 200, {"ok": True, "template_dir": str(template_dir), "templates": templates}

    def create_from_template(self, payload: Any) -> tuple[int, dict[str, Any]]:
        raw = payload if isinstance(payload, dict) else {}
        template_name = _safe_scenario_repo_filename(str(raw.get("template_filename") or ""), default_name="")
        if not template_name:
            return 400, {"ok": False, "error": "template_filename is required"}

        suggested = str(raw.get("filename") or raw.get("target_filename") or "")
        if not suggested:
            suggested = f"{Path(template_name).stem}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.lbpkg"
        target_name = _safe_scenario_repo_filename(suggested, default_name="")
        if not target_name:
            return 400, {"ok": False, "error": "filename is required"}
        if target_name == template_name:
            return 400, {"ok": False, "error": "Target filename must differ from template filename"}

        template_path = _scenario_template_dir() / template_name
        target_path = _scenario_package_repo_dir() / target_name
        if not template_path.is_file():
            return 404, {"ok": False, "error": "Template package not found"}
        if target_path.exists():
            return 409, {"ok": False, "error": "Target package already exists"}

        package_payload = _parse_uploaded_scenario_package(template_path.read_bytes(), template_name)
        package_payload = _normalize_to_self_contained_package(package_payload, source="repository-template")
        package_payload = _ensure_converter_contract_metadata(package_payload)
        self_contained_errors = _validate_self_contained_scenario_package(
            package_payload,
            require_full_contract=True,
        )
        if self_contained_errors:
            return 422, {
                "ok": False,
                "error": "Template package is not self-contained",
                "errors": self_contained_errors,
            }

        target_path.write_bytes(_build_scenario_package_archive_bytes(package_payload))
        index_payload = _load_scenario_repo_index()
        index_packages = index_payload.setdefault("packages", {})
        if isinstance(index_packages, dict):
            index_packages[target_name] = {
                "tags": ["template-instance"],
                "version_notes": "",
                "notes": f"Created from template {template_name}",
            }
            _save_scenario_repo_index(index_payload)

        stat = target_path.stat()
        return 200, {
            "ok": True,
            "created": {
                "name": target_path.name,
                "size": int(stat.st_size),
                "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat().replace("+00:00", "Z"),
                "template": template_name,
            },
        }

    def import_package(self, payload: Any) -> tuple[int, dict[str, Any]]:
        raw = payload if isinstance(payload, dict) else {}
        filename = _safe_scenario_repo_filename(str(raw.get("filename") or ""), default_name="")
        if not filename:
            return 400, {"ok": False, "error": "filename is required"}

        package_path = _scenario_package_repo_dir() / filename
        if not package_path.exists() or not package_path.is_file():
            return 404, {"ok": False, "error": "Package not found in repository"}

        package_payload = _parse_uploaded_scenario_package(package_path.read_bytes(), filename)
        package_payload = _ensure_converter_contract_metadata(package_payload)
        self_contained_errors = _validate_self_contained_scenario_package(
            package_payload,
            require_full_contract=True,
        )
        if self_contained_errors:
            return 422, {
                "ok": False,
                "valid": False,
                "errors": self_contained_errors,
                "warnings": [],
                "scenario_package": package_payload,
                "compile": {"ok": False, "errors": self_contained_errors, "warnings": []},
                "summary": {"filename": filename, "repository_import": True},
            }

        compile_result = self._compile_package(package_payload)
        if not compile_result.get("ok"):
            return 422, {
                "ok": False,
                "valid": False,
                "errors": compile_result.get("errors", []) or [{"code": "compile_failed", "message": "Compile failed"}],
                "warnings": compile_result.get("warnings", []),
                "scenario_package": package_payload,
                "compile": compile_result,
                "summary": {"filename": filename, "repository_import": True},
            }

        forwarded = self._load_package(package_payload)
        status_code = 200 if forwarded.get("ok") else 422
        return status_code, {
            "ok": 200 <= status_code < 300,
            "valid": bool(forwarded.get("ok")),
            "errors": forwarded.get("errors", []),
            "warnings": compile_result.get("warnings", []),
            "scenario_package": package_payload,
            "compile": compile_result,
            "forwarded": forwarded,
            "summary": {"filename": filename, "repository_import": True},
        }

    def update_metadata(self, payload: Any) -> tuple[int, dict[str, Any]]:
        raw = payload if isinstance(payload, dict) else {}
        filename = _safe_scenario_repo_filename(str(raw.get("filename") or ""), default_name="")
        if not filename:
            return 400, {"ok": False, "error": "filename is required"}

        package_path = _scenario_package_repo_dir() / filename
        if not package_path.exists() or not package_path.is_file():
            return 404, {"ok": False, "error": "Package not found"}

        tags = [str(item).strip() for item in (raw.get("tags") or []) if str(item).strip()]
        version_notes = str(raw.get("version_notes") or "")
        notes = str(raw.get("notes") or "")
        index_payload = _load_scenario_repo_index()
        index_packages = index_payload.setdefault("packages", {})
        if isinstance(index_packages, dict):
            index_packages[filename] = {
                "tags": tags,
                "version_notes": version_notes,
                "notes": notes,
            }
            _save_scenario_repo_index(index_payload)

        return 200, {
            "ok": True,
            "updated": {
                "name": filename,
                "tags": tags,
                "version_notes": version_notes,
                "notes": notes,
            },
        }

    def rename_package(self, payload: Any) -> tuple[int, dict[str, Any]]:
        raw = payload if isinstance(payload, dict) else {}
        source_name = _safe_scenario_repo_filename(str(raw.get("source_filename") or ""), default_name="")
        target_name = _safe_scenario_repo_filename(str(raw.get("target_filename") or ""), default_name="")
        if not source_name or not target_name:
            return 400, {"ok": False, "error": "source_filename and target_filename are required"}

        repo_dir = _scenario_package_repo_dir()
        source_path = repo_dir / source_name
        target_path = repo_dir / target_name
        if not source_path.exists() or not source_path.is_file():
            return 404, {"ok": False, "error": "Source package not found"}
        if target_path.exists():
            return 409, {"ok": False, "error": "Target package already exists"}

        source_path.replace(target_path)
        index_payload = _load_scenario_repo_index()
        index_packages = index_payload.setdefault("packages", {})
        if isinstance(index_packages, dict) and source_name in index_packages:
            index_packages[target_name] = dict(index_packages.pop(source_name) or {})
            _save_scenario_repo_index(index_payload)

        stat = target_path.stat()
        return 200, {
            "ok": True,
            "renamed": {
                "name": target_name,
                "size": int(stat.st_size),
                "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat().replace("+00:00", "Z"),
            },
        }

    def delete_package(self, filename: str) -> tuple[int, dict[str, Any]]:
        safe_name = _safe_scenario_repo_filename(filename, default_name="")
        if not safe_name:
            return 400, {"ok": False, "error": "filename is required"}

        target = _scenario_package_repo_dir() / safe_name
        if not target.exists() or not target.is_file():
            return 404, {"ok": False, "error": "Package not found"}

        target.unlink()
        index_payload = _load_scenario_repo_index()
        index_packages = index_payload.setdefault("packages", {})
        if isinstance(index_packages, dict) and safe_name in index_packages:
            index_packages.pop(safe_name, None)
            _save_scenario_repo_index(index_payload)
        return 200, {"ok": True, "deleted": safe_name}

    def download_package_path(self, filename: str) -> Path:
        safe_name = _safe_scenario_repo_filename(filename, default_name="")
        if not safe_name:
            raise HTTPException(status_code=400, detail="filename is required")
        target = _scenario_package_repo_dir() / safe_name
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="Package not found")
        return target

    def read_package(self, filename: str) -> tuple[int, dict[str, Any]]:
        safe_name = _safe_scenario_repo_filename(filename, default_name="")
        if not safe_name:
            return 400, {"ok": False, "error": "filename is required"}

        package_path = _scenario_package_repo_dir() / safe_name
        if not package_path.exists() or not package_path.is_file():
            return 404, {"ok": False, "error": "Package not found"}

        package_payload = _parse_uploaded_scenario_package(package_path.read_bytes(), safe_name)
        return 200, {"ok": True, "filename": safe_name, "scenario_package": package_payload}

    def upload_package(
        self,
        package_bytes: bytes,
        *,
        upload_filename: str,
        requested_filename: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        if not package_bytes:
            return 400, {"ok": False, "error": "Uploaded package file is empty"}

        try:
            package_payload = _parse_uploaded_scenario_package(package_bytes, upload_filename)
        except HTTPException as exc:
            return exc.status_code, {"ok": False, "error": str(exc.detail)}

        package_payload = _normalize_to_self_contained_package(package_payload, source="repository-upload")
        package_payload = _ensure_converter_contract_metadata(package_payload)
        self_contained_errors = _validate_self_contained_scenario_package(
            package_payload,
            require_full_contract=True,
        )
        if self_contained_errors:
            return 422, {
                "ok": False,
                "valid": False,
                "errors": self_contained_errors,
                "warnings": [],
                "scenario_package": package_payload,
                "compile": {"ok": False, "errors": self_contained_errors, "warnings": []},
            }

        compile_result = self._compile_package(package_payload)
        if not compile_result.get("ok"):
            return 422, {
                "ok": False,
                "valid": False,
                "errors": compile_result.get("errors", []) or [{"code": "compile_failed", "message": "Compile failed"}],
                "warnings": compile_result.get("warnings", []),
                "scenario_package": package_payload,
                "compile": compile_result,
            }

        suggested = str(requested_filename or upload_filename or package_payload.get("id") or package_payload.get("name") or "uploaded-package")
        filename = _safe_scenario_repo_filename(suggested, default_name="uploaded-package")
        target = _scenario_package_repo_dir() / filename
        target.write_bytes(_build_scenario_package_archive_bytes(package_payload))

        metadata_payload = package_payload.get("metadata")
        metadata_payload = metadata_payload if isinstance(metadata_payload, dict) else {}
        tags = [str(item).strip() for item in (metadata_payload.get("tags") or []) if str(item).strip()]
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
        return 200, {
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

    def package_file_action(
        self,
        workbook_bytes: bytes,
        *,
        workbook_filename: str,
        options: Mapping[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        if not workbook_bytes:
            return 400, {"ok": False, "error": "Uploaded Excel file is empty"}

        payload_raw = {
            "filename": (options or {}).get("filename") or workbook_filename or "excel-converted",
            "name": (options or {}).get("name") or "",
            "id": (options or {}).get("id") or "",
            "version": (options or {}).get("version") or "",
            "description": (options or {}).get("description") or "",
            "version_notes": (options or {}).get("version_notes") or "",
            "tags": [item for item in str((options or {}).get("tags") or "").split(",") if item.strip()],
        }

        target_filename = _safe_scenario_repo_filename(str(payload_raw["filename"] or ""), default_name="")
        try:
            source_package_path = _resolve_converter_source_package(target_filename=target_filename)
        except FileNotFoundError as exc:
            return 400, {
                "ok": False,
                "valid": False,
                "error": "Missing converter source package",
                "errors": [{"code": "converter_source_not_selected", "message": str(exc)}],
            }

        try:
            source_package_payload = _parse_uploaded_scenario_package(
                source_package_path.read_bytes(),
                source_package_path.name,
            )
            source_runner_artifact = _resolve_package_runner_artifact(source_package_payload)
            source_converter_artifact = _resolve_package_converter_artifact(source_package_payload)
        except Exception as exc:
            return 422, {
                "ok": False,
                "valid": False,
                "error": "Source package does not declare required runtime artifacts",
                "errors": [{"code": "source_package_contract_invalid", "message": str(exc)}],
                "source_package": source_package_path.name,
            }

        try:
            program_payload = _parse_program_with_package_converter(
                workbook_bytes,
                package_path=source_package_path,
                converter_artifact=source_converter_artifact,
                filename=workbook_filename,
            )
        except Exception as exc:
            return 422, {
                "ok": False,
                "valid": False,
                "error": "Failed to parse workbook with package converter",
                "errors": [{"code": "package_converter_parse_failed", "message": str(exc)}],
                "source_package": source_package_path.name,
            }

        package_defaults = program_payload.get("package_defaults") if isinstance(program_payload, dict) else {}
        package_defaults = package_defaults if isinstance(package_defaults, dict) else {}
        resolved_id = str(
            payload_raw["id"]
            or package_defaults.get("id")
            or program_payload.get("id")
            or Path(workbook_filename or "scenario").stem.replace(" ", "-").lower()
            or "scenario-package"
        )
        resolved_name = str(
            payload_raw["name"]
            or package_defaults.get("name")
            or program_payload.get("name")
            or Path(workbook_filename or "Scenario").stem
            or "Scenario Package"
        )
        resolved_version = str(payload_raw["version"] or package_defaults.get("version") or "0.1.0")
        resolved_description = str(
            payload_raw["description"]
            or package_defaults.get("description")
            or f"Excel-converted package from {workbook_filename or 'workbook.xlsx'}"
        )
        meta_tags = [str(item).strip() for item in (package_defaults.get("tags") or []) if str(item).strip()]
        resolved_tags = [str(item).strip() for item in (payload_raw["tags"] or meta_tags) if str(item).strip()]

        try:
            package_payload = _exec_package_converter(
                package_path=source_package_path,
                runner_artifact=source_runner_artifact,
                converter_artifact=source_converter_artifact,
                package_id=resolved_id,
                package_name=resolved_name,
                version=resolved_version,
                description=resolved_description,
                tags=resolved_tags,
                version_notes=str(payload_raw["version_notes"] or ""),
                program_payload=dict(program_payload or {}),
                source_workbook_bytes=workbook_bytes,
                source_workbook_name=workbook_filename,
            )
        except Exception as exc:
            return 422, {
                "ok": False,
                "valid": False,
                "error": "Failed to build package with package converter",
                "errors": [{"code": "package_converter_build_failed", "message": str(exc)}],
                "source_package": source_package_path.name,
            }

        package_payload = _normalize_to_self_contained_package(package_payload, source="repository-package-file-action")
        metadata_payload = package_payload.get("metadata")
        if not isinstance(metadata_payload, dict):
            metadata_payload = {}
        metadata_payload["converter_script_artifact"] = source_converter_artifact
        package_payload["metadata"] = metadata_payload

        self_contained_errors = _validate_self_contained_scenario_package(
            package_payload,
            require_full_contract=True,
        )
        if self_contained_errors:
            return 422, {
                "ok": False,
                "valid": False,
                "error": "Package converter output is not self-contained",
                "errors": self_contained_errors,
                "source_package": source_package_path.name,
            }

        compile_result = self._compile_package(package_payload)
        if not compile_result.get("ok"):
            return 422, {
                "ok": False,
                "valid": False,
                "errors": compile_result.get("errors", []) or [{"code": "compile_failed", "message": "Compile failed"}],
                "warnings": compile_result.get("warnings", []),
                "scenario_package": package_payload,
                "compile": compile_result,
            }

        suggested = str(payload_raw["filename"] or package_payload.get("name") or package_payload.get("id") or "excel-package")
        filename = _safe_scenario_repo_filename(suggested, default_name="excel-package")
        target = _scenario_package_repo_dir() / filename
        target.write_bytes(_build_scenario_package_archive_bytes(package_payload))

        index_payload = _load_scenario_repo_index()
        index_packages = index_payload.setdefault("packages", {})
        tags = [str(item).strip() for item in resolved_tags if str(item).strip()]
        version_notes = str(payload_raw["version_notes"] or "")
        if isinstance(index_packages, dict):
            index_packages[filename] = {
                "tags": tags,
                "version_notes": version_notes,
                "notes": f"Converted from {workbook_filename or 'Excel workbook'}",
            }
            _save_scenario_repo_index(index_payload)

        stat = target.stat()
        return 200, {
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
        }