# Supervisor Agent API

**Base URL:** `http://<node-host>:8780`  
**Source:** `Supervisor/infrastructure/agent_api.py`

Each fermenter node runs one Agent server. It exposes node metadata, the list of managed services, a summary endpoint, and a transparent HTTP proxy to individual services.

---

## Node Info

### `GET /agent/info`

Returns static node metadata and the current service map.

**Response** `200 OK`
```json
{
  "node_id": "01",
  "node_name": "Test",
  "services": {
    "control_service": {
      "healthy": true,
      "base_url": "http://127.0.0.1:8767",
      "docs": "docs/api/control-service-api.md"
    },
    "schedule_service": {
      "healthy": true,
      "base_url": "http://127.0.0.1:8768",
      "docs": "docs/api/schedule-service-api.md"
    },
    "data_service": {
      "healthy": true,
      "base_url": "http://127.0.0.1:8769",
      "docs": "docs/api/data-service-api.md"
    },
    "ParameterDB": {
      "healthy": true,
      "base_url": "http://127.0.0.1:8765",
      "docs": "docs/api/parameterdb-api.md"
    }
  }
}
```

### `GET /agent/services`

Returns only the service map (same `services` object as above).

### `GET /agent/summary`

Returns a high-level availability summary computed by the Supervisor.

**Response** `200 OK`
```json
{
  "node_id": "rpi-node-1",
  "node_name": "Fermentation Room A",
  "schedule_available": true,
  "control_available": true,
  "data_available": true,
  "services": {
    "schedule_service": {
      "name": "schedule_service",
      "healthy": true,
      "outdated": false
    },
    "control_service": {
      "name": "control_service",
      "healthy": true,
      "outdated": false
    },
    "data_service": {
      "name": "data_service",
      "healthy": true,
      "outdated": false
    }
  },
  "repo_update": {
    "repo_url": "https://github.com/FelixAbeln/LabBREW.git",
    "branch": "main",
    "local_revision": "abc123...",
    "remote_revision": "def456...",
    "outdated": true,
    "dirty": false,
    "restart_requested": false,
    "error": null
  }
}
```

### `GET /agent/repo/status`

Returns the node-local repository update status used by the System tab update card.

**Query params**

| Param | Type | Default | Description |
|---|---|---|---|
| `force` | bool | `false` | If true, bypasses the short status cache and refreshes from git immediately |

**Response** `200 OK`
```json
{
  "ok": true,
  "status": {
    "repo_url": "https://github.com/FelixAbeln/LabBREW.git",
    "branch": "main",
    "local_revision": "abc123...",
    "remote_revision": "def456...",
    "outdated": true,
    "dirty": false,
    "error": null,
    "restart_requested": false
  }
}
```

### `POST /agent/repo/update`

Applies an in-place git update on the current branch, refreshes Python dependencies, and reports whether a supervisor restart was requested.

When an update is applied, the supervisor requests its own shutdown so process managers such as systemd (`Restart=always`) can relaunch it with the new code.

**Response** `200 OK`
```json
{
  "ok": true,
  "updated": true,
  "restart_requested": true,
  "details": [
    "fetched latest main from GitHub",
    "fast-forward pull applied",
    "pip requirements install succeeded",
    "pip project install succeeded",
    "supervisor restart requested"
  ],
  "before": {"outdated": true},
  "after": {"outdated": false}
}
```

If dependency installation or git operations fail, this endpoint returns an error with failure details.

---

## Local ParameterDB Endpoints

The agent also exposes a small local HTTP facade over the node's ParameterDB and datasource TCP services. These endpoints are used by BrewSupervisor for the ParameterDB tab.

### `POST /parameterdb/params`

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

### `PUT /parameterdb/params/{name}/value`

Writes a new parameter value.

### `PUT /parameterdb/params/{name}/config`

Applies config changes from a JSON object body.

### `PUT /parameterdb/params/{name}/metadata`

Applies metadata changes from a JSON object body.

### `GET /parameterdb/snapshot-file`

Exports the current full snapshot payload and current snapshot persistence stats.

### `POST /parameterdb/snapshot-file`

Imports a previously exported snapshot payload.

**Request body**

```json
{
  "snapshot": {
    "format_version": 1,
    "parameters": {}
  },
  "replace_existing": true,
  "save_to_disk": true
}
```

These endpoints are local to the node agent. The central BrewSupervisor UI reaches them through its `/fermenters/{id}/parameterdb/...` proxy routes.

---

## Service Proxy

### `GET|POST|PUT|DELETE /proxy/{service_name}/{service_path}`

Transparently proxies the request to the named service.

| Parameter | Description |
|---|---|
| `service_name` | Registered service name, e.g. `control_service`, `schedule_service` |
| `service_path` | Path on the target service, e.g. `control/read/reactor.temp` |

The Agent looks up `service_name` in its service map. If the service is not present or not healthy it returns `404`. Otherwise it forwards the request (method, headers, body, query parameters) and returns the JSON response verbatim.

**Error responses**

| Status | Meaning |
|---|---|
| `404` | Service name not found or not healthy |
| `502` | Upstream request to the service failed |
