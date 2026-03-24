# BrewSupervisor Gateway API

**Base URL:** `http://<host>:8782`  
**Source:** `BrewSupervisor/api/routes.py`, `BrewSupervisor/api/app.py`

The BrewSupervisor Gateway is the single entry-point consumed by the React frontend. It maintains a registry of discovered fermenter nodes (via mDNS) and proxies requests to the per-node [Supervisor Agent](./agent-api.md).

---

## General

### `GET /health`

Returns a liveness check.

**Response** `200 OK`
```json
{"ok": true}
```

---

## Fermenter Registry

### `GET /fermenters`

Lists all discovered fermenter nodes.

**Response** `200 OK` — array of `FermenterView` objects.

```json
[
  {
    "id": "01",
    "name": "Test",
    "address": "192.168.1.10:8780",
    "host": "192.168.1.10",
    "online": true,
    "agent_base_url": "http://192.168.1.10:8780",
    "services_hint": ["control_service", "schedule_service", "ParameterDB"],
    "services": {
      "control_service": {"healthy": true, "base_url": "http://127.0.0.1:8767"}
    },
    "summary": {"schedule_available": true, "control_available": true},
    "last_error": null
  }
]
```

### `GET /fermenters/{fermenter_id}`

Returns a single fermenter node. Returns `404` if the node is unknown.

---

### `GET /fermenters/{fermenter_id}/agent/info`

Proxies `GET /agent/info` on the node's Supervisor Agent. See [Agent API — GET /agent/info](./agent-api.md#get-agentinfo).

### `GET /fermenters/{fermenter_id}/agent/services`

Proxies `GET /agent/services` on the node's Supervisor Agent.

### `GET /fermenters/{fermenter_id}/summary`

Proxies `GET /agent/summary` on the node's Supervisor Agent.

---

## Dashboard

### `GET /fermenters/{fermenter_id}/dashboard`

Aggregates data from multiple services into a single dashboard payload. Best-effort — fields may be `null` if an upstream service is unavailable.

**Response** `200 OK`
```json
{
  "fermenter": { /* FermenterView */ },
  "schedule": { /* RunStatus from schedule_service/status */ },
  "schedule_definition": { /* ScheduleDefinition from schedule_service */ },
  "owned_target_values": [
    {
      "target": "reactor.temp.setpoint",
      "ok": true,
      "value": 30.5,
      "owner": "schedule"
    }
  ]
}
```

---

## Schedule Import

These endpoints parse an Excel workbook and optionally push the result to the schedule service. See **[Schedule Excel Import Format](./schedule-excel-import.md)** for the full workbook syntax reference.

### `PUT /fermenters/{fermenter_id}/schedule/validate-import`

Validates an Excel schedule file without persisting anything.

**Request** — `multipart/form-data`
| Field | Type | Description |
|---|---|---|
| `file` | binary | `.xlsx` schedule workbook |

**Response** `200 OK`
```json
{
  "ok": true,
  "valid": true,
  "errors": [],
  "warnings": ["Sheet 'Plan' has no wait conditions"],
  "schedule": { /* parsed ScheduleDefinition */ },
  "summary": {
    "setup_step_count": 2,
    "plan_step_count": 10
  }
}
```

Returns `ok: false` and a list of `errors` if the workbook fails validation.

### `PUT /fermenters/{fermenter_id}/schedule/import`

Validates and imports an Excel schedule to the schedule service. Returns `422` if validation fails; otherwise forwards the parsed payload to `PUT /schedule` on the schedule service and mirrors its response.

**Request** — `multipart/form-data` (same as validate-import)

**Response** `200 OK` on success, `422 Unprocessable Entity` on validation failure.
```json
{
  "ok": true,
  "valid": true,
  "errors": [],
  "warnings": [],
  "schedule": { /* ScheduleDefinition */ },
  "forwarded": { /* response from schedule_service */ }
}
```

---

## Service Proxy Routes

The gateway provides convenience proxy routes that forward requests to named services through the Agent's `/proxy/*` mechanism. All HTTP methods (`GET`, `POST`, `PUT`, `DELETE`) are supported unless noted.

| Gateway path | Forwarded to |
|---|---|
| `/fermenters/{id}/control[/{path}]` | `control_service` — `control/{path}` |
| `/fermenters/{id}/rules[/{path}]` | `control_service` — `rules/{path}` |
| `/fermenters/{id}/system[/{path}]` | `control_service` — `system/{path}` |
| `/fermenters/{id}/ws[/{path}]` | `control_service` — `ws/{path}` |
| `/fermenters/{id}/schedule[/{path}]` | `schedule_service` — `schedule/{path}` |
| `/fermenters/{id}/data[/{path}]` | `data_service` — `{path}` |
| `/fermenters/{id}/services/{service}[/{path}]` | `{service}` — `{path}` |

See [Control Service API](./control-service-api.md) and [Schedule Service API](./schedule-service-api.md) for the full endpoint reference.

For Data Service endpoints, see [Data Service API](./data-service-api.md).

---

## Archive Download Convenience Route

### `GET /fermenters/{fermenter_id}/data/archives/download/{name}`

Streams an archive file from the Data Service as a binary response (`application/zip`).

This route is provided as a convenience path for browser downloads. It forwards to Data Service `GET /archives/download/{name}` and preserves non-JSON payloads.

**Query params**
- `output_dir` (optional) — forwarded to Data Service.

---

## Error Responses

| Status | Meaning |
|---|---|
| `404` | Fermenter ID not found in registry |
| `422` | Schedule validation failed |
| `502` | Upstream service request failed |
