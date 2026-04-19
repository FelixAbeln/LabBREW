# ParameterDB Math Plugin

The math parameter type evaluates an arithmetic equation each scan cycle using values from other parameters.

It can also mirror its computed output to one or more destination parameters, similar to PID output routing.

## Parameter Type

- parameter_type: math

## Config Keys

- equation (string, required)
: Arithmetic expression to evaluate.
- enable_param (string, optional)
: Parameter name used as boolean-like gate. If false, evaluation is skipped.
- output_params (array[string] or string, optional)
: Parameters that should receive the same computed output value.

## Supported Expression Features

- Numeric constants
- Parameter symbols by name
- Dotted parameter names directly in expressions, for example brewcan.density.0
- Operators: +, -, *, /, //, %, **
- Unary operators: +, -
- Functions: abs, min, max, pow, round, ceil, floor, sqrt, exp, log, log10, sin, cos, tan
- Constants: pi, e

Unsupported or unsafe syntax (attributes, comprehensions, keyword args, and arbitrary code execution) is rejected.

## Examples

### 1) Link one parameter to another

Equation:

```text
brewcan.density.0 * 1
```

Result:

The math parameter always tracks brewcan.density.0.

### 2) Scale and mirror output

Config example:

```json
{
  "equation": "brewcan.density.0 * 2 / 2",
  "output_params": ["display.density"]
}
```

Result:

- math parameter value updates from the equation
- display.density receives the same computed value each scan

### 3) Gated evaluation

Config example:

```json
{
  "equation": "tank.temp.0",
  "enable_param": "math.enable",
  "output_params": ["tank.temp.link"]
}
```

If math.enable is false, no new calculation is applied for that cycle.

## Runtime State

Common engine-managed keys:

- connected
- last_error
- last_sync

Math-specific state keys commonly exposed:

- equation
- symbols
- output_targets
- missing_output_targets
- enabled

## Error Behavior

The plugin sets last_error for recoverable issues, including:

- empty equation
- invalid equation syntax
- missing referenced parameters
- non-numeric referenced parameters
- disallowed operators/functions

When last_error is non-empty, the engine marks the parameter disconnected for that cycle.

## Notes on Names

Parameter names containing dots are supported directly in equations, for example:

brewcan.density.0 * 1

This matches common LabBREW naming conventions and avoids requiring alias maps.
