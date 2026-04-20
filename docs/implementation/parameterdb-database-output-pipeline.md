# ParameterDB Database-Owned Output Pipeline

## Overview

The **Database Output Pipeline** is a centralized system for transforming and distributing parameter values. It runs in the scan engine after plugin logic completes, ensuring consistent behavior across all parameter types.

The pipeline executes in this order for each parameter scan:
1. **Calibration**: Apply mathematical transformation to plugin output
2. **Mirror**: Write calibrated value to target parameters
3. *(timeshift is now metadata-only for post-processing)*

## Configuration Fields

All ParameterDB parameters support these three database-owned fields in the "Database Output Pipeline" section:

### mirror_to

**Type**: String or Array of Strings  
**Default**: `[]` (empty)  
**Runtime Behavior**: Applied at every scan cycle

Specifies one or more parameters that should receive the calibrated output value.

**Examples:**
```json
"mirror_to": "display.temperature"
```
or
```json
"mirror_to": ["display.temperature", "archive.temperature", "ui.live_temp"]
```

Each scan cycle:
1. Plugin computes value
2. Calibration equation applied (if set)
3. Result written to all mirror targets
4. State tracks successful writes and any missing targets

---

### calibration_equation

**Type**: String (mathematical expression)  
**Default**: `""` (empty, no transformation)  
**Runtime Behavior**: Applied after plugin scan, before mirroring  
**References**: Plugin output (`x`) and other parameters by name

The calibration equation is a mathematical transformation applied to each plugin output. Use `x` to reference the plugin's computed value.

#### Syntax

**Operators:**
- Addition: `+`
- Subtraction: `-`
- Multiplication: `*`
- Division: `/`
- Floor division: `//`
- Modulo: `%`
- Power: `**`
- Unary minus: `-x`
- Unary plus: `+x`

**Functions:**
- `abs(x)` — Absolute value
- `max(a, b)` — Maximum of two values
- `min(a, b)` — Minimum of two values
- `pow(x, n)` — Raise to power
- `round(x)` or `round(x, digits)` — Round to digits
- `ceil(x)` — Ceiling
- `floor(x)` — Floor
- `sqrt(x)` — Square root
- `exp(x)` — e^x
- `log(x)` — Natural logarithm
- `log10(x)` — Base-10 logarithm
- `sin(x)`, `cos(x)`, `tan(x)` — Trigonometric functions (x in radians)

**Constants:**
- `pi` — 3.14159...
- `e` — 2.71828...

#### Examples

**Simple scaling:**
```
calibration_equation: "2*x + 5"
```
If plugin outputs 10, result is 25.

**Reference other parameters** (with dependency tracking):
```
calibration_equation: "x * tank.volume"
```
Reads `tank.volume` parameter on each scan, multiplies by plugin output.
Engine automatically adds `tank.volume` to dependency graph.

**Multi-parameter calculation:**
```
calibration_equation: "(x - tank.offset) / tank.scale"
```
Calibrates sensor reading using offset and scale from other parameters.

**Trigonometric adjustment:**
```
calibration_equation: "abs(sin(x * pi / 180))"
```
Converts degrees to radians and takes absolute sine.

**Conditional-like logic** (use max/min):
```
calibration_equation: "max(min(x, 100), 0)"
```
Clamps output to range [0, 100].

#### Parameter References

Any symbol in the equation (other than `x`, `value`, functions, and constants) is treated as a **parameter reference** using dot notation:

```
calibration_equation: "x * sensor.gain + sensor.offset"
```

This reads:
- `sensor.gain` — Value of parameter named `sensor.gain`
- `sensor.offset` — Value of parameter named `sensor.offset`
- `x` — Plugin's output value

**Dependency Tracking**: Engine automatically extracts all parameter references and adds them to the scan dependency graph. This ensures:
- Parameters are scanned in correct order
- Conflicts are detected (e.g., circular dependencies)
- Scan order is optimized for parallel execution where possible

#### Error Handling

If the equation is invalid or references a missing parameter:
- Parameter value unchanged from plugin output
- Error recorded in parameter state: `last_error`
- Pipeline detail keys are cleared before each pipeline attempt, then repopulated only on success (`calibration_symbols`, `calibration_input`, `calibration_output`, transducer details, mirror target details)

---

### timeshift

**Type**: Number (seconds)  
**Default**: `0.0`  
**Runtime Behavior**: NOT applied (metadata only)  
**Export**: Included in snapshots for post-processing tools

Metadata field specifying the time offset to align this parameter's timeseries with real events.

Since actual data acquisition always has inherent delay, offline processing tools use this value to shift the timeseries forward (mathematically: `t' = t + timeshift`) to align curves with events that triggered them.

**Example:**
```json
"timeshift": 2.5
```

In post-processing, tools would shift this parameter's values 2.5 seconds forward to align with the actual event timing.

**Why not applied at runtime?**
- Real-time scanning cannot shift forward (future data unavailable)
- Delay-based timeshift doesn't align with actual event timing
- Post-processing has full timeseries context for accurate alignment

**Use case:**
```yaml
# Configuration
tank.temperature:
  timeshift: 1.2  # Known delay from sensor to measurement

# Export snapshot
# -> Offline tool reads snapshot
# -> Applies 1.2s forward shift to temperature curve
# -> Temperature now aligns with timestamps from event log
```

---

## State Fields

After pipeline execution, parameters report state:

### mirror_to state
- `output_targets: list[str]` — Parameters successfully written to
- `missing_output_targets: list[str]` — Targets that don't exist (if any)

### calibration_equation state
- `calibration_equation: str` — The equation that was applied
- `calibration_symbols: list[str]` — All referenced parameters/constants
- `calibration_input: float` — Raw plugin output before equation
- `calibration_output: float` — Result after equation
- `calibration_error: str` — Error message if evaluation failed (optional)

### timeshift state
- (Cleared on each scan; timeshift is metadata-only)

---

## Dependency Graph Integration

**Calibration equations are fully integrated into the scan dependency graph.**

### When the graph is rebuilt (lazy rebuild)

The engine uses a lazy rebuild strategy:

- It checks whether the store revision changed at scan-time and graph-info access time.
- If revision is unchanged, the existing graph and scan order are reused.
- If revision changed, the graph is rebuilt immediately before continuing.

This means changes are picked up automatically on the next scan cycle (or next graph query).

**Yes: adding a new parameter auto-triggers a rebuild check and the graph is rebuilt on next use.**

Store revision changes on:

- Parameter add/remove
- Parameter config updates
- Parameter metadata updates
- Scan-time value writes that actually change value
- External value writes that actually change the value (including mirror target writes)

### How it works

1. Engine parses all `calibration_equation` fields
2. Extracts parameter references (e.g., `tank.temperature`, `sensor.offset`)
3. Adds them as **read dependencies** to the dependency graph
4. Topological sort ensures dependencies scan before parameters that reference them
5. Circular dependencies are detected and reported as warnings

### Example

```yaml
# Three parameters
sensor.raw:
  type: linear_sensor
  config: {}

processed.value:
  type: math
  config:
    equation: "sensor.raw * 2"
    
tank.density:
  type: static
  config:
    calibration_equation: "processed.value / tank.volume"
    mirror_to: "display.density"
    
tank.volume:
  type: modbus_register
  config: {}
```

**Scan order determined:**
1. `sensor.raw` — No dependencies
2. `processed.value` — Depends on `sensor.raw`
3. `tank.volume` — No dependencies
4. `tank.density` — Depends on `processed.value` and `tank.volume`
5. `display.density` — Receives mirror write from `tank.density`

**Graph warning if circular:**
```
If tank.volume had calibration_equation: "tank.density + 1"
→ Warning: "Circular dependency detected: tank.density → tank.volume → tank.density"
```

---

## UI Configuration

All parameters expose the "Database Output Pipeline" section in create/edit forms:

**To configure:**

1. Open parameter create/edit form
2. Scroll to **Database Output Pipeline** section
3. Set fields:
   - **Mirror Output To**: Select parameters to receive calibrated value
   - **Calibration Equation**: Enter math expression (e.g., `2*x + 5`)
   - **Post-Processing Timeshift (s)**: Metadata offset for export

Changes take effect immediately on next scan cycle.

---

## Backward Compatibility

**Snapshots with legacy `output_params`:**
- Field is recognized at runtime as a fallback mirror source when `mirror_to` is not set
- All existing snapshots remain compatible

**Plugins with `output_params` in UI specs:**
- Removed; field is now purely database-owned
- Ensures clean separation: plugins define logic, database owns output

---

## Performance Notes

- **Calibration evaluation**: Single-pass symbolic math, cached compiled expressions
- **Mirror writes**: Atomic updates to target parameters
- **Dependency resolution**: O(n log n) topological sort at startup, cached until store changes

---

## See Also

- [Writing a ParameterDB Plugin](./writing-a-parameterdb-plugin.md)
- [ParameterDB Math Plugin](./parameterdb-math-plugin.md) (uses same expression syntax)
- [ParameterDB Signal Plugins](./parameterdb-signal-plugins.md)
