# ParameterDB Datasource Status Contract

This document defines the minimum status behavior every ParameterDB datasource must expose.

## Required Status Parameters

Each datasource must publish these status fields as `static` parameters under its prefix:

- `connected`
: `bool` flag for current health of the datasource runtime loop.
- `last_error`
: `string` with the most recent error message. Empty string means no active error.
- `last_sync`
: `string` UTC timestamp (ISO-8601) of the most recent successful sync cycle.

## Behavior Rules

1. On successful sync cycle:
- Set `connected = true`
- Set `last_error = ""`
- Update `last_sync` to current UTC timestamp

2. On runtime/sync failure:
- Set `connected = false`
- Set `last_error = <error text>`
- Do not clear `last_sync`; it remains the most recent successful timestamp

3. On shutdown/stop:
- Best effort set `connected = false`

4. On disconnect/close failures:
- Must not be silently swallowed
- Must be reflected through `last_error` (for example: `Disconnect failed: ...`)

## Conformance (current sources)

| Source | connected | last_error | last_sync | Disconnect errors surfaced |
|---|---:|---:|---:|---:|
| `modbus_relay` | yes | yes | yes | yes |
| `brewtools_kvaser` | yes | yes | yes | yes |
| `labps3005dn` | yes | yes | yes | yes |
| `digital_twin` | yes | yes | yes | n/a (no external socket close path) |
| `system_time` | yes | yes | yes | n/a |

## Notes

- Additional status fields are allowed (`status`, `last_frame_utc`, etc.), but the required core fields above must always exist.
- Custom parameter names via config (`*_param`) are allowed, as long as the semantic contract is preserved.

## Ownership Metadata Contract

Every parameter created or owned by a datasource should include ownership metadata so UIs and tooling can group published parameters back to the datasource instance.

Required metadata keys for datasource-owned parameters:

- `created_by = "data_source"`
- `owner = <datasource instance name>`
- `source_type = <datasource type>`

Recommended metadata keys when applicable:

- `device = <device family or logical device name>`
- `role = <measurement|status|command|...>`
- `node_id = <hardware node/channel id>`
- `kind = <temperature|pressure|level|...>`

This metadata is the canonical way for higher-level tools to determine which datasource publishes which parameters.
