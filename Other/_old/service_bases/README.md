# Service bases

This folder is the first untangling pass.

## Goal

Keep shared concerns in one place and make each service a thin app:

- `apps/scheduler_base` wraps the schedule runtime
- `apps/safety_base` wraps the safety rule engine
- `core/app_server.py` provides a shared JSON HTTP server shell
- `core/cli.py` provides shared CLI flags

## Why this helps

The old code had each service owning its own HTTP server and entrypoint wiring.
That tends to drift and creates copy/paste architecture.

This base layer is intentionally small:

- no heavy framework migration
- no runtime logic rewrite yet
- route registration is now composable
- both services can live in the same tree without sibling cross-import spaghetti

## Next refactor targets

1. Move schedule operator evaluation onto `shared_service/operators.py`
2. Add a policy hook before backend writes in `schedule_service/runtime.py`
3. Split `FcsRuntimeService` into smaller runtime/state/execution pieces
4. Move shared HTTP response helpers out of legacy `http_api.py`
