# Multi-Device Routing and Topology Setup

This guide explains how to run one logical fermenter across multiple devices while keeping BrewSupervisor routing correct.

## Goal

Expose a single fermenter in BrewSupervisor even when services are split across hosts, for example:

- control + schedule on an IPC
- data + ParameterDB on a server

BrewSupervisor can route per service to different agents as long as the split nodes advertise a shared fermenter identity.

## Key Rules

1. Use the same `--node-id` on every device that belongs to the same fermenter.
2. Use the same `--node-name` on every device for consistent UI labeling.
3. Set `--advertise-host` per device to an address reachable by BrewSupervisor.
4. In each device topology YAML, advertise only services actually hosted on that device.
5. For cross-device dependencies, use `external_capabilities` in YAML.
6. For HTTP dependencies, target the remote Supervisor Agent (`:8780`) instead of direct service ports.

## Identity and Discovery

Each running Supervisor Agent advertises `_fcs._tcp.local.` with a service list.
BrewSupervisor merges advertisements by fermenter `node_id` into one logical fermenter view and routes each service call to the agent that advertises that service.

If `node_id` differs, BrewSupervisor treats them as different fermenters.

## Example Deployment

### Device A (IPC): control + schedule

Save as `data/system_topology_ipc.yaml`:

```yaml
advertise_service_type: _fcs._tcp.local.

external_capabilities:
  ParameterDB:
    endpoint:
      host: 10.10.0.20
      port: 8765
      proto: tcp
  data_service:
    endpoint:
      host: 10.10.0.20
      port: 8780
      proto: http
      path: /

services:
  control_service:
    module: Services.control_service.service
    docs: docs/api/control-service-api.md
    listen:
      host: 0.0.0.0
      port: 8767
      proto: http
      path: /
    backend: ParameterDB
    static_args: []
    advertise_as:
      - control_service

  schedule_service:
    module: Services.schedule_service.service
    docs: docs/api/schedule-service-api.md
    listen:
      host: 0.0.0.0
      port: 8768
      proto: http
      path: /
    backends:
      control_service:
        host_flag: --backend-host
        port_flag: --backend-port
      data_service:
        host_flag: --data-backend-host
        port_flag: --data-backend-port
    static_args: []
    advertise_as:
      - schedule_service
```

Start command:

```powershell
python run_supervisor.py --config ./data/system_topology_ipc.yaml --node-id 01 --node-name Fermenter-01 --advertise-host 10.10.0.10
```

### Device B (Server): ParameterDB + data

Save as `data/system_topology_server.yaml`:

```yaml
advertise_service_type: _fcs._tcp.local.

services:
  ParameterDB:
    module: Services.parameterDB.serviceDB
    docs: docs/api/parameterdb-api.md
    listen:
      host: 0.0.0.0
      port: 8765
      proto: tcp
      path: /
    static_args:
      - --scan-mode
      - adaptive
      - --target-utilization
      - "0.7"
    advertise_as:
      - ParameterDB

  ParameterDB_DataSource:
    module: Services.parameterDB.serviceDS
    docs: docs/api/parameterdb-api.md
    listen:
      host: 0.0.0.0
      port: 8766
      proto: tcp
      path: /
    backend: ParameterDB
    static_args: []
    advertise_as:
      - ParameterDB_DataSource

  data_service:
    module: Services.data_service.service
    docs: docs/api/data-service-api.md
    listen:
      host: 0.0.0.0
      port: 8769
      proto: http
      path: /
    backend: ParameterDB
    static_args: []
    advertise_as:
      - data_service
```

Start command:

```powershell
python run_supervisor.py --config ./data/system_topology_server.yaml --node-id 01 --node-name Fermenter-01 --advertise-host 10.10.0.20
```

## Verifying Routing

1. Start BrewSupervisor gateway.
2. Call `GET /fermenters` on the gateway and confirm the fermenter shows combined service availability.
3. Test each service route:
   - `/fermenters/01/control/...`
   - `/fermenters/01/schedule/...`
   - `/fermenters/01/data/...`
4. Confirm each endpoint responds when only that device hosts the service.
5. Verify bridge pathing directly: `GET http://10.10.0.20:8780/data/status`.

## Common Pitfalls

- Mismatched `node_id` between devices: routing cannot merge services.
- Services listed in `advertise_as` but not actually running: routing target exists but upstream calls fail.
- `external_capabilities` missing for remote backend dependencies: service startup fails dependency resolution.
- Using direct remote service ports for HTTP dependencies in split mode: bypasses the agent bridge and breaks the intended supervisor-to-supervisor path.
- `--advertise-host` set to loopback (`127.0.0.1`) on remote nodes: gateway cannot reach proxied endpoints.

## Scope Note

Agent bridging in this guide applies to HTTP capabilities (`control_service`, `schedule_service`, `data_service`).

`ParameterDB` remains a binary TCP capability and is configured with direct TCP endpoints.

## Custom Capability Aliases (database.local pattern)

You can define topology-level aliases for remote capabilities and inject them as URL endpoints.

Example: schedule on node A consumes a remote database-related HTTP backend through node B's Agent bridge.

```yaml
external_capabilities:
  database.local:
    endpoint:
      host: 10.10.0.20
      port: 8780
      proto: http
      path: /data

services:
  schedule_service:
    module: Services.schedule_service.service
    listen:
      host: 0.0.0.0
      port: 8768
      proto: http
      path: /
    backends:
      database.local:
        url_flag: --data-backend-url
    advertise_as:
      - schedule_service
```

With this setup, Supervisor injects a URL endpoint (including path) and the service talks to `http://10.10.0.20:8780/data/...`, which is forwarded by node B's Agent to its local `data_service`.

This enables supervisor-managed remote backend indirection without changing service business logic.

## Recommended Rollout

1. Start with one fermenter split across two devices.
2. Validate all gateway proxy route groups.
3. Add additional fermenters only after split routing is verified end-to-end.
