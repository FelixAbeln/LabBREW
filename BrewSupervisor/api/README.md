# BrewSupervisor schedule import patch

Adds clean schedule import support to the UI backend.

## New routes

- `PUT /fermenters/{id}/schedule/validate-import`
- `PUT /fermenters/{id}/schedule/import`

Both accept `multipart/form-data` with a `file` field.

## Workbook format

### Sheet: `meta`
| key | value |
|---|---|
| id | proper-api-test-plan |
| name | Proper API test plan |

### Sheet: `setup_steps` and `plan_steps`
Supported columns:
- `step_id`
- `name`
- `enabled`
- `action_kind`
- `target`
- `value`
- `duration_s`
- `wait_kind`
- `wait_source`
- `wait_operator`
- `wait_threshold`
- `wait_for_s`
- `wait_duration_s`

## Notes

- Scheduler remains JSON-only.
- BrewSupervisor parses Excel, validates, and forwards canonical JSON to `PUT /schedule`.
- This patch uses `openpyxl`; install it in the UI backend environment if needed.
