# Scenario Service Integration Plan

This document tracks the migration from `schedule_service` to `scenario_service`.

For runner module implementation details, see [Writing a Scenario Runner](./writing-a-scenario-runner.md).

## Goal

Build a thin orchestration service that:
- compiles/loads scenario packages,
- emits run intents,
- delegates control ownership/writes to `control_service`,
- delegates measurement/archive lifecycle to `data_service`.

## API Proposal (v1, first slice)

Base URL: `http://<node-host>:8770`

### Package endpoints

- `GET /scenario/package`
  - Returns active package (or `null`).
- `PUT /scenario/package`
  - Loads/replaces package.
  - Accepts `runner.kind=scripted`.
- `DELETE /scenario/package`
  - Clears active package.
- `POST /scenario/compile`
  - Validates and normalizes package payload without loading it.

### Run endpoints

- `POST /scenario/run/start`
- `POST /scenario/run/pause`
- `POST /scenario/run/resume`
- `POST /scenario/run/stop`
- `POST /scenario/run/next`
- `POST /scenario/run/previous`
- `GET /scenario/run/status`

`run/*` endpoints execute package-provided scripted runners.

## Data Model (v1)

### ScenarioPackageDefinition

```json
{
  "id": "scenario-whtc-01",
  "name": "WHTC Cold Start",
  "version": "0.1.0",
  "description": "Scripted scenario package",
  "interface": {
    "kind": "labbrew.scenario-package",
    "version": "1.0"
  },
  "validation": {
    "required_fields": ["id", "name", "runner", "interface", "endpoint_code", "program"]
  },
  "endpoint_code": {
    "language": "python",
    "entrypoint": "bin/runner.py"
  },
  "runner": {
    "kind": "scripted",
    "entrypoint": null,
    "config": {}
  },
  "program": {
    "id": "whtc",
    "name": "WHTC",
    "measurement_config": {},
    "setup_steps": [],
    "plan_steps": []
  },
  "metadata": {
    "author": "lab"
  }
}
```

### ScenarioCompileResult

```json
{
  "ok": true,
  "runner": "scripted",
  "errors": [],
  "warnings": [],
  "normalized_program": {}
}
```

### ScenarioRunStatus

```json
{
  "ok": true,
  "status": {
    "state": "running",
    "package_id": "scenario-whtc-01",
    "package_name": "WHTC Cold Start",
    "runner_kind": "scripted",
    "wait_message": "Active step: warmup",
    "pause_reason": null,
    "event_log": [],
    "owned_targets": [],
    "details": {}
  },
  "runner_status": {},
  "package": {}
}
```

## First Implementation Slice (completed)

- [x] New service package scaffolded at `Services/scenario_service/`.
- [x] New API routes created under `/scenario/*`.
- [x] New scenario package models added.
- [x] New runtime created with compile/load package flow.
- [x] Runtime executes package scripts via `ScriptedRunner`.
- [x] New runner script added: `run_service_scenario.py`.
- [x] Scenario state persistence introduced (`data/scenario_state.json`).

## File-by-File Migration Map

### New files (first slice)

- `Services/scenario_service/__init__.py`
- `Services/scenario_service/api/__init__.py`
- `Services/scenario_service/api/routes_scenario.py`
- `Services/scenario_service/models.py`
- `Services/scenario_service/repository.py`
- `Services/scenario_service/runtime.py`
- `Services/scenario_service/service.py`
- `run_service_scenario.py`

### Existing files to migrate next

- `BrewSupervisor/api/routes.py`
  - Add `/fermenters/{id}/scenario/*` proxy and dashboard fields.
  - Remove `/schedule/*` compatibility bridge.
- `Supervisor/infrastructure/agent_api.py`
  - Add `/scenario/*` bridge to `scenario_service`.
  - Remove `/schedule/*` compatibility bridge.
- `BrewSupervisor/reat-frontend/brew-ui/src/features/schedule/ScheduleTab.jsx`
  - Retarget actions to `/scenario/run/*`.
  - Rename workbook/import UX to package/import UX.
- `BrewSupervisor/reat-frontend/brew-ui/src/features/schedule/scheduleUtils.js`
  - Replace run-toggle paths with scenario run paths.
- `BrewSupervisor/reat-frontend/brew-ui/src/App.jsx`
  - Add scenario status/package polling and scenario module terminology.
- `BrewSupervisor/reat-frontend/brew-ui/src/features/app/workspaceModuleCatalog.jsx`
  - Swap schedule summary module bindings to scenario runtime data.

### Existing files to keep (short term compatibility)

- `Services/schedule_service/*`
  - Keep running while frontend and supervisor are migrated.
- `BrewSupervisor/api/schedule_import/*`
  - Keep workbook import; compile workbook payload into scripted package artifacts.

## Next implementation slice

1. Add supervisor and agent route bridging for `/scenario/*`.
2. Remove schedule bridge routes from gateway and agent APIs.
3. Add import adapter in BrewSupervisor:
   - workbook -> scenario package payload,
   - forward to `PUT /scenario/package`.
4. Add initial scenario API docs in `docs/api/` and register service port 8770 in architecture docs.
