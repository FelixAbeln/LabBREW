# LabBREW Frontend

The LabBREW frontend is a React-based browser UI that gives you a real-time window into every fermenter node in your LabBREW installation. Through a single web page you can monitor live parameters, run scenario packages, define automation rules, record measurements, and explore the parameter database — all without writing a single line of code.

---

## What You Can Do With the UI

| Tab | What it is for |
|-----|----------------|
| **Scenario** | Upload an Excel workbook, validate/package it, and drive step-by-step execution (play · pause · next · previous · stop) |
| **Control** | Operate datasource and custom manual controls rendered from backend control UI spec |
| **System** | Get an at-a-glance health and status overview for every fermenter node |
| **Data** | Configure and start/stop parameter recording; set the logging rate and capture loadstep averages |
| **ParameterDB** | Browse, create, and edit parameters; visualise parameter relationships as an interactive graph; manage data sources |
| **Rules** | Build condition → action automation rules that are evaluated continuously against the live parameter snapshot |
| **Archive** | Browse historical measurement sessions and delete old recordings |

---

## Technology Stack

| Area | Choice |
|------|--------|
| Framework | [React 19](https://react.dev/) |
| Build tool | [Vite](https://vitejs.dev/) |
| Styling | [Tailwind CSS 4](https://tailwindcss.com/) + per-feature CSS files |
| Graph visualisation | [@xyflow/react](https://reactflow.dev/) with [Dagre](https://github.com/dagrejs/dagre) layout |
| Language | JavaScript (ES modules) |
| Linting | ESLint 9 |

---

## Getting Started

### Prerequisites

- [Node.js](https://nodejs.org/) ≥ 24
- The LabBREW backend must be reachable on the same machine or network (see [Quick Start](#quick-start-with-the-backend))

### Install and run the development server

```bash
cd BrewSupervisor/reat-frontend/brew-ui
npm install
npm run dev
```

The development server starts at **http://localhost:5173** with Hot Module Replacement enabled. The Vite proxy forwards `/api` requests to the BrewSupervisor gateway at `http://localhost:8782`, so the backend and frontend can run side-by-side without any CORS configuration.

### Build for production

```bash
npm run build      # outputs to dist/
npm run preview    # locally preview the production build
```

### Lint

```bash
npm run lint
```

### Quick Start with the backend

```bash
# From the project root — start the backend node supervisor
python run_supervisor.py

# Start the BrewSupervisor gateway (port 8782) — this is what the UI talks to
python run_FrontEndsupervisor.py

# Then start the frontend dev server
cd BrewSupervisor/reat-frontend/brew-ui
npm run dev
```

Open http://localhost:5173 in your browser.

---

## Feature Overview

### Fermenter Sidebar

The left-hand sidebar lists every fermenter node discovered automatically via mDNS (`_fcs._tcp.local.`). Click a node to select it — all tabs then show data for that node. A colour indicator reflects node availability.

---

### Scenario Tab

Manage the execution of multi-step scenario runs.

**What you can do:**
- **Upload** a `.lbpkg` or `.zip` scenario package archive
- **Validate** the package with a dry-run before committing it — compile or contract errors are reported inline
- **Start** the scenario run to execute setup then repeating plan steps
- **Pause / Resume** at any time without losing position
- **Step manually** using *Next* (skip to the next step) and *Previous* (go back one step)
- **Stop** execution and reset
- View the **current step**, elapsed time, and wait condition status in real time

For package authoring and format details, see [Writing a LabBREW `.lbpkg` Package](../implementation/writing-an-lbpkg-package.md).

---

### System Tab

A read-only dashboard showing the overall health of the selected fermenter node: service statuses, software versions, and any reported errors. Useful for a quick sanity check before starting a run.

The System tab also includes a GitHub update card:

- **Check updates** compares the node's current git revision with the remote branch revision.
- **Update from GitHub** performs a fast-forward update and Python dependency refresh on the node.
- If an update is applied, the node supervisor requests restart so service managers (for example systemd with `Restart=always`) can relaunch it using the new code.
- In manual/non-managed runs, a requested restart means the supervisor process exits and must be started again manually.

---

### Control Tab

Operate writable controls discovered from datasource SourceDef contracts plus custom controls from `data/control_variable_map.json`.

**What you can do:**
- View one card per datasource, plus a `Custom Manual Controls` card when manual map controls exist
- Write values through the manual path (`POST /control/manual-write`)
- Apply numeric/text controls explicitly with an Apply button
- Toggle boolean controls immediately on click
- Release current manual ownership via `POST /control/release-manual`

Related setup guide: [Manual Control Map Setup](../api/manual-control-map.md).

---

### Data Tab

Control parameter recording for the selected fermenter.

**What you can do:**
- Set the **recording rate** in Hz (e.g. `10` for ten samples per second)
- **Start recording** — values are written to timestamped files on the node
- **Stop recording** — the session is finalised and appears in the Archive tab
- Configure **loadstep capture**: set a window duration (seconds) and trigger a timed average — useful for characterising a step-change response
- View a live **snapshot** of all current parameter values, searchable and tree-structured

---

### ParameterDB Tab

Explore and manage the parameter database.

**What you can do:**
- **Browse** the full parameter list with search and filtering
- **Create or edit** parameters using a dynamic form generated from the parameter's JSON schema
- View **parameter metadata**: type, unit, default value, constraints, ownership
- Switch to the **Graph view** to see an interactive node-and-edge diagram of how parameters relate to one another — zoom, pan, and click a node to open its detail panel
- Manage **data sources** — the pluggable adapters that push values into ParameterDB (e.g. hardware drivers, OPC-UA, simulators):
  - **Delete** removes the source definition only; its parameters remain in ParameterDB
  - **Delete + Clean** removes the source *and* all parameters it owns (confirmed via an in-app modal — no browser pop-up)
- **Star** frequently used parameters so they appear at the top of the list (stored in browser `localStorage`)

The Graph view populates the **Depends On** column automatically for supported source types. For example, `brewtools` sources emit dependency edges for agitator PWM outputs, density calibration, and pressure calibration commands so that graph ordering reflects the real hardware execution order required by operators.

---

### Rules Tab

Automate control decisions with persistent rules.

**What you can do:**
- **Create a rule** by defining a condition (a parameter, an operator such as `>` or `==`, and a threshold value) and one or more actions (`set` or `ramp` a parameter)
- **Edit** existing rules at any time using the modal rule editor
- **Delete** rules with a confirmation step
- See the **live evaluation status** of every rule against the current parameter snapshot — green when the condition is satisfied, grey when it is not

---

### Archive Tab

Browse and manage historical measurement data.

**What you can do:**
- List all **recording sessions** stored on the selected node, showing session name, start time, and duration
- **Delete** a session to free disk space (a confirmation dialog prevents accidental deletion)

---

## Source Layout

```
BrewSupervisor/reat-frontend/brew-ui/
├── src/
│   ├── api/                      # HTTP client, BrewSupervisor API wrapper, request caching
│   │   ├── brewApi.js            # High-level API methods used by feature modules
│   │   ├── client.js             # Base axios/fetch client with base URL
│   │   └── requestLayer.js       # TTL-based request deduplication and batching
│   ├── components/
│   │   └── DataValueTree.jsx     # Reusable tree component for hierarchical parameter display
│   ├── features/
│   │   ├── app/                  # Layout shell (AppShell, FermenterTabContent, tab containers)
│   │   ├── archive/              # Archive tab and data loaders
│   │   ├── control/              # Control tab cards and styles
│   │   ├── data/                 # Data recording tab, snapshot utilities, loaders
│   │   ├── fermenters/           # Sidebar and tab header for fermenter node selection
│   │   ├── parameterdb/          # ParameterDB tab, graph view, schema form, sources panel
│   │   ├── rules/                # Rules tab, rule editor modal, rule form hook
│   │   ├── schedule/             # Scenario tab components and import utilities
│   │   └── system/               # System overview tab
│   ├── hooks/
│   │   └── useAdaptivePolling.js # Polling hook with configurable back-off
│   ├── App.jsx                   # Root component — global state, polling, action handlers
│   ├── App.css                   # Application-wide styles
│   └── main.jsx                  # React entry point
├── index.html                    # HTML shell
├── vite.config.js                # Vite configuration (dev proxy → port 8782)
├── eslint.config.js              # ESLint rules
└── package.json                  # Dependencies and scripts
```

---

## Architecture Notes

- **All requests go through the BrewSupervisor gateway** (port 8782). The frontend never talks directly to individual service ports.
- **No external state management library** is used. State lives in `App.jsx` and is passed down as props. Complex derived state is memoised with `useMemo`.
- **Polling** is handled by `useAdaptivePolling`, which adjusts the polling interval based on whether the tab is in focus and whether recent requests were successful.
- **Request deduplication** in `requestLayer.js` prevents duplicate in-flight requests and caches responses for a short TTL to reduce backend load when multiple components need the same data.
- **Graph visualisation** uses `@xyflow/react` for rendering and `@dagrejs/dagre` for automatic hierarchical layout. The graph model is built in `features/parameterdb/graph/graphModel.js`.
- **Starred parameters** are persisted in `localStorage` under the key `brew-ui.starred-params`.

---

## Related Documentation

- [API Overview](../api/README.md) — index of all backend service APIs
- [BrewSupervisor Gateway API](../api/brewsupervisor-api.md) — the primary API consumed by this UI
- [Schedule Excel Import Guide](../api/schedule-excel-import.md) — workbook format for the Scenario tab
- [Control Service API](../api/control-service-api.md) — ownership, ramp, rules, WebSocket streaming
- [Manual Control Map Setup](../api/manual-control-map.md) — setup and maintenance for custom manual controls
- [ParameterDB + Relationship Setup Guide](./parameterdb-relationship-setup.md) — step-by-step frontend workflow for building parameter and source relationships
- [Data Service API](../api/data-service-api.md) — recording, loadstep capture
- [Architecture Overview](../api/architecture.md) — service dependencies and data-flow diagrams
