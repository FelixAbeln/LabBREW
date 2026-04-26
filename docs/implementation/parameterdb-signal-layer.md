# ParameterDB Signal Layer

## Overview

Every parameter in ParameterDB maintains **two values** simultaneously:

| Field | Description |
|---|---|
| **Signal** | The raw value written by the plugin or datasource during scan. This is what the hardware / computation produced before any transformation. |
| **Value** | The post-pipeline value — what operators and downstream parameters see. This is Signal after calibration equations and transducer mappings have been applied. |

When no pipeline is configured (no calibration equation, no transducer), Signal and Value are equal.

---

## How it works

Each scan cycle follows this sequence:

```
1. Plugin / datasource writes raw measurement → Signal (param.value)
2. Engine reads Signal
3. Engine applies calibration equation  (if configured)
4. Engine applies transducer mapping    (if configured)
5. Engine applies channel limits        (if configured)
6. Engine writes result → Value (param._pipeline_value)
7. Engine mirrors Value to any mirror_to targets
```

**Important**: Plugins write the Signal by either calling `param.set_value(measurement)` or directly assigning `param.value = measurement`. Both approaches reset the freshness timer (_last_signal_time), which is used for datasource silence detection (stale_timeout_s).

Between scans, if an external write (`store.set_value()`) arrives — for example a manual override from the UI — it writes the Signal and resets the pipeline to *pending*. `get_value()` falls back to the raw Signal until the next scan cycle processes it through the pipeline.

---

## Stale Detection (Datasource Silence)

When a datasource stops sending updates, a parameter configured with `stale_timeout_s` will be marked as stale (amber warning) rather than invalid (red error). This indicates the last known value is present but potentially outdated.

**Configuration** (in parameter config):
```json
{
  "stale_timeout_s": 30
}
```

If no Signal write occurs for more than 30 seconds, the parameter is marked with `datasource_silent` reason and shows as amber "STALE" in the UI. Staleness propagates to downstream parameters as `dependency_stale` — the whole dependency chain goes amber if an upstream sensor stops sending.

Stale parameters recover automatically when Signal writes resume.

---

## Reading values in code

```python
# Read the post-pipeline value (what operators see)
store.get_value("brewcan.density.0")

# Read the raw signal (what the plugin/datasource produced)
store.get_signal_value("brewcan.density.0")

# Both are present in every record snapshot
record = store.get_record("brewcan.density.0")
record.value         # post-pipeline
record.signal_value  # raw signal
```

---

## Frontend — Signal column colours

The **Signal** column in the ParameterDB parameter list uses colour to communicate pipeline state at a glance:

### Grey — no active pipeline

```
SIGNAL        VALUE
1.0489...     1.0489...
```

The Signal is grey (`#475569`) when Signal == Value. This indicates that, for this reading, the pipeline did not change the numeric result. Commonly, this happens when:
- No `calibration_equation` is configured, **and**
- No `transducer_id` is configured

It can also happen when a configured calibration/transducer pipeline is effectively a passthrough or otherwise produces the same numeric result. In all cases, both columns show the same number.

---

### Amber / yellow — pipeline is transforming the value

```
SIGNAL        VALUE
1.0489...     1.0634...
```

The Signal is amber (`#f59e0b`) when Signal ≠ Value. This means the pipeline has applied at least one transformation — a calibration equation, a transducer mapping, or both. The Signal column shows what the hardware actually measured; the Value column shows the corrected/calibrated reading.

**Example**: a density sensor reads `1.0489` specific gravity. A calibration equation `x + 0.0145` has been configured to compensate for a known sensor offset. The parameter will show:

| Signal | Value |
|---|---|
| `1.0489` | `1.0634` |

---

## Graph view

The same logic applies in the parameter graph:

- Each graph node shows the Value prominently.
- A small `raw` label below the value shows the Signal.
  - **Grey**: passthrough (Signal == Value)
  - **Amber**: pipeline active (Signal ≠ Value)
- The **detail panel** (click a node) shows a "Signal (raw)" row below "Value", coloured the same way.

---

## Why keep both?

- **Audit trail**: you always know what the sensor produced, separate from what calibration did to it.
- **Debugging**: if a calibration equation drifts or a transducer is misconfigured, you can compare Signal vs Value to diagnose the discrepancy instantly without needing logs.
- **Safety**: the pipeline is stateless and deterministic. Signal is the ground truth every cycle; the pipeline cannot accumulate drift because it always starts fresh from the raw reading.
