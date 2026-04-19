# LabBREW API Documentation

LabBREW is a microservices-based fermentation management and control system. This directory contains reference documentation for all HTTP and binary-protocol APIs exposed between its services, the API gateway, and the frontend.

## Services at a Glance

| Service | Protocol | Default Port | Purpose |
|---|---|---|---|
| [BrewSupervisor Gateway](./brewsupervisor-api.md) | HTTP (REST) | 8782 | API gateway consumed by the React frontend |
| [Supervisor Agent](./agent-api.md) | HTTP (REST) | 8780 | Per-node agent: health, discovery, service proxy |
| [Control Service](./control-service-api.md) | HTTP (REST + WebSocket) | 8767 | Parameter ownership, ramping, rules engine |
| [Scenario Service](./schedule-service-api.md) | HTTP (REST) | 8770 | Scenario package execution and run orchestration |
| [Data Service](./data-service-api.md) | HTTP (REST) | 8769 | High-rate parameter logging and loadstep averaging |
| [ParameterDB](./parameterdb-api.md) | Binary (TCP) | 8765 | Parameter store with real-time scanning |

## Guides

| Guide | Description |
|---|---|
| [Schedule Excel Import](./schedule-excel-import.md) | Workbook sheet layout, column syntax, wait expressions, and validation rules for importing `.xlsx` scenario packages |
| [Writing a LabBREW `.lbpkg` Package](../implementation/writing-an-lbpkg-package.md) | Build a complete self-contained runtime package: manifest, artifacts, runner, validation, editor spec, repository integration, and test workflow |
| [Writing a Scenario Runner](../implementation/writing-a-scenario-runner.md) | Build scripted runner modules with full context API, progress fields, waits/actions, and compatibility patterns |
| [Manual Control Map Setup](./manual-control-map.md) | How to configure `data/control_variable_map.json` for custom manual controls in the Control tab |
| [Multi-Device Topology Setup](./multi-device-topology-setup.md) | Configure split-service fermenter deployments across multiple devices, including YAML topology patterns |

## Requirements Contracts

| Contract | Description |
|---|---|
| [Datasource Status Contract](../requirements/parameterdb-datasource-status-contract.md) | Required status fields and runtime behavior for ParameterDB datasources |
| [Plugin Runtime State Contract](../requirements/parameterdb-plugin-state-contract.md) | Required runtime state fields and scan-cycle behavior for ParameterDB plugins |

## Quick Navigation

- **Frontend developers** — start with [BrewSupervisor Gateway API](./brewsupervisor-api.md); all browser requests go there.
- **Frontend ParameterDB work** — start with [BrewSupervisor Gateway API](./brewsupervisor-api.md#parameterdb-gateway-routes), then [Supervisor Agent API](./agent-api.md#local-parameterdb-endpoints), then [ParameterDB Binary Protocol](./parameterdb-api.md) if you need backend protocol details.
- **Backend / integration developers** — read [Architecture](./architecture.md) first, then the individual service pages.
- **Hardware / driver developers** — read [ParameterDB Binary Protocol](./parameterdb-api.md).

## Architecture Overview

See [architecture.md](./architecture.md) for a full description of the service dependency chain, communication protocols, and data-flow diagrams.
