# Schedule Service API

**Base URL:** `http://<node-host>:8768`  
**Source:** `Services/schedule_service/api/routes_schedule.py`, `Services/schedule_service/models.py`

The Schedule Service executes multi-step fermentation schedules. A schedule has two phases: **setup** (run once at start) and **plan** (the main repeating sequence). Each step can carry a list of control actions and an optional wait condition that gates progression to the next step.

The runtime can call both Control Service and Data Service backends. This allows schedule steps to apply setpoints and trigger recording/loadstep operations in the same sequence.

Measurement lifecycle with scheduler state:

- `start`: scheduler auto-starts global measurement.
- `pause`: measurement continues running (fermentation is still active).
- `resume`: scheduler ensures measurement is running; if it stopped while paused, it is auto-started again.
- `stop`: scheduler stops/finalizes measurement.

---

## Data Models

### `ScheduleDefinition`

```json
{
  "id": "my-schedule",
  "name": "Standard Lager",
  "setup_steps": [ /* array of ScheduleStep */ ],
  "plan_steps":  [ /* array of ScheduleStep */ ]
}
```

### `ScheduleStep`

```json
{
  "id": "step-1",
  "name": "Dough-in",
  "enabled": true,
  "actions": [ /* array of ScheduleAction */ ],
  "wait": { /* WaitSpec or null — see WaitSpec section below */ }
}
```

### `ScheduleAction`

```json
{
  "kind": "set",
  "target": "reactor.temp.setpoint",
  "value": 65.0,
  "duration_s": null,
  "owner": "schedule",
  "params": {}
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `kind` | string | yes | Action type (see below) |
| `target` | string | yes | Parameter name to act on |
| `value` | any | for `set`/`ramp` | Value to write or ramp to |
| `duration_s` | number | for `ramp` | Duration of the ramp in seconds |
| `owner` | string | no | Caller identity for ownership checks |
| `params` | object | no | Extra type-specific parameters |

**`kind` values**

| `kind` | Description |
|---|---|
| `set` / `write` | Write `value` to `target` immediately via the Control Service |
| `ramp` | Linearly ramp `target` from its current value to `value` over `duration_s` seconds |
| `request_control` | Request ownership of `target` via the Control Service |
| `release_control` | Release ownership of `target` via the Control Service |
| `global_measurement` | Start/stop Data Service recording session (`value` or `params.mode`: `start`, `setup_start`, `stop`) |
| `take_loadstep` | Trigger Data Service loadstep averaging (`duration_s` / `params.duration_seconds`) |

For `global_measurement=start`, optional `params` include:

- `parameters`: list of parameter names (if omitted, scheduler auto-uses control snapshot keys)
- `hz`: sample rate (default `10`)
- `output_dir`: output directory (default `data/measurements`)
- `output_format`: `parquet`, `csv`, `jsonl` (default `parquet`)
- `session_name`: explicit measurement name (default is generated from schedule id + UTC time)

Runtime behavior is idempotent:

- If `global_measurement=start` is called while recording is already active, scheduler keeps the existing recording and does not fault.
- If `global_measurement=stop` is called while recording is already stopped, scheduler treats it as a no-op.

For `take_loadstep`, optional `params` include:

- `loadstep_name`: explicit name (default is generated from schedule id + UTC time)
- `parameters`: subset list to average (defaults to active measurement parameters)
- `timing`: `on_enter` (default) or `before_next`/`on_exit` to capture right before step transition

Loadstep persistence note:

- `take_loadstep` triggers Data Service averaging windows.
- The averaged loadstep summaries are exposed by Data Service status/stop responses.
- They are persisted by Data Service to `<output_dir>/<session_name>.loadsteps.<output_format>` (same format as the main recording) and are not written as dedicated records inside the measurement sample file format.

---

### `WaitSpec`

The `wait` field of a `ScheduleStep` is a **WaitSpec** — a possibly-nested structure evaluated each runtime tick before the scheduler advances to the next step. It is `null` / omitted when no wait is needed.

#### Kind: `none`

Always passes immediately. Equivalent to omitting the `wait` field entirely.

```json
{"kind": "none"}
```

#### Kind: `elapsed`

Waits until at least `duration_s` seconds have passed since the step started.

```json
{"kind": "elapsed", "duration_s": 3600}
```

| Field | Type | Required |
|---|---|---|
| `duration_s` | number | yes |

#### Kind: `condition`

Waits for a single parameter condition to be true. Optionally holds for `for_s` seconds continuously before advancing.

```json
{
  "kind": "condition",
  "condition": {
    "source": "reactor.temp",
    "operator": ">=",
    "threshold": 64.0,
    "for_s": 60
  }
}
```

**`condition` fields**

| Field | Type | Required | Description |
|---|---|---|---|
| `source` | string | yes | ParameterDB parameter name to read |
| `operator` | string | yes | Comparison operator (see table below) |
| `threshold` | number / bool | yes | Value to compare against |
| `for_s` | number | no | Condition must stay true for this many seconds (default `0`) |

**Available operators**

| Operator | Description | `threshold` type |
|---|---|---|
| `>` | Greater than | number |
| `>=` | Greater than or equal | number |
| `<` | Less than | number |
| `<=` | Less than or equal | number |
| `==` | Loose equality (number, bool, string) | any |
| `!=` | Loose inequality | any |
| `in_range` | Inclusive range — requires `params.min` and `params.max` instead of `threshold` | number |
| `out_of_range` | Outside inclusive range — requires `params.min` and `params.max` | number |
| `always_true` | Always passes regardless of value | any |

For `in_range` / `out_of_range` use the `params` key instead of `threshold`:

```json
{
  "source": "reactor.temp",
  "operator": "in_range",
  "params": {"min": 60.0, "max": 70.0}
}
```

The condition object can also contain composite logic using `all`, `any`, and `not` keys (see below).

#### Kind: `all_of`

All child `WaitSpec` nodes must match before advancing.

```json
{
  "kind": "all_of",
  "children": [
    {"kind": "elapsed", "duration_s": 600},
    {
      "kind": "condition",
      "condition": {"source": "reactor.temp", "operator": ">=", "threshold": 64.0}
    }
  ]
}
```

#### Kind: `any_of`

At least one child `WaitSpec` node must match before advancing.

```json
{
  "kind": "any_of",
  "children": [
    {"kind": "elapsed", "duration_s": 7200},
    {
      "kind": "condition",
      "condition": {"source": "abort.flag", "operator": "==", "threshold": true}
    }
  ]
}
```

#### Composite conditions inside a `condition` wait

The `condition` field of a `kind: "condition"` wait can itself be a **composite condition** using `all`, `any`, or `not` keys instead of a flat `source`/`operator`/`threshold` map:

```json
{
  "kind": "condition",
  "condition": {
    "all": [
      {"source": "reactor.temp", "operator": ">=", "threshold": 63.0},
      {"source": "agitator.rpm",  "operator": ">=", "threshold": 100}
    ],
    "for_s": 30
  }
}
```

| Composite key | Behaviour |
|---|---|
| `all` | All child conditions must be true |
| `any` | At least one child condition must be true |
| `not` | Inverts its single child condition |

All composite nodes also support `for_s` to require the composite result to remain true for a minimum hold time.

### `RunStatus`

Returned by `GET /schedule/status`.

```json
{
  "state": "running",
  "phase": "plan",
  "schedule_id": "my-schedule",
  "schedule_name": "Standard Lager",
  "current_step_index": 3,
  "current_step_name": "Beta-glucan rest",
  "wait_message": "Waiting: reactor.temp >= 40",
  "pause_reason": null,
  "owned_targets": ["reactor.temp.setpoint"],
  "last_action_result": {"ok": true},
  "event_log": [
    "2024-01-15T10:00:00Z  [setup] Step 'Dough-in' actions applied",
    "2024-01-15T10:05:00Z  [plan]  Step 'Protein rest' started"
  ]
}
```

**`state` values**

| Value | Description |
|---|---|
| `idle` | No schedule loaded or stopped |
| `running` | Actively executing steps |
| `paused` | Execution suspended |
| `completed` | All plan steps finished |
| `stopped` | Manually stopped |
| `faulted` | Runtime error |

**`phase` values**

| Value | Description |
|---|---|
| `setup` | Running setup steps |
| `plan` | Running plan steps |
| `idle` | Not running |

---

## Endpoints

### `GET /schedule`

Returns the currently loaded schedule definition.

**Response** `200 OK`
```json
{
  "schedule": { /* ScheduleDefinition or null */ }
}
```

---

### `PUT /schedule`

Loads (replaces) the schedule. Clears any running execution.

**Request body** — a `ScheduleDefinition` object.

```json
{
  "id": "my-schedule",
  "name": "Standard Lager",
  "setup_steps": [],
  "plan_steps": [
    {
      "id": "step-1",
      "name": "Mash-in",
      "enabled": true,
      "actions": [
        {"kind": "set", "target": "reactor.temp.setpoint", "value": 65.0, "owner": "schedule"}
      ],
      "wait": {
        "condition": {"operator": "gte", "target": "reactor.temp", "value": 64.0},
        "timeout_s": 3600
      }
    }
  ]
}
```

**Response** `200 OK`
```json
{"ok": true}
```

---

### `DELETE /schedule`

Removes the loaded schedule and resets execution state.

**Response** `200 OK`
```json
{"ok": true}
```

---

### `POST /schedule/start`

Starts execution of the loaded schedule from the beginning (setup phase first).

**Response** `200 OK`
```json
{"ok": true}
```

---

### `POST /schedule/pause`

Pauses execution after the current step's actions complete.

**Response** `200 OK`
```json
{"ok": true, "pause_reason": "manual pause"}
```

---

### `POST /schedule/resume`

Resumes a paused schedule.

**Response** `200 OK`
```json
{"ok": true}
```

---

### `POST /schedule/stop`

Stops execution and releases all owned parameter targets.

**Response** `200 OK`
```json
{"ok": true}
```

---

### `POST /schedule/next`

Advances to the next step immediately, bypassing any wait condition.

**Response** `200 OK`
```json
{"ok": true}
```

---

### `POST /schedule/previous`

Returns to the previous step.

**Response** `200 OK`
```json
{"ok": true}
```

---

### `GET /schedule/status`

Returns the current `RunStatus`.

**Response** `200 OK` — see [RunStatus](#runstatus) above.

---

## Error Responses

| Status | Meaning |
|---|---|
| `503` | Schedule runtime not initialized yet |
