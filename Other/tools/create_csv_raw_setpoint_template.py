from __future__ import annotations

import base64
import csv
import io
import json
import zipfile
from pathlib import Path

import msgpack


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = WORKSPACE_ROOT / "data" / "scenario_templates"
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATE_PATH = TEMPLATE_DIR / "CSV_Raw_Setpoints.lbpkg"
SAMPLE_CSV_PATH = TEMPLATE_DIR / "CSV_Raw_Setpoints.sample.csv"


RUNNER_SOURCE = """from __future__ import annotations

import json


def _load_program(ctx) -> dict:
    blob = ctx.get_artifact("data/program.json")
    return json.loads(blob.decode("utf-8")) if blob else {}


def run(ctx) -> None:
    program = _load_program(ctx)
    setpoints = list(program.get("setpoints") or [])
    if not setpoints:
        ctx.log("No setpoints found in data/program.json")
        return

    setpoints = sorted(setpoints, key=lambda item: float(item.get("time_s", 0.0)))
    requested = set()
    for item in setpoints:
        target = str(item.get("target") or "").strip()
        if target and target not in requested:
            ctx.request_control(target)
            requested.add(target)

    buckets: list[tuple[float, list[dict]]] = []
    for item in setpoints:
        at_s = float(item.get("time_s", 0.0))
        if not buckets or buckets[-1][0] != at_s:
            buckets.append((at_s, [item]))
        else:
            buckets[-1][1].append(item)

    requested_start_index = getattr(ctx, "start_index", None)
    start_bucket_index = 0
    if requested_start_index is not None:
        try:
            start_bucket_index = max(0, int(requested_start_index))
        except Exception:
            start_bucket_index = 0
    if start_bucket_index >= len(buckets):
        ctx.log(
            f"Requested run index {start_bucket_index + 1} is outside program range (1-{max(1, len(buckets))})"
        )
        return

    if start_bucket_index > 0:
        ctx.log(f"Starting from run index {start_bucket_index + 1}")

    prev_time = buckets[start_bucket_index][0] if start_bucket_index > 0 else 0.0
    total = float(len(buckets))
    for idx, (at_s, items) in enumerate(buckets[start_bucket_index:], start=start_bucket_index + 1):
        if ctx.is_stopped():
            ctx.log("Run stopped")
            return

        wait_s = max(0.0, at_s - prev_time)
        if wait_s > 0.0:
            ctx.set_progress(
                phase="wait",
                step_index=idx - 1,
                step_name=f"Wait {wait_s:.2f}s",
                wait_message=f"Waiting {wait_s:.2f}s before t={at_s:.2f}s",
            )
            ctx.sleep(wait_s)

        updates = []
        for item in items:
            target = str(item.get("target") or "").strip()
            value = item.get("value")
            updates.append(f"{target}={value}")
            ctx.write_setpoint(target, value)

        ctx.set_progress(
            phase="run",
            step_index=idx,
            step_name=f"t={at_s:.2f}s",
            wait_message=f"Applying {len(items)} setpoint(s)",
        )
        ctx.log(
            f"Applied time bucket #{idx}/{int(total)} at t={at_s:.2f}s: "
            + ", ".join(updates)
        )
        prev_time = at_s

    ctx.set_progress(phase="done", step_index=int(total), step_name="Completed", wait_message="Completed")
    ctx.log("CSV raw setpoint program completed")
"""


CONVERTER_SOURCE = """from __future__ import annotations

import base64
import csv
import io
import json
import re
from datetime import UTC, datetime


def _slugify(text: str, fallback: str = "csv-setpoints") -> str:
    raw = str(text or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return slug or fallback


def _as_float(value, *, field_name: str) -> float:
    try:
        return float(value)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Invalid numeric value for {field_name}: {value!r}") from exc


def parse_workbook(workbook_bytes: bytes, *, filename: str, default_measurements_output_dir: str) -> dict:
    try:
        text = workbook_bytes.decode("utf-8-sig")
    except Exception as exc:  # noqa: BLE001
        raise ValueError("CSV upload must be UTF-8 text") from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV is missing a header row")

    headers = [str(name or "").strip() for name in reader.fieldnames]
    header_map = {name.lower(): name for name in headers if name}

    time_key = ""
    for candidate in ("time_s", "time", "seconds", "t"):
        key = header_map.get(candidate)
        if key:
            time_key = key
            break
    if not time_key:
        raise ValueError("CSV must include a time column: time_s, time, seconds, or t")

    target_columns = [name for name in headers if name and name != time_key]
    if not target_columns:
        raise ValueError("CSV must include at least one setpoint column besides time")

    setpoints: list[dict] = []
    last_time = -1e-9
    for row_idx, row in enumerate(reader, start=2):
        raw_time = row.get(time_key)
        if raw_time in (None, ""):
            continue
        at_s = _as_float(raw_time, field_name=f"{time_key} (row {row_idx})")
        if at_s < last_time:
            raise ValueError(f"Time must be monotonic ascending (row {row_idx})")
        last_time = at_s

        for target in target_columns:
            raw_value = row.get(target)
            if raw_value in (None, ""):
                continue
            setpoints.append(
                {
                    "time_s": at_s,
                    "target": target,
                    "value": _as_float(raw_value, field_name=f"{target} (row {row_idx})"),
                }
            )

    if not setpoints:
        raise ValueError("CSV produced no setpoint events")

    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    package_id = _slugify(stem, fallback="csv-setpoints")
    package_name = str(stem or "CSV Raw Setpoints")

    return {
        "id": package_id,
        "name": package_name,
        "description": "Raw time/value CSV setpoint program",
        "program": {
            "kind": "raw-csv-setpoints",
            "setpoints": setpoints,
            "measurement_config": {
                "hz": 10,
                "output_format": "parquet",
                "output_dir": default_measurements_output_dir,
            },
        },
        "package_defaults": {
            "id": package_id,
            "name": package_name,
            "description": "Raw time/value CSV setpoint program",
            "version": "0.1.0",
            "tags": ["csv", "setpoints", "template"],
        },
    }


def _artifact(path: str, payload: bytes, media_type: str) -> dict:
    return {
        "path": path,
        "media_type": media_type,
        "encoding": "base64",
        "content_b64": base64.b64encode(payload).decode("ascii"),
        "size": len(payload),
    }


def build_package(
    program_payload: dict,
    *,
    runner_source: str,
    converter_source: str,
    source_name: str,
    package_id: str,
    package_name: str,
    version: str,
    description: str,
    tags: list[str],
    version_notes: str,
    source_workbook_bytes: bytes | None = None,
) -> dict:
    program_obj = dict(program_payload.get("program") or {})
    if not program_obj:
        program_obj = dict(program_payload or {})

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    editor_spec = {
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
                "id": "upload_csv_setpoints",
                "label": "Upload CSV Setpoints",
                "accept": [".csv", "text/csv"],
                "endpoint": "repository/package-file-action",
                "method": "POST",
                "description": "Build this package from CSV columns: time_s, set_temp_Fermentor (and any other real command parameter names)",
            }
        ],
        "repository_save": {
            "filename_template": "${package.id}.lbpkg",
            "tags_path": "metadata.tags",
            "version_notes_path": "metadata.version_notes",
            "notes_path": "metadata.notes",
        },
    }

    validation_spec = {
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

    artifacts = [
        _artifact("bin/raw_setpoint_runner.py", runner_source.encode("utf-8"), "text/x-python"),
        _artifact("tools/csv_raw_setpoints_converter.py", converter_source.encode("utf-8"), "text/x-python"),
        _artifact("data/program.json", json.dumps(program_obj, ensure_ascii=False, indent=2).encode("utf-8"), "application/json"),
        _artifact("validation/validation.json", json.dumps(validation_spec, ensure_ascii=False, indent=2).encode("utf-8"), "application/json"),
        _artifact("editor/spec.json", json.dumps(editor_spec, ensure_ascii=False, indent=2).encode("utf-8"), "application/json"),
    ]

    if source_workbook_bytes:
        artifacts.append(
            _artifact(
                f"source/{source_name}",
                bytes(source_workbook_bytes),
                "text/csv",
            )
        )

    return {
        "id": package_id,
        "name": package_name,
        "version": version,
        "description": description,
        "interface": {"kind": "labbrew.scenario-package", "version": "1.0"},
        "validation": {"artifact": "validation/validation.json", "required_fields": validation_spec["required_fields"]},
        "editor_spec": {"artifact": "editor/spec.json", "version": "1.0"},
        "endpoint_code": {
            "language": "python",
            "entrypoint": "bin/raw_setpoint_runner.py",
            "interface_contract": "labbrew.scenario-package@1.0",
        },
        "runner": {"kind": "scripted", "entrypoint": "scripted.run", "config": {}},
        "program": program_obj,
        "artifacts": artifacts,
        "metadata": {
            "tags": list(tags or []),
            "version_notes": str(version_notes or ""),
            "packaging": "self-contained",
            "import_source": "csv",
            "created_at": now,
            "source_workbook_artifact": f"source/{source_name}" if source_workbook_bytes else "",
            "converter_script_artifact": "tools/csv_raw_setpoints_converter.py",
        },
    }
"""


def _artifact(path: str, payload: bytes, media_type: str) -> dict:
    return {
        "path": path,
        "media_type": media_type,
        "encoding": "base64",
        "content_b64": base64.b64encode(payload).decode("ascii"),
        "size": len(payload),
    }


def _parse_csv_to_program(csv_bytes: bytes) -> dict:
    text = csv_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    headers = [str(x or "").strip() for x in (reader.fieldnames or [])]
    if not headers:
        raise ValueError("sample CSV is missing headers")
    time_col = "time_s" if "time_s" in headers else headers[0]
    targets = [h for h in headers if h and h != time_col]
    setpoints: list[dict] = []
    for row in reader:
        raw_time = row.get(time_col)
        if raw_time in (None, ""):
            continue
        at_s = float(raw_time)
        for target in targets:
            raw_value = row.get(target)
            if raw_value in (None, ""):
                continue
            setpoints.append({"time_s": at_s, "target": target, "value": float(raw_value)})
    return {
        "kind": "raw-csv-setpoints",
        "setpoints": setpoints,
        "measurement_config": {
            "hz": 10,
            "output_format": "parquet",
            "output_dir": "data/measurements",
        },
    }


def _build_template_payload() -> dict:
    csv_bytes = SAMPLE_CSV_PATH.read_bytes()
    program = _parse_csv_to_program(csv_bytes)

    artifacts = [
        _artifact("bin/raw_setpoint_runner.py", RUNNER_SOURCE.encode("utf-8"), "text/x-python"),
        _artifact("tools/csv_raw_setpoints_converter.py", CONVERTER_SOURCE.encode("utf-8"), "text/x-python"),
        _artifact("data/program.json", json.dumps(program, ensure_ascii=False, indent=2).encode("utf-8"), "application/json"),
        _artifact(
            "validation/validation.json",
            json.dumps(
                {
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
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
            "application/json",
        ),
        _artifact(
            "editor/spec.json",
            json.dumps(
                {
                    "type": "labbrew.editor-spec",
                    "version": "1.0",
                    "sections": [
                        {
                            "id": "identity",
                            "title": "Identity",
                            "fields": ["id", "name", "version", "description"],
                        }
                    ],
                    "file_upload_actions": [
                        {
                            "id": "upload_csv_setpoints",
                            "label": "Upload CSV Setpoints",
                            "accept": [".csv", "text/csv"],
                            "endpoint": "repository/package-file-action",
                            "method": "POST",
                            "description": "Upload CSV with columns: time_s, set_temp_Fermentor (and any other real command parameter names)",
                        }
                    ],
                    "repository_save": {
                        "filename_template": "${package.id}.lbpkg",
                        "tags_path": "metadata.tags",
                        "version_notes_path": "metadata.version_notes",
                        "notes_path": "metadata.notes",
                    },
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
            "application/json",
        ),
        _artifact("source/CSV_Raw_Setpoints.sample.csv", csv_bytes, "text/csv"),
    ]

    return {
        "id": "csv-raw-setpoints-template",
        "name": "CSV Raw Setpoints Template",
        "version": "1.0.0",
        "description": "Template that consumes CSV time/value setpoints and runs them as raw setpoint writes.",
        "interface": {"kind": "labbrew.scenario-package", "version": "1.0"},
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
        "endpoint_code": {
            "language": "python",
            "entrypoint": "bin/raw_setpoint_runner.py",
            "interface_contract": "labbrew.scenario-package@1.0",
        },
        "runner": {"kind": "scripted", "entrypoint": "scripted.run", "config": {}},
        "program": program,
        "artifacts": artifacts,
        "metadata": {
            "tags": ["template", "csv", "setpoints"],
            "version_notes": "",
            "packaging": "self-contained",
            "import_source": "template",
            "converter_script_artifact": "tools/csv_raw_setpoints_converter.py",
        },
    }


def _write_lbpkg(payload: dict, target_path: Path) -> None:
    manifest = dict(payload)
    artifacts = list(manifest.pop("artifacts", []) or [])
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("scenario.package.msgpack", msgpack.packb(manifest, use_bin_type=True))
            for item in artifacts:
                path = str(item.get("path") or "").strip()
                content_b64 = str(item.get("content_b64") or "").strip()
                if not path or not content_b64:
                    continue
                archive.writestr(path, base64.b64decode(content_b64))
        target_path.write_bytes(buffer.getvalue())


def main() -> None:
    if not SAMPLE_CSV_PATH.exists():
        raise FileNotFoundError(f"Missing sample CSV: {SAMPLE_CSV_PATH}")
    payload = _build_template_payload()
    _write_lbpkg(payload, TEMPLATE_PATH)
    print(f"Wrote template: {TEMPLATE_PATH}")


if __name__ == "__main__":
    main()
