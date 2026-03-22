# LabBREW API Documentation

LabBREW is a microservices-based fermentation management and control system. This directory contains reference documentation for all HTTP and binary-protocol APIs exposed between its services, the API gateway, and the frontend.

## Services at a Glance

| Service | Protocol | Default Port | Purpose |
|---|---|---|---|
| [BrewSupervisor Gateway](./brewsupervisor-api.md) | HTTP (REST) | 8782 | API gateway consumed by the React frontend |
| [Supervisor Agent](./agent-api.md) | HTTP (REST) | 8780 | Per-node agent: health, discovery, service proxy |
| [Control Service](./control-service-api.md) | HTTP (REST + WebSocket) | 8767 | Parameter ownership, ramping, rules engine |
| [Schedule Service](./schedule-service-api.md) | HTTP (REST) | 8768 | Multi-step fermentation schedule execution |
| [ParameterDB](./parameterdb-api.md) | Binary (TCP) | 8765 | Parameter store with real-time scanning |

## Quick Navigation

- **Frontend developers** — start with [BrewSupervisor Gateway API](./brewsupervisor-api.md); all browser requests go there.
- **Backend / integration developers** — read [Architecture](./architecture.md) first, then the individual service pages.
- **Hardware / driver developers** — read [ParameterDB Binary Protocol](./parameterdb-api.md).

## Architecture Overview

See [architecture.md](./architecture.md) for a full description of the service dependency chain, communication protocols, and data-flow diagrams.
