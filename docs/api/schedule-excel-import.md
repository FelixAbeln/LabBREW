# Schedule Excel Import Format

**Source:** `BrewSupervisor/api/schedule_import/parser.py`, `BrewSupervisor/api/schedule_import/validator.py`  
**Related API:** [`PUT /fermenters/{id}/schedule/import`](./brewsupervisor-api.md#put-fermentersfermenteridfscheduleimport)

The BrewSupervisor Gateway accepts a `.xlsx` workbook and converts it to the JSON `ScheduleDefinition` expected by the [Schedule Service](./schedule-service-api.md). This page documents every sheet, column, and cell syntax the parser understands.

---

## Workbook Structure

A valid workbook must contain these sheets (all names are case-sensitive):

| Sheet | Required | Description |
|---|---|---|
| `meta` | **yes** | Schedule identity fields (id, name) |
| `setup_steps` | no | Steps executed once at schedule start |
| `plan_steps` | no | Steps executed as the main sequence |

---

## Sheet: `meta`

Row 1 is ignored (header row). Each subsequent row is a **key → value** pair:

| Column A (key) | Column B (value) | Required | Description |
|---|---|---|---|
| `id` | string | yes | Unique schedule identifier (no spaces) |
| `name` | string | yes | Human-readable schedule name |

**Example:**

| key | value |
|---|---|
| id | lager-cold-crash |
| name | Lager Cold Crash Program |

---

## Sheets: `setup_steps` and `plan_steps`

Row 1 is the **header row** (column names are read from it and matched by name). The order of columns does not matter. All remaining rows are steps; blank rows are skipped.

### Required columns

| Column | Type | Description |
|---|---|---|
| `step_id` | string | Unique identifier within the phase |
| `name` | string | Human-readable step label |

### Optional columns

| Column | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | `false` / `0` / `no` disables the step (it is skipped) |
| `actions` | string | _(none)_ | Semicolon-separated action expressions (see below) |
| `wait` | string | _(none)_ | Wait expression (see below) |

---

## `actions` column syntax

Zero or more actions separated by **`;`** (semicolon). Whitespace around `;` is ignored.

### Write action

```
target:value
```

Sets `target` to `value` immediately.

```
reactor.temp.setpoint:65
heater.enable:true
```

### Ramp action

```
target:value:duration_seconds
```

Ramps `target` from its current value to `value` over `duration_seconds` seconds.

```
reactor.temp.setpoint:0:3600
```

### Multiple actions in one cell

Actions are applied left-to-right in the order they appear:

```
reactor.temp.setpoint:65;heater.enable:true;agitator.rpm:120
```

### Value parsing rules

| Cell text | Parsed as |
|---|---|
| `65` | integer `65` |
| `65.5` | float `65.5` |
| `true` / `false` | boolean |
| anything else | string |

---

## `wait` column syntax

A single wait expression. Leave blank (or omit the column) for no wait.

### `elapsed` — wait for a time duration

```
elapsed:seconds
```

The step advances after `seconds` have passed since it started.

```
elapsed:3600
```

### `cond` — wait for a parameter condition

```
cond:source:operator:threshold
cond:source:operator:threshold:for_seconds
```

| Part | Description |
|---|---|
| `source` | ParameterDB parameter name |
| `operator` | Comparison operator (see table below) |
| `threshold` | Value to compare against (parsed with the same rules as action values) |
| `for_seconds` | Optional: condition must stay true this many seconds before advancing |

**Available operators**

| Operator | Description |
|---|---|
| `>` | Greater than |
| `>=` | Greater than or equal |
| `<` | Less than |
| `<=` | Less than or equal |
| `==` | Loose equality |
| `!=` | Loose inequality |

```
cond:reactor.temp:>=:64
cond:reactor.temp:>=:64:60
```

### `all(…)` — all sub-waits must match

```
all(expr1;expr2;...)
```

```
all(elapsed:600;cond:reactor.temp:>=:64)
```

### `any(…)` — at least one sub-wait must match

```
any(expr1;expr2;...)
```

Useful for timeout-or-condition patterns:

```
any(elapsed:7200;cond:abort.flag:==:true)
```

### Nesting

`all` and `any` can be nested to arbitrary depth. The parser splits on `;` respecting parenthesis depth, so inner `;` characters inside `all(…)` / `any(…)` are not treated as separators at the outer level:

```
all(elapsed:600;any(cond:reactor.temp:>=:64;cond:abort.flag:==:true))
```

---

## Complete Example

```
Sheet: meta
───────────────────────────────
key     │ value
────────┼──────────────────────
id      │ standard-mash
name    │ Standard Mash Program

Sheet: setup_steps
───────────────────────────────────────────────────────────────────────────────────────────────────
step_id   │ name        │ enabled │ actions                                          │ wait
──────────┼─────────────┼─────────┼──────────────────────────────────────────────────┼───────────
init-heat │ Initial heat│ true    │ reactor.temp.setpoint:65;heater.enable:true       │

Sheet: plan_steps
───────────────────────────────────────────────────────────────────────────────────────────────────
step_id    │ name              │ enabled │ actions                          │ wait
───────────┼───────────────────┼─────────┼──────────────────────────────────┼──────────────────────────────────
beta-gluc  │ Beta-glucan rest  │ true    │ reactor.temp.setpoint:39         │ cond:reactor.temp:>=:38:300
protein    │ Protein rest      │ true    │ reactor.temp.setpoint:52:900     │ all(elapsed:1800;cond:reactor.temp:>=:51)
sacc-1     │ Saccharification 1│ true    │ reactor.temp.setpoint:63         │ elapsed:3600
sacc-2     │ Saccharification 2│ true    │ reactor.temp.setpoint:72         │ cond:reactor.temp:>=:71:600
mash-out   │ Mash out          │ true    │ reactor.temp.setpoint:78:600     │ any(elapsed:1800;cond:abort.flag:==:true)
cool-down  │ Cool down         │ true    │ reactor.temp.setpoint:0:7200     │ cond:reactor.temp:<=:20
```

---

## Validation

Before the JSON payload is forwarded to the Schedule Service the parser runs validation checks. Errors block import; warnings are informational only.

**Hard errors (block import)**
- Missing or empty `id` / `name` in the `meta` sheet
- Missing `step_id` or `name` in a step row
- Invalid action syntax (wrong number of `:` separators)
- Invalid wait syntax (unknown prefix or malformed expression)
- `ramp` action missing `duration_s`
- `condition` wait missing `source`, `operator`, or `threshold`
- Unknown wait or action kind

**Warnings (allow import)**
- A step has no actions
