from __future__ import annotations

import argparse
import ast
import base64
import json
from pathlib import Path

from BrewSupervisor.api.schedule_import.parser import parse_schedule_workbook


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


def build_package(program: dict, source_name: str, package_id: str | None, package_name: str | None) -> dict:
    resolved_id = (package_id or str(program.get("id") or "scenario")).strip() or "scenario"
    resolved_name = (package_name or str(program.get("name") or "Scenario")).strip() or "Scenario"
    entrypoint_artifact = "bin/excel_program_runner.py"
    program_artifact = "data/program.json"
    validation_artifact = "validation/validation.json"
    editor_spec_artifact = "editor/spec.json"

    runner_source_path = Path(__file__).resolve().parent / "demo_sources" / "excel_program_runner.py"
    runner_source = runner_source_path.read_text(encoding="utf-8")
    _validate_runner_source(runner_source, source_path=runner_source_path)
    program_json = json.dumps(program, indent=2)
    validation_json = json.dumps({"type": "labbrew.validation-spec", "version": "1.0"}, indent=2)
    editor_json = json.dumps({
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
    }, indent=2)

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
            "content_b64": base64.b64encode(validation_json.encode("utf-8")).decode("ascii"),
            "size": len(validation_json.encode("utf-8")),
        },
        {
            "path": editor_spec_artifact,
            "encoding": "base64",
            "content_b64": base64.b64encode(editor_json.encode("utf-8")).decode("ascii"),
            "size": len(editor_json.encode("utf-8")),
        },
    ]

    return {
        "id": resolved_id,
        "name": resolved_name,
        "version": "0.1.0",
        "description": f"Scenario package generated from {source_name}",
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
        "program": program,
        "artifacts": artifacts,
        "metadata": {
            "created_by": "Other.Builders.convert_excel_to_scenario_package",
            "import_source": "excel",
            "source_filename": source_name,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Excel schedule workbook to scenario package JSON")
    parser.add_argument("excel", help="Path to source .xlsx workbook")
    parser.add_argument(
        "--out",
        default="",
        help="Output path for package JSON (default: data/scenario_packages/<excel_stem>.package.json)",
    )
    parser.add_argument("--id", default="", help="Override package id")
    parser.add_argument("--name", default="", help="Override package name")
    args = parser.parse_args()

    excel_path = Path(args.excel)
    if not excel_path.exists() or not excel_path.is_file():
        raise SystemExit(f"Excel file not found: {excel_path}")

    output_path = Path(args.out) if args.out else Path("data/scenario_packages") / f"{excel_path.stem}.package.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    workbook_payload = parse_schedule_workbook(excel_path.read_bytes(), filename=excel_path.name)
    package_payload = build_package(
        workbook_payload,
        source_name=excel_path.name,
        package_id=args.id or None,
        package_name=args.name or None,
    )

    output_path.write_text(json.dumps(package_payload, indent=2), encoding="utf-8")
    print(str(output_path))


if __name__ == "__main__":
    main()
