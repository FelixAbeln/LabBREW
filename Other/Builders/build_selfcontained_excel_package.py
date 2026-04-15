from __future__ import annotations

import argparse
import ast
import base64
import json
import zipfile
from pathlib import Path

import msgpack

from BrewSupervisor.api.schedule_import.parser import parse_schedule_workbook
from Services.schedule_service.models import ScheduleDefinition


def _validate_runner_source(runner_source: str, *, source_path: Path) -> None:
    """Fail fast if the embedded runner is not on the shared scripted path."""
    if "Services.scenario_service.scripted_helpers" not in runner_source:
        raise ValueError(
            "Runner template must import shared scenario helpers from "
            f"Services.scenario_service.scripted_helpers: {source_path}"
        )

    tree = ast.parse(runner_source)
    has_run_fn = False
    has_run_program_call = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            has_run_fn = True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run_program":
            has_run_program_call = True

    if not has_run_fn:
        raise ValueError(f"Runner template missing run(ctx) function: {source_path}")
    if not has_run_program_call:
        raise ValueError(
            "Runner template must call shared run_program(...) helper; "
            f"refusing to package {source_path}"
        )


def _default_manifest(
    *,
    package_id: str,
    package_name: str,
    entrypoint_artifact: str,
    program_artifact: str,
    validation_artifact: str,
    editor_spec_artifact: str,
    program_payload: dict,
    artifacts: list[dict],
) -> dict:
    return {
        "id": package_id,
        "name": package_name,
        "version": "0.1.0",
        "description": "Self-contained scenario package with packaged runner, validation, and editor specs",
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
            "artifact": validation_artifact,
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
            "created_by": "Other.Builders.build_selfcontained_excel_package",
            "packaging": "self-contained",
            "import_source": "excel",
        },
    }


def build_package_archive(
    *,
    excel_path: Path,
    output_path: Path,
    package_id: str,
    package_name: str,
) -> None:
    entrypoint_artifact = "bin/excel_program_runner.py"
    program_artifact = "data/program.json"
    validation_artifact = "validation/validation.json"
    editor_spec_artifact = "editor/spec.json"

    parsed_program = parse_schedule_workbook(
        excel_path.read_bytes(),
        filename=excel_path.name,
    )
    program_payload = ScheduleDefinition.from_payload(parsed_program).to_dict()

    runner_source_path = Path(__file__).resolve().parent / "demo_sources" / "excel_program_runner.py"
    runner_source = runner_source_path.read_text(encoding="utf-8")
    _validate_runner_source(runner_source, source_path=runner_source_path)
    program_json = json.dumps(program_payload, indent=2)

    artifacts = [
        {
            "path": entrypoint_artifact,
            "encoding": "base64",
            "content_b64": base64.b64encode(runner_source.encode("utf-8")).decode("ascii"),
            "size": len(runner_source.encode("utf-8")),
        },
        {
            "path": program_artifact,
            "encoding": "base64",
            "content_b64": base64.b64encode(program_json.encode("utf-8")).decode("ascii"),
            "size": len(program_json.encode("utf-8")),
        },
        {
            "path": validation_artifact,
            "encoding": "base64",
            "content_b64": base64.b64encode(json.dumps({"type": "labbrew.validation-spec", "version": "1.0"}, indent=2).encode("utf-8")).decode("ascii"),
            "size": len(json.dumps({"type": "labbrew.validation-spec", "version": "1.0"}, indent=2).encode("utf-8")),
        },
        {
            "path": editor_spec_artifact,
            "encoding": "base64",
            "content_b64": base64.b64encode(json.dumps({"type": "labbrew.editor-spec", "version": "1.0"}, indent=2).encode("utf-8")).decode("ascii"),
            "size": len(json.dumps({"type": "labbrew.editor-spec", "version": "1.0"}, indent=2).encode("utf-8")),
        },
    ]

    manifest = _default_manifest(
        package_id=package_id,
        package_name=package_name,
        entrypoint_artifact=entrypoint_artifact,
        program_artifact=program_artifact,
        validation_artifact=validation_artifact,
        editor_spec_artifact=editor_spec_artifact,
        program_payload=program_payload,
        artifacts=artifacts,
    )

    validation_payload = {
        "type": "labbrew.validation-spec",
        "version": "1.0",
        "required_fields": manifest["validation"]["required_fields"],
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

    editor_spec_payload = {
        "type": "labbrew.editor-spec",
        "version": "1.0",
        "sections": [
            {
                "id": "identity",
                "title": "Identity",
                "fields": ["id", "name", "version", "description"],
            },
            {
                "id": "runner",
                "title": "Runner",
                "fields": ["runner.kind", "runner.entrypoint", "endpoint_code.entrypoint"],
            },
            {
                "id": "artifacts",
                "title": "Artifacts",
                "fields": ["validation.artifact", "editor_spec.artifact", "endpoint_code.entrypoint", "artifacts"],
            },
            {
                "id": "program",
                "title": "Program",
                "fields": ["program.setup_steps", "program.plan_steps", "program.measurement_config"],
            },
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "scenario.package.msgpack",
            msgpack.packb(manifest, use_bin_type=True),
        )
        archive.writestr(entrypoint_artifact, runner_source)
        archive.writestr(program_artifact, program_json)
        archive.writestr(validation_artifact, json.dumps(validation_payload, indent=2))
        archive.writestr(editor_spec_artifact, json.dumps(editor_spec_payload, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build self-contained scenario .lbpkg from Excel")
    parser.add_argument("excel", help="Path to source .xlsx workbook")
    parser.add_argument(
        "--out",
        default="",
        help="Output .lbpkg path (default: data/scenario_packages/<excel_stem>.lbpkg)",
    )
    parser.add_argument("--id", default="", help="Package id override")
    parser.add_argument("--name", default="", help="Package name override")
    args = parser.parse_args()

    excel_path = Path(args.excel)
    if not excel_path.exists() or not excel_path.is_file():
        raise SystemExit(f"Excel file not found: {excel_path}")

    package_id = (args.id or excel_path.stem.replace(" ", "-").lower()).strip() or "scenario-package"
    package_name = (args.name or f"{excel_path.stem} Scenario Package").strip() or "Scenario Package"

    output_path = (
        Path(args.out)
        if args.out
        else Path("data/scenario_packages") / f"{excel_path.stem}.lbpkg"
    )

    build_package_archive(
        excel_path=excel_path,
        output_path=output_path,
        package_id=package_id,
        package_name=package_name,
    )
    print(str(output_path))


if __name__ == "__main__":
    main()
