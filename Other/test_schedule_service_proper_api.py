from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

BASE = 'http://127.0.0.1:8768'
CONTROL = 'http://127.0.0.1:8767'
TARGET = 'test'
STATE_FILE = Path(__file__).resolve().parent / 'state' / 'schedule_state.json'


class TestFailure(AssertionError):
    pass


def get(path: str) -> dict[str, Any]:
    response = requests.get(f'{BASE}{path}', timeout=5)
    response.raise_for_status()
    return response.json()


def put(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.put(f'{BASE}{path}', json=payload, timeout=5)
    response.raise_for_status()
    return response.json()


def post(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.post(f'{BASE}{path}', json=payload or {}, timeout=5)
    response.raise_for_status()
    return response.json()


def delete(path: str) -> dict[str, Any]:
    response = requests.delete(f'{BASE}{path}', timeout=5)
    response.raise_for_status()
    return response.json()
def clear_schedule_if_present():
    try:
        post_json("/schedule/stop")
    except Exception:
        pass
    try:
        delete_json("/schedule")
    except Exception:
        pass

def control_read() -> dict[str, Any]:
    response = requests.get(f'{CONTROL}/control/read/{TARGET}', timeout=5)
    response.raise_for_status()
    return response.json()


def status() -> dict[str, Any]:
    return get('/schedule/status')


def state_payload() -> dict[str, Any]:
    if not STATE_FILE.exists():
        raise TestFailure(f'Expected persistence file at {STATE_FILE}')
    return json.loads(STATE_FILE.read_text(encoding='utf-8'))


def line(prefix: str = '') -> str:
    s = status()
    r = control_read()
    return (
        f"{prefix}state={s['state']:<9} phase={s['phase']:<5} "
        f"step={s['current_step_name']!r:<36} value={r.get('value')!r:<10} "
        f"owner={r.get('current_owner')!r:<18} wait={s['wait_message']!r}"
    )


def print_status(prefix: str = '') -> None:
    print(line(prefix))


def wait_until(predicate, timeout_s: float, sleep_s: float = 0.2, label: str = 'condition'):
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = status()
        if predicate(last):
            return last
        time.sleep(sleep_s)
    raise TestFailure(f'Timeout waiting for {label}. Last status:\n{json.dumps(last, indent=2)}')


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise TestFailure(message)


# ---------- schedules ----------

def build_main_schedule() -> dict[str, Any]:
    return {
        'id': 'proper-api-test-plan',
        'name': 'Proper API test plan',
        'setup_steps': [
            {
                'id': 'setup-1',
                'name': 'Request control of test',
                'actions': [
                ],
            }
        ],
        'plan_steps': [
            {
                'id': 'plan-1',
                'name': 'Write zero then ramp to 10 over 4 seconds',
                'actions': [
                    {'kind': 'write', 'target': TARGET, 'value': 0},
                    {'kind': 'ramp', 'target': TARGET, 'value': 10, 'duration_s': 4.0},
                ],
                'wait': {
                    'kind': 'condition',
                    'condition': {
                        'source': TARGET,
                        'operator': '>=',
                        'threshold': 9.8,
                        'for_s': 0.5,
                    },
                },
            },
            {
                'id': 'plan-2',
                'name': 'Wait 5 seconds before next ramp',
                'actions': [],
                'wait': {'kind': 'elapsed', 'duration_s': 5.0},
            },
            {
                'id': 'plan-3',
                'name': 'Ramp to 20 over 4 seconds',
                'actions': [
                    {'kind': 'ramp', 'target': TARGET, 'value': 20, 'duration_s': 4.0},
                ],
                'wait': {
                    'kind': 'condition',
                    'condition': {
                        'source': TARGET,
                        'operator': '>=',
                        'threshold': 19.8,
                        'for_s': 0.5,
                    },
                },
            },
        ],
    }


def build_other_schedule() -> dict[str, Any]:
    return {
        'id': 'reset-check-plan',
        'name': 'Reset Check Plan',
        'setup_steps': [],
        'plan_steps': [
            {
                'id': 'plan-1',
                'name': 'Wait shortly',
                'actions': [],
                'wait': {'kind': 'elapsed', 'duration_s': 1.0},
            }
        ],
    }


# ---------- helpers ----------

def hard_reset() -> None:
    try:
        post('/schedule/stop')
    except Exception:
        pass
    try:
        delete('/schedule')
    except Exception:
        pass
    time.sleep(0.4)


def wait_for_step(step_name: str, timeout_s: float = 8.0) -> dict[str, Any]:
    return wait_until(lambda s: s['current_step_name'] == step_name, timeout_s, label=f'step {step_name!r}')


def wait_for_state(state_name: str, timeout_s: float = 20.0) -> dict[str, Any]:
    return wait_until(lambda s: s['state'] == state_name, timeout_s, label=f'state {state_name!r}')


# ---------- tests ----------

def test_empty_state() -> None:
    print('\n[1] Empty-state checks')
    hard_reset()
    sched = get('/schedule')
    stat = status()
    expect(sched['schedule'] is None, 'Expected no schedule loaded')
    expect(stat['state'] in {'idle', 'stopped'}, 'Expected idle-like state after reset')
    print('PASS: empty state')


def test_crud_and_event_log_reset() -> None:
    print('\n[2] PUT/GET/DELETE schedule and event-log reset')
    hard_reset()

    put('/schedule', build_main_schedule())
    sched = get('/schedule')
    stat = status()
    expect(sched['schedule']['id'] == 'proper-api-test-plan', 'Wrong schedule returned after load')
    expect(stat['event_log'] == ['Loaded schedule Proper API test plan'], 'Event log should reset on load')

    delete('/schedule')
    stat = status()
    expect(stat['state'] == 'idle', 'Expected idle after clear schedule')
    expect(stat['event_log'] == ['Schedule cleared'], 'Event log should reset on clear')

    put('/schedule', build_other_schedule())
    stat = status()
    expect(stat['event_log'] == ['Loaded schedule Reset Check Plan'], 'Event log should reset on second load')
    print('PASS: put/get/delete and event-log reset')


def test_start_pause_resume_stop_and_persistence() -> None:
    print('\n[3] START/PAUSE/RESUME/STOP/STATUS + persistence')
    hard_reset()
    put('/schedule', build_main_schedule())

    start = post('/schedule/start')
    expect(start['ok'] is True, f'Expected start ok, got {start}')
    running = wait_for_state('running', timeout_s=3.0)
    print_status('  running: ')
    expect(running['phase'] == 'setup', 'Expected setup right after start')

    paused = post('/schedule/pause')
    expect(paused['ok'] is True, f'Expected pause ok, got {paused}')
    stat = status()
    print_status('   paused: ')
    expect(stat['state'] == 'paused', 'Expected paused state')
    expect(stat['pause_reason'] == 'manual', 'Expected manual pause reason')

    persisted = state_payload()
    expected_keys = {
        'schedule', 'state', 'phase', 'current_step_index', 'step_started_at_utc',
        'pause_reason', 'owned_targets', 'last_action_result', 'event_log'
    }
    expect(set(persisted.keys()) == expected_keys, f'Persistence keys mismatch: {persisted.keys()}')
    expect(persisted['schedule']['id'] == 'proper-api-test-plan', 'Persisted schedule id mismatch')
    expect(persisted['state'] == 'paused', 'Persisted state should be paused')
    expect(persisted['phase'] == 'setup', 'Persisted phase should be setup')
    expect(persisted['current_step_index'] == 0, 'Persisted step index should be 0 in setup')
    expect(persisted['pause_reason'] == 'manual', 'Persisted pause reason should be manual')

    resumed = post('/schedule/resume')
    expect(resumed['ok'] is True, f'Expected resume ok, got {resumed}')
    stat = wait_for_state('running', timeout_s=3.0)
    print_status('  resumed: ')
    expect(stat['wait_message'] != 'Paused manually', 'Resume should refresh wait message')

    stopped = post('/schedule/stop')
    expect(stopped['ok'] is True, f'Expected stop ok, got {stopped}')
    stat = wait_for_state('stopped', timeout_s=3.0)
    print_status('  stopped: ')
    read = control_read()
    expect(read.get('current_owner') is None, 'Ownership should be cleared on stop')
    print('PASS: start/pause/resume/stop/status + persistence')


def test_next_previous_controls() -> None:
    print('\n[4] NEXT/PREVIOUS controls')

    hard_reset()
    put('/schedule', build_main_schedule())

    post('/schedule/start')
    time.sleep(0.4)
    post('/schedule/pause')

    status0 = status()
    print('   paused:', line())

    pos0 = (
        status0['phase'],
        status0['current_step_index'],
        status0['current_step_name'],
    )

    # ---- next 1 ----
    resp1 = post('/schedule/next')
    expect(resp1.get('ok') is True, f'Next should succeed, got {resp1}')
    status1 = status()
    print('     next:', line())

    pos1 = (
        status1['phase'],
        status1['current_step_index'],
        status1['current_step_name'],
    )
    expect(pos1 != pos0, 'Next should move to a different step')

    # ---- next 2 ----
    resp2 = post('/schedule/next')
    expect(resp2.get('ok') is True, f'Second next should succeed, got {resp2}')
    status2 = status()
    print('     next:', line())

    pos2 = (
        status2['phase'],
        status2['current_step_index'],
        status2['current_step_name'],
    )
    expect(pos2 != pos1, 'Second next should move again')

    # ---- previous ----
    resp3 = post('/schedule/previous')
    expect(resp3.get('ok') is True, f'Previous should succeed, got {resp3}')
    status3 = status()
    print(' previous:', line())

    pos3 = (
        status3['phase'],
        status3['current_step_index'],
        status3['current_step_name'],
    )
    expect(pos3 == pos1, 'Previous should move back one step')

    # ---- walk back to first ----
    seen = {pos3}
    while True:
        current = status()
        current_pos = (
            current['phase'],
            current['current_step_index'],
            current['current_step_name'],
        )

        resp = post('/schedule/previous')
        if not resp.get('ok'):
            break

        after = status()
        after_pos = (
            after['phase'],
            after['current_step_index'],
            after['current_step_name'],
        )

        print(' previous:', line())

        expect(after_pos != current_pos, 'Previous should change position')
        expect(after_pos not in seen, 'Previous should keep moving toward first step')
        seen.add(after_pos)

    # final previous should fail
    resp_final = post('/schedule/previous')
    expect(resp_final.get('ok') is False, 'Previous should fail at first step')

    # resume should still work
    resp_resume = post('/schedule/resume')
    expect(resp_resume.get('ok') is True, 'Resume should succeed after navigation')

    print_status('  resumed: ')

    hard_reset()
    print('PASS: next/previous controls')

def test_happy_path_completion() -> None:
    print('\n[5] Full happy-path execution')
    hard_reset()
    put('/schedule', build_main_schedule())
    post('/schedule/start')

    saw_elapsed_step = False
    saw_elapsed_progress = False
    deadline = time.time() + 25.0
    while time.time() < deadline:
        stat = status()
        print('   tick -> ' + line())
        if stat['state'] == 'faulted':
            raise TestFailure('Schedule faulted unexpectedly:\n' + json.dumps(stat, indent=2))
        if stat['current_step_name'] == 'Wait 5 seconds before next ramp':
            saw_elapsed_step = True
            if 'elapsed' in stat['wait_message'].lower():
                saw_elapsed_progress = True
        if stat['state'] == 'completed':
            break
        time.sleep(0.6)
    else:
        raise TestFailure('Timed out waiting for completion')

    expect(saw_elapsed_step, 'Elapsed wait step was never reached')
    # allow one transition snapshot, but require elapsed progress to show at least once before completion
    expect(saw_elapsed_progress, 'Elapsed wait step never reported elapsed progress')

    final_stat = status()
    final_read = control_read()
    print('  final control read:', json.dumps(final_read, indent=2))
    expect(final_stat['state'] == 'completed', 'Expected completed state at end of happy path')
    expect(final_read.get('current_owner') is None, 'Ownership should be released on completion')
    expect(abs(float(final_read.get('value', 0.0)) - 20.0) < 0.5, 'Expected final test value near 20.0')
    print('PASS: happy path execution')


def test_stop_mid_run() -> None:
    print('\n[6] Stop mid-run')
    hard_reset()
    put('/schedule', build_main_schedule())
    post('/schedule/start')
    wait_for_step('Write zero then ramp to 10 over 4 seconds', timeout_s=5.0)
    print_status(' pre-stop: ')
    stop_result = post('/schedule/stop')
    expect(stop_result['ok'] is True, f'Expected stop ok, got {stop_result}')
    stat = wait_for_state('stopped', timeout_s=3.0)
    print_status('post-stop: ')
    read = control_read()
    expect(read.get('current_owner') is None, 'Stop should clear ownership')
    expect(stat['phase'] == 'idle', 'Stop should return phase to idle')
    print('PASS: stop mid-run')


def main() -> int:
    tests = [
        test_empty_state,
        test_crud_and_event_log_reset,
        test_start_pause_resume_stop_and_persistence,
        test_next_previous_controls,
        test_happy_path_completion,
        test_stop_mid_run,
    ]

    print('=== SCHEDULE SERVICE PROPER API TEST START ===')
    failures: list[str] = []

    for test in tests:
        try:
            test()
        except Exception as exc:
            failures.append(f'- {test.__name__}: {exc}')
            print(f'FAIL: {test.__name__}\n      {exc}')

    print('\n=== FINAL STATUS SNAPSHOT ===')
    try:
        print(json.dumps(status(), indent=2))
    except Exception as exc:
        print(f'Could not read final status: {exc}')

    print('\n=== TEST SUMMARY ===')
    if failures:
        for failure in failures:
            print(failure)
        print(f'\nFAILED: {len(failures)} test group(s)')
        return 1

    print('All test groups passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
