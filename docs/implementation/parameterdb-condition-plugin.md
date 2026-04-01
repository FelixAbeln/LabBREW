# ParameterDB Condition Plugin

Related documentation:
- [Schedule Excel Import Format](../api/schedule-excel-import.md)
- [ParameterDB Binary Protocol API](../api/parameterdb-api.md)
- [Wait Event Engine](../implementation/wait-event-engine.md)

The condition parameter type evaluates the shared wait-expression DSL already used by schedule import and stores the final boolean result in ParameterDB.

This means the plugin follows the existing LabBREW syntax directly instead of defining a second condition language.

## Parameter Type

- parameter_type: condition

## Config Keys

- condition (string, required)
: Wait-expression DSL string.
- enable_param (string, optional)
: Parameter name used as a boolean-like gate. If false, evaluation is skipped and the timing state is reset.

For backward compatibility, the plugin still accepts the older structured dict form, but the DSL string is the documented and preferred syntax.

## Syntax

This syntax is intentionally the same as the wait syntax documented in [Schedule Excel Import Format](../api/schedule-excel-import.md#wait-column-syntax).

### `cond` - parameter comparison

```
cond:source:operator:threshold
cond:source:operator:threshold:for_seconds
```

Examples:

```
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

```
elapsed:seconds
```

Example:

```
elapsed:900
```

For the condition plugin, elapsed time starts when the plugin first becomes active after creation, config change, or re-enable.

When `enable_param` is `false`, elapsed timing state is reset. Re-enabling starts elapsed timing from zero again.

### `all(...)` - every child must match

```
all(expr1;expr2;...)
```

Example:

```
all(elapsed:900;cond:brewcan.density.0:<=:1.012:120)
```

### `any(...)` - at least one child must match

```
any(expr1;expr2;...)
```

Example:

```
any(elapsed:7200;cond:abort.flag:==:true)
```

### `rising(...)` - match once on false -> true transition

```
rising(expr)
```

Example:

```
rising(cond:brew.phase.ready:==:true)
```

### `falling(...)` - match once on true -> false transition

```
falling(expr)
```

Example:

```
falling(cond:brew.phase.ready:==:true)
```

### `pulse(...)` - edge-triggered hold window

```
pulse(expr;hold_seconds)
```

Example:

```
pulse(cond:brew.phase.ready:==:true;10)
```

The pulse starts on the rising edge of `expr` and remains matched for `hold_seconds`.

### Nesting

`all(...)`, `any(...)`, `rising(...)`, and `falling(...)` can be nested:

```
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

Notes:

- `logic_kind` reflects the top-level wait node such as `condition`, `elapsed`, `all_of`, or `any_of`.
- `condition_kind` is populated when the plugin is evaluating a direct condition node and reports `atomic`, `all`, `any`, or `not`.
- `elapsed_s` is wall-clock time since the current logic run started, not only the condition hold time.
- `required_for_s` reports the active threshold for the top-level timing gate, for example `elapsed:900` or `cond:...:120`.

## Error Behavior

The plugin sets `last_error` for recoverable issues, including:

- invalid DSL syntax
- invalid legacy dict config
- missing referenced values
- malformed operator parameters

When a referenced value is missing, the plugin preserves the previous stored boolean and reports the error for that scan cycle.

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