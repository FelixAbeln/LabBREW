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
| `takeover` | `target`/`targets`, `owner` | Force ownership |
| `ramp` | `target`/`targets`, `value`, `duration`, `owner` | Start a ramp |

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
