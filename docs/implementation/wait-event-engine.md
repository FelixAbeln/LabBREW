# Wait Event Engine

This document defines the event-layer extensions added on top of the shared wait engine.

The goal is to support event-driven transitions (edge detection) while staying compatible
with existing `elapsed`, `cond`, `all`, and `any` wait behavior.

## Scope

The event layer is implemented in the shared wait stack and therefore applies to:

- scheduler runtime step waits
- schedule Excel `wait` expressions
- ParameterDB `condition` plugin expressions

No existing syntax was removed.

## New DSL forms

### Rising edge

```
rising(expr)
```

Matches once when `expr` transitions from false to true.

### Falling edge

```
falling(expr)
```

Matches once when `expr` transitions from true to false.

### Pulse window

```
pulse(expr;hold_seconds)
```

Starts on the rising edge of `expr`, then remains matched for `hold_seconds`.

## Payload schema

The parsed payload form is:

```json
{
  "kind": "rising" | "falling" | "pulse",
  "child": { ...wait expression payload... },
  "hold_s": 10.0
}
```

Notes:

- `child` is required for all event kinds.
- `hold_s` is required for `pulse` and ignored for `rising`/`falling`.

## Runtime semantics

Event state is tracked per wait-node path inside `WaitState.event_nodes`.

Each node stores:

- `previous_child_matched`
- `pulse_started_monotonic`

This keeps event evaluation deterministic across scan cycles without breaking existing
condition-hold state (`WaitState.condition_state`).

## Scheduler and loadstep integration

The scheduler runtime now supports event waits directly in step `wait` payloads.

Important behavior for one-shot waits (`rising`, `falling`):

- once the edge matches and a `before_next` loadstep is started,
- scheduler keeps polling pending exit loadsteps,
- even if subsequent scans no longer match the one-shot edge condition.

This prevents stalls where the first edge starts a loadstep but later ticks would otherwise
stop checking completion.

## Validation

Schedule validation now accepts event wait kinds and enforces:

- `MISSING_WAIT_CHILD` when `child` is missing
- `MISSING_PULSE_HOLD_SECONDS` when `pulse.hold_s` is missing
- `INVALID_PULSE_HOLD_SECONDS` when `pulse.hold_s` is non-numeric or negative

## Suggested usage patterns

1. Manual acknowledgment edge:

```text
rising(cond:operator.next:==:true)
```

2. Timeout or event:

```text
any(elapsed:900;rising(cond:operator.next:==:true))
```

3. Event plus fixed capture window:

```text
pulse(cond:phase.started:==:true;30)
```

4. Event-gated loadstep transition:

- step wait uses `rising(...)`
- step has `take_loadstep` with `timing=before_next`
- scheduler waits for loadstep completion before advancing

5. Triggered loadstep during a step:

- `take_loadstep` action uses `params.timing = on_trigger`
- `params.trigger_wait` contains any wait expression (`cond`, `all`, `any`, `rising`, `falling`, `pulse`)
- default duration can be supplied by `measurement_config.loadstep_duration_seconds`
