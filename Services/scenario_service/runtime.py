from __future__ import annotations

import base64
import binascii
import json
import threading
import time
from typing import Any

from .models import (
    QueueEntry,
    ScenarioCompileIssue,
    ScenarioPackageDefinition,
    ScenarioRunStatus,
)
from .package_repository import ScenarioPackageRepository
from .repository import InMemoryScenarioRepository, JsonScenarioStateStore
from .scripted_runner import ScriptedRunner


class ScenarioRuntime:
    """Scenario runtime facade.

    Scripted-only runtime:
    - ``scripted``: loads and executes a Python script from the package archive.
    """

    def __init__(
        self,
        *,
        control_client,
        data_client,
        repository: InMemoryScenarioRepository | None = None,
        state_store: JsonScenarioStateStore | None = None,
        owner: str = "scenario_service",
    ) -> None:
        self._control_client = control_client
        self._data_client = data_client
        self._owner = owner
        self.repository = repository or InMemoryScenarioRepository()
        self.state_store = state_store or JsonScenarioStateStore()
        self.package_repository = ScenarioPackageRepository(
            compile_package=self.compile_package,
            load_package=self.load_package,
            get_current_package_payload=lambda: (
                self.repository.get_current().to_dict()
                if self.repository.get_current() is not None
                else None
            ),
        )
        self._lock = threading.RLock()
        self._status = ScenarioRunStatus(runner_kind="scripted")
        self._scripted_runner: ScriptedRunner | None = None
        self._active_runner_kind: str = "scripted"
        self._queue: list[QueueEntry] = []
        self._queue_enabled: bool = True
        self._queue_advance_on_stop: bool = False
        self._queue_pause_wait_timeout_s: float = 5.0
        self._queue_pause_wait_poll_s: float = 0.2
        self._restore_from_store()

    # ------------------------------------------------------------------ lifecycle

    def start_background(self) -> None:
        """No background tick; kept for service API compatibility."""

    def shutdown(self) -> None:
        if self._scripted_runner is not None:
            self._scripted_runner.shutdown()

    # ------------------------------------------------------------------ package API

    def compile_package(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            payload = {}
        package = ScenarioPackageDefinition.from_payload(payload)
        issues: list[ScenarioCompileIssue] = []
        normalized_program: dict[str, Any] = {}

        raw_id = str(payload.get("id") or "").strip()
        raw_name = str(payload.get("name") or "").strip()
        if not raw_id:
            issues.append(
                ScenarioCompileIssue(
                    level="error",
                    code="package_id_missing",
                    message="Package id is required and cannot be blank",
                    path="id",
                )
            )
        if not raw_name:
            issues.append(
                ScenarioCompileIssue(
                    level="error",
                    code="package_name_missing",
                    message="Package name is required and cannot be blank",
                    path="name",
                )
            )

        artifact_by_path = {
            str(item.get("path", "")).strip(): item
            for item in package.artifacts
            if str(item.get("path", "")).strip()
        }

        validation_artifact = str(
            (package.validation or {}).get("artifact")
            or (package.validation or {}).get("spec_artifact")
            or ""
        ).strip()
        if validation_artifact:
            if validation_artifact not in artifact_by_path:
                issues.append(
                    ScenarioCompileIssue(
                        level="error",
                        code="validation_artifact_not_found",
                        message=(
                            f"validation artifact '{validation_artifact}' was not found "
                            "in package.artifacts"
                        ),
                        path="validation.artifact",
                    )
                )
        else:
            issues.append(
                ScenarioCompileIssue(
                    level="error",
                    code="validation_artifact_missing",
                    message=(
                        "validation.artifact is required so validation instructions "
                        "live inside package binaries"
                    ),
                    path="validation.artifact",
                )
            )

        editor_artifact = str(
            (package.editor_spec or {}).get("artifact")
            or (package.editor_spec or {}).get("schema_artifact")
            or ""
        ).strip()
        if not editor_artifact:
            issues.append(
                ScenarioCompileIssue(
                    level="error",
                    code="editor_spec_artifact_missing",
                    message="Package editor_spec.artifact is required",
                    path="editor_spec.artifact",
                )
            )
        elif editor_artifact not in artifact_by_path:
            issues.append(
                ScenarioCompileIssue(
                    level="error",
                    code="editor_spec_artifact_not_found",
                    message=(
                        f"editor spec artifact '{editor_artifact}' was not found "
                        "in package.artifacts"
                    ),
                    path="editor_spec.artifact",
                )
            )

        interface_kind = str(package.interface.get("kind", "") or "").strip()
        interface_version = str(package.interface.get("version", "") or "").strip()
        if not interface_kind:
            issues.append(
                ScenarioCompileIssue(
                    level="error",
                    code="interface_kind_missing",
                    message="Package interface.kind is required",
                    path="interface.kind",
                )
            )
        if not interface_version:
            issues.append(
                ScenarioCompileIssue(
                    level="error",
                    code="interface_version_missing",
                    message="Package interface.version is required",
                    path="interface.version",
                )
            )

        endpoint_language = str(package.endpoint_code.get("language", "") or "").strip()
        endpoint_entrypoint = str(package.endpoint_code.get("entrypoint", "") or "").strip()
        if not endpoint_language:
            issues.append(
                ScenarioCompileIssue(
                    level="error",
                    code="endpoint_language_missing",
                    message="Package endpoint_code.language is required",
                    path="endpoint_code.language",
                )
            )
        elif endpoint_language.lower() != "python":
            issues.append(
                ScenarioCompileIssue(
                    level="error",
                    code="endpoint_language_unsupported",
                    message="Package endpoint_code.language must be 'python'",
                    path="endpoint_code.language",
                )
            )
        if not endpoint_entrypoint:
            issues.append(
                ScenarioCompileIssue(
                    level="error",
                    code="endpoint_entrypoint_missing",
                    message="Package endpoint_code.entrypoint is required",
                    path="endpoint_code.entrypoint",
                )
            )

        required_fields = package.validation.get("required_fields")
        if isinstance(required_fields, list):
            for item in required_fields:
                field_name = str(item or "").strip()
                if not field_name:
                    continue
                value = payload.get(field_name)
                if value in (None, "", [], {}):
                    issues.append(
                        ScenarioCompileIssue(
                            level="error",
                            code="required_field_missing",
                            message=(
                                "validation.required_fields requires non-empty "
                                f"'{field_name}'"
                            ),
                            path=field_name,
                        )
                    )

        runner_kind = "scripted"
        incoming_runner_kind = str(
            ((payload.get("runner") or {}) if isinstance(payload.get("runner"), dict) else {}).get("kind")
            or package.runner.kind
            or ""
        ).strip().lower()
        if incoming_runner_kind and incoming_runner_kind != "scripted":
            issues.append(
                ScenarioCompileIssue(
                    level="error",
                    code="runner_kind_unsupported",
                    message=(
                        f"runner.kind='{incoming_runner_kind}' is unsupported; "
                        "scenario_service requires runner.kind='scripted'"
                    ),
                    path="runner.kind",
                )
            )

        # The script entrypoint IS the run artifact — must be present in archive.
        entrypoint = str(package.endpoint_code.get("entrypoint", "") or "").strip()
        if not entrypoint:
            issues.append(
                ScenarioCompileIssue(
                    level="error",
                    code="entrypoint_missing",
                    message=(
                        "endpoint_code.entrypoint is required for scripted runner"
                    ),
                    path="endpoint_code.entrypoint",
                )
            )
        elif entrypoint not in artifact_by_path:
            issues.append(
                ScenarioCompileIssue(
                    level="error",
                    code="entrypoint_not_found",
                    message=f"entrypoint '{entrypoint}' was not found in package.artifacts",
                    path="endpoint_code.entrypoint",
                )
            )

        errors = [issue.to_dict() for issue in issues if issue.level == "error"]
        warnings = [issue.to_dict() for issue in issues if issue.level == "warning"]

        return {
            "ok": not errors,
            "runner": runner_kind,
            "interface": {
                "kind": interface_kind,
                "version": interface_version,
            },
            "errors": errors,
            "warnings": warnings,
            "normalized_program": normalized_program,
        }

    def load_package(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            package = ScenarioPackageDefinition.from_payload(payload)
            compiled = self.compile_package(package.to_dict())
            if not compiled.get("ok", False):
                return {
                    "ok": False,
                    "errors": compiled.get("errors", []),
                    "warnings": compiled.get("warnings", []),
                }

            self.repository.save(package)
            self._status.package_id = package.id
            self._status.package_name = package.name
            self._status.runner_kind = "scripted"
            self._status.details = {
                "version": package.version,
                "description": package.description,
                "interface": dict(package.interface),
                "validation": dict(package.validation),
                "editor_spec": dict(package.editor_spec),
                "endpoint_code": {
                    "language": package.endpoint_code.get("language"),
                    "entrypoint": package.endpoint_code.get("entrypoint"),
                },
                "metadata": dict(package.metadata),
            }

            artifact_by_path = {
                str(item.get("path", "")).strip(): item
                for item in package.artifacts
                if str(item.get("path", "")).strip()
            }
            entrypoint = str(package.endpoint_code.get("entrypoint", "") or "").strip()
            artifact_item = artifact_by_path.get(entrypoint, {})
            entrypoint_code = base64.b64decode(artifact_item.get("content_b64", ""))
            if self._scripted_runner is not None:
                self._scripted_runner.shutdown()
            self._scripted_runner = ScriptedRunner(
                entrypoint_code=entrypoint_code,
                artifacts=package.artifacts,
                control_client=self._control_client,
                data_client=self._data_client,
                owner=self._owner,
                package_id=package.id,
                package_program=package.program,
                package_snapshot=package.to_dict(),
            )
            self._scripted_runner._on_run_end = self._on_run_ended
            self._active_runner_kind = "scripted"

            self._append_event(f"Loaded package {package.name}")
            self._sync_status_from_runner_locked()
            self._persist_locked()
            return {
                "ok": True,
                "package": package.to_dict(),
                "compile": compiled,
            }

    def get_package(self) -> dict[str, Any]:
        package = self.repository.get_current()
        return {
            "ok": True,
            "package": package.to_dict() if package else None,
        }

    def tune_package(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Patch the currently loaded package and reload it.

        Supported mutations:
        - ``artifact_updates``: list of {path, content_b64, media_type?}
        - ``editor_spec_patch``: shallow merge into package.editor_spec
        - ``metadata_patch``: shallow merge into package.metadata
        """
        with self._lock:
            package = self.repository.get_current()
            if package is None:
                return {"ok": False, "error": "No package loaded"}

            runner = self._active_runner()
            if runner is not None:
                state = str((runner.status() or {}).get("state", "idle"))
                if state in {"running", "paused"}:
                    return {
                        "ok": False,
                        "error": "Cannot tune package while run is active",
                        "state": state,
                    }

            if not isinstance(payload, dict):
                payload = {}

            updated = package.to_dict()
            artifacts = list(updated.get("artifacts") or [])
            path_index = {
                str(item.get("path", "")).strip(): idx
                for idx, item in enumerate(artifacts)
                if isinstance(item, dict) and str(item.get("path", "")).strip()
            }

            updates = payload.get("artifact_updates")
            if updates is not None and not isinstance(updates, list):
                return {"ok": False, "error": "artifact_updates must be a list"}

            for item in updates or []:
                if not isinstance(item, dict):
                    return {
                        "ok": False,
                        "error": "Each artifact update must be an object",
                    }
                path = str(item.get("path") or "").strip()
                content_b64 = str(item.get("content_b64") or "").strip()
                if not path:
                    return {
                        "ok": False,
                        "error": "artifact_updates.path is required",
                    }
                if not content_b64:
                    return {
                        "ok": False,
                        "error": f"artifact '{path}' is missing content_b64",
                    }
                try:
                    raw = base64.b64decode(content_b64, validate=True)
                except (binascii.Error, ValueError):
                    return {
                        "ok": False,
                        "error": f"artifact '{path}' content_b64 is not valid base64",
                    }

                media_type = str(item.get("media_type") or "").strip()
                replacement = {
                    "path": path,
                    "encoding": "base64",
                    "content_b64": content_b64,
                    "size": len(raw),
                }
                if media_type:
                    replacement["media_type"] = media_type

                idx = path_index.get(path)
                if idx is None:
                    path_index[path] = len(artifacts)
                    artifacts.append(replacement)
                else:
                    merged = dict(artifacts[idx]) if isinstance(artifacts[idx], dict) else {}
                    merged.update(replacement)
                    artifacts[idx] = merged

            editor_spec_patch = payload.get("editor_spec_patch")
            if editor_spec_patch is not None:
                if not isinstance(editor_spec_patch, dict):
                    return {"ok": False, "error": "editor_spec_patch must be an object"}
                editor_spec = dict(updated.get("editor_spec") or {})
                editor_spec.update(editor_spec_patch)
                updated["editor_spec"] = editor_spec

                spec_artifact_path = str(
                    editor_spec.get("artifact") or editor_spec.get("schema_artifact") or ""
                ).strip()
                if spec_artifact_path:
                    spec_raw = json.dumps(editor_spec, ensure_ascii=False, indent=2).encode(
                        "utf-8"
                    )
                    spec_item = {
                        "path": spec_artifact_path,
                        "encoding": "base64",
                        "content_b64": base64.b64encode(spec_raw).decode("ascii"),
                        "size": len(spec_raw),
                        "media_type": "application/json",
                    }
                    idx = path_index.get(spec_artifact_path)
                    if idx is None:
                        path_index[spec_artifact_path] = len(artifacts)
                        artifacts.append(spec_item)
                    else:
                        merged = dict(artifacts[idx]) if isinstance(artifacts[idx], dict) else {}
                        merged.update(spec_item)
                        artifacts[idx] = merged

            metadata_patch = payload.get("metadata_patch")
            if metadata_patch is not None:
                if not isinstance(metadata_patch, dict):
                    return {"ok": False, "error": "metadata_patch must be an object"}
                metadata = dict(updated.get("metadata") or {})
                metadata.update(metadata_patch)
                updated["metadata"] = metadata

            package_patch = payload.get("package_patch")
            program_touched = False
            editor_spec_touched = editor_spec_patch is not None
            if package_patch is not None:
                if not isinstance(package_patch, dict):
                    return {"ok": False, "error": "package_patch must be an object"}

                program_touched = "program" in package_patch
                editor_spec_touched = editor_spec_touched or ("editor_spec" in package_patch)

                def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
                    for key, value in src.items():
                        if isinstance(value, dict) and isinstance(dst.get(key), dict):
                            _deep_merge(dst[key], value)
                        else:
                            dst[key] = value
                    return dst

                _deep_merge(updated, package_patch)

            program_payload = updated.get("program")
            if program_touched and isinstance(program_payload, dict):
                program_path = "data/program.json"
                program_idx = path_index.get(program_path)
                if program_idx is not None:
                    program_raw = json.dumps(program_payload, ensure_ascii=False, indent=2).encode(
                        "utf-8"
                    )
                    program_item = {
                        "path": program_path,
                        "encoding": "base64",
                        "content_b64": base64.b64encode(program_raw).decode("ascii"),
                        "size": len(program_raw),
                        "media_type": "application/json",
                    }
                    merged = (
                        dict(artifacts[program_idx])
                        if isinstance(artifacts[program_idx], dict)
                        else {}
                    )
                    merged.update(program_item)
                    artifacts[program_idx] = merged

            editor_spec = updated.get("editor_spec")
            if editor_spec_touched and isinstance(editor_spec, dict):
                spec_artifact_path = str(
                    editor_spec.get("artifact") or editor_spec.get("schema_artifact") or ""
                ).strip()
                if spec_artifact_path:
                    spec_raw = json.dumps(editor_spec, ensure_ascii=False, indent=2).encode(
                        "utf-8"
                    )
                    spec_item = {
                        "path": spec_artifact_path,
                        "encoding": "base64",
                        "content_b64": base64.b64encode(spec_raw).decode("ascii"),
                        "size": len(spec_raw),
                        "media_type": "application/json",
                    }
                    spec_idx = path_index.get(spec_artifact_path)
                    if spec_idx is None:
                        path_index[spec_artifact_path] = len(artifacts)
                        artifacts.append(spec_item)
                    else:
                        merged = (
                            dict(artifacts[spec_idx])
                            if isinstance(artifacts[spec_idx], dict)
                            else {}
                        )
                        merged.update(spec_item)
                        artifacts[spec_idx] = merged

            updated["artifacts"] = artifacts
            result = self.load_package(updated)
            if not result.get("ok"):
                return result

            touched_count = len(updates or [])
            if editor_spec_patch is not None:
                touched_count += 1
            if metadata_patch is not None:
                touched_count += 1
            self._append_event(f"Package tuned ({touched_count} update(s))")
            self._persist_locked()
            return {
                "ok": True,
                "package": result.get("package"),
                "compile": result.get("compile"),
            }

    def clear_package(self) -> dict[str, Any]:
        with self._lock:
            self.repository.clear()
            if self._scripted_runner is not None:
                self._scripted_runner.shutdown()
                self._scripted_runner = None
            self._active_runner_kind = "scripted"
            self._status = ScenarioRunStatus(runner_kind="scripted")
            self._append_event("Package cleared")
            self._persist_locked()
            return {"ok": True}

    # ------------------------------------------------------------------ run control

    def start_run(self, start_index: int | None = None) -> dict[str, Any]:
        with self._lock:
            runner = self._active_runner()
            if runner is None:
                return {"ok": False, "error": "No scripted package loaded"}
            result = runner.start_run(start_index=start_index)
            self._sync_status_from_runner_locked()
            self._persist_locked()
            return result

    def pause_run(self) -> dict[str, Any]:
        with self._lock:
            runner = self._active_runner()
            if runner is None:
                return {"ok": False, "error": "No scripted package loaded"}
            result = runner.pause_run()
            self._sync_status_from_runner_locked()
            self._persist_locked()
            return result

    def resume_run(self) -> dict[str, Any]:
        with self._lock:
            runner = self._active_runner()
            if runner is None:
                return {"ok": False, "error": "No scripted package loaded"}
            result = runner.resume_run()
            self._sync_status_from_runner_locked()
            self._persist_locked()
            return result

    def stop_run(self) -> dict[str, Any]:
        with self._lock:
            runner = self._active_runner()
            if runner is None:
                return {"ok": False, "error": "No scripted package loaded"}
            result = runner.stop_run()
            self._sync_status_from_runner_locked()
            self._persist_locked()
            return result

    # ------------------------------------------------------------------ queue management

    def get_queue(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "queue": [e.to_dict() for e in self._queue],
                "enabled": self._queue_enabled,
                "advance_on_stop": self._queue_advance_on_stop,
            }

    def set_queue(
        self,
        entries: list[dict],
        advance_on_stop: bool | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        """Replace queue order/flags, preserving embedded payload unless omitted.

        Queue updates from UI commonly omit ``package_payload`` for compact
        responses. When an incoming entry omits that field, the existing
        embedded payload for the matching queue entry is retained.

        To explicitly clear embedded payload for an entry, send
        ``package_payload: null`` in that entry.
        """
        with self._lock:
            previous_queue = list(self._queue)
            parsed: list[QueueEntry] = []
            for item in entries:
                if not isinstance(item, dict):
                    return {"ok": False, "error": "Each queue entry must be an object"}
                pkg_id = str(item.get("package_id") or "").strip()
                pkg_filename = str(item.get("package_filename") or "").strip()
                if not pkg_id and not pkg_filename:
                    return {
                        "ok": False,
                        "error": "Each queue entry requires package_id or package_filename",
                    }
                parsed_entry = QueueEntry.from_dict(item)
                # UI queue updates intentionally omit embedded package payload for
                # compact responses; keep the existing payload when the logical
                # queue item is being updated/reordered.
                if "package_payload" not in item and parsed_entry.package_payload is None:
                    prior = self._find_matching_queue_entry(previous_queue, parsed_entry)
                    if prior is not None and isinstance(prior.package_payload, dict):
                        parsed_entry.package_payload = dict(prior.package_payload)
                parsed.append(parsed_entry)
            self._queue = parsed
            if advance_on_stop is not None:
                self._queue_advance_on_stop = bool(advance_on_stop)
            if enabled is not None:
                self._queue_enabled = bool(enabled)
            self._persist_locked()
            return {
                "ok": True,
                "queue": [e.to_dict() for e in self._queue],
                "enabled": self._queue_enabled,
                "advance_on_stop": self._queue_advance_on_stop,
            }

    def _find_matching_queue_entry(
        self,
        candidates: list[QueueEntry],
        target: QueueEntry,
    ) -> QueueEntry | None:
        target_package_id = target.package_id
        target_package_filename = target.package_filename

        for candidate in candidates:
            if (
                candidate.package_id == target_package_id
                and candidate.package_filename == target_package_filename
                and candidate.label == target.label
                and candidate.run_index == target.run_index
            ):
                return candidate
        matches = [
            candidate
            for candidate in candidates
            if (
                candidate.package_id == target_package_id
                and candidate.package_filename == target_package_filename
                and candidate.run_index == target.run_index
            )
        ]
        if len(matches) == 1:
            return matches[0]
        if target_package_id and target_package_filename:
            matches = [
                candidate
                for candidate in candidates
                if (
                    candidate.package_id == target_package_id
                    and candidate.package_filename == target_package_filename
                )
            ]
            if len(matches) == 1:
                return matches[0]

        if target_package_id and not target_package_filename:
            matches = [
                candidate
                for candidate in candidates
                if candidate.package_id and candidate.package_id == target_package_id
            ]
            if len(matches) == 1:
                return matches[0]

        if target_package_filename and not target_package_id:
            matches = [
                candidate
                for candidate in candidates
                if (
                    candidate.package_filename
                    and candidate.package_filename == target_package_filename
                )
            ]
            if len(matches) == 1:
                return matches[0]
        return None

    def enqueue(
        self,
        entry: dict,
        advance_on_stop: bool | None = None,
        queue_enabled: bool | None = None,
    ) -> dict[str, Any]:
        """Append one entry to the end of the queue."""
        if not isinstance(entry, dict):
            return {"ok": False, "error": "Entry must be an object"}
        pkg_id = str(entry.get("package_id") or "").strip()
        pkg_filename = str(entry.get("package_filename") or "").strip()
        if not pkg_id and not pkg_filename:
            return {"ok": False, "error": "Entry requires package_id or package_filename"}
        with self._lock:
            self._queue.append(QueueEntry.from_dict(entry))
            if advance_on_stop is not None:
                self._queue_advance_on_stop = bool(advance_on_stop)
            if queue_enabled is not None:
                self._queue_enabled = bool(queue_enabled)
            self._persist_locked()
            return {
                "ok": True,
                "queue": [e.to_dict() for e in self._queue],
                "enabled": self._queue_enabled,
                "advance_on_stop": self._queue_advance_on_stop,
            }

    def dequeue(self, index: int) -> dict[str, Any]:
        """Remove the entry at the given 0-based index."""
        with self._lock:
            if index < 0 or index >= len(self._queue):
                return {"ok": False, "error": f"Index {index} out of range"}
            removed = self._queue.pop(index)
            self._persist_locked()
            return {
                "ok": True,
                "removed": removed.to_dict(),
                "queue": [e.to_dict() for e in self._queue],
                "enabled": self._queue_enabled,
                "advance_on_stop": self._queue_advance_on_stop,
            }

    def clear_queue(self) -> dict[str, Any]:
        with self._lock:
            self._queue.clear()
            self._persist_locked()
            return {
                "ok": True,
                "queue": [],
                "enabled": self._queue_enabled,
                "advance_on_stop": self._queue_advance_on_stop,
            }

    def start_next_queued(self) -> dict[str, Any]:
        """Start the next enabled queued entry.

        Entry is only removed from the queue after load + start succeeds.
        """
        queued_from_paused = False
        blocked_targets: list[str] = []
        with self._lock:
            runner = self._active_runner()
            if runner is not None:
                runner_status = runner.status() or {}
                runner_state = str(runner_status.get("state", "idle"))
                if runner_state == "running":
                    return {
                        "ok": False,
                        "error": "Cannot start next queued run while a run is active",
                        "state": runner_state,
                    }
                if runner_state == "paused":
                    pause_reason = str(runner_status.get("pause_reason") or "")
                    if not pause_reason.startswith("control_lost:"):
                        return {
                            "ok": False,
                            "error": "Cannot start next queued run while a run is paused",
                            "state": runner_state,
                        }
                    blocked_targets = [
                        str(target).strip()
                        for target in (runner_status.get("owned_targets") or [])
                        if str(target).strip()
                    ]
            if not self._queue:
                return {"ok": False, "error": "Queue is empty"}
            if not self._queue_enabled:
                return {
                    "ok": False,
                    "error": "Queue is disabled",
                }
            enabled_index = next((idx for idx, entry in enumerate(self._queue) if entry.enabled), None)
            if enabled_index is None:
                return {
                    "ok": False,
                    "error": "Queue has no enabled entries",
                }
            next_entry = self._queue[enabled_index]

        if runner is not None and runner_state == "paused":
            still_blocked, wait_error = self._wait_for_targets_release(blocked_targets)
            if wait_error:
                with self._lock:
                    self._append_event(
                        f"Queue: ownership check failed before stepping ({wait_error})"
                    )
                    self._persist_locked()
                return {
                    "ok": False,
                    "error": f"Failed to verify control ownership before continuing queue: {wait_error}",
                    "state": runner_state,
                }
            if still_blocked:
                with self._lock:
                    self._append_event(
                        "Queue: waiting for control release before stepping"
                    )
                    self._persist_locked()
                return {
                    "ok": False,
                    "error": "Cannot continue queue while control targets are still owned",
                    "state": runner_state,
                    "blocked_targets": still_blocked,
                }
            queued_from_paused = True
            with self._lock:
                self._append_event("Queue: replacing paused run after control release")

        try:
            pkg_data = dict(next_entry.package_payload or {})
            if not pkg_data:
                with self._lock:
                    self._append_event(
                        f"Queue: package '{next_entry.package_id or next_entry.package_filename}' is missing embedded package data"
                    )
                    self._persist_locked()
                return {
                    "ok": False,
                    "error": "Queue entry is missing embedded package data",
                }

            load_result = self.load_package(pkg_data)
            if not load_result.get("ok"):
                errs = load_result.get("errors", [])
                message = (
                    errs[0].get("message", "compile error")
                    if errs and isinstance(errs[0], dict)
                    else "compile error"
                )
                with self._lock:
                    self._append_event(
                        f"Queue: failed to load '{next_entry.package_id}' - {message}"
                    )
                    self._persist_locked()
                return {"ok": False, "error": message}

            start_index = (
                max(0, next_entry.run_index - 1)
                if next_entry.run_index is not None
                else None
            )
            with self._lock:
                self._append_event(
                    f"Queue: starting '{next_entry.label or next_entry.package_id}'"
                )
                if queued_from_paused:
                    self._status.pause_reason = None
            start_result = self.start_run(start_index=start_index)
            if not start_result.get("ok"):
                return start_result
            with self._lock:
                # Remove only after successful run start.
                if 0 <= enabled_index < len(self._queue):
                    current = self._queue[enabled_index]
                    if (
                        current.package_id == next_entry.package_id
                        and current.package_filename == next_entry.package_filename
                        and current.label == next_entry.label
                        and current.run_index == next_entry.run_index
                        and current.enabled == next_entry.enabled
                    ):
                        self._queue.pop(enabled_index)
                    else:
                        for i, queued in enumerate(self._queue):
                            if (
                                queued.package_id == next_entry.package_id
                                and queued.package_filename == next_entry.package_filename
                                and queued.label == next_entry.label
                                and queued.run_index == next_entry.run_index
                                and queued.enabled == next_entry.enabled
                            ):
                                self._queue.pop(i)
                                break
                self._persist_locked()
            return {
                "ok": True,
                "started": next_entry.to_dict(),
                "queue": [e.to_dict() for e in self._queue],
                "enabled": self._queue_enabled,
                "advance_on_stop": self._queue_advance_on_stop,
            }
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._append_event(f"Queue: failed to start next run: {exc}")
                self._persist_locked()
            return {"ok": False, "error": str(exc)}

    def _wait_for_targets_release(self, targets: list[str]) -> tuple[list[str], str | None]:
        watched_targets = [str(target).strip() for target in targets if str(target).strip()]
        if not watched_targets:
            return [], None

        deadline = time.monotonic() + max(0.0, float(self._queue_pause_wait_timeout_s))
        poll_interval = max(0.05, float(self._queue_pause_wait_poll_s))
        blocked_targets: list[str] = list(watched_targets)

        while True:
            try:
                ownership_snapshot = self._control_client.ownership()
            except Exception as exc:  # noqa: BLE001
                return watched_targets, str(exc)
            if not isinstance(ownership_snapshot, dict):
                return watched_targets, "ownership response was not an object"
            blocked_targets = []
            for target in watched_targets:
                meta = ownership_snapshot.get(target)
                owner = ""
                if isinstance(meta, dict):
                    owner = str(meta.get("owner") or "").strip()
                elif isinstance(meta, str):
                    owner = meta.strip()
                if owner and owner != self._owner:
                    blocked_targets.append(target)

            if not blocked_targets:
                return [], None

            if time.monotonic() >= deadline:
                return blocked_targets, None

            time.sleep(poll_interval)

    def _on_run_ended(self, final_state: str) -> None:
        """Called from the runner thread when a run finishes. Advances the queue if appropriate."""
        advance = False
        with self._lock:
            if not self._queue_enabled:
                advance = False
            elif final_state == "completed":
                advance = bool(self._queue)

        if not advance:
            with self._lock:
                self._sync_status_from_runner_locked()
                self._persist_locked()
            return

        result = self.start_next_queued()
        if not result.get("ok"):
            with self._lock:
                self._append_event(
                    f"Queue: auto-advance skipped ({result.get('error', 'unknown error')})"
                )
                self._sync_status_from_runner_locked()
                self._persist_locked()

    def next_step(self) -> dict[str, Any]:
        with self._lock:
            runner = self._active_runner()
            if runner is None:
                return {"ok": False, "error": "No scripted package loaded"}
            result = runner.next_step()
            self._sync_status_from_runner_locked()
            self._persist_locked()
            return result

    def previous_step(self) -> dict[str, Any]:
        with self._lock:
            runner = self._active_runner()
            if runner is None:
                return {"ok": False, "error": "No scripted package loaded"}
            result = runner.previous_step()
            self._sync_status_from_runner_locked()
            self._persist_locked()
            return result

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._sync_status_from_runner_locked()
            package = self.repository.get_current()
            runner_status = (
                self._active_runner().status()
                if self._active_runner() is not None
                else {
                    "state": "idle",
                    "phase": None,
                    "current_step_index": None,
                    "current_step_name": None,
                    "wait_message": "Idle",
                    "pause_reason": None,
                    "owned_targets": [],
                    "event_log": [],
                }
            )
            return {
                "ok": True,
                "status": self._status.to_dict(),
                "runner_status": runner_status,
                "package": package.to_dict() if package else None,
                "queue": [e.to_dict() for e in self._queue],
                "queue_enabled": self._queue_enabled,
                "queue_advance_on_stop": self._queue_advance_on_stop,
            }

    # ------------------------------------------------------------------ internals

    def _active_runner(self):
        """Return the loaded scripted runner, if any."""
        return self._scripted_runner

    def _append_event(self, text: str) -> None:
        self._status.event_log.append(text)
        self._status.event_log = self._status.event_log[-100:]

    def _sync_status_from_runner_locked(self) -> None:
        runner = self._active_runner()
        if runner is None:
            self._status.state = "idle"
            self._status.wait_message = "Idle"
            self._status.pause_reason = None
            self._status.owned_targets = []
            self._status.details["phase"] = None
            self._status.details["current_step_index"] = None
            self._status.details["current_step_name"] = None
            return

        runner_status = runner.status()
        self._status.state = str(runner_status.get("state", "idle"))
        self._status.wait_message = str(runner_status.get("wait_message", "Idle"))
        self._status.pause_reason = runner_status.get("pause_reason")
        self._status.owned_targets = [
            str(item) for item in (runner_status.get("owned_targets") or [])
        ]
        self._status.details["phase"] = runner_status.get("phase")
        self._status.details["current_step_index"] = runner_status.get("current_step_index")
        self._status.details["current_step_name"] = runner_status.get("current_step_name")

    def _persist_locked(self) -> None:
        package = self.repository.get_current()
        payload = {
            "package": package.to_dict() if package else None,
            "status": self._status.to_dict(),
            "queue": [e.to_dict(include_package_payload=True) for e in self._queue],
            "queue_enabled": self._queue_enabled,
            "queue_advance_on_stop": self._queue_advance_on_stop,
        }
        self.state_store.save(payload)

    def _restore_from_store(self) -> None:
        payload = self.state_store.load()
        if not isinstance(payload, dict):
            return

        package_payload = payload.get("package")
        if isinstance(package_payload, dict):
            package = ScenarioPackageDefinition.from_payload(package_payload)
            self.repository.save(package)
            self._status.package_id = package.id
            self._status.package_name = package.name
            self._status.runner_kind = "scripted"
            self._active_runner_kind = "scripted"

            artifact_by_path = {
                str(item.get("path", "")).strip(): item
                for item in package.artifacts
                if str(item.get("path", "")).strip()
            }
            entrypoint = str(package.endpoint_code.get("entrypoint", "") or "").strip()
            artifact_item = artifact_by_path.get(entrypoint, {})
            content_b64 = str(artifact_item.get("content_b64") or "")
            if entrypoint and content_b64:
                try:
                    entrypoint_code = base64.b64decode(content_b64)
                    if self._scripted_runner is not None:
                        self._scripted_runner.shutdown()
                    self._scripted_runner = ScriptedRunner(
                        entrypoint_code=entrypoint_code,
                        artifacts=package.artifacts,
                        control_client=self._control_client,
                        data_client=self._data_client,
                        owner=self._owner,
                        package_id=package.id,
                        package_program=package.program,
                        package_snapshot=package.to_dict(),
                    )
                    self._scripted_runner._on_run_end = self._on_run_ended
                except Exception as exc:  # noqa: BLE001
                    self._append_event(f"Failed to restore scripted runner: {exc}")
                    self._scripted_runner = None

        status_payload = payload.get("status")
        if isinstance(status_payload, dict):
            self._status.state = str(status_payload.get("state", self._status.state))
            self._status.wait_message = str(
                status_payload.get("wait_message", self._status.wait_message)
            )
            self._status.pause_reason = status_payload.get("pause_reason")
            self._status.event_log = [
                str(item) for item in (status_payload.get("event_log") or [])
            ][-100:]
            self._status.owned_targets = [
                str(item) for item in (status_payload.get("owned_targets") or [])
            ]
            details = status_payload.get("details")
            self._status.details = dict(details) if isinstance(details, dict) else {}

        queue_payload = payload.get("queue")
        if isinstance(queue_payload, list):
            try:
                self._queue = [
                    QueueEntry.from_dict(item)
                    for item in queue_payload
                    if isinstance(item, dict)
                    and (
                        str(item.get("package_id") or "").strip()
                        or str(item.get("package_filename") or "").strip()
                    )
                ]
            except Exception:  # noqa: BLE001
                self._queue = []
        self._queue_enabled = bool(payload.get("queue_enabled", True))
        self._queue_advance_on_stop = bool(payload.get("queue_advance_on_stop", False))

        if self._active_runner_kind == "scripted":
            # Script execution state itself cannot be resumed after process restart.
            # Keep package loaded but reset run state to idle for a clean restart.
            self._status.state = "idle"
            self._status.wait_message = "Restored package; run is idle"
            self._status.pause_reason = None
            self._status.owned_targets = []
            self._append_event("Scripted package restored; run reset to idle")
