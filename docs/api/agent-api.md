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
      "base_url": "http://127.0.0.1:8767"
    },
    "schedule_service": {
      "healthy": true,
      "base_url": "http://127.0.0.1:8768"
    },
    "ParameterDB": {
      "healthy": true,
      "base_url": "http://127.0.0.1:8765"
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
  "control_available": true
}
```

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
