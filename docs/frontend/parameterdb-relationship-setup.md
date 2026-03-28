# ParameterDB + Relationship Setup Guide (Frontend)

This guide shows how to build your ParameterDB and relationship graph end-to-end using the frontend editor.

It focuses on three outcomes:

1. A clean parameter namespace.
2. Correct relationship wiring (depends on, used by, writes).
3. Validated datasource links in Graph and Sources views.

## Before You Start

Run backend and frontend from the project root:

```bash
python run_supervisor.py
python run_FrontEndsupervisor.py
cd BrewSupervisor/reat-frontend/brew-ui
npm run dev
```

Open the UI at `http://localhost:5173`, select your fermenter in the sidebar, then open the `ParameterDB` tab.

## How The Relationship Model Is Built

The frontend gets relationship data from backend graph data and displays it in:

- `Parameters` view columns:
  - `Depends on`
  - `Used by`
  - `Writes`
- `Graph` view edges:
  - dependency edges
  - write edges
- `Sources` view:
  - `Feeds From`
  - `Publishes`

For source configuration, relationship inputs are discovered from schema fields such as:

- `parameter_ref`
- `parameter_ref_list`
- config keys that look like `*_param`, `*_params`, or input-binding fields.

## Datasource-Created Parameters

Not all parameters are manually created in the Parameters editor.

Many parameters are created and updated by datasources at runtime.

Important behavior:

- Datasource plugins publish their own parameter names.
- Names are typically derived from source config (for example source name or parameter prefix).
- When a source starts, it can create parameters automatically.
- Those parameters then appear in Parameters, Sources, and Graph views.

Practical implication:

- Do not assume every parameter comes from manual creation.
- Treat datasource parameter naming as source-owned unless you intentionally override via source config.
- Use stable source names/prefixes so published parameter names remain predictable.

## Step 1: Plan Naming and Structure

Use a stable namespace before creating parameters. A simple pattern is:

- Measurements: `brewcan.temperature.0`, `brewcan.pressure.0`
- Setpoints: `set_temp_Fermentor`, `set_pres_Fermentor`, `set_spd_Agitator`
- Control outputs: `relay.ch1`, `relay.ch2`
- Controller internals: `pid_temp.*`, `dbc_temp_*`

Guidelines:

- Keep names lowercase with separators unless you need legacy compatibility.
- Keep one physical concept per parameter.
- Reserve `set_*` names for writable targets.

## Step 2: Create Base Parameters (Parameters View)

1. In `ParameterDB` open `Parameters` view.
2. Click `+ Add Parameter`.
3. Select a parameter type.
4. Fill required fields from the schema form.
5. Save.

Suggested order:

1. Create base static parameters first (setpoints, toggles, references).
2. Create derived/controller parameters next (deadband, PID, logic).
3. Only then wire cross-parameter references.

Why this order helps: relationship fields can point to existing parameters immediately, reducing graph warnings.

## Step 3: Wire Parameter Relationships

Edit each controller/derived parameter and set reference fields in config.

Typical wiring patterns:

- Controller input reference to measurement parameter.
- Controller setpoint reference to setpoint parameter.
- Output target list to writable actuator/set parameter(s).

After each save, verify the row in `Parameters`:

- `Depends on` should list expected upstream parameters.
- `Writes` should list expected target parameters.
- Referenced targets should show the current parameter under their `Used by` column.

If a reference is misspelled or missing, graph warnings appear and relationship columns will not match intent.

## Step 4: Configure Datasources (Sources View)

1. Switch to `Sources` view.
2. Click `+ Add Source`.
3. Select source type.
4. Fill source config from dynamic schema.
5. Save and confirm source state becomes `running`.

Then verify:

- `Feeds From` contains expected input parameters from your config bindings.
- `Publishes` contains parameters created by that source at runtime.

For each source:

- keep a stable `name`
- use explicit parameter prefixes where available
- map input bindings to existing base parameters

## Step 5: Validate In Graph View

1. Open `Graph` view.
2. Use filter to isolate subsystem names (`temp`, `pid`, `relay`, etc.).
3. Click a node to show lineage highlighting.
4. Inspect detail panel for dependencies and write targets.

Expected edge semantics:

- Solid dependency edge: upstream value dependency.
- Dashed write edge: active writer/target relationship.
- Source-node edges: datasource publishes and feed bindings.

If a subsystem looks disconnected:

1. Re-open related parameter or source edit form.
2. Check reference fields for exact name match.
3. Save and refresh.

## Step 6: Operational Checks

Before relying on automation/control:

1. In `Parameters`, confirm no unexpected graph warnings.
2. In `Sources`, ensure required sources are `running`.
3. In `Graph`, verify critical write paths (controller to actuator target).
4. In `Control` tab, verify writable targets appear as intended.

## Common Mistakes

- Creating controller parameters before creating referenced base parameters.
- Inconsistent naming (`set_temp_fermentor` vs `set_temp_Fermentor`).
- Mixing units without metadata (harder to debug and tune).
- Using one parameter name for multiple physical meanings.

## Recommended Build Pattern (Template)

Use this sequence for each new control loop:

1. Create measurement parameter.
2. Create setpoint parameter.
3. Create actuator target parameter.
4. Create controller/deadband parameter.
5. Wire references (depends/writes).
6. Validate row columns.
7. Validate graph lineage.
8. Validate source integration.

## Quick Troubleshooting

- Missing dependency edge:
  - check parameter reference fields in config.
- Missing write edge:
  - check output target field names.
- Source not feeding graph:
  - check source config input bindings and source running state.
- Source publishes missing:
  - check source runtime health and parameter prefix configuration.

## Related Docs

- [Frontend Overview](./README.md)
- [ParameterDB Binary Protocol API](../api/parameterdb-api.md)
- [Control Service API](../api/control-service-api.md)
- [Manual Control Map Setup](../api/manual-control-map.md)