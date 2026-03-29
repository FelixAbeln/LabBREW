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
  "schedule_available": true,
  "control_available": true,
  "data_available": true
}
```

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
