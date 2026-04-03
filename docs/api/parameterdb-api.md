# ParameterDB Binary Protocol API

Related implementation contracts:
- [Datasource Status Contract](../requirements/parameterdb-datasource-status-contract.md)
- [Plugin Runtime State Contract](../requirements/parameterdb-plugin-state-contract.md)

**Transport:** TCP, default port **8765** (DB service) / **8766** (data-source service)  
**Source:** `Services/parameterDB/parameterdb_core/`, `Services/parameterDB/parameterdb_service/`

ParameterDB uses a framed binary protocol built on [MessagePack](https://msgpack.org/) for efficient, low-latency parameter storage and real-time streaming. The Python client library (`parameterdb_core/client.py`) wraps this protocol and is the recommended way to interact with the service.

---

## Wire Format

Every message is a **length-prefixed MessagePack map**.

```
┌─────────────────────────────────────┐
│  length  (4 bytes, big-endian uint) │
├─────────────────────────────────────┤
│  body    (MessagePack map)          │
└─────────────────────────────────────┘
```

### Request Envelope

```msgpack
{
  "v":       1,           // protocol version (must be 1)
  "req_id":  "<uuid-hex>",// optional correlation ID (string)
  "cmd":     "<command>", // command name
  "payload": { ... }      // command-specific parameters
}
```

### Success Response Envelope

```msgpack
{
  "v":      1,
  "req_id": "<uuid-hex>",
  "ok":     true,
  "result": <command-specific result>,
  "error":  null
}
```

### Error Response Envelope

```msgpack
{
  "v":      1,
  "req_id": "<uuid-hex>",
  "ok":     false,
  "result": null,
  "error":  {
    "type":    "ValueError",   // Python exception class name
    "message": "human-readable description"
  }
}
```

---

## Python Client

Two client classes are provided. Use `SignalClient` for one-shot requests and `SignalSession` for connection reuse (recommended for high-frequency access):

```python
from Services.parameterDB.parameterdb_core.client import SignalClient, SignalSession

# One-shot (new TCP connection per call)
client = SignalClient(host="127.0.0.1", port=8765)
value = client.get_value("reactor.temp")

# Persistent session (reconnects automatically)
with SignalSession(host="127.0.0.1", port=8765, reconnect_attempts=3) as session:
    session.set_value("reactor.temp.setpoint", 65.0)
    value = session.get_value("reactor.temp")
```

---

## Commands

### `ping`

**Payload:** _(empty)_  
**Result:** `"pong"` (string)

Health check.

---

### `stats`

**Payload:** _(empty)_  
**Result:** scan-engine statistics plus subscriber count.

```json
{
  "scan_count": 12345,
  "last_scan_duration_s": 0.0003,
  "subscriber_count": 2
}
```

---

### `snapshot`

**Payload:** _(empty)_  
**Result:** map of parameter name → current value.

```json
{
  "reactor.temp": 30.1,
  "reactor.temp.setpoint": 35.0
}
```

---

### `export_snapshot`

**Payload:** _(empty)_  
**Result:** full snapshot payload suitable for persistence or later import, plus optional persistence stats.

```json
{
  "snapshot": {
    "format_version": 1,
    "store_revision": 42,
    "saved_at": "2024-01-01T12:34:56Z",
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

Use this when you want an exportable file rather than the reduced value-only `snapshot` command.

---

### `import_snapshot`

**Payload:**

| Field | Type | Required | Description |
|---|---|---|---|
| `snapshot` | object | yes | Snapshot payload previously produced by `export_snapshot` or persisted to disk |
| `replace_existing` | boolean | no | Remove current parameters before restoring the snapshot (default `true`) |
| `save_to_disk` | boolean | no | Persist the imported snapshot to the configured snapshot file after restore (default `true`) |

**Result:** restore summary.

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

During import, the scan engine is stopped if it is running, parameters are restored, and then the engine is started again.

---

### `describe`

**Payload:** _(empty)_  
**Result:** map of parameter name → full record (type, config, metadata, value).

---

### `list_parameters`

**Payload:** _(empty)_  
**Result:** list of parameter name strings.

```json
["reactor.temp", "reactor.temp.setpoint", "heater.enable"]
```

---

### `create_parameter`

**Payload:**

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Unique parameter name |
| `parameter_type` | string | yes | Type plugin name (e.g. `static`, `pid`, `deadband`, `math`, `condition`) |
| `value` | any | no | Initial value |
| `config` | object | no | Type-specific configuration |
| `metadata` | object | no | Arbitrary metadata key-value pairs |

**Result:** `true` on success.

```python
client.create_parameter(
    "reactor.temp.setpoint",
    "static",
    value=25.0,
    config={},
    metadata={"unit": "°C", "label": "Temperature Setpoint"},
)

client.create_parameter(
  "brewcan.density.link",
  "math",
  value=0.0,
  config={
    "equation": "brewcan.density.0 * 2 / 2",
    "output_params": ["display.density"],
  },
  metadata={"label": "Linked Density"},
)

client.create_parameter(
    "reactor.is_hot",
    "condition",
    value=False,
    config={
      "condition": "all(elapsed:900;cond:brewcan.density.0:<=:1.012:120)",
    },
    metadata={"label": "Density Ready"},
  )
```

For the `condition` parameter type, `config.condition` uses the shared wait-expression DSL already used by schedule import. Supported forms include `cond:source:operator:threshold[:for_seconds]`, `elapsed:seconds`, `all(...)`, and `any(...)`.

Detailed syntax reference:
- [ParameterDB Condition Plugin](../implementation/parameterdb-condition-plugin.md)
- [Schedule Excel Import Format](./schedule-excel-import.md#wait-column-syntax)

---

### `delete_parameter`

**Payload:**

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Parameter name to remove |

**Result:** `true` on success.

---

### `get_value`

**Payload:**

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Parameter name |
| `default` | any | no | Value returned if parameter does not exist |

**Result:** Current value (any JSON-compatible type).

---

### `set_value`

**Payload:**

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Parameter name |
| `value` | any | yes | New value |

**Result:** `true` on success.

---

### `update_config`

**Payload:**

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Parameter name |
| `changes` | object | yes | Config key-value pairs to update |

**Result:** `true` on success.

---

### `update_metadata`

**Payload:**

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Parameter name |
| `changes` | object | yes | Metadata key-value pairs to update |

**Result:** `true` on success.

---

### `list_parameter_types`

**Payload:** _(empty)_  
**Result:** map of type name → type descriptor.

---

### `get_parameter_type_ui`

**Payload:**

| Field | Type | Required | Description |
|---|---|---|---|
| `parameter_type` | string | yes | Type name |

**Result:** UI metadata for the parameter type (field descriptions, defaults).

---

### `load_parameter_type_folder`

**Payload:**

| Field | Type | Required | Description |
|---|---|---|---|
| `folder` | string | yes | Absolute path to a plugin folder to load at runtime |

**Result:** Loaded type name (string).

---

### `graph_info`

**Payload:** _(empty)_  
**Result:** Dependency graph information from ParameterDB scan engine (`scan_order`, `dependencies`, `write_targets`, `warnings`).

Note: this is the raw ParameterDB graph response. The BrewSupervisor gateway endpoint `GET /fermenters/{fermenter_id}/parameterdb/graph` may enrich it with datasource-level graph metadata under `graph.sources[*].graph`.

---

## Streaming: `subscribe`

The `subscribe` command upgrades the connection to a **push stream**. After the initial acknowledgement the server pushes change events whenever a subscribed parameter's value changes. The connection is one-way (server → client) after the ACK; no further requests can be sent on this socket.

### Initiating a Subscription

**Payload:**

| Field | Type | Required | Description |
|---|---|---|---|
| `names` | array of strings | no | Parameters to watch; empty/omitted = all parameters |
| `send_initial` | boolean | no | Push current values immediately (default `true`) |
| `max_queue` | integer | no | Max pending events per subscriber before oldest are dropped (default `1000`) |

### Server Acknowledgement (first response)

```json
{"ok": true, "result": {"status": "subscribed"}, ...}
```

### Change Event (subsequent messages)

```json
{
  "name": "reactor.temp",
  "value": 30.5,
  "revision": 42
}
```

### Python Usage

```python
with client.subscribe(names=["reactor.temp", "reactor.temp.setpoint"], send_initial=True) as sub:
    for event in sub:
        print(event["name"], "→", event["value"])
```

---

## Concurrency Notes

The ParameterDB server uses four internal locks:

| Lock | Scope |
|---|---|
| `_lock` | Parameter dict, value mutations, revision counter |
| `_graph_lock` | Dependency graph, scan order |
| `_state_lock` | Scan-thread lifecycle |
| `_broker_lock` | Subscription registry |

No lock is held while doing I/O. See `Services/parameterDB/LOCKING.md` for the full concurrency policy.

---

## Persistence

The ParameterDB periodically snapshots all parameter values to a JSON file (default interval 5 s) and reloads them on startup when `restore_snapshot` is enabled. All commands are optionally recorded to a JSONL audit log.

The same snapshot payload format is also exposed at runtime through `export_snapshot` and `import_snapshot`, which is what the Supervisor agent and frontend ParameterDB editor use for operator-driven backup and restore.
