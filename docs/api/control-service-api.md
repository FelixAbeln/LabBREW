# Control Service API

**Base URL:** `http://<node-host>:8767`  
**Source:** `Services/control_service/api/`

The Control Service manages parameter ownership, value writes, ramping, and an automated rules engine. It communicates with [ParameterDB](./parameterdb-api.md) over the binary TCP protocol.

---

## Control Endpoints (`/control`)

### `GET /control/ownership`

Returns the current ownership map: which owner holds each controlled target.

**Response** `200 OK`
```json
{
  "reactor.temp.setpoint": {
    "owner": "schedule",
    "reason": "step 3",
    "rule_id": null,
    "timestamp": "2024-01-15T10:23:45Z"
  }
}
```

---

### `POST /control/request`

Requests ownership of a target. Fails if the target is already owned by someone else.

**Request body**
```json
{"target": "reactor.temp.setpoint", "owner": "my-controller"}
```

**Response** `200 OK`
```json
{"ok": true, "target": "reactor.temp.setpoint", "owner": "my-controller"}
```

---

### `POST /control/release`

Releases ownership of a target.

**Request body**
```json
{"target": "reactor.temp.setpoint", "owner": "my-controller"}
```

**Response** `200 OK`
```json
{"ok": true}
```

---

### `POST /control/force-takeover`

Forces ownership of a target regardless of the current owner.

**Request body**
```json
{
  "target": "reactor.temp.setpoint",
  "owner": "operator",
  "reason": "emergency override"
}
```

**Response** `200 OK`
```json
{"ok": true, "target": "reactor.temp.setpoint", "owner": "operator"}
```

---

### `POST /control/reset`

Resets a target to its default value and clears its ownership.

**Request body**
```json
{"target": "reactor.temp.setpoint"}
```

---

### `POST /control/clear-ownership`

Clears all ownership records.

**Response** `200 OK`
```json
{"ok": true}
```

---

### `GET /control/read/{target}`

Reads the current value of a parameter from ParameterDB.

**Path parameter:** `target` — parameter name, e.g. `reactor.temp.setpoint`

**Response** `200 OK`
```json
{
  "ok": true,
  "target": "reactor.temp.setpoint",
  "value": 30.5,
  "current_owner": "schedule"
}
```

---

### `POST /control/write`

Writes a value to a parameter. Requires the caller to hold ownership (or the target to be unowned).

**Request body**
```json
{
  "target": "reactor.temp.setpoint",
  "value": 35.0,
  "owner": "my-controller"
}
```

**Response** `200 OK`
```json
{"ok": true, "target": "reactor.temp.setpoint", "value": 35.0}
```

---

### `POST /control/manual-write`

Manual operator write path. If the target is owned by a non-safety owner (e.g. schedule/rules), ownership is force-taken by the manual owner before writing.

Safety exception: if the target is currently owned by `safety`, manual writes are blocked unless the caller itself is `safety`.

Owner consistency:
- Manual writes are normalized to owner `operator` (except `owner: safety`, which is reserved).
- Rule takeover/ramp ownership is normalized to `safety`.

**Request body**
```json
{
  "target": "reactor.temp.setpoint",
  "value": 35.0,
  "owner": "operator",
  "reason": "manual override"
}
```

**Response** `200 OK`
```json
{
  "ok": true,
  "written": true,
  "target": "reactor.temp.setpoint",
  "owner": "operator",
  "takeover": true,
  "previous_owner": "schedule",
  "current_owner": "operator"
}
```

---

### `POST /control/release-manual`

Releases all currently held manual ownership records (owner_source `manual`, or owner `operator`) and stops associated ramps.

Use this before scheduler resume if manual override was active.

**Request body** (optional)
```json
{
  "targets": ["reactor.temp.setpoint", "agitator.rpm"]
}
```

If body is omitted, all manual ownership records are released.

**Response** `200 OK`
```json
{
  "ok": true,
  "released": ["reactor.temp.setpoint"],
  "released_count": 1,
  "skipped": ["heater.enable"]
}
```

Blocked-by-safety response example:
```json
{
  "ok": false,
  "written": false,
  "blocked": true,
  "target": "reactor.temp.setpoint",
  "owner": "operator",
  "current_owner": "safety",
  "reason": "target owned by safety"
}
```

---

### `POST /control/ramp`

Starts a linear ramp on one or more targets from their current values to the specified value over a given duration.

**Request body**
```json
{
  "targets": ["reactor.temp.setpoint"],
  "value": 40.0,
  "duration": 600,
  "owner": "my-controller"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `target` | string | one of | Single target (alternative to `targets`) |
| `targets` | array of strings | one of | Multiple targets |
| `value` | number | yes | Target value at end of ramp |
| `duration` | number | yes | Ramp duration in seconds |
| `owner` | string | yes | Caller identity |

**Response** `200 OK`
```json
{"ok": true}
```

Returns `ok: false` with an `error` message if any target is owned by a different owner.

---

## Rules Endpoints (`/rules`)

Rules are JSON objects that define a condition and a set of actions. When the condition evaluates to `true` the actions execute; optionally ownership is released when the condition clears.

### `GET /rules/`

Lists all persisted rules.

**Response** `200 OK`
```json
[
  {
    "id": "high-temp-alarm",
    "enabled": true,
    "condition": {
      "operator": "gt",
      "target": "reactor.temp",
      "value": 45.0
    },
    "actions": [
      {"kind": "set", "target": "heater.enable", "value": 0}
    ],
    "release_when_clear": true
  }
]
```

### `POST /rules/`

Creates or updates a rule.

**Request body** — a rule object (same shape as above).

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | Unique rule identifier |
| `enabled` | boolean | yes | Whether the rule is active |
| `condition` | object | yes | Condition evaluated each tick |
| `actions` | array | yes | Actions executed when condition is true |
| `release_when_clear` | boolean | no | Release ownership when condition becomes false |

**Action kinds**

| `kind` | Required fields | Description |
|---|---|---|
| `set` | `target`/`targets`, `value` | Write a value |
| `takeover` | `target`/`targets` | Force ownership to `safety` |
| `ramp` | `target`/`targets`, `value`, `duration` | Start a ramp owned by `safety` |

For rule actions, owner is not user-configurable. Takeover and ramp actions are normalized to owner `safety` by the runtime.

**Response** `200 OK`
```json
{"ok": true, "id": "high-temp-alarm"}
```

### `DELETE /rules/{rule_id}`

Deletes a rule by ID. Returns `404` if not found.

**Response** `200 OK`
```json
{"ok": true, "id": "high-temp-alarm"}
```

---

## System Endpoints (`/system`)

Manual map setup reference: see [Manual Control Map Setup](./manual-control-map.md) for configuring `data/control_variable_map.json`.

### `GET /system/control-contract`

Returns frontend-oriented control metadata from `data/control_variable_map.json`, resolved against live backend values and ownership.

**Response** `200 OK`
```json
{
  "ok": true,
  "source": ".../data/control_variable_map.json",
  "contract": {
    "version": 1,
    "controls": []
  },
  "resolved_controls": [
    {
      "id": "reactor_temp_setpoint",
      "target": "reactor.temp.setpoint",
      "target_exists": true,
      "current_value": 64.2,
      "current_owner": "schedule",
      "safety_locked": false
    }
  ],
  "available_targets": ["reactor.temp", "reactor.temp.setpoint"]
}
```

### `GET /system/datasource-contract`

Returns a live datasource-to-parameter-to-control mapping snapshot for UI auto-generation.

This endpoint joins:
- active datasource instances from ParameterDB datasource service (`list_sources`)
- SourceDef control spec from datasource UI modules (`get_source_type_ui(..., mode="control")`)
- live ParameterDB parameter metadata (`describe`) for parameters created by datasources
- control map targets from `data/control_variable_map.json`

Use this endpoint to answer:
- what datasource devices currently exist
- what parameters each datasource actually created
- which control-map entries target those parameters

Unlike create/edit UI spec mapping, this reflects runtime-created parameters even when a user relies on automatic parameter creation.

**Response** `200 OK`
```json
{
  "ok": true,
  "datasource_backend": {
    "host": "127.0.0.1",
    "port": 8766,
    "reachable": true,
    "error": null
  },
  "control_map": {
    "source": ".../data/control_variable_map.json",
    "control_count": 3
  },
  "datasources": [
    {
      "name": "brewtools_can_demo",
      "source_type": "brewtools",
      "running": true,
      "parameter_count": 24,
      "control_count": 2,
      "source_control_spec": {
        "spec_version": 1,
        "controls": []
      },
      "parameters": [
        {
          "name": "brewcan.agitator.0.set_pwm",
          "role": "command",
          "mapped_controls": [
            {
              "id": "agitator_rpm",
              "target": "brewcan.agitator.0.set_pwm",
              "target_exists": true
            }
          ]
        }
      ],
      "controls": [
        {
          "id": "agitator_rpm",
          "target": "brewcan.agitator.0.set_pwm",
          "widget": "number",
          "write": {"kind": "number"},
          "source": "sourcedef"
        }
      ]
    }
  ],
  "manual_controls": [
    {
      "id": "reactor_temp_setpoint",
      "target": "reactor.temp.setpoint",
      "source": "manual_map"
    }
  ],
  "ui_cards": [
    {
      "card_id": "source:brewtools_can_demo",
      "title": "brewtools_can_demo",
      "controls": []
    }
  ],
  "orphan_sources": [],
  "orphan_parameters": []
}
```

### `GET /system/control-ui-spec`

Returns frontend-ready control cards to render directly.

Each card represents either:
- a datasource device (from SourceDef control spec + discovered command/control parameters + manual map overlays), or
- custom manual controls defined only in `data/control_variable_map.json`.

**Response** `200 OK`
```json
{
  "ok": true,
  "manual_owner": "operator",
  "write_path": "/control/manual-write",
  "release_path": "/control/release-manual",
  "cards": [
    {
      "card_id": "source:bench_psu",
      "kind": "datasource",
      "title": "bench_psu",
      "subtitle": "labps3005dn",
      "controls": [
        {
          "id": "set_voltage",
          "label": "Voltage Setpoint",
          "target": "psu.set_voltage",
          "widget": "number",
          "write": {"kind": "number", "min": 0.0, "max": 30.0, "step": 0.01},
          "source": "sourcedef"
        }
      ]
    }
  ]
}
```

### `GET /system/health`

Liveness check.

**Response** `200 OK`
```json
{"ok": true}
```

### `GET /system/operators`

Lists all available condition operators (e.g. `gt`, `lt`, `eq`, `ne`).

### `GET /system/rule-dir`

Returns the filesystem path where rules are stored.

**Response** `200 OK`
```json
{"rule_dir": "/data/rules"}
```

### `GET /system/schema`

Returns a machine-readable description of the API schema: supported action fields, rule fields, and snapshot/WebSocket query parameters.

### `GET /system/snapshot`

Returns a live snapshot of the runtime state.

**Query parameters**

| Parameter | Type | Description |
|---|---|---|
| `targets` | string | Optional comma-separated list of parameter names to include in `values` |

**Response** `200 OK`
```json
{
  "ownership": { /* same as GET /control/ownership */ },
  "ramps": {
    "reactor.temp.setpoint": {
      "from": 30.0,
      "to": 40.0,
      "started_at": "2024-01-15T10:00:00Z",
      "duration_s": 600
    }
  },
  "active_rules": ["high-temp-alarm"],
  "held_rules": [],
  "values": {
    "reactor.temp.setpoint": 32.5
  }
}
```

---

## WebSocket (`/ws`)

### `WS /ws/live`

Streams live runtime snapshots at a configurable interval. The connection accepts only outbound messages from the server.

**Query parameters**

| Parameter | Default | Description |
|---|---|---|
| `targets` | (all) | Comma-separated parameter names to include in `values` |
| `interval` | `0.5` | Seconds between snapshots (minimum `0.1`) |

**Message format** — same JSON structure as `GET /system/snapshot`. A message is only sent when the payload changes.

**Example connection** (JavaScript)
```js
const ws = new WebSocket(
  'ws://localhost:8767/ws/live?targets=reactor.temp,reactor.temp.setpoint&interval=1'
);
ws.onmessage = (event) => {
  const snapshot = JSON.parse(event.data);
  console.log(snapshot.values);
};
```

---

## Error Responses

| Status | Meaning |
|---|---|
| `400` | Invalid rule payload |
| `404` | Rule not found |
| `503` | Control runtime not initialized yet |
