# Manual Control Map Setup

This guide explains how to set up and maintain the manual control map file used by the Control Service and the frontend Control tab.

## Purpose

The file `data/control_variable_map.json` defines custom controls that are not already provided by datasource SourceDef `mode="control"` specs.

The Control Service reads this file and exposes it through:

- `GET /system/control-contract`
- `GET /system/datasource-contract`
- `GET /system/control-ui-spec`

The frontend Control tab renders these controls as the `Custom Manual Controls` card.

## File Location

- `data/control_variable_map.json`

## Minimal Schema

```json
{
  "version": 1,
  "description": "Manual control map",
  "groups": [
    { "id": "general", "label": "General" }
  ],
  "controls": [
    {
      "id": "set_temp_fermentor",
      "label": "Temp Fermentor",
      "group": "general",
      "target": "set_temp_Fermentor",
      "widget": "number",
      "unit": "C",
      "step": 0.1,
      "min": 0,
      "max": 30
    }
  ]
}
```

## Supported Control Fields

- `id` (string): stable unique ID for the UI/control contract.
- `label` (string): display label shown in the frontend.
- `group` (string): references a group `id` from `groups`.
- `target` (string): ParameterDB parameter name to write.
- `widget` (string): recommended UI widget (`number`, `text`, `toggle`, `button`).
- `unit` (string, optional): display unit suffix.
- `step` (number, optional): numeric input step.
- `min` / `max` (number, optional): numeric bounds hints.

Notes:

- Ownership fields are ignored in this file. Runtime ownership policy is fixed:
  - manual owner: `operator`
  - rule takeover/ramp owner: `safety`
- Keep this file UTF-8 (BOM is tolerated by runtime, but plain UTF-8 is preferred).

## Setup Workflow

1. Start from an empty template or the current file in `data/control_variable_map.json`.
2. Add one or more `groups` to organize controls in UI.
3. Add `controls` entries for parameters you want manually writable.
4. Avoid duplicating controls that are already provided by SourceDef `mode="control"` specs.
5. Save file and refresh Control UI.

## Verify Configuration

Use these endpoints to validate the result:

1. `GET /fermenters/{id}/system/control-contract`
   - check `resolved_controls`, `target_exists`, `current_value`, `current_owner`.
2. `GET /fermenters/{id}/system/datasource-contract`
   - check `manual_controls` and `ui_cards`.
3. `GET /fermenters/{id}/system/control-ui-spec`
   - check that a `manual:custom-map` card appears when manual controls exist.

## Operational Notes

- Manual writes use `POST /control/manual-write`.
- Manual release uses `POST /control/release-manual`.
- If a target is currently owned by `safety`, manual writes are blocked.

## Recommended Maintenance

- Keep `id` stable over time so UI state and diagnostics remain consistent.
- Remove entries that became SourceDef-owned controls to avoid duplicate cards.
- Keep labels user-friendly and targets exact (case-sensitive).