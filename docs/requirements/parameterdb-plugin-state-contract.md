# ParameterDB Plugin Runtime State Contract

This document defines the minimum runtime state fields expected for parameter plugins (`static`, `pid`, `deadband`, `math`, `condition`, and future plugins).

For a step-by-step guide to writing a new plugin see [Writing a ParameterDB Plugin](../implementation/writing-a-parameterdb-plugin.md).

## Required Runtime State Keys

Each plugin state payload must expose these keys (published via scan engine state updates):

- `connected`: `bool`, plugin scan health for the current cycle.
- `last_error`: `string`, plugin error text; empty string means no active error.
- `last_sync`: `string` UTC timestamp (ISO-8601) of the most recent successful plugin scan.

## Engine-Enforced Rules

The scan engine enforces baseline behavior for all plugins:

1. If `scan()` raises an exception:
- `connected = false`
- `last_error = <exception text>`

2. If `scan()` returns with non-empty `state.last_error` set by plugin logic:
- `connected = false`
- `last_error` is preserved

3. If plugin reports `state.enabled == false` and no active error:
- `connected = false`
- `last_error = ""`

4. If scan succeeds and no active error:
- `connected = true`
- `last_error = ""`
- `last_sync = <current UTC timestamp>`

## Plugin Responsibilities

Plugins should continue to set domain-specific state keys (`pv`, `sp`, `error`, etc.).

Plugins should set `state.last_error` for recoverable validation/config issues that do not throw exceptions (for example, missing required config like `pv`/`sp`).

## Mirror Output Convention

The following plugins support an optional `output_params` config key: `pid`, `deadband`, `math`, `condition`.

When `output_params` is set, the plugin writes its computed output value to each named parameter in the store on every successful scan cycle. The following state keys are published by any plugin that implements mirror output:

- `output_targets`: `list[str]`, parameter names that were successfully written during the last scan cycle.
- `missing_output_targets`: `list[str]`, entries from `output_params` that do not exist in the store. Key is absent when all targets are present.

Rules:

- A plugin never writes to its own name (self-reference is silently skipped).
- Duplicate names in `output_params` are deduplicated before writing.
- A missing target is recorded in `missing_output_targets` but does not set `last_error` or prevent the plugin value from being updated.

## Conformance (current plugins)

| Plugin | connected | last_error | last_sync | mirror output | Notes |
|---|---:|---:|---:|---:|---|
| `static` | yes (engine) | yes (engine) | yes (engine) | — | Passive plugin; no custom scan logic |
| `deadband` | yes (engine) | yes (plugin + engine) | yes (engine) | yes | Sets `last_error` when required config missing |
| `pid` | yes (engine) | yes (plugin + engine) | yes (engine) | yes | Sets `last_error` when required config missing |
| `math` | yes (engine) | yes (plugin + engine) | yes (engine) | yes | Sets `last_error` for invalid equation, missing symbols, or non-numeric inputs |
| `condition` | yes (engine) | yes (plugin + engine) | yes (engine) | yes | Sets `last_error` for invalid condition config or missing referenced values |

## Notes

- The runtime state contract is independent of API transport and applies to internal state persistence and publications.
- Additional plugin-specific state keys are encouraged; these required keys are the minimum shared contract.
