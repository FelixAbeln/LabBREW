# ParameterDB Signal Plugins

Related documentation:
- [Writing a ParameterDB Plugin](../implementation/writing-a-parameterdb-plugin.md)
- [Plugin Runtime State Contract](../requirements/parameterdb-plugin-state-contract.md)
- [ParameterDB Binary Protocol API](../api/parameterdb-api.md)

This document covers the signal-processing style ParameterDB plugins used to smooth, transform, or differentiate values from other parameters.

All of these plugins follow the standard ParameterDB mirror-output convention:
- the plugin always updates its own parameter value
- `output_params` is optional and mirrors that same output to additional parameters
- the plugin never treats its own name as a mirror target

## Available Plugins

### `derivative`

Computes rate-of-change from a source parameter.

Config keys:
- `source` (required)
- `enable_param` (optional)
- `mode` (optional, `continuous` or `window`, default `continuous`)
- `window_s` (optional, default `2.0`, used when mode is `window`)
- `scale` (optional, default `1.0`)
- `min_dt` (optional, default `1e-6`)
- `output_params` (optional)

Use when:
- you want slope or speed of change
- you need to detect how fast a process variable is moving

Notes:
- output updates every scan cycle
- `continuous` mode uses elapsed time between detected source changes rather than collapsing immediately to zero on unchanged scans
- `window` mode uses a fixed trailing time window, for example `window_s = 2.0` for a two-second derivative
- disable/re-enable resets the baseline

### `lowpass`

Applies a first-order lowpass filter.

Config keys:
- `source` (required)
- `enable_param` (optional)
- `tau_s` (optional, default `1.0`)
- `output_params` (optional)

Behavior:
- first enabled scan snaps to the current source value
- later scans use `alpha = dt / (tau_s + dt)`
- larger `tau_s` means stronger smoothing
- `tau_s = 0` means pass-through

Use when:
- noise is continuous and you want a smooth analog signal
- you want an exponential-style smoothing response

### `moving_average`

Applies a rolling arithmetic mean over the most recent `window` samples.

Config keys:
- `source` (required)
- `enable_param` (optional)
- `window` (optional, default `5`)
- `output_params` (optional)

Behavior:
- each scan adds the current source value to the rolling window
- output is the average of the retained samples
- disable/re-enable clears the window and restarts from fresh samples

Use when:
- you want simple smoothing over a fixed number of recent points
- the data is sampled fairly uniformly

### `median`

Applies a rolling median over the most recent `window` samples.

Config keys:
- `source` (required)
- `enable_param` (optional)
- `window` (optional, default `5`)
- `output_params` (optional)

Behavior:
- each scan adds the current source value to the rolling window
- output is the median of retained samples
- disable/re-enable clears the window and restarts from fresh samples

Use when:
- noise has occasional spikes or outliers
- you want better rejection of single bad samples than a moving average provides

## Mirror Output Example

All signal plugins support the same mirror-output config shape:

```json
{
  "source": "brewcan.density.0",
  "output_params": ["brewcan.density.filtered"]
}
```

The plugin parameter still holds the primary computed value itself. `output_params` only adds extra destinations.

## Choosing Between Them

Use `lowpass` when:
- you want smooth analog behavior based on time constant
- scan timing may vary a little and you still want stable smoothing

Use `moving_average` when:
- you want a fixed-size rolling average
- the last `N` samples matter more than continuous-time behavior

Use `median` when:
- the signal has spikes or occasional bad readings
- you want to reject outliers before further logic uses the value

Use `derivative` when:
- you want rate-of-change instead of smoothing
- you want to build acceleration, trend, or edge-like behavior from analog signals

## Runtime State

Common engine-managed keys:
- `connected`
- `last_error`
- `last_sync`

Plugin-specific state commonly exposed:
- `source`
- `input`
- `enabled`
- `output_targets`
- `missing_output_targets`

Additional per-plugin state:
- `derivative`: `mode`, `window_s`, `delta`, `raw_derivative`, `scale`, `dt`, `effective_dt`, `elapsed_since_change_s`, `updated_on_change`, `history_sample_count`, `history_span_s`
- `lowpass`: `tau_s`, `dt`, `alpha`
- `moving_average`: `window`, `sample_count`, `samples`
- `median`: `window`, `sample_count`, `samples`

## Example Configs

Lowpass:

```json
{
  "source": "brewcan.density.0",
  "tau_s": 3.0,
  "output_params": ["brewcan.density.lp"]
}
```

Moving average:

```json
{
  "source": "brewcan.density.0",
  "window": 8,
  "output_params": ["brewcan.density.avg"]
}
```

Median:

```json
{
  "source": "brewcan.density.0",
  "window": 7,
  "output_params": ["brewcan.density.med"]
}
```

Derivative:

```json
{
  "source": "brewcan.density.lp",
  "mode": "window",
  "window_s": 2.0,
  "scale": 1.0,
  "output_params": ["brewcan.density.rate"]
}
```
