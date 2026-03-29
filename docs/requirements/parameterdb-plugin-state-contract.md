# ParameterDB Plugin Runtime State Contract

This document defines the minimum runtime state fields expected for parameter plugins (`static`, `pid`, `deadband`, `math`, and future plugins).

## Required Runtime State Keys

Each plugin state payload must expose these keys (published via scan engine state updates):

- `connected`
: `bool`, plugin scan health for the current cycle.
- `last_error`
: `string`, plugin error text; empty string means no active error.
- `last_sync`
: `string` UTC timestamp (ISO-8601) of the most recent successful plugin scan.

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

## Conformance (current plugins)

| Plugin | connected | last_error | last_sync | Notes |
|---|---:|---:|---:|---|
| `static` | yes (engine) | yes (engine) | yes (engine) | Passive plugin; no custom scan logic |
| `deadband` | yes (engine) | yes (plugin + engine) | yes (engine) | Sets `last_error` when required config missing |
| `pid` | yes (engine) | yes (plugin + engine) | yes (engine) | Sets `last_error` when required config missing |
| `math` | yes (engine) | yes (plugin + engine) | yes (engine) | Sets `last_error` for invalid equation, missing symbols, or non-numeric inputs |

## Notes

- The runtime state contract is independent of API transport and applies to internal state persistence and publications.
- Additional plugin-specific state keys are encouraged; these required keys are the minimum shared contract.
