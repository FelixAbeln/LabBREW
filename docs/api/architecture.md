# System Architecture

## Overview

LabBREW is a microservices system that controls and monitors laboratory fermentation hardware. Each physical fermenter node runs a stack of Python services managed by a **Supervisor** process. A central **BrewSupervisor Gateway** federates multiple nodes and exposes a single REST API to the React frontend.

## Service Dependency Chain

```
┌─────────────────────────────────────────────┐
│  React Frontend  (browser)                  │
└─────────────────┬───────────────────────────┘
                  │ HTTP REST  (port 8782)
┌─────────────────▼───────────────────────────┐
│  BrewSupervisor Gateway                     │
│  – Fermenter registry (mDNS)                │
│  – Schedule import (Excel → JSON)           │
│  – HTTP proxy to per-node services          │
└─────────────────┬───────────────────────────┘
                  │ HTTP REST  (port 8780)
┌─────────────────▼───────────────────────────┐
│  Supervisor Agent  (per fermenter node)     │
│  – Process supervision & health checks      │
│  – mDNS advertisement (_fcs._tcp.local.)    │
│  – /proxy/* → individual services          │
└──────┬──────────┬──────────────────────────┘
       │          │
  port 8767   port 8768
       │          │
┌──────▼──────┐  ┌▼─────────────────────────┐
│  Control    │  │  Schedule Service         │
│  Service    │←─│  – Step execution         │
│  – Ownership│  │  – Wait conditions        │
│  – Rules    │  │  – Phase management       │
│  – Ramping  │  └──────────────────────────┘
│  – WebSocket│
└──────┬──────┘
       │ Binary TCP  (port 8765)
┌──────▼──────────────────────────────────────┐
│  ParameterDB                                │
│  – Parameter store (thread-safe)            │
│  – Real-time scan engine (50 ms default)    │
│  – Event broker (pub/sub)                  │
│  – Snapshot persistence (JSON)             │
│  – Plugin system (PID, script, deadband…)  │
└─────────────────────────────────────────────┘
```

## Communication Protocols

| Layer | Protocol | Ports | Used By |
|---|---|---|---|
| Frontend ↔ Gateway | HTTP REST / multipart | 8782 | React UI |
| Gateway ↔ Agent | HTTP REST | 8780 | BrewSupervisor |
| Agent ↔ Services | HTTP proxy | 8767, 8768 | Agent |
| Control ↔ ParameterDB | Custom binary over TCP | 8765 | Control Service |
| Data source ↔ ParameterDB | Custom binary over TCP | 8766 | Data sources |
| Service discovery | mDNS (Zeroconf) | 5353 UDP | Supervisor, BrewSupervisor |

## Data Flow Examples

### Read a Parameter Value

```
Frontend
  → GET /fermenters/{id}/control/read/{target}          (BrewSupervisor :8782)
  → GET /proxy/control_service/control/read/{target}    (Agent :8780)
  → GET /control/read/{target}                          (Control Service :8767)
  → TCP get_value cmd                                   (ParameterDB :8765)
  ← value
```

### Write a Parameter (with Ownership Check)

```
Frontend
  → POST /fermenters/{id}/control/write  {target, value, owner}
  → POST /proxy/control_service/control/write
  → POST /control/write
  → TCP set_value cmd  (only if owner matches)
  ← {ok, value}
```

### Execute a Schedule Step

```
Schedule Service (background thread)
  ↓ evaluates wait condition (polls ParameterDB values)
  ↓ POST /control/write  (one action at a time)
  ↓ TCP set_value
```

### Live Parameter Updates (WebSocket)

```
Frontend
  → WS /fermenters/{id}/ws/live?targets=T1,T2&interval=0.5
  → WS (proxied via Agent)
  → WS /ws/live  (Control Service)
  ← JSON snapshot pushed every interval seconds
```

## Service Discovery

The **Supervisor** on each fermenter node publishes an mDNS record of type `_fcs._tcp.local.` using Zeroconf. The **BrewSupervisor** browses for these records and automatically registers discovered nodes in its fermenter registry. Each mDNS record carries:

| Property | Description |
|---|---|
| `node_id` | Unique node identifier |
| `node_name` | Human-readable label |
| `hostname` | IP address or hostname |
| `proto` | Always `http` |
| `services` | Comma-separated list of service names |

## Configuration

Service startup is driven by a YAML topology file (default `data/system_topology.yaml`). It declares each service's module path, listen address, protocol, and inter-service dependencies.

```yaml
advertise_service_type: _fcs._tcp.local.
services:
  ParameterDB:
    module: Services.parameterDB.serviceDB
    listen: {host: 127.0.0.1, port: 8765, proto: ParameterDB_Binary, path: /}
  control_service:
    module: Services.control_service.service
    listen: {host: 127.0.0.1, port: 8767, proto: http, path: /}
    backend: ParameterDB
  schedule_service:
    module: Services.schedule_service.service
    listen: {host: 127.0.0.1, port: 8768, proto: http, path: /}
    backend: control_service
```

The Supervisor resolves the dependency graph, starts services in the correct order, and performs TCP health checks before marking each service as healthy.
