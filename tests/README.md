# LabBREW Test Suite

This folder contains unit, API, runtime, and optional live integration tests for LabBREW services.

## Quick Commands

- Run all tests:

```bash
python -m pytest -q
```

- Run with coverage:

```bash
python -m pytest --cov=Services --cov=BrewSupervisor --cov-report=term-missing --cov-report=html -q
```

- Run only integration tests (requires local services):

```bash
python -m pytest -q -m integration
```

## Test Categories

- `test_control_*`: Control API, runtime ownership, ramp, and manual override behavior.
- `test_schedule_*`: Schedule API, runtime navigation/actions/persistence, and integration flows.
- `test_data_*`: Data API and runtime recording/archive behavior.
- `test_parameterdb_*`: ParameterDB store/engine logic and optional live smoke checks.
- `test_brewsupervisor_*`: BrewSupervisor gateway and dashboard route behavior.
- `test_rules_engine.py` / `test_wait_engine.py`: shared condition/wait logic used by services.

## Special Ownership Logic Coverage

## Scenario Service Tests

The Scenario Service is tested through integration tests in:

- `tests/test_scenario_scripted_runner.py` - Tests runner context and execution
- `tests/test_scenario_runtime.py` - Tests package loading and compilation

## Integration Preconditions

Integration tests automatically skip when services are unreachable. For best results, start:

- Control service (`127.0.0.1:8767`)
- Scenario service (`127.0.0.1:8770`)
- Data service (`127.0.0.1:8769`) for scenario-data tests
- ParameterDB (`127.0.0.1:8765`) for parameter-backed integration tests

## Notes

- Integration tests create temporary parameters where needed and clean them up.
- Route-level tests reset module-level runtime globals via `tests/conftest.py`.