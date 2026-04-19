# BrewSupervisor scenario package import

Gateway endpoints for validating and importing scenario package archives.

## New routes

- `PUT /fermenters/{id}/scenario/validate-import`
- `PUT /fermenters/{id}/scenario/import`

Both accept `multipart/form-data` with a `file` field.

## Supported upload formats

- `.lbpkg` or `.zip` archive
- Archive must contain one of:
	- `scenario.package.msgpack`
	- `scenario-package.msgpack`
	- `package.msgpack`

## Notes

- Scenario runtime executes package-provided runner scripts via `runner.kind=scripted`.
- BrewSupervisor forwards validate/import requests to `scenario_service` and mirrors the response.
- Dry-run validation is available via `PUT /fermenters/{id}/scenario/validate-import`.
- Import is available via `PUT /fermenters/{id}/scenario/import`.
