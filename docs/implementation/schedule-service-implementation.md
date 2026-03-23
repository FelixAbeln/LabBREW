# Schedule Service — Implementation Status

> Last updated: 2026-03-23

---

## Architecture

The schedule service lives in `Services/schedule_service/` and is structured
as a FastAPI app backed by a threaded poll-loop runtime.

```
Services/schedule_service/
├── service.py                  # App wiring — FastAPI + uvicorn entry point
├── models.py                   # Data models: ScheduleDefinition, ScheduleStep,
│                               #   ScheduleAction, StepRuntime, RunStatus
├── repository.py               # InMemoryScheduleRepository + JsonScheduleStateStore
├── control_client.py           # HTTP client → control service (ownership, read/write/ramp)
├── data_client.py              # HTTP client → data service (measurement, loadstep)
│
├── runtime/
│   ├── __init__.py             # Public export for ScheduleRuntime
│   ├── core.py                 # Thin orchestrator — ScheduleRuntime class
│   ├── utils.py                # _UtilsMixin (naming/index/event/wait helpers)
│   ├── ownership.py            # _OwnershipMixin
│   ├── measurement.py          # _MeasurementMixin
│   ├── actions.py              # _ActionsMixin
│   ├── navigation.py           # _NavigationMixin
│   └── persistence.py          # _PersistenceMixin
│
└── api/
    └── routes_schedule.py      # FastAPI routes — thin passthrough to runtime
```

---

## Implemented ✅

### Core runtime

- [x] Background poll loop (configurable interval, default 200 ms)
- [x] State machine: `idle → running ↔ paused → stopped / completed / faulted`
- [x] Schedule load / clear (persisted to `data/schedule_state.json`)
- [x] Startup restore from JSON state store
- [x] Elapsed-time and condition-based wait evaluation via `WaitEngine`
- [x] Step activation resets all elapsed / condition tracking

### Step execution

- [x] `request_control`, `release_control`, `write`, `ramp` actions
- [x] Global measurement auto-start at run start (from schedule-level config)
- [x] Resume ensures measurement is running (auto-starts if it is not)
- [x] `take_loadstep` with `timing=on_enter` (immediate) and
      `timing=before_next` (deferred, fires at natural step conclusion)
- [x] Deferred loadsteps block step advance until the data service reports
      completion (`completed_loadsteps`)
- [x] Steps with `wait: none` skip deferred loadsteps entirely
- [x] Manual Next / Previous never triggers exit loadsteps
- [x] Measurement finalized on run stop, complete, and abort

### Pause / resume

- [x] Manual pause
- [x] Pause keeps measurement running
- [x] Resume resets elapsed / condition wait state to zero (timers
      restart fresh after pause)
- [x] Resume preserves in-flight loadstep wait when exit loadsteps were
      already triggered before pause

### Ownership tracking

- [x] Owned targets tracked per-owner string
- [x] Ownership-lost detection pauses the run automatically
- [x] All owned targets released on stop / clear / complete

### Phase transitions

- [x] `setup` → `plan` transition
- [x] `plan` → `completed` when all enabled plan steps finish
- [x] Previous step can cross from `plan` back into `setup`

### Persistence

- [x] Full schedule definition serialised alongside run state
- [x] Step elapsed time restored via UTC offset on restart

### HTTP clients

- [x] `DataClient` — pooled `requests.Session` (`pool_block=True`,
      bounded connection pool, `keep-alive`)
- [x] `ControlClient` — pooled `requests.Session`
- [x] Auto-fallback: data service falls back parquet → JSONL when
      `pyarrow` is not installed

### API layer

- [x] `GET  /schedule` — return loaded schedule
- [x] `PUT  /schedule` — load / replace schedule
- [x] `DELETE /schedule` — clear schedule
- [x] `POST /schedule/start`
- [x] `POST /schedule/pause`
- [x] `POST /schedule/resume`
- [x] `POST /schedule/stop`
- [x] `POST /schedule/next`
- [x] `POST /schedule/previous`
- [x] `GET  /schedule/status`

### Excel import

- [x] `.xlsx` workbook → schedule payload parser (`BrewSupervisor/api/schedule_import/`)
- [x] `measurement_config` generated from `meta` sheet settings (schedule-level)
- [x] `take_loadstep` column is numeric duration in seconds only
- [x] All Excel-sourced loadsteps tagged `timing=before_next`
- [x] Measurement session name defaults to generated schedule-based naming
      with optional `meta.measurement_name` override
- [x] Template workbook at `data/Example_Schedule.xlsx` (6 sheets,
      unified dark-blue header style)

---

## Incomplete / Not Implemented ❌

### Testing

- [ ] **No unit tests exist** for any schedule service module.
      `WaitEngine`, action dispatch, persistence, and navigation are all
      untested.  This is the highest-priority gap.
- [ ] No integration / end-to-end tests against a live control service.
- [ ] No property-based tests for the Excel parser edge cases.

### Runtime features

- [ ] **Action failure strategy** — currently raises `RuntimeError` which
      faults the run.  No retry, skip, or alert options.
- [ ] **Timeout-based auto-advance** — no per-step maximum duration.
      A stuck wait condition runs forever.
- [ ] **Step repeat / loop** — no way to loop back N times from the
      schedule definition.
- [ ] **Conditional branching** — no if/else or jump-to-step support.
- [ ] **Dry-run mode** — no simulation path that skips hardware writes.
- [ ] **Multi-schedule support** — only one schedule can be loaded at
      a time.  Swapping mid-run is undefined behaviour.
- [ ] **Abort vs stop distinction** — `stop_run` always finalises
      measurement.  There is no hard-abort path that skips cleanup.

### Pause / resume

- [ ] **Pending exit-loadstep state is not persisted** — if the service
      restarts while waiting for a before_next loadstep to complete, the
      wait is lost and the step advances immediately on restore.
- [ ] **Pause reason surfacing** — `pause_reason` field exists in the
      model but only `manual` and `ownership_lost` are populated.
      Other fault conditions set `faulted` state instead.

### Persistence

- [ ] **Concurrent write safety** — `JsonScheduleStateStore.save()` does
      a full overwrite on every tick.  Under load this could cause partial
      reads.  No atomic write (temp file + rename) is implemented.
- [ ] **History / audit log** — `event_log` is capped at 100 entries and
      is lost on restart.  No persistent run history.
- [ ] **Multiple state slots** — only one schedule state file at
      `data/schedule_state.json`.

### API / integration

- [ ] **WebSocket / SSE push** — clients must poll `/schedule/status`.
      No real-time event stream.
- [ ] **Authentication** — all endpoints are open.  No auth middleware.
- [ ] **Schedule versioning** — no schema version field; old schedule
      state files may silently break after changes to `ScheduleDefinition`.
- [ ] **Schedule validation endpoint** — there is no `POST /schedule/validate`
      dry-run that returns errors without loading.
- [ ] **Export run results** — no endpoint or mechanism to download a
      completed run's event log or measurement references.

### Excel import

- [ ] **Round-trip export** — the parser is import-only; there is no way
      to export a running schedule back to `.xlsx`.
- [ ] **JSON / YAML import** — only `.xlsx` is supported.
- [ ] **Multi-sheet step lists** — all setup steps must be on one sheet
      and all plan steps on one sheet; no support for splitting across
      multiple sheets.
- [ ] **Import validation errors surface to UI** — parse errors are
      returned as exceptions; the front-end has no structured error list.

### Observability

- [ ] **Metrics** — no Prometheus / StatsD counters for tick latency,
      step durations, or fault rates.
- [ ] **Structured logging** — `event_log` is plain strings.  No
      structured JSON log output.
- [ ] **Health endpoint** — no `/health` or `/ready` probe.

---

## Known Issues

| # | Description | Workaround |
|---|-------------|------------|
| 1 | `pyarrow` not installed → parquet write silently fails | Auto-fallback to JSONL is implemented in `data_service/runtime.py` |
| 2 | `pending_exit_loadsteps` lost on restart | Rare in practice; step will advance without waiting on next restore |
| 3 | State file written on every 200 ms tick | Acceptable for current scale; use atomic write if throughput increases |

---

## Dependencies

| Package | Used for |
|---------|----------|
| `fastapi` | HTTP API framework |
| `uvicorn` | ASGI server |
| `requests` | HTTP client to control and data services |
| `openpyxl` | Excel schedule import |
| `pyarrow` | (optional) Parquet measurement files |

Internal shared modules:

| Module | Purpose |
|--------|---------|
| `Services/_shared/wait_engine` | `WaitEngine`, `WaitSpec`, `WaitState`, `parse_wait_spec` |
| `Services/_shared/operator_engine` | `ConditionEngine`, `EvaluationState`, plugin registry |
| `Services/_shared/cli` | `parse_args` for host/port CLI flags |
