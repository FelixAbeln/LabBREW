from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import msgpack
from fastapi import FastAPI
from fastapi.testclient import TestClient

from Services.scenario_service.api.routes_scenario import router as scenario_router
from Services.scenario_service.api.routes_scenario import set_runtime
from Services.scenario_service.package_repository import (
    _build_scenario_package_archive_bytes,
    _parse_uploaded_scenario_package,
    _validate_self_contained_scenario_package,
)
from Services.scenario_service.runtime import ScenarioRuntime


class _CC:
    def write(self, *_args, **_kwargs):
        return {"ok": True}

    def read(self, *_args, **_kwargs):
        return {"ok": True, "value": None, "current_owner": None}

    def release(self, *_args, **_kwargs):
        return {"ok": True}


class _DC:
    def snapshot(self, *_args, **_kwargs):
        return {"ok": True}

    def append(self, *_args, **_kwargs):
        return {"ok": True}


def _make_client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setattr(
        "Services.scenario_service.package_repository.storage_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    monkeypatch.setattr(
        "Services.scenario_service.repository.storage_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    runtime = ScenarioRuntime(control_client=_CC(), data_client=_DC())
    app = FastAPI()
    set_runtime(runtime)
    app.include_router(scenario_router)
    return TestClient(app)


def _make_scenario_lbpkg(
    manifest_override: dict | None = None,
    *,
    include_converter_artifact: bool = True,
) -> bytes:
    manifest: dict = {
        "id": "test-pkg",
        "name": "Test Package",
        "version": "0.1.0",
        "runner": {"kind": "scripted", "entrypoint": "scripted.run", "config": {}},
        "interface": {"kind": "labbrew.scenario-package", "version": "1"},
        "validation": {
            "artifact": "validation/validation.json",
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
        },
        "editor_spec": {"artifact": "editor/spec.json", "version": "1.0"},
        "endpoint_code": {"language": "python", "entrypoint": "bin/runner.py"},
        "program": {
            "setup_steps": [],
            "plan_steps": [],
            "measurement_config": {
                "hz": 10,
                "output_format": "parquet",
                "output_dir": "data/measurements",
            },
        },
    }
    if manifest_override:
        manifest.update(manifest_override)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("scenario.package.msgpack", msgpack.packb(manifest, use_bin_type=True))
        zf.writestr("bin/runner.py", b"# runner stub")
        if include_converter_artifact:
            zf.writestr("bin/excel_package_converter.py", b"# converter stub")
        zf.writestr("data/program.json", b"{}")
        zf.writestr("validation/validation.json", b"{}")
        zf.writestr("editor/spec.json", b"{}")
    return buf.getvalue()


def test_repository_upload_rejects_package_without_converter_contract(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)

    response = client.post(
        "/scenario/repository/upload-package",
        files={"file": ("test.lbpkg", _make_scenario_lbpkg(include_converter_artifact=False), "application/octet-stream")},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert any(issue.get("code") == "missing_converter_artifact_reference" for issue in body.get("errors", []))


def test_validate_import_rejects_json_format(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)

    for path in ["/scenario/validate-import", "/scenario/import"]:
        response = client.put(
            path,
            files={"file": ("plan.json", b'{"id": "x"}', "application/json")},
        )
        assert response.status_code == 415


def test_validate_import_accepts_valid_lbpkg(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)

    response = client.put(
        "/scenario/validate-import",
        files={"file": ("test.lbpkg", _make_scenario_lbpkg(), "application/octet-stream")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["valid"] is True
    assert body["errors"] == []


def test_import_accepts_valid_lbpkg(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)

    response = client.put(
        "/scenario/import",
        files={"file": ("test.lbpkg", _make_scenario_lbpkg(), "application/octet-stream")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["forwarded"]["ok"] is True


def test_validate_import_rejects_archive_without_manifest(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("README.txt", "no manifest here")

    response = client.put(
        "/scenario/validate-import",
        files={"file": ("empty.lbpkg", buf.getvalue(), "application/octet-stream")},
    )

    assert response.status_code == 422
    assert "msgpack" in response.json()["detail"].lower()


def test_validate_import_rejects_corrupt_msgpack(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("scenario.package.msgpack", b"\xff\xfe\xfd not valid msgpack")

    response = client.put(
        "/scenario/validate-import",
        files={"file": ("bad.lbpkg", buf.getvalue(), "application/octet-stream")},
    )

    assert response.status_code == 422
    assert "messagepack" in response.json()["detail"].lower()


def test_import_returns_422_on_compile_failure(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    bad_payload = _make_scenario_lbpkg(manifest_override={"id": ""})

    response = client.put(
        "/scenario/import",
        files={"file": ("test.lbpkg", bad_payload, "application/octet-stream")},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert any(e["code"] == "package_id_missing" for e in body["errors"])


def test_repository_create_from_template_outputs_self_contained_package(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    template_dir = tmp_path / "scenario_templates"
    template_dir.mkdir(parents=True, exist_ok=True)
    (template_dir / "excel-template.lbpkg").write_bytes(_make_scenario_lbpkg())

    create_response = client.post(
        "/scenario/repository/create-from-template",
        json={
            "template_filename": "excel-template.lbpkg",
            "filename": "excel-instance.lbpkg",
        },
    )

    assert create_response.status_code == 200
    created_path = tmp_path / "scenario_packages" / "excel-instance.lbpkg"
    created_payload = _parse_uploaded_scenario_package(
        created_path.read_bytes(),
        "excel-instance.lbpkg",
    )
    created_errors = _validate_self_contained_scenario_package(
        created_payload,
        require_full_contract=True,
    )
    assert created_errors == []
    assert created_payload.get("metadata", {}).get("converter_script_artifact") == "bin/excel_package_converter.py"


def test_repository_create_from_template_rewrites_legacy_editor_action_endpoint(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    template_dir = tmp_path / "scenario_templates"
    template_dir.mkdir(parents=True, exist_ok=True)

    template_payload = _parse_uploaded_scenario_package(_make_scenario_lbpkg(), "legacy-template.lbpkg")
    for artifact in template_payload.get("artifacts", []):
        if str(artifact.get("path") or "") != "editor/spec.json":
            continue
        legacy_spec = {
            "type": "labbrew.editor-spec",
            "version": "1.0",
            "sections": [],
            "file_upload_actions": [
                {
                    "id": "replace_excel",
                    "label": "Replace Excel source",
                    "accept": ".xlsx",
                    "endpoint": "repository/convert-excel",
                }
            ],
        }
        raw = json.dumps(legacy_spec, indent=2).encode("utf-8")
        artifact["content_b64"] = base64.b64encode(raw).decode("ascii")
        artifact["media_type"] = "application/json"
        artifact["size"] = len(raw)
        break

    (template_dir / "legacy-template.lbpkg").write_bytes(
        _build_scenario_package_archive_bytes(template_payload)
    )

    create_response = client.post(
        "/scenario/repository/create-from-template",
        json={
            "template_filename": "legacy-template.lbpkg",
            "filename": "legacy-instance.lbpkg",
        },
    )

    assert create_response.status_code == 200
    created_path = tmp_path / "scenario_packages" / "legacy-instance.lbpkg"
    created_payload = _parse_uploaded_scenario_package(
        created_path.read_bytes(),
        "legacy-instance.lbpkg",
    )

    endpoint = None
    for artifact in created_payload.get("artifacts", []):
        if str(artifact.get("path") or "") != "editor/spec.json":
            continue
        spec = json.loads(base64.b64decode(str(artifact.get("content_b64") or "")))
        actions = spec.get("file_upload_actions") if isinstance(spec, dict) else []
        if isinstance(actions, list) and actions and isinstance(actions[0], dict):
            endpoint = actions[0].get("endpoint")
        break

    assert endpoint == "repository/package-file-action"


def test_repository_save_accepts_package_when_converter_reference_is_inferred(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    package_payload = _parse_uploaded_scenario_package(
        _make_scenario_lbpkg(),
        "inferred-converter.lbpkg",
    )

    response = client.post(
        "/scenario/repository/save",
        json={
            "filename": "inferred-converter.lbpkg",
            "package": package_payload,
        },
    )

    assert response.status_code == 200
    saved_payload = _parse_uploaded_scenario_package(
        (tmp_path / "scenario_packages" / "inferred-converter.lbpkg").read_bytes(),
        "inferred-converter.lbpkg",
    )
    assert saved_payload.get("metadata", {}).get("converter_script_artifact") == "bin/excel_package_converter.py"