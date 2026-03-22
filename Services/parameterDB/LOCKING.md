# ParameterDB Locking and Concurrency Policy

## Goals

Keep the concurrency model small, predictable, and easy to audit.

## Locks and owners

### `ParameterStore._lock`
Owns:
- parameter dictionary membership
- parameter mutation through store methods
- store revision counter
- broker attachment

Rules:
- do not hold this lock during socket or queue I/O
- public store methods return copies/snapshots only
- live runtime parameter objects are only exposed through internal underscore methods

### `ScanEngine._graph_lock`
Owns:
- cached dependency graph
- scan order
- graph warnings and dependency maps

Rules:
- graph rebuild uses a snapshot of runtime parameters from the store
- do not hold graph lock while sleeping or doing network I/O

### `ScanEngine._state_lock`
Owns:
- running flag
- scan thread lifecycle
- cycle counter
- last-scan timing fields

Rules:
- keep critical sections short
- do not call store methods while holding state lock unless the call is guaranteed not to block

### `EventBroker._lock`
Owns:
- subscription registry
- per-subscription metadata

Rules:
- take a snapshot of subscribers under lock
- release the lock before queue fanout work
- slow subscribers must not block publishers

## Eventing rules

- the store emits events after mutations, outside the main mutation critical section
- the event broker owns subscriber queues and overflow policy
- subscriber queues are bounded
- overflow policy is: drop oldest, emit overflow notice, then enqueue newest
- if a subscriber still cannot accept events, disconnect it

## Network I/O rules

- never hold store, graph, or broker locks while blocking on socket writes
- subscription streaming reads from a subscriber queue and writes to the socket without holding global runtime locks

## Runtime mutation rules

- service API code uses snapshot-returning store methods by default
- engine scan loop is the narrow internal path allowed to use runtime parameter objects
- delete lifecycle uses the internal runtime remove path so `on_removed()` can still run

## Thread model

Current threads:
- TCP request handler threads
- one scan engine thread
- source runner threads/processes outside the service
- subscriber queue consumers inside request handler threads

This model is acceptable for light to moderate use as long as queue bounds and lock ownership rules are followed.
