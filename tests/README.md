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

These tests verify the specialty scheduler-manual ownership flow:

- Scheduler pauses when manual control takes ownership (`ownership_lost`):
  - `tests/test_schedule_navigation_actions.py::test_schedule_runtime_pauses_when_target_ownership_is_lost`

- Scheduler resume reclaims control after manual override is released:
  - `tests/test_schedule_navigation_actions.py::test_resume_after_manual_override_reclaims_control_for_active_step`
  - `tests/test_schedule_service_api_integration.py::test_manual_override_pauses_and_resume_reclaims_live_apis`

- Reclaim fails safely if a non-manual owner still holds the target:
  - `tests/test_schedule_navigation_actions.py::test_resume_fails_when_non_manual_owner_still_holds_target`

- Multi-target ownership in one step:
  - `tests/test_schedule_navigation_actions.py::test_schedule_runtime_tracks_multiple_owned_targets_in_one_step`

## Integration Preconditions

Integration tests automatically skip when services are unreachable. For best results, start:

- Control service (`127.0.0.1:8767`)
- Schedule service (`127.0.0.1:8768`)
- Data service (`127.0.0.1:8769`) for schedule-data tests
- ParameterDB (`127.0.0.1:8765`) for parameter-backed integration tests

## Notes

- Integration tests create temporary parameters where needed and clean them up.
- Route-level tests reset module-level runtime globals via `tests/conftest.py`.