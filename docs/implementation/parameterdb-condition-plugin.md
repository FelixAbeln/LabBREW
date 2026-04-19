# ParameterDB Condition Plugin

Related documentation:
- [Schedule Excel Import Format](../api/schedule-excel-import.md)
- [ParameterDB Binary Protocol API](../api/parameterdb-api.md)
- [Wait Event Engine](../implementation/wait-event-engine.md)
- [Writing a ParameterDB Plugin](../implementation/writing-a-parameterdb-plugin.md)

The condition parameter type evaluates the shared wait-expression DSL already used by schedule import and stores the final boolean result in ParameterDB.

This means the plugin follows the existing LabBREW syntax directly instead of defining a second condition language.

## Parameter Type

- parameter_type: condition

## Config Keys

- condition (string, required)
: Wait-expression DSL string.
- enable_param (string, optional)
: Parameter name used as a boolean-like gate. If false, evaluation is skipped and the timing state is reset.
- output_params (list of strings, optional)
: One or more ParameterDB parameter names that should receive the same boolean value on every successful scan cycle. Follows the same mirror-output convention as `pid`, `deadband`, and `math`.

For backward compatibility, the plugin still accepts the older structured dict form, but the DSL string is the documented and preferred syntax.

## Syntax

This syntax is intentionally the same as the wait syntax documented in [Schedule Excel Import Format](../api/schedule-excel-import.md#wait-column-syntax).

### `cond` - parameter comparison

```text
cond:source:operator:threshold
cond:source:operator:threshold:for_seconds
```

Examples:

```text
cond:test:!=:10
cond:brewcan.density.0:<=:1.012:120
```

Parts:

- `source`
: ParameterDB parameter name to read.
- `operator`
: Comparison operator such as `>`, `>=`, `<`, `<=`, `==`, or `!=`.
- `threshold`
: Value to compare against. Numbers and `true` / `false` are parsed automatically.
- `for_seconds`
: Optional continuous-true hold time. This is where the condition-level hold logic belongs.

### `elapsed` - elapsed time since the logic started

```text
elapsed:seconds
```

Example:

```text
elapsed:900
```

For the condition plugin, elapsed time starts when the plugin first becomes active after creation, config change, or re-enable.

When `enable_param` is `false`, elapsed timing state is reset. Re-enabling starts elapsed timing from zero again.

### `all(...)` - every child must match

```text
all(expr1;expr2;...)
```

Example:

```text
all(elapsed:900;cond:brewcan.density.0:<=:1.012:120)
```

### `any(...)` - at least one child must match

```text
any(expr1;expr2;...)
```

Example:

```text
any(elapsed:7200;cond:abort.flag:==:true)
```

### `rising(...)` - match once on false -> true transition

```text
rising(expr)
```

Example:

```text
rising(cond:brew.phase.ready:==:true)
```

### `falling(...)` - match once on true -> false transition

```text
falling(expr)
```

Example:

```text
falling(cond:brew.phase.ready:==:true)
```

### `pulse(...)` - edge-triggered hold window

```text
pulse(expr;hold_seconds)
```

Example:

```text
pulse(cond:brew.phase.ready:==:true;10)
```

The pulse starts on the rising edge of `expr` and remains matched for `hold_seconds`.

### Nesting

`all(...)`, `any(...)`, `rising(...)`, `falling(...)`, and `pulse(...)` can be nested:

```text
all(elapsed:600;any(cond:reactor.temp:>=:64;cond:abort.flag:==:true))
```

## Runtime State

Common engine-managed keys:

- connected
- last_error
- last_sync

Condition-specific keys commonly exposed:

- expression
- logic_kind
- condition_kind
- source
- operator
- params
- sources
- matched
- elapsed_s
- required_for_s
- observed_values
- message
- enabled
- output_targets
- missing_output_targets
- invalid_config

Notes:

- `logic_kind` reflects the top-level wait node such as `condition`, `elapsed`, `all_of`, or `any_of`.
- `condition_kind` is populated when the plugin is evaluating a direct condition node and reports `atomic`, `all`, `any`, or `not`.
- `elapsed_s` is wall-clock time since the current logic run started, not only the condition hold time.
- `required_for_s` reports the active threshold for the top-level timing gate, for example `elapsed:900` or `cond:...:120`.
- `output_targets` lists the parameter names that were successfully written during the last scan cycle.
- `missing_output_targets` lists any `output_params` entries that do not exist in the store; absent from state when all targets are present.
- `invalid_config` is `true` when the configured logic cannot be compiled (invalid DSL or malformed condition payload).

## Error Behavior

The plugin sets `last_error` for recoverable issues, including:

- invalid DSL syntax
- invalid legacy dict config
- missing referenced values
- malformed operator parameters

When a referenced value is missing, the plugin preserves the previous stored boolean and reports the error for that scan cycle.

When logic is invalid, the plugin marks `invalid_config=true` and keeps the previous stored boolean value.

## Examples

### 1. Simple parameter boolean

```json
{
  "condition": "cond:test:!=:10"
}
```

### 2. Your density example

```json
{
  "condition": "all(elapsed:900;cond:brewcan.density.0:<=:1.012:120)"
}
```

### 3. Gated evaluation

```json
{
  "condition": "any(elapsed:7200;cond:abort.flag:==:true)",
  "enable_param": "logic.enable"
}
```

### 4. Impromptu timer pattern

You can use a condition parameter as a reusable timer by pairing `elapsed` with `enable_param`:

```json
{
  "condition": "elapsed:300",
  "enable_param": "timer.start"
}
```

- Set `timer.start = false` to reset and hold the timer idle.
- Set `timer.start = true` to start counting from zero.
- After 300 seconds, the condition output becomes `true`.

### 5. Mirror output to another parameter

When the condition evaluates to `true`, `relay.pump` receives the same boolean value:

```json
{
  "condition": "cond:brewcan.density.0:<=:1.012:120",
  "output_params": ["relay.pump"]
}
```
