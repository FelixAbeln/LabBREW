# Writing a Scenario Runner Module

This guide explains how to build a production-ready scripted scenario runner for LabBREW packages.

If you need the full package-authoring workflow, including `.lbpkg` archive structure, manifest fields, editor spec, validation artifacts, and repository integration, start with [Writing a LabBREW `.lbpkg` Package](./writing-an-lbpkg-package.md).

It covers:
- the required package shape,
- the runner entrypoint contract,
- the full RunnerContext API,
- progress and status publishing,
- wait/action patterns,
- compatibility and troubleshooting,
- validation and test workflow.

---

## 1. Runtime model (what executes your code)

Scenario packages are executed by the scripted runner host in [Services/scenario_service/scripted_runner.py](../../Services/scenario_service/scripted_runner.py).

Execution behavior:
- Your package entrypoint script is loaded from package artifacts and executed with Python `exec`.
- The script must expose `run(ctx)`.
- `run(ctx)` executes inside a background daemon thread.
- Pause and stop are event-driven and respected by `ctx.sleep(...)`.
- Unhandled exceptions in your script fault the run and surface in `/scenario/run/status` as `Fault: ...`.

---

## 2. Required package fields

Your package manifest must include the following sections:

- `interface`
  - `kind`: `labbrew.scenario-package`
  - `version`: `1.0`
- `runner`
  - `kind`: `scripted`
- `endpoint_code`
  - `language`: `python`
  - `entrypoint`: artifact path to your runner script (for example `bin/runner.py`)
- `artifacts`
  - must include the entrypoint path above
  - can include any additional files your runner reads via `ctx.get_artifact(...)`

Minimal example:

```json
{
  "id": "example-scenario",
  "name": "Example Scenario",
  "version": "1.0.0",
  "interface": {
    "kind": "labbrew.scenario-package",
    "version": "1.0"
  },
  "runner": {
    "kind": "scripted",
    "config": {}
  },
  "endpoint_code": {
    "language": "python",
    "entrypoint": "bin/runner.py"
  },
  "artifacts": [
    {
      "path": "bin/runner.py",
      "content_b64": "..."
    }
  ]
}
```

---

## 3. Runner entrypoint contract

Your module must define exactly one callable entrypoint:

```python
def run(ctx):
    ...
```

Guidelines:
- Keep all side effects inside `run(ctx)`.
- Return normally for successful completion.
- Check `ctx.is_stopped()` in long loops.
- Use `ctx.sleep(...)` instead of `time.sleep(...)` so pause/stop works correctly.
- Use `try/finally` to release control for all owned targets.

---

## 4. RunnerContext API reference

Methods currently available:

- `ctx.write_setpoint(target, value)`
  - Writes a setpoint through control service.
- `ctx.read_value(target) -> Any`
  - Reads current value.
- `ctx.request_control(target)`
  - Claims ownership of a target.
- `ctx.release_control(target)`
  - Releases ownership.
- `ctx.release_all()`
  - Releases all targets owned by this runner.
- `ctx.sleep(seconds)`
  - Pause/stop-aware sleep.
- `ctx.is_stopped() -> bool`
  - True after stop has been requested.
- `ctx.log(message)`
  - Appends to event log shown in run status.
- `ctx.get_artifact(path) -> bytes`
  - Reads an artifact from the package archive.
- `ctx.set_progress(phase=None, step_index=None, step_name=None, wait_message=None)`
  - Updates status fields consumed by dashboard cards and run status endpoints.

Progress field mapping:
- `phase` -> run phase display
- `step_index` -> run index display
- `step_name` -> active step display
- `wait_message` -> wait/status display

---

## 5. Recommended runner skeleton

Use this as a base template:

```python
from __future__ import annotations

import json


def _set_progress(ctx, **kwargs) -> None:
    """Best-effort progress updates for mixed runtime versions."""
    fn = getattr(ctx, "set_progress", None)
    if callable(fn):
        try:
            fn(**kwargs)
        except Exception:
            pass


def run(ctx) -> None:
    target = "agitator.speed.setpoint"
    ctx.request_control(target)
    _set_progress(ctx, phase="setup", step_index=0, step_name="Initialize", wait_message="Running")

    try:
        program = json.loads(ctx.get_artifact("data/program.json").decode("utf-8"))
        steps = program.get("plan_steps") or []

        for i, step in enumerate(steps):
            if ctx.is_stopped():
                ctx.log("Stopped by operator")
                return

            name = str(step.get("name") or f"Step {i + 1}")
            value = step.get("value")
            duration = float(step.get("duration_s") or 0.0)

            _set_progress(
                ctx,
                phase="plan",
                step_index=i,
                step_name=name,
                wait_message=f"Holding {duration:.1f}s",
            )
            ctx.write_setpoint(target, value)
            ctx.sleep(duration)

        _set_progress(ctx, phase="done", wait_message="Completed")

    finally:
        ctx.release_control(target)
```

Why this pattern:
- Compatibility shim prevents faults if older nodes do not expose `set_progress`.
- `ctx.sleep(...)` keeps pause/stop functional.
- `finally` guarantees ownership cleanup.

---

## 6. Wait and action implementation patterns

Most runners need reusable wait/action primitives. Recommended structure:

- Action layer
  - write: direct setpoint write
  - ramp: stepped interpolation loop using `ctx.sleep(slice)`
  - trigger: fire-and-continue commands
- Wait layer
  - none: immediate continue
  - elapsed: fixed duration sleep
  - condition: poll + compare (`ctx.read_value`)
  - any_of: success when first child completes
  - all_of: success when all child waits complete

Implementation rules:
- Always short-circuit if `ctx.is_stopped()`.
- Poll at a small interval (for example 0.05 to 0.2 seconds).
- Keep condition parsing tolerant of bad/missing values.
- Write readable `wait_message` values to aid operator debugging.

The reference implementation used by Excel-imported packages lives inside the tracked template package at [data/scenario_templates/Excel_Conditions.lbpkg](../../data/scenario_templates/Excel_Conditions.lbpkg) under `bin/excel_program_runner.py`.

---

## 7. Packaging checklist

Before publishing a package:

1. Confirm manifest fields (`runner.kind=scripted`, valid entrypoint path).
2. Confirm entrypoint artifact exists.
3. Confirm all required data artifacts exist.
4. Verify runner imports only standard library or code embedded in artifacts.
5. Validate script can run with missing `set_progress` (compat shim).
6. Ensure every `request_control` has a matching release (directly or through `release_all`).
7. Ensure loops check `ctx.is_stopped()`.
8. Ensure all delays use `ctx.sleep(...)`.

---

## 8. Local validation workflow

### Validate package manifest and artifacts

Use the same pattern used for package checks:

```powershell
.venv\Scripts\python.exe -c "import msgpack, zipfile; p='data/scenario_packages/your_package.lbpkg'; z=zipfile.ZipFile(p,'r'); m=msgpack.unpackb(z.read('scenario.package.msgpack'), raw=False); print('runner.kind=', m.get('runner',{}).get('kind')); print('endpoint=', m.get('endpoint_code',{}).get('entrypoint')); print('status_endpoint=', m.get('interface',{}).get('status_endpoint')); print('has_runner=', any(n=='bin/runner.py' for n in z.namelist()))"
```

### Service-level smoke test

1. Load package with `PUT /scenario/package`.
2. Start run with `POST /scenario/run/start`.
3. Poll `GET /scenario/run/status`.
4. Confirm fields update:
   - `state`
   - `phase`
   - `current_step_index`
   - `current_step_name`
   - `wait_message`

### Regression test targets

Use or extend tests around scripted execution and route integration:
- [tests/test_scenario_scripted_runner.py](../../tests/test_scenario_scripted_runner.py)
- [tests/test_brewsupervisor_routes.py](../../tests/test_brewsupervisor_routes.py)
- [tests/test_multidevice_simulation.py](../../tests/test_multidevice_simulation.py)

---

## 9. Troubleshooting

### Fault: RunnerContext object has no attribute set_progress

Cause:
- Package script calls `ctx.set_progress(...)` but runtime host is older or not restarted.

Fix:
- Use a best-effort compatibility helper (`_set_progress`) that checks method availability.
- Restart services after updating runtime code.
- Rebuild package so embedded runner contains the compatibility helper.

### Runner ignores pause/stop

Cause:
- Script uses `time.sleep(...)` directly or long blocking calls without stop checks.

Fix:
- Replace all delays with `ctx.sleep(...)`.
- Add `ctx.is_stopped()` checks inside loops.

### Targets remain owned after completion

Cause:
- Missing release in error paths.

Fix:
- Wrap owned-target operations in `try/finally` and release in `finally`.

### Artifact not found

Cause:
- Path mismatch between manifest artifact list and `ctx.get_artifact(path)`.

Fix:
- Ensure exact path match including directory and casing.

---

## 10. Versioning and compatibility guidance

- Prefer additive changes to runner data files and config.
- Keep default behavior when optional fields are missing.
- When introducing new context APIs, keep package-side fallbacks for one migration window.
- Record package schema changes in release notes and in this guide.

---

## 11. Related references

- [Scenario Service Integration Plan](./scenario-service-integration.md)
- [Schedule Excel Import Guide](../api/schedule-excel-import.md)
- [Wait Event Engine Notes](./wait-event-engine.md)
- [Scripted runner host implementation](../../Services/scenario_service/scripted_runner.py)
