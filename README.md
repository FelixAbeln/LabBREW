# LabBREW  
**Laboratory Bioreactor Real-time Execution and Workflow system**

```
 ██╗      █████╗ ██████╗ ██████╗ ██████╗ ███████╗██╗    ██╗
 ██║     ██╔══██╗██╔══██╗██╔══██╗██╔══██╗██╔════╝██║    ██║
 ██║     ███████║██████╔╝██████╔╝██████╔╝█████╗  ██║ █╗ ██║
 ██║     ██╔══██║██╔══██╗██╔══██╗██╔══██╗██╔══╝  ██║███╗██║
 ███████╗██║  ██║██████╔╝██████╔╝██║  ██║███████╗╚███╔███╔╝
 ╚══════╝╚═╝  ╚═╝╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝ ╚══╝╚══╝
```

> LabBREW is a test-cell-inspired fermentation control and execution platform designed to make fermentation processes observable, repeatable, and programmable. Instead of treating brewing as a collection of timers and setpoints, LabBREW treats it as a controlled process: plans are executed, conditions are evaluated in real time, and every action, signal, and outcome is recorded. The result is a system where fermentation can be run, analyzed, and reproduced with the same rigor as an engineering experiment.

A microservices-based fermentation management and control platform for laboratory bioreactor hardware. LabBREW connects multiple fermenter nodes through a central gateway, providing real-time parameter monitoring, automated scenario execution, rule-driven control, and a React web interface — all exposed through clean REST and binary-protocol APIs.

---

## Core Concepts

### 🔁 Process Execution (not just control)
LabBREW executes **multi-step fermentation plans** with condition-based transitions. It is not a thermostat or dashboard — it is a **process execution system**.

### ⚙️ Deterministic Control Runtime
A scan-cycle engine evaluates parameters, logic blocks (PID, deadband, ramps), and outputs in a predictable order. An ownership model ensures only one controller writes to a parameter at a time.

### 🧪 Criteria-Driven Automation
Steps advance based on:
- time
- parameter conditions
- logical combinations (`all`, `any`, `not`)
- hold durations and timeouts

### 📊 Full Observability
All signals are logged:
- parameters (including implicit setpoints)
- measured values
- control outputs
- events and overrides

### 🔁 Reproducibility
A run consists of:
- scenario package (intent)
- event log (execution)
- time-series data (result)

Runs can be replayed and compared.

### ⚠️ Safety First
Scenario runs do not have final authority. Rules and safety logic can override control and enforce safe states.

---

## What Makes It Different

LabBREW is not just a controller or dashboard.

> It is a **batch process execution system with test-cell-grade control and logging**.

---

## What Has Been Built

| Component | Description |
|---|---|
| **BrewSupervisor** | Central API gateway + React frontend. Aggregates all fermenter nodes, proxies service requests, and serves the browser UI. |
| **Control Service** | Handles parameter ownership, write protection, linear ramping, and a condition-based rules engine. |
| **Scenario Service** | Loads and executes scenario packages with setup and plan phases, pause/resume, and complex wait conditions. |
| **Data Service** | Records parameter values to files at configurable rates and computes loadstep averages for timed capture windows. |
| **ParameterDB** | High-performance binary TCP parameter store with a real-time scan engine, plugin system, and snapshot persistence. |
| **Supervisor Agent** | Per-node process supervisor that advertises services over mDNS and proxies requests to local services. |
| **Scenario Package Import** | Upload a `.xlsx` workbook to BrewSupervisor; it is validated and forwarded to scenario service as a package payload. |
| **Service Discovery** | Automatic node registration and discovery via mDNS (`_fcs._tcp.local.`) — no manual configuration needed. |

---

## Current Features

### 🧪 Fermenter Node Management
- Automatic discovery of fermenter nodes over mDNS
- Per-node health, metadata, and availability summary
- Aggregated dashboard view across all nodes

### ⚙️ Parameter Control
- Ownership model — only one controller may write a parameter at a time
- Force-takeover for emergency overrides
- Synchronous reads and writes via REST
- **Linear ramps** — smoothly move a setpoint from current value to target over a specified duration

### 📋 Scenario Run Execution
- Scenario runs consist of a **setup phase** (run once) and a **plan phase** (repeating sequence of steps)
- Each step carries **actions** (`set`, `ramp`) and a **wait condition**
- Wait types: elapsed time, parameter condition, composite (`all`, `any`, `not`), with optional hold duration (`for_seconds`) and timeout
- Full playback control: start · pause · resume · stop · next · previous

### 📊 Real-Time Streaming
- WebSocket endpoint streams live parameter snapshots at a configurable interval
- Subscribe to any subset of parameters by name

### 🔁 Rules Engine
- Persistent rules stored as condition → action pairs
- Conditions use standard comparison operators (`>`, `>=`, `<`, `<=`, `==`, `!=`)
- Rules evaluated continuously against the live parameter snapshot

### 📥 Scenario Package Import
- Upload a `.xlsx` workbook directly to the gateway
- Dry-run validation endpoint returns any errors before committing
- Workbook format: `meta`, `setup_steps`, and `plan_steps` sheets with simple column syntax

### 🗄️ ParameterDB Binary Protocol
- Custom MessagePack-over-TCP protocol for minimal latency
- Thread-safe parameter store with fixed/adaptive scan modes (current node topology runs adaptive at target utilization 0.7, bounded by 2-50 ms period; up to 500 Hz at the 2 ms floor)
- Pub/sub event broker, snapshot persistence (JSON by default or topology-configured Postgres), plugin hooks (PID, deadband, scripts)
- Python client library included

### 🔌 Built-in Data Source Support
- `system_time` (system clock publishing)
- `tilt_hydrometer` (Tilt Bridge HTTP and direct BLE, including Tilt Pro scaling)
- `brewtools` (Brewtools CAN transport framework with two transport modes: direct Kvaser CANlib or PEAK/PCAN Ethernet Gateway via UDP)
- `modbus_relay` (Modbus TCP relay boards)
- `labps3005dn` (serial bench PSU integration)
- `digital_twin` (FMU-based runtime twin)

`brewtools` also includes operator-facing command outputs for agitator PWM, density calibration (including target SG), and pressure zeroing, and now publishes these command parameters in graph `depends_on` to keep dependency ordering consistent in the UI.

→ See [ParameterDB Source Definitions](./docs/implementation/parameterdb-source-definitions.md) for details and transport notes.

### 🌐 React Frontend
- Browser UI backed by the BrewSupervisor gateway at port 8782
- Connects over standard HTTP REST and WebSocket
- **Scenario tab** — upload an Excel workbook, validate/package it, and drive step-by-step execution (play · pause · next · previous · stop)
- **Control tab** — render datasource and custom manual controls from backend control UI spec, including manual write/release actions
- **System tab** — at-a-glance health and service-status overview for the selected fermenter node
- **Data tab** — configure recording rate (Hz), start/stop parameter logging, and trigger loadstep captures
- **ParameterDB tab** — browse, create, and edit parameters; visualise relationships in an interactive graph; manage data sources
- **Rules tab** — build condition → action automation rules evaluated continuously against the live parameter snapshot
- **Archive tab** — browse and delete historical recording sessions

→ See the [Frontend Documentation](./docs/frontend/README.md) for a full feature reference, tech-stack details, and setup instructions.

---

## API Documentation

| Document | Description |
|---|---|
| [API Overview](./docs/api/README.md) | Index of all service APIs and quick navigation guide |
| [Architecture](./docs/api/architecture.md) | Service dependency chain, communication protocols, data-flow diagrams |
| [Frontend Documentation](./docs/frontend/README.md) | React UI — features, tech stack, setup, and source layout |
| [ParameterDB Source Definitions](./docs/implementation/parameterdb-source-definitions.md) | Built-in datasource types, hardware/protocol coverage, and Tilt BLE notes |
| [ParameterDB + Relationship Setup Guide](./docs/frontend/parameterdb-relationship-setup.md) | Frontend workflow to set up ParameterDB entities and graph relationships |
| [PostgreSQL Persistence Testing Guide](./docs/POSTGRES_PERSISTENCE_TESTING.md) | Set up and test PostgreSQL backends for parameter snapshots, datasource configs, and control rules |
| [BrewSupervisor Gateway API](./docs/api/brewsupervisor-api.md) | Central gateway: fermenter discovery, dashboard, scenario package import — **start here for frontend work** |
| [Supervisor Agent API](./docs/api/agent-api.md) | Per-node agent: health, service proxy, mDNS registration |
| [Control Service API](./docs/api/control-service-api.md) | Ownership, read/write/ramp, rules engine, WebSocket streaming |
| [Manual Control Map Setup](./docs/api/manual-control-map.md) | Configure `data/control_variable_map.json` for custom manual controls |
| [Scenario Service Integration](./docs/implementation/scenario-service-integration.md) | Scenario package load, run control, migration status |
| [Writing a Scenario Runner](./docs/implementation/writing-a-scenario-runner.md) | End-to-end guide for scripted runner module contract, context API, packaging, and troubleshooting |
| [Data Service API](./docs/api/data-service-api.md) | Measurement setup/start/stop, file logging, loadstep capture |
| [ParameterDB Binary Protocol](./docs/api/parameterdb-api.md) | Low-level TCP binary protocol and Python client |
| [Schedule Excel Import Guide](./docs/api/schedule-excel-import.md) | Workbook sheet layout, column syntax, wait expressions, validation rules for scenario package generation |

---

## Service Ports at a Glance

| Service | Port | Protocol |
|---|---|---|
| BrewSupervisor Gateway | 8782 | HTTP REST |
| Supervisor Agent | 8780 | HTTP REST |
| Control Service | 8767 | HTTP REST + WebSocket |
| Scenario Service | 8770 | HTTP REST |
| Data Service | 8769 | HTTP REST |
| ParameterDB | 8765 | Binary TCP (MessagePack) |
| ParameterDB DataSource | 8766 | Binary TCP |

---

## Quick Start

All launch scripts are run from the **project root**.

```bash
# Create your local runtime topology from the sample (first run only)
cp data/system_topology.sample.yaml data/system_topology.yaml
```

```bash
# 1. Start the backend node supervisor
#    Reads data/system_topology.yaml, starts ParameterDB, Control Service,
#    Scenario Service, Data Service, and the Supervisor Agent (port 8780).
python run_supervisor.py

# 2. Start the frontend API supervisor (BrewSupervisor gateway on port 8782)
python run_FrontEndsupervisor.py
```

> **React frontend** — the browser UI source lives in `BrewSupervisor/reat-frontend/` but does not yet have a dedicated launch script. Start it manually with your preferred dev server (e.g. `npm start` inside that directory) or build it and serve the static output.

Node topology is loaded from your local [`data/system_topology.yaml`](./data/system_topology.yaml), typically created from [`data/system_topology.sample.yaml`](./data/system_topology.sample.yaml). An example scenario workbook is provided at [`data/Example_Schedule.xlsx`](./data/Example_Schedule.xlsx).

### Global Storage / Topology Override

You can move runtime files (snapshots, audits, rules, schedule state, measurements, source configs) to another drive, such as a USB stick, by setting environment variables before launch.

```bash
# Optional: move all runtime storage to another location
export LABBREW_STORAGE_ROOT=/mnt/usb/labbrew-data

# Optional: override topology file location explicitly
export LABBREW_TOPOLOGY_PATH=/mnt/usb/labbrew-data/system_topology.yaml

python run_supervisor.py
```

Windows PowerShell example:

```powershell
$env:LABBREW_STORAGE_ROOT = "E:\labbrew-data"
$env:LABBREW_TOPOLOGY_PATH = "E:\labbrew-data\system_topology.yaml"
python .\run_supervisor.py
```

If `LABBREW_STORAGE_ROOT` is not set, existing `./data/...` defaults are used.

### Remote ParameterDB Persistence

If you want ParameterDB state to live in a running database instead of a local snapshot file, add a `persistence` block to the `ParameterDB` service in [data/system_topology.yaml](data/system_topology.yaml). The supervisor forwards those settings into the service environment when it launches the backend.

Example:

```yaml
services:
  ParameterDB:
    module: Services.parameterDB.serviceDB
    listen:
      host: 127.0.0.1
      port: 8765
      proto: ParameterDB_Binary
      path: /
    persistence:
      kind: postgres
      host: db.internal
      port: 5432
      database: labbrew
      username: brew
      password: change-me
      table_prefix: parameterdb
      sslmode: require
```

With this enabled, ParameterDB writes its current full snapshot to Postgres tables and restores from those tables on startup. Without it, the service stays on the existing local JSON persistence path.

The datasource service can be configured the same way in that same topology file. Add a `persistence` block to `ParameterDB_DataSource` if you want source instance configs to live in Postgres instead of `data/sources`.

The control service now supports the same pattern for safety and automation rules. Add a `persistence` block to `control_service` if you want rule definitions to live in Postgres instead of `data/Rules`.

That keeps the whole node description in one topology document while still letting each service own its own storage schema. The System tab now surfaces all three backends separately: ParameterDB snapshots, datasource source definitions, and control rules.

### Raspberry Pi Backend Install

To install the backend stack on a Raspberry Pi without the React frontend, you can either run the installer from a checked-out repository or let it clone the repository from GitHub and walk you through setup.

From a local checkout:

```bash
sudo bash deploy/install_raspberry_pi_backend.sh --node-id 01 --node-name "Fermenter Pi"
```

From GitHub with interactive prompts:

```bash
curl -fsSL https://raw.githubusercontent.com/FelixAbeln/LabBREW/refs/heads/main/deploy/install_raspberry_pi_backend.sh -o install_labbrew.sh
sudo bash install_labbrew.sh
```

The installer can prompt for:

- Git repository URL
- fermenter node id
- fermenter display name
- Raspberry Pi hostname / network name
- advertised host/IP for service discovery

If you choose hostname alignment, the script sets the Pi hostname so the network name matches the fermenter name you provide during setup.

The installer can clone the repository itself, installs `git` when apt provisioning is enabled, and copies the resulting checkout to `/opt/labbrew` while preserving git metadata so the node-local update API can pull future changes in place. It validates that `python3` is version 3.11 or newer, creates a Python virtual environment, installs the core project package, then attempts optional runtime packages used by specific features (`bleak` for Tilt BLE, `fmpy` for FMU digital twin, `pyarrow` for Parquet output). If one of those optional packages fails to install, the backend dry run can still proceed and the installer will emit a warning instead of aborting. It also provisions common Pi runtime packages for `.local` discovery and BLE (`avahi-daemon`, `bluez`, `dbus`, `libnss-mdns`) and enables the relevant services when available. It writes `/etc/labbrew/labbrew-supervisor.env`, enables a `labbrew-supervisor` systemd service, and verifies that the service reaches the local agent API before reporting success. The frontend is intentionally skipped.

For a first Pi dry run, use Raspberry Pi OS Bookworm or newer so `python3` resolves to 3.11+.

The GitHub update feature does not require the React frontend. On a command-line-only Pi you can call the local Supervisor Agent API directly, for example with `curl`, and let `systemd` restart the service after the update.

If you use the `brewtools` datasource with the `kvaser` transport, the remaining manual step is installing the vendor Kvaser Linux CANlib driver/userspace on the Pi. That part is not automated by this repository because it depends on vendor-distributed software outside the project.

If you use `brewtools` with the `pcan_gateway_udp` transport (PEAK PCAN-Ethernet Gateway), no local Kvaser CANlib install is required on the node. Configure gateway host/ports in the datasource (`gateway_host`, `gateway_tx_port`, `gateway_rx_port`, optional `gateway_bind_host`) and ensure UDP reachability between the node and gateway.

Follow this guide for the full Pi driver build/install workflow: [Kvaser CANlib Setup on Raspberry Pi (Leaf v3)](./docs/implementation/kvaser_pi_setup_updated.md).

For serial-port access on Raspberry Pi, add the service user (and optionally the default `pi` user) to `dialout`, then reboot:

```bash
sudo usermod -aG dialout labbrew
sudo usermod -aG dialout pi
sudo reboot
```

---

---

## Repository Layout

```
LabBREW/
├── BrewSupervisor/       # API gateway + React frontend
├── Services/
│   ├── parameterDB/      # Parameter store & scan engine
│   ├── control_service/  # Ownership, ramp, rules
│   ├── scenario_service/ # Scenario package execution (replaces schedule_service)
│   ├── data_service/     # Parameter recording and loadstep capture
│   └── _shared/          # Shared operator, wait engines, storage paths
├── Supervisor/           # Per-node process supervisor
├── Other/Sims/           # Hardware simulators / test harnesses
├── data/                 # Topology config, scenario examples, rule definitions
└── docs/api/             # Full API reference
```
## Philosophy

LabBREW is built to advance brewing and fermentation understanding.

This project is intended to be released as free and open software.

---

## Final Thought

If you can control, observe, and repeat a fermentation process — you can actually learn from it.
