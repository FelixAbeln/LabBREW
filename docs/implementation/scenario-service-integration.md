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
- [x] Scenario state persistence introduced (`data/scenario_state.json`).
- [x] HTTP clients (ControlClient, DataClient) moved to scenario_service.
- [x] Legacy ScheduleDefinition models preserved for Excel importer compatibility.
- [x] All schedule_service tests removed.
- [x] **schedule_service folder deleted completely.**

## Second Implementation Slice (COMPLETED - April 19, 2026)

### Files Migrated (schedule_service removed)

#### Schedule Service Deletion
- ✅ Removed: `Services/schedule_service/` (entire folder)
- ✅ Removed: `Services/schedule_service/runtime/*` (core, actions, measurement, navigation, ownership, persistence, utils)
- ✅ Removed: `Services/schedule_service/api/routes_schedule.py`
- ✅ Removed: All 14 `tests/test_schedule*.py` test files

#### Added to Scenario Service
- ✅ `Services/scenario_service/control_client.py` (moved from schedule_service)
- ✅ `Services/scenario_service/data_client.py` (moved from schedule_service)
- ✅ `Services/scenario_service/models.py` – added ScheduleDefinition classes for Excel importer
- ✅ `Services/scenario_service/__init__.py` – maintained

#### Updated References
- ✅ `tests/conftest.py` – routes_schedule → routes_scenario
- ✅ Excel conversion package templates now sourced from tracked template artifacts (`data/scenario_templates/Excel_Conditions.lbpkg`)
- ✅ `tests/test_supervisor_config_loader.py` – all 4 YAML fixtures updated (schedule_service → scenario_service, port 8768 → 8770)
- ✅ `docs/api/architecture.md` – diagram and data flows updated
- ✅ `docs/api/schedule-service-api.md` – marked deprecated, redirects to Scenario Service

### Remaining Frontend/Gateway Work

These are out of scope for April 2026 phase:

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

## Historical File Map

### New files (first slice)

- `Services/scenario_service/__init__.py`
- `Services/scenario_service/api/__init__.py`
- `Services/scenario_service/api/routes_scenario.py`
- `Services/scenario_service/models.py`
- `Services/scenario_service/repository.py`
- `Services/scenario_service/runtime.py`
- `Services/scenario_service/service.py`

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

### Files Kept (for historical reference or compatibility)

- `BrewSupervisor/api/schedule_import/*`
  - Workbook import still present; imports ScheduleDefinition from scenario_service models.
  - Converts Excel → scenario package JSON artifacts.

### Removed Files Deleted

- `Services/schedule_service/` (entire service)
  - `api/routes_schedule.py`
  - `runtime/core.py`
  - `runtime/utils.py`
  - `runtime/actions.py`
  - `runtime/measurement.py`
  - `runtime/navigation.py`
  - `runtime/ownership.py`
  - `runtime/persistence.py`
  - `control_client.py` (moved to scenario_service)
  - `data_client.py` (moved to scenario_service)
  - `models.py` (ScheduleDefinition moved to scenario_service)
  - `repository.py` (no longer needed)

## Next implementation slice

1. ✅ Backend consolidation complete — schedule_service deleted, scenario_service ready.
2. **IN PROGRESS**: Frontend route bridging and proxy setup.
3. Update/test scenario runner execution against real control/data services.
4. Validate Excel workbook → scenario package conversion pipeline.
