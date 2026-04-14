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

When multiple Supervisor Agents advertise the same `node_id` (split deployment), BrewSupervisor merges them into one logical fermenter and keeps per-service agent routing metadata internally.

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

### `GET /fermenters/{fermenter_id}/agent/persistence`

Proxies `GET /agent/persistence` on the node's Supervisor Agent.

Used by the System tab to show ParameterDB snapshot backend health, backend type, and the last save error if persistence is degraded.

### `GET /fermenters/{fermenter_id}/summary`

Proxies `GET /agent/summary` on the node's Supervisor Agent.

### `GET /fermenters/{fermenter_id}/agent/repo/status`

Proxies `GET /agent/repo/status` on the node's Supervisor Agent.

Supports optional `?force=1` query parameter to force a fresh git check.

### `POST /fermenters/{fermenter_id}/agent/repo/update`

Proxies `POST /agent/repo/update` on the node's Supervisor Agent.

Used by the System tab `Update from GitHub` button.

On successful update apply, the node may request supervisor restart (`restart_requested: true`) so a process manager can relaunch it with updated code.

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

In split deployments, these routes are service-aware: each request is routed to the agent currently associated with that specific service (`control_service`, `schedule_service`, `data_service`, and so on). This allows one fermenter to span several devices.

| Gateway path | Forwarded to |
|---|---|
| `/fermenters/{id}/parameterdb[/{path}]` | Supervisor Agent local ParameterDB facade — `parameterdb/{path}` |
| `/fermenters/{id}/control[/{path}]` | `control_service` — `control/{path}` |
| `/fermenters/{id}/rules[/{path}]` | `control_service` — `rules/{path}` |
| `/fermenters/{id}/system[/{path}]` | `control_service` — `system/{path}` |
| `/fermenters/{id}/ws[/{path}]` | `control_service` — `ws/{path}` |
| `/fermenters/{id}/schedule[/{path}]` | `schedule_service` — `schedule/{path}` |
| `/fermenters/{id}/data[/{path}]` | `data_service` — `{path}` |
| `/fermenters/{id}/services/{service}[/{path}]` | `{service}` — `{path}` |

See [Control Service API](./control-service-api.md) and [Schedule Service API](./schedule-service-api.md) for the full endpoint reference.

For Data Service endpoints, see [Data Service API](./data-service-api.md).

For the underlying node-local ParameterDB HTTP facade, see [Supervisor Agent API](./agent-api.md#local-parameterdb-endpoints).

For setup instructions and YAML examples, see [Multi-Device Topology Setup](./multi-device-topology-setup.md).

---

## ParameterDB Gateway Routes

These routes are the browser-facing entrypoint used by the React ParameterDB tab. They proxy to the node agent's local `/parameterdb/...` endpoints rather than directly to the binary TCP protocol.

### `GET /fermenters/{fermenter_id}/parameterdb/params`

Returns the current parameter records map.

### `POST /fermenters/{fermenter_id}/parameterdb/params`

Creates a parameter.

**Request body**

```json
{
  "name": "reactor.temp.setpoint",
  "parameter_type": "static",
  "value": 25.0,
  "config": {},
  "metadata": {"unit": "C"}
}
```

### `PUT /fermenters/{fermenter_id}/parameterdb/params/{name}/value`

Writes a new value for an existing parameter.

### `PUT /fermenters/{fermenter_id}/parameterdb/params/{name}/config`

Applies config changes from a JSON object body.

### `PUT /fermenters/{fermenter_id}/parameterdb/params/{name}/metadata`

Applies metadata changes from a JSON object body.

### `DELETE /fermenters/{fermenter_id}/parameterdb/params/{name}`

Deletes a parameter.

### `GET /fermenters/{fermenter_id}/parameterdb/graph`

Returns dependency graph information used by the ParameterDB graph view.

Response includes the raw ParameterDB graph (`scan_order`, `dependencies`, `write_targets`, `warnings`) plus an enriched `sources` object from the datasource admin service. Each source may include `graph.depends_on` when the source definition publishes explicit dependency metadata.

**Response** `200 OK`

```json
{
  "ok": true,
  "graph": {
    "store_revision": 42,
    "scan_order": ["reactor.temp", "logic.ready"],
    "dependencies": {
      "logic.ready": ["reactor.temp"]
    },
    "write_targets": {},
    "warnings": [],
    "sources": {
      "relay": {
        "source_type": "modbus_relay",
        "running": true,
        "config": {
          "parameter_prefix": "relay"
        },
        "graph": {
          "depends_on": ["relay.ch1", "relay.ch2"]
        }
      }
    }
  }
}
```

### `GET /fermenters/{fermenter_id}/parameterdb/stats`

Returns scan-engine statistics and utilization information.

### `GET /fermenters/{fermenter_id}/parameterdb/param-types`

Lists available parameter types and their UI metadata.

### `GET /fermenters/{fermenter_id}/parameterdb/param-types/{parameter_type}/ui`

Returns the UI schema used to build the create/edit parameter form for one parameter type.

### `GET /fermenters/{fermenter_id}/parameterdb/sources`

Returns active datasource instances.

### `POST /fermenters/{fermenter_id}/parameterdb/sources`

Creates a datasource instance.

### `PUT /fermenters/{fermenter_id}/parameterdb/sources/{name}`

Updates an existing datasource configuration.

### `DELETE /fermenters/{fermenter_id}/parameterdb/sources/{name}`

Deletes a datasource instance. Optionally removes all parameters that the source created.

**Query parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `delete_owned_parameters` | bool | `false` | When `true`, deletes every ParameterDB parameter whose metadata has `created_by = "data_source"` and `owner = <name>`. |

**Response** `200 OK`
```json
{ "ok": true }
```

### `GET /fermenters/{fermenter_id}/parameterdb/snapshot-file`

Downloads the current full ParameterDB snapshot payload for backup/export workflows.

**Response** `200 OK`

```json
{
  "ok": true,
  "snapshot": {
    "format_version": 1,
    "saved_at": 1743273600.0,
    "store_revision": 42,
    "parameters": {
      "reactor.temp": {
        "parameter_type": "fake",
        "value": 30.1,
        "config": {"unit": "C"},
        "state": {},
        "metadata": {"owner": "operator"}
      }
    }
  },
  "snapshot_stats": {
    "enabled": true,
    "path": "./data/parameterdb_snapshot.json"
  }
}
```

### `POST /fermenters/{fermenter_id}/parameterdb/snapshot-file`

Replaces or restores the live ParameterDB state from a previously exported snapshot payload.

**Request body**

```json
{
  "snapshot": {
    "format_version": 1,
    "saved_at": 1743273600.0,
    "store_revision": 42,
    "parameters": {
      "reactor.temp": {
        "parameter_type": "fake",
        "value": 30.1,
        "config": {"unit": "C"},
        "state": {},
        "metadata": {"owner": "operator"}
      }
    }
  },
  "replace_existing": true,
  "save_to_disk": true
}
```

**Response** `200 OK`

```json
{
  "ok": true,
  "removed_count": 12,
  "restored_count": 12,
  "snapshot_stats": {
    "enabled": true,
    "path": "./data/parameterdb_snapshot.json"
  }
}
```

The gateway forwards these requests unchanged to the node agent, preserving the request body for create/edit/import flows.

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
