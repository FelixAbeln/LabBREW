# Schedule Service API

**Base URL:** `http://<node-host>:8768`  
**Source:** `Services/schedule_service/api/routes_schedule.py`, `Services/schedule_service/models.py`

The Schedule Service executes multi-step fermentation schedules. A schedule has two phases: **setup** (run once at start) and **plan** (the main repeating sequence). Each step can carry a list of control actions and an optional wait condition that gates progression to the next step.

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
  "wait": { /* WaitCondition or null */ }
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

| `kind` | Description |
|---|---|
| `set` | Write `value` to `target` via the Control Service |
| `ramp` | Ramp `target` to `value` over `duration_s` seconds |

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
