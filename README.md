```
 ██╗      █████╗ ██████╗ ██████╗ ██████╗ ███████╗██╗    ██╗
 ██║     ██╔══██╗██╔══██╗██╔══██╗██╔══██╗██╔════╝██║    ██║
 ██║     ███████║██████╔╝██████╔╝██████╔╝█████╗  ██║ █╗ ██║
 ██║     ██╔══██║██╔══██╗██╔══██╗██╔══██╗██╔══╝  ██║███╗██║
 ███████╗██║  ██║██████╔╝██████╔╝██║  ██║███████╗╚███╔███╔╝
 ╚══════╝╚═╝  ╚═╝╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝ ╚══╝╚══╝
```

> **Lab**oratory **B**ioreactor **R**eal-time **E**xecution and **W**orkflow system

A microservices-based fermentation management and control platform for laboratory bioreactor hardware. LabBREW connects multiple fermenter nodes through a central gateway, providing real-time parameter monitoring, automated schedule execution, rule-driven control, and a React web interface — all exposed through clean REST and binary-protocol APIs.

---

## What Has Been Built

| Component | Description |
|---|---|
| **BrewSupervisor** | Central API gateway + React frontend. Aggregates all fermenter nodes, proxies service requests, and serves the browser UI. |
| **Control Service** | Handles parameter ownership, write protection, linear ramping, and a condition-based rules engine. |
| **Schedule Service** | Loads and executes multi-step fermentation schedules with setup and plan phases, pause/resume, and complex wait conditions. |
| **ParameterDB** | High-performance binary TCP parameter store with a real-time scan engine, plugin system, and snapshot persistence. |
| **Supervisor Agent** | Per-node process supervisor that advertises services over mDNS and proxies requests to local services. |
| **Excel Schedule Import** | Upload a `.xlsx` workbook to BrewSupervisor; it is validated and forwarded as canonical JSON to the schedule service. |
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

### 📋 Fermentation Schedule Execution
- Schedules consist of a **setup phase** (run once) and a **plan phase** (repeating sequence of steps)
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

### 📥 Excel Schedule Import
- Upload a `.xlsx` workbook directly to the gateway
- Dry-run validation endpoint returns any errors before committing
- Workbook format: `meta`, `setup_steps`, and `plan_steps` sheets with simple column syntax

### 🗄️ ParameterDB Binary Protocol
- Custom MessagePack-over-TCP protocol for minimal latency
- Thread-safe parameter store with a 50 ms default scan cycle
- Pub/sub event broker, snapshot persistence (JSON), plugin hooks (PID, deadband, scripts)
- Python client library included

### 🌐 React Frontend
- Browser UI backed by the BrewSupervisor gateway
- Connects over standard HTTP and WebSocket

---

## API Documentation

| Document | Description |
|---|---|
| [API Overview](./docs/api/README.md) | Index of all service APIs and quick navigation guide |
| [Architecture](./docs/api/architecture.md) | Service dependency chain, communication protocols, data-flow diagrams |
| [BrewSupervisor Gateway API](./docs/api/brewsupervisor-api.md) | Central gateway: fermenter discovery, dashboard, schedule import — **start here for frontend work** |
| [Supervisor Agent API](./docs/api/agent-api.md) | Per-node agent: health, service proxy, mDNS registration |
| [Control Service API](./docs/api/control-service-api.md) | Ownership, read/write/ramp, rules engine, WebSocket streaming |
| [Schedule Service API](./docs/api/schedule-service-api.md) | Schedule load, execution control, status |
| [ParameterDB Binary Protocol](./docs/api/parameterdb-api.md) | Low-level TCP binary protocol and Python client |
| [Schedule Excel Import Guide](./docs/api/schedule-excel-import.md) | Workbook sheet layout, column syntax, wait expressions, validation rules |

---

## Service Ports at a Glance

| Service | Port | Protocol |
|---|---|---|
| BrewSupervisor Gateway | 8782 | HTTP REST |
| Supervisor Agent | 8780 | HTTP REST |
| Control Service | 8767 | HTTP REST + WebSocket |
| Schedule Service | 8768 | HTTP REST |
| ParameterDB | 8765 | Binary TCP (MessagePack) |
| ParameterDB DataSource | 8766 | Binary TCP |

---

## Quick Start

All launch scripts are run from the **project root**.

```bash
# 1. Start the backend node supervisor
#    Reads data/system_topology.yaml, starts ParameterDB, Control Service,
#    Schedule Service, and the Supervisor Agent (port 8780).
python run_supervisor.py

# 2. Start the frontend API supervisor (BrewSupervisor gateway on port 8782)
python run_FrontEndsupervisor.py
```

> **React frontend** — the browser UI source lives in `BrewSupervisor/reat-frontend/` but does not yet have a dedicated launch script. Start it manually with your preferred dev server (e.g. `npm start` inside that directory) or build it and serve the static output.

Node topology is configured in [`data/system_topology.yaml`](./data/system_topology.yaml). An example fermentation schedule is provided at [`data/Example_Schedule.xlsx`](./data/Example_Schedule.xlsx).

---

## Repository Layout

```
LabBREW/
├── BrewSupervisor/       # API gateway + React frontend
├── Services/
│   ├── parameterDB/      # Parameter store & scan engine
│   ├── control_service/  # Ownership, ramp, rules
│   ├── schedule_service/ # Schedule execution engine
│   └── _shared/          # Shared operator & wait engines
├── Supervisor/           # Per-node process supervisor
├── Other/Sims/           # Hardware simulators / test harnesses
├── data/                 # Topology config, example schedule, rule definitions
└── docs/api/             # Full API reference
```
