# Writing a LabBREW `.lbpkg` Package

This guide is the practical, end-to-end version of LabBREW scenario package authoring.

It is written for developers who want to build a working runtime package without first reverse-engineering the backend. If you follow this document, you should be able to:

- understand what a `.lbpkg` file actually is,
- build a valid package archive from scratch,
- implement a package runner that executes under `scenario_service`,
- add validation and editor metadata so the package works in the repository UI,
- test and troubleshoot the package locally,
- publish a package that other developers can edit, import, and run.

This guide complements, but does not replace, [Writing a Scenario Runner](./writing-a-scenario-runner.md). That document is runner-focused. This one is package-focused.

---

## 1. What a `.lbpkg` package is

A LabBREW runtime package is a zip archive with a `.lbpkg` extension.

At minimum it contains:

- one msgpack manifest file named `scenario.package.msgpack`
- one Python runner artifact referenced by `endpoint_code.entrypoint`
- any additional artifacts your runner needs, such as:
  - `data/program.json`
  - `validation/validation.json`
  - `editor/spec.json`
  - source input files such as `source/workbook.xlsx` or `source/data.csv`

Important detail:

- the manifest stored in `scenario.package.msgpack` does **not** contain the `artifacts` list
- the artifact files are stored as normal zip entries beside the manifest
- when the package is loaded, LabBREW reconstructs the full package object by combining the manifest with the zip entries

This is the archive layout pattern used by the package builders in the repo.

Example archive:

```text
my_package.lbpkg
├── scenario.package.msgpack
├── bin/runner.py
├── data/program.json
├── validation/validation.json
├── editor/spec.json
└── source/example_input.csv
```

---

## 2. Runtime architecture in one page

At runtime the package flows through these layers:

1. BrewSupervisor accepts a `.lbpkg` or `.zip` upload/import.
2. BrewSupervisor forwards the package to `scenario_service`.
3. `scenario_service` compiles and validates the package.
4. `scenario_service` loads the package into memory and persists it to `data/scenario_state.json`.
5. When the operator presses Start, `scenario_service` creates a `ScriptedRunner`.
6. `ScriptedRunner` loads the package entrypoint artifact and runs `run(ctx)`.
7. Your runner uses the `RunnerContext` API to request control, write setpoints, wait, log, and publish progress.

Relevant implementation files:

- `Services/scenario_service/runtime.py`
- `Services/scenario_service/scripted_runner.py`
- `Services/scenario_service/models.py`
- `BrewSupervisor/api/routes.py`

---

## 3. The full package object

The runtime model is `ScenarioPackageDefinition` in `Services/scenario_service/models.py`.

The package fields are:

- `id`
- `name`
- `version`
- `description`
- `runner`
- `interface`
- `validation`
- `editor_spec`
- `endpoint_code`
- `artifacts`
- `program`
- `metadata`

The backend accepts extra keys inside nested objects, but the package should always include the fields above.

---

## 4. Fields that are actually required in practice

Some fields are logically required because the runtime compile step rejects packages without them.

### Required top-level intent

Your package should always include:

- `id`
- `name`
- `runner.kind = "scripted"`
- `interface.kind = "labbrew.scenario-package"`
- `interface.version = "1.0"`
- `endpoint_code.language = "python"`
- `endpoint_code.entrypoint = "bin/runner.py"` or similar
- `validation.artifact`
- `editor_spec.artifact`
- `artifacts` containing the entrypoint and the validation/editor files

### Required artifact relationships

The following references must resolve to actual artifact paths in the package:

- `endpoint_code.entrypoint`
- `validation.artifact`
- `editor_spec.artifact`

If those paths are missing from the package, compile validation fails.

---

## 5. Minimal manifest example

This is the smallest useful package shape to start from:

```json
{
  "id": "hello-scenario",
  "name": "Hello Scenario",
  "version": "1.0.0",
  "description": "Minimal scripted scenario package",
  "interface": {
    "kind": "labbrew.scenario-package",
    "version": "1.0"
  },
  "runner": {
    "kind": "scripted",
    "entrypoint": "scripted.run",
    "config": {}
  },
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
      "artifacts"
    ]
  },
  "editor_spec": {
    "artifact": "editor/spec.json",
    "version": "1.0"
  },
  "endpoint_code": {
    "language": "python",
    "entrypoint": "bin/runner.py",
    "interface_contract": "labbrew.scenario-package@1.0"
  },
  "program": {
    "kind": "hello-program",
    "steps": []
  },
  "metadata": {
    "tags": ["example"],
    "packaging": "self-contained"
  }
}
```

Notes:

- `runner.entrypoint` is not the Python file path; the host uses `endpoint_code.entrypoint` to find the embedded file
- `runner.entrypoint = "scripted.run"` is just the logical runner kind/config convention used in existing packages
- `program` is package-defined data; the runtime does not enforce a single schema there

---

## 6. Artifact object format

When a package exists as a full JSON payload in memory or over HTTP, each artifact is represented like this:

```json
{
  "path": "bin/runner.py",
  "media_type": "text/x-python",
  "encoding": "base64",
  "content_b64": "...",
  "size": 1234
}
```

Fields to include:

- `path`: archive-relative path
- `media_type`: MIME-like type, for example `text/x-python` or `application/json`
- `encoding`: use `base64`
- `content_b64`: base64 encoded bytes
- `size`: raw decoded byte length

Inside the `.lbpkg` zip itself, artifacts are stored as decoded raw files, not as JSON objects.

---

## 7. The easiest authoring workflow

For most packages, use this workflow:

1. Define your runtime behavior in a Python runner.
2. Define your package data in `program.json` or another artifact.
3. Create a small `validation/validation.json` artifact.
4. Create an `editor/spec.json` artifact so the repository UI knows how to edit/save the package.
5. Build the archive with Python using `msgpack` + `zipfile`.
6. Import it through BrewSupervisor or store it in the scenario repository.

If you are creating a package family or template, follow the pattern used in:

- `Other/tools/create_csv_raw_setpoint_template.py`

That file is the best current example of a self-contained package builder.

---

## 8. Authoring, replacing, and changing packages over time

You should treat a package as something that will evolve, not as a sealed artifact.

In practice, package development usually follows this cycle:

1. author a package family with a stable layout and stable artifact paths
2. import or save the package into the repository
3. replace source inputs, metadata, or program content as requirements change
4. rebuild the package with the same internal contract
5. re-import or overwrite the repository copy

This matters because most real packages do not stay static. A package may start as a temperature program and later need:

- a throttle map
- a torque curve
- a setpoint generator
- new measurement capture requirements
- richer metadata for traceability
- a new source file format

The right way to support that is to separate the package into concerns:

- runner logic in `bin/...py`
- conversion/build logic in `tools/...py`
- runtime data in `data/program.json`
- source material in `source/...`
- UI/edit/save contract in `editor/spec.json`
- self-description and save semantics in `metadata`

If you keep those boundaries stable, you can replace one layer without rewriting the whole package family.

---

## 9. Minimal runner contract

Your entrypoint file must define:

```python
def run(ctx):
    ...
```

The host executes your embedded Python file via `exec(...)` and then calls `run(ctx)`.

If `run(ctx)` raises, the scenario faults.

If `run(ctx)` returns normally, the scenario completes.

---

## 10. `RunnerContext` API you can use

The full implementation lives in `Services/scenario_service/scripted_runner.py`.

The APIs package authors should treat as supported are:

- `ctx.request_control(target)`
- `ctx.release_control(target)`
- `ctx.release_all()`
- `ctx.write_setpoint(target, value)`
- `ctx.ramp_setpoint(target, value, duration_s)`
- `ctx.read_value(target)`
- `ctx.snapshot_values()`
- `ctx.sleep(seconds)`
- `ctx.is_stopped()`
- `ctx.is_paused()`
- `ctx.consume_navigation()`
- `ctx.log(message)`
- `ctx.get_artifact(path)`
- `ctx.set_progress(phase=None, step_index=None, step_name=None, wait_message=None)`
- `ctx.measurement_status()`
- `ctx.setup_measurement(...)`
- `ctx.start_measurement()`
- `ctx.stop_measurement()`
- `ctx.take_loadstep(...)`

Useful runtime field:

- `ctx.start_index`
  - zero-based internal start position supplied by `POST /scenario/run/start`
  - if you expose "Start At Run Index" in the UI, convert the user-facing 1-based run index to zero-based before assigning your own loop index

Important conventions:

- use `ctx.sleep(...)`, not `time.sleep(...)`
- use `try/finally` so owned targets are always released
- call `ctx.is_stopped()` inside any long-running loop
- use `ctx.set_progress(...)` if you want the dashboard to show meaningful progress
- `ctx.sleep(...)` returns early if navigation is pending, so step-based runners should re-check navigation around waits

---

## 11. A complete minimal runner example

This is a small but production-safe example.

```python
from __future__ import annotations

import json


def _set_progress_safe(ctx, **kwargs) -> None:
    fn = getattr(ctx, "set_progress", None)
    if callable(fn):
        try:
            fn(**kwargs)
        except Exception:
            pass


def _load_program(ctx) -> dict:
    blob = ctx.get_artifact("data/program.json")
    return json.loads(blob.decode("utf-8")) if blob else {}


def run(ctx) -> None:
    program = _load_program(ctx)
    steps = list(program.get("steps") or [])
    if not steps:
        ctx.log("No steps defined")
        return

    target = str(program.get("target") or "")
    if not target:
        raise RuntimeError("program.target is required")

    start_index = 0
    requested = getattr(ctx, "start_index", None)
    if requested is not None:
        try:
            start_index = max(0, int(requested))
        except Exception:
            start_index = 0

    ctx.request_control(target)
    try:
        for internal_index, step in enumerate(steps[start_index:], start=start_index):
            if ctx.is_stopped():
                ctx.log("Run stopped")
                return

            run_index = internal_index + 1
            name = str(step.get("name") or f"Step {run_index}")
            value = step.get("value")
            hold_s = float(step.get("hold_s") or 0.0)

            _set_progress_safe(
                ctx,
                phase="run",
                step_index=run_index,
                step_name=name,
                wait_message=f"Holding {hold_s:.2f}s",
            )
            ctx.write_setpoint(target, value)
            ctx.log(f"Applied {name}: {target}={value}")
            ctx.sleep(hold_s)

        _set_progress_safe(ctx, phase="done", step_name="Completed", wait_message="Completed")
        ctx.log("Run completed")
    finally:
        ctx.release_control(target)
```

---

## 12. Designing `program.json`

`program` is your package-owned runtime data. There is no single backend-enforced schema beyond “must be a dict-like payload.”

That means you should define a schema that is:

- explicit
- versionable
- resilient to additive change
- easy to validate

Good pattern:

```json
{
  "kind": "tank-setpoint-program",
  "schema_version": "1.0",
  "target": "set_temp_Fermentor",
  "steps": [
    { "name": "Warmup", "value": 22.0, "hold_s": 10.0 },
    { "name": "Hold", "value": 24.0, "hold_s": 30.0 }
  ],
  "measurement_config": {
    "hz": 10,
    "output_format": "parquet",
    "output_dir": "data/measurements"
  }
}
```

Recommended fields:

- `kind`
- `schema_version`
- a clearly named execution payload such as `steps`, `plan_steps`, or `setpoints`
- `measurement_config` if the package should coordinate data recording

For anything beyond a trivial runner, keep `program.json` as the place where change happens most often.

Examples:

- a throttle package might store breakpoints, interpolation mode, and output scaling
- a torque package might store a torque curve and a target-selection strategy
- a setpoint generator package might store a high-level recipe and compile it into executable steps during conversion

Good rule:

- change `program` when the data model changes
- change `bin/...py` when runtime behavior changes
- change `tools/...py` when authoring/import behavior changes

---

## 13. Validation artifact: what it is for

`validation/validation.json` is required because LabBREW wants validation instructions shipped with the package binary.

At minimum include:

```json
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
    "artifacts"
  ],
  "rules": [
    {
      "code": "entrypoint_present",
      "message": "endpoint_code.entrypoint must exist in package artifacts"
    }
  ]
}
```

Today, the runtime mainly checks package structure and artifact presence. You should still ship validation metadata because:

- it is compile-required
- it documents package assumptions
- it keeps package behavior self-describing

---

## 14. Editor spec artifact: what it is for

`editor/spec.json` tells the repository UI how to edit and save the package.

At minimum include:

```json
{
  "type": "labbrew.editor-spec",
  "version": "1.0",
  "sections": [
    {
      "id": "identity",
      "title": "Identity",
      "fields": ["id", "name", "version", "description"]
    },
    {
      "id": "metadata",
      "title": "Metadata",
      "fields": ["metadata"]
    }
  ],
  "file_upload_actions": [],
  "repository_save": {
    "filename_template": "${package.id}.lbpkg",
    "tags_path": "metadata.tags",
    "version_notes_path": "metadata.version_notes",
    "notes_path": "metadata.notes"
  }
}
```

Use `file_upload_actions` when the repository UI should accept a source file and rebuild the package using package-owned conversion logic.

This is how the CSV and Excel template flows work.

The important design point is that `editor/spec.json` is not just cosmetic metadata. It is the author-facing contract that tells the repository UI:

- what can be edited directly
- what metadata fields should persist on save
- what source files can be uploaded to regenerate the package
- how package replacement should behave from the user’s point of view

---

## 15. Repository-driven package editing pattern

If you want non-backend developers to maintain a package, support these pieces:

1. `editor/spec.json` for editable metadata fields.
2. `repository_save` paths so the UI knows how to save tags/notes/version notes.
3. `file_upload_actions` if the package can be regenerated from a source workbook/CSV/etc.
4. A converter script artifact if package regeneration logic should live inside the package family, not in BrewSupervisor.

The current package template pattern looks like this:

- runner artifact in `bin/...py`
- converter artifact in `tools/...py`
- program data in `data/program.json`
- upload action pointing to `repository/package-file-action`

Important current constraint:

- `repository/package-file-action` accepts one uploaded file per action
- if your package logically needs multiple source inputs, you should package them into one uploaded file, usually a zip archive
- the package converter should unpack that one file and derive everything it needs from it

Reference implementation:

- `Other/tools/create_csv_raw_setpoint_template.py`

---

## 16. Author and replace flow in the repository

This is the practical package lifecycle you should design for.

### Author a new package family

Start by deciding which parts are meant to be user-changeable:

- identity and metadata
- raw source files
- generated program content
- runner behavior
- measurement behavior

Then build a package with:

- a stable runner path
- a stable converter path if regeneration is supported
- a stable `program.json` schema
- an editor spec that points save/update operations at the right metadata paths

### Replace source input without rewriting the package family

This is the main template workflow.

For example, the CSV template stores:

- the runner at `bin/raw_setpoint_runner.py`
- the converter at `tools/csv_raw_setpoints_converter.py`
- the generated program at `data/program.json`
- the original uploaded file under `source/...`
- metadata that records where the source and converter live

That means a user can upload a new CSV, rebuild the package contents, and keep the same package family behavior.

### Worked example: a loadstep archive package

This is the right pattern for the case where you want to build a scenario from recorded measurement output and loadstep averages.

The current UI does not support uploading two independent source files in one package action. So if you want both:

- raw parquet measurement data
- loadstep averages

the source input should be one `.archive.zip` file, not two separate uploads.

That fits the data service well, because LabBREW already produces archive bundles in exactly that style.

The archive format already supports:

- one measurement member such as `session.parquet`, `session.jsonl`, or `session.csv`
- one loadstep member such as `session.loadsteps.parquet`, `session.loadsteps.jsonl`, or `session.loadsteps.csv`
- optional extra payloads and sidecar files included in the same zip

That means a package can treat the archive zip as the single source of truth.

Recommended repository flow for this package family:

1. create or save a repository package that already contains the runner and converter contract
2. open that repository package in the scenario builder editor
3. run a package function such as `Upload Archive Bundle`
4. upload one `.archive.zip` file exported from the data service
5. let the package converter read the archive, extract loadstep averages and any needed parquet metadata, and regenerate `data/program.json`
6. save or load the rebuilt package

This matches the current backend behavior exactly. The package action rebuilds a selected repository package using its embedded converter. It does not assemble a package from multiple independent uploads.

### What the converter should do

For this package family, `parse_workbook(...)` is still the package-converter entrypoint name, but the uploaded payload does not need to be an Excel workbook. It can be any bytes.

In this example, the converter should:

1. open the uploaded `.archive.zip`
2. locate the first measurement member ending in `.parquet`, `.jsonl`, or `.csv`
3. locate the loadstep member whose name contains `.loadsteps.`
4. parse the loadstep rows into records shaped like:
   - `name`
   - `duration_seconds`
   - `timestamp`
   - `average`
5. use those loadstep averages to build the package `program`
6. optionally keep the original uploaded archive under `source/...`
7. write metadata showing which archive and converter generated the package

The important point is that the converter is where authoring logic belongs.

- if you want to pick specific parameters from the archive, do that in the converter
- if you want to transform loadstep averages into torque targets, do that in the converter
- if you want to generate a denser step plan from sparse loadsteps, do that in the converter

The runner should execute an already prepared program, not re-interpret the archive format on every run.

### Suggested program shape for the archive package

The package `program` for this example should contain the derived runtime plan, not the whole archive.

Good example:

```json
{
  "kind": "loadstep-archive-program",
  "schema_version": "1.0",
  "archive": {
    "source_name": "my-test.archive.zip",
    "measurement_member": "my-test.parquet",
    "loadsteps_member": "my-test.loadsteps.parquet"
  },
  "generator": {
    "mode": "loadstep-average",
    "selected_parameters": ["torque_actual", "speed_actual", "throttle_actual"]
  },
  "steps": [
    {
      "name": "loadstep-1",
      "hold_s": 30.0,
      "writes": [
        { "target": "set_torque_Device", "value": 21.4 },
        { "target": "set_throttle_Device", "value": 37.0 }
      ]
    }
  ],
  "measurement_config": {
    "parameters": ["torque_actual", "speed_actual", "throttle_actual"],
    "hz": 20,
    "output_format": "parquet",
    "output_dir": "data/measurements"
  }
}
```

That schema leaves room for the exact use case you described:

- loadsteps are what you care about
- raw parquet stays available as source evidence
- the converter can derive a throttle map, torque curve, or generated setpoint plan from the archive
- the runner only has to apply the resulting executable steps

### Why this is better than two separate uploads

Using one archive file has practical advantages:

- it works with the current single-file upload action contract
- measurement data and loadstep data stay synchronized
- one uploaded file is easier to version, trace, and preserve under `source/...`
- package replacement becomes deterministic because one source file fully defines one generated program

If you later need more inputs, keep extending the archive content or embed a manifest inside the uploaded zip rather than depending on multiple unrelated uploads.

### Replace metadata without replacing runtime behavior

Repository save should let authors change:

- tags
- version notes
- freeform notes
- version string
- description
- package name

Those changes should not require touching the runner or the converter.

### Replace runtime behavior without breaking saved packages

If you need to add new runtime behavior, prefer one of these patterns:

1. additive program fields with backward-compatible defaults
2. a new `program.schema_version`
3. a new package family ID when the semantics change too much

Do not casually rename artifact paths such as `data/program.json` or `bin/runner.py` unless you are also updating every reference in:

- `endpoint_code.entrypoint`
- `validation.artifact`
- `editor_spec.artifact`
- any package-owned metadata fields that point at those artifacts

---

## 17. Metadata that is worth carrying

Metadata is not only for display. It is how packages remain understandable after they have been copied, edited, and replaced several times.

Strongly recommended metadata fields:

- `metadata.tags`
- `metadata.version_notes`
- `metadata.notes`
- `metadata.packaging`
- `metadata.import_source`
- `metadata.created_at`
- `metadata.source_workbook_artifact`
- `metadata.converter_script_artifact`

The CSV template already demonstrates this pattern.

In particular, these fields are useful:

- `metadata.source_workbook_artifact`
  - records which embedded source file generated the current package
- `metadata.converter_script_artifact`
  - records which converter artifact owns the rebuild logic
- `metadata.import_source`
  - distinguishes template-generated packages from imported source-driven packages

If you later need auditability, this metadata becomes very valuable.

---

## 18. Build a package archive in Python

This is the simplest complete builder pattern.

```python
from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import msgpack


def artifact(path: str, payload: bytes, media_type: str) -> dict:
    return {
        "path": path,
        "media_type": media_type,
        "encoding": "base64",
        "content_b64": base64.b64encode(payload).decode("ascii"),
        "size": len(payload),
    }


runner_source = Path("bin/runner.py").read_text(encoding="utf-8")
program_payload = {
    "kind": "hello-program",
    "target": "set_temp_Fermentor",
    "steps": [{"name": "Step 1", "value": 20.0, "hold_s": 5.0}],
}
validation_payload = {
    "type": "labbrew.validation-spec",
    "version": "1.0",
    "required_fields": ["id", "name", "runner", "interface", "validation", "editor_spec", "endpoint_code", "artifacts"],
    "rules": [{"code": "entrypoint_present", "message": "endpoint_code.entrypoint must exist in package artifacts"}],
}
editor_payload = {
    "type": "labbrew.editor-spec",
    "version": "1.0",
    "sections": [{"id": "identity", "title": "Identity", "fields": ["id", "name", "version", "description"]}],
    "file_upload_actions": [],
    "repository_save": {"filename_template": "${package.id}.lbpkg"},
}

artifacts = [
    artifact("bin/runner.py", runner_source.encode("utf-8"), "text/x-python"),
    artifact("data/program.json", json.dumps(program_payload, indent=2).encode("utf-8"), "application/json"),
    artifact("validation/validation.json", json.dumps(validation_payload, indent=2).encode("utf-8"), "application/json"),
    artifact("editor/spec.json", json.dumps(editor_payload, indent=2).encode("utf-8"), "application/json"),
]

manifest = {
    "id": "hello-scenario",
    "name": "Hello Scenario",
    "version": "1.0.0",
    "description": "Minimal scripted scenario package",
    "interface": {"kind": "labbrew.scenario-package", "version": "1.0"},
    "runner": {"kind": "scripted", "entrypoint": "scripted.run", "config": {}},
    "validation": {"artifact": "validation/validation.json", "required_fields": validation_payload["required_fields"]},
    "editor_spec": {"artifact": "editor/spec.json", "version": "1.0"},
    "endpoint_code": {"language": "python", "entrypoint": "bin/runner.py", "interface_contract": "labbrew.scenario-package@1.0"},
    "program": program_payload,
    "metadata": {"tags": ["example"], "packaging": "self-contained"},
}

buf = io.BytesIO()
with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("scenario.package.msgpack", msgpack.packb(manifest, use_bin_type=True))
    for item in artifacts:
        archive.writestr(item["path"], base64.b64decode(item["content_b64"]))

Path("hello-scenario.lbpkg").write_bytes(buf.getvalue())
```

This is the pattern LabBREW uses internally.

---

## 19. How to change an existing package safely

When someone says “we need to change the package,” first identify which layer actually owns the change.

### Change only metadata

Update:

- `name`
- `version`
- `description`
- `metadata.*`

Do not touch runner or program artifacts unless the behavior changed.

### Change only the execution data

Update:

- `program`
- `data/program.json`
- optionally `source/...`

This is the common case for new recipes, new setpoint profiles, new curves, or new maps.

### Change only the import/conversion behavior

Update:

- `tools/...py`
- `editor/spec.json` upload action definitions if needed
- metadata pointers that identify the converter artifact

This is the right place to add support for a new authoring source, such as:

- a throttle table CSV
- a torque-curve JSON file
- a workbook that generates multiple coordinated targets

### Change runtime semantics

Update:

- `bin/...py`
- `program.schema_version` if the runner now expects new fields

This is where you add capabilities like:

- derived setpoint generation
- interpolation between source points
- grouped writes across multiple outputs
- measurement orchestration
- navigation-aware step logic

---

## 20. Import and repository flows

There are two main ways packages enter the system.

### Direct load into scenario service

- `PUT /scenario/package`
- loads/replaces the active package in `scenario_service`

### Through BrewSupervisor

Use the BrewSupervisor routes when working through the frontend or the repository:

- import/load a package into the active scenario service
- save a package into the repository
- read/copy/rename/delete repository packages
- create packages from templates
- run package-defined file upload actions

The repository flow is what makes package families reusable by non-backend developers.

---

## 21. Measurement helper details

If your package needs to coordinate recording, use the measurement API instead of treating recording as an external manual step.

The runtime exposes:

- `ctx.measurement_status()`
- `ctx.setup_measurement(parameters, hz, output_dir, output_format, session_name, include_files=None, include_payloads=None)`
- `ctx.start_measurement()`
- `ctx.stop_measurement()`
- `ctx.take_loadstep(duration_seconds, loadstep_name, parameters=None)`

Typical pattern:

```python
measurement = program.get("measurement_config") or {}
parameters = list(measurement.get("parameters") or [])
if parameters:
  ctx.setup_measurement(
    parameters=parameters,
    hz=float(measurement.get("hz") or 10.0),
    output_dir=str(measurement.get("output_dir") or "data/measurements"),
    output_format=str(measurement.get("output_format") or "parquet"),
    session_name=str(measurement.get("session_name") or program.get("name") or "scenario-run"),
    include_files=["data/program.json"],
    include_payloads=[{"kind": "scenario-package", "program": program}],
  )
  ctx.start_measurement()
```

Practical guidance:

- call `setup_measurement(...)` before `start_measurement()`
- include `data/program.json` or other source artifacts if you want the run to be reconstructable later
- use `include_payloads` for compact machine-readable run metadata
- stop measurement explicitly if the package owns the measurement lifecycle

This is especially important for packages that are more than simple setpoint replays.

---

## 22. What to implement for a useful reusable package

If your goal is “someone else can pick this up and use it,” implement all of the following:

### Required

- a valid manifest
- a runner artifact
- a program artifact
- a validation artifact
- an editor spec artifact

### Strongly recommended

- `metadata.tags`
- `metadata.version_notes`
- `metadata.notes`
- source-to-package traceability metadata
- deterministic package IDs and names
- explicit `program.kind` and `program.schema_version`
- readable event log messages
- progress updates with stable run indices

### Recommended for repository-first workflows

- `file_upload_actions`
- embedded converter artifact in `tools/...py`
- source artifacts stored under `source/...`

### Recommended for advanced control packages

- grouped or generated setpoint logic
- measurement setup/start behavior
- schema-versioned program payloads
- source artifacts that preserve the original authored input

---

## 23. Template nuances from the packages already in this repo

The current templates are useful because they show the actual design patterns that already work in LabBREW.

### CSV Raw Setpoints template

The CSV template is intentionally simple, but there are important nuances in it.

- it converts a source CSV into `data/program.json`
- it stores the original CSV under `source/...`
- it embeds its own converter as `tools/csv_raw_setpoints_converter.py`
- it stores metadata pointers back to the source artifact and converter artifact
- it batches all setpoints at the same `time_s` and applies them together
- it honors `ctx.start_index` using bucket index semantics, not individual-row semantics

That last point matters. Because writes are bucketed by time, the effective run step is “all setpoints at a given timestamp,” not “each CSV row.”

If you copy this template for a new package family, decide early whether your execution unit is:

- row-based
- timestamp-bucket-based
- stage-based
- generated-step-based

### Excel-style packages

The Excel-style packages are a better reference for:

- richer authoring input
- navigation-aware execution
- more structured multi-step programs
- measurement integration

If you need a package that behaves like a real authored process rather than a flat replay, use the Excel pattern as the conceptual reference and the CSV template as the packaging reference.

---

## 24. Designing packages for future change

The package should be designed around expected change.

For example, if you know a package will eventually need a throttle map, torque curve, and generated setpoints, do not hard-code the package around a single flat list of values.

Instead, define a program schema more like this:

```json
{
  "kind": "torque-profile-generator",
  "schema_version": "2.0",
  "inputs": {
    "throttle_map": [...],
    "torque_curve": [...],
    "limits": {...}
  },
  "generation": {
    "mode": "interpolated",
    "sample_period_s": 0.5
  },
  "execution": {
    "target": "set_torque_Device",
    "hold_strategy": "per-sample"
  },
  "measurement_config": {
    "parameters": ["torque_actual", "speed_actual"],
    "hz": 20,
    "output_format": "parquet",
    "output_dir": "data/measurements"
  }
}
```

Then make the converter own generation of the executable runtime representation.

That gives you a clean split:

- author input changes live in `inputs`
- generation logic changes live in `tools/...py`
- runtime execution changes live in `bin/...py`

That is the level of separation you want for packages that will evolve.

---

## 25. Run index conventions

LabBREW’s UI shows a run index. Use that consistently.

Recommended rule:

- internal Python loop index may be zero-based
- user-facing `step_index` published to `ctx.set_progress(...)` should be one-based
- logs shown to operators should use the same one-based numbering

Example:

```python
for internal_index, step in enumerate(steps[start_index:], start=start_index):
    run_index = internal_index + 1
    ctx.set_progress(step_index=run_index, step_name=step_name, wait_message="Running")
```

That keeps “Start At Run Index” aligned with what the UI displays.

---

## 26. Measurement integration

If your package should start or manage data recording, use the measurement APIs from `RunnerContext`.

Typical pattern:

1. define `measurement_config` in `program`
2. call `ctx.setup_measurement(...)`
3. call `ctx.start_measurement()`
4. optionally inspect `ctx.measurement_status()`
5. stop or let runtime cleanup happen at the end depending on your package design

Use the existing Excel-style packages as the reference behavior here.

---

## 27. Navigation integration

If your package supports `Next` and `Previous`, your runner must explicitly consume navigation requests.

The runtime queues navigation events, but the package decides how to apply them.

Use:

- `ctx.consume_navigation()`
- `ctx.is_paused()`

The Excel runner implementation is the best reference for step navigation behavior.

---

## 28. Validation and smoke-test checklist

Before handing a package to someone else, verify all of this:

1. The archive contains `scenario.package.msgpack`.
2. `endpoint_code.entrypoint` exists in the zip.
3. `validation.artifact` exists in the zip.
4. `editor_spec.artifact` exists in the zip.
5. The runner can execute using only embedded artifacts and standard library imports.
6. The runner releases control in `finally`.
7. The runner uses `ctx.sleep(...)` instead of `time.sleep(...)`.
8. The runner publishes progress with a stable run index.
9. The repository editor can open the package.
10. The package can be imported and started without faults.

Quick local inspection command:

```powershell
.venv\Scripts\python.exe -c "import msgpack, zipfile; p='data/scenario_packages/your_package.lbpkg'; z=zipfile.ZipFile(p,'r'); m=msgpack.unpackb(z.read('scenario.package.msgpack'), raw=False); print('id=', m.get('id')); print('runner.kind=', m.get('runner',{}).get('kind')); print('endpoint=', m.get('endpoint_code',{}).get('entrypoint')); print('validation=', m.get('validation',{}).get('artifact')); print('editor=', m.get('editor_spec',{}).get('artifact')); print('entries=', len(z.namelist()))"
```

---

## 29. Troubleshooting

### Package compiles but runner faults immediately

Usually one of:

- missing `run(ctx)` function
- artifact path typo in `ctx.get_artifact(...)`
- non-stdlib import not shipped in package artifacts
- invalid `program.json` schema for your runner logic

### Package imports but repository editor does not work

Usually one of:

- missing `editor_spec.artifact`
- `editor_spec.artifact` path not present in `artifacts`
- malformed `editor/spec.json`

### Package compiles but start does nothing meaningful

Usually one of:

- runner never requests control
- runner never writes setpoints
- runner has an empty `program`
- all steps are skipped due to start-index logic

### Package leaves controls owned after stop/fault

Cause:

- missing release path

Fix:

- use `try/finally`
- call `ctx.release_all()` or `ctx.release_control(...)` in `finally`

---

## 30. Recommended package layout standard

If your team wants a repeatable convention, use this layout for all new package families:

```text
bin/
  runner.py
tools/
  converter.py              # optional, for repository/template rebuilds
data/
  program.json
validation/
  validation.json
editor/
  spec.json
source/
  original_input.ext        # optional, preserved source material
```

This layout is easy to reason about and already matches the package template tooling in this repo.

---

## 31. What to read next

- [Writing a Scenario Runner](./writing-a-scenario-runner.md)
- [Scenario Service Integration Plan](./scenario-service-integration.md)
- [Schedule Excel Import](../api/schedule-excel-import.md)
- `Other/tools/create_csv_raw_setpoint_template.py`
- `Services/scenario_service/scripted_runner.py`

If you are creating a new package family, start from the builder pattern in `Other/tools/create_csv_raw_setpoint_template.py` and adapt it rather than inventing a brand new package structure.