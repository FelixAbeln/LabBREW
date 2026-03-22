from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from typing import Any

import requests


class TestFailure(AssertionError):
    pass


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise TestFailure(message)


def wait_until(predicate, *, timeout_s: float, label: str, sleep_s: float = 0.2):
    deadline = time.time() + timeout_s
    last_value = None
    while time.time() < deadline:
        last_value = predicate()
        if last_value:
            return last_value
        time.sleep(sleep_s)
    raise TestFailure(f"Timeout waiting for {label}. Last value: {last_value}")


class Api:
    def __init__(self, schedule_base: str, data_base: str, timeout_s: float = 6.0) -> None:
        self.schedule_base = schedule_base.rstrip('/')
        self.data_base = data_base.rstrip('/')
        self.timeout_s = timeout_s

    def _get(self, base: str, path: str) -> dict[str, Any]:
        resp = requests.get(f"{base}{path}", timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json()

    def _post(self, base: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = requests.post(f"{base}{path}", json=(payload or {}), timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json()

    def _put(self, base: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = requests.put(f"{base}{path}", json=payload, timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, base: str, path: str) -> dict[str, Any]:
        resp = requests.delete(f"{base}{path}", timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json()

    def schedule_get(self, path: str) -> dict[str, Any]:
        return self._get(self.schedule_base, path)

    def schedule_post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._post(self.schedule_base, path, payload)

    def schedule_put(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._put(self.schedule_base, path, payload)

    def schedule_delete(self, path: str) -> dict[str, Any]:
        return self._delete(self.schedule_base, path)

    def data_get(self, path: str) -> dict[str, Any]:
        return self._get(self.data_base, path)

    def data_post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._post(self.data_base, path, payload)


def build_schedule(schedule_id: str) -> dict[str, Any]:
    return {
        'id': schedule_id,
        'name': 'Schedule Data Actions Test',
        'setup_steps': [
            {
                'id': 'setup-1',
                'name': 'Start global measurement',
                'enabled': True,
                'actions': [
                    {
                        'kind': 'global_measurement',
                        'value': 'start',
                        'params': {
                            'hz': 10.0,
                            'output_format': 'jsonl',
                            'output_dir': 'data/measurements',
                        },
                    }
                ],
                'wait': {'kind': 'elapsed', 'duration_s': 0.4},
            }
        ],
        'plan_steps': [
            {
                'id': 'plan-1',
                'name': 'Take loadstep',
                'enabled': True,
                'actions': [
                    {
                        'kind': 'take_loadstep',
                        'duration_s': 2.0,
                        'params': {},
                    }
                ],
                'wait': {'kind': 'elapsed', 'duration_s': 2.5},
            },
            {
                'id': 'plan-2',
                'name': 'Stop global measurement',
                'enabled': True,
                'actions': [
                    {
                        'kind': 'global_measurement',
                        'value': 'stop',
                        'params': {},
                    }
                ],
                'wait': {'kind': 'elapsed', 'duration_s': 0.2},
            },
        ],
    }


def hard_reset(api: Api) -> None:
    try:
        api.schedule_post('/schedule/stop')
    except Exception:
        pass
    try:
        api.schedule_delete('/schedule')
    except Exception:
        pass

    # Best-effort cleanup in case data recording was left active by a previous run.
    try:
        api.data_post('/measurement/stop')
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description='Integration test for schedule_service + data_service actions')
    parser.add_argument('--schedule-base', default='http://127.0.0.1:8768')
    parser.add_argument('--data-base', default='http://127.0.0.1:8769')
    args = parser.parse_args()

    api = Api(schedule_base=args.schedule_base, data_base=args.data_base)
    schedule_id = f'schedule-data-actions-{utc_stamp()}'

    print('=== SCHEDULE + DATA ACTIONS TEST START ===')
    print(f'schedule_base={args.schedule_base} data_base={args.data_base}')

    try:
        print('\n[1] Service health checks')
        data_health = api.data_get('/health')
        schedule_status = api.schedule_get('/schedule/status')
        expect('status' in data_health, f'Unexpected data health payload: {data_health}')
        expect('state' in schedule_status, f'Unexpected schedule status payload: {schedule_status}')
        print('PASS: services reachable')

        print('\n[2] Reset state and load schedule')
        hard_reset(api)
        load_result = api.schedule_put('/schedule', build_schedule(schedule_id))
        expect(load_result.get('ok') is True, f'Expected ok=true when loading schedule, got: {load_result}')
        print('PASS: schedule loaded')

        print('\n[3] Start run and assert measurement starts')
        start_result = api.schedule_post('/schedule/start')
        expect(start_result.get('ok') is True, f'Expected start ok=true, got: {start_result}')

        wait_until(
            lambda: api.data_get('/status') if api.data_get('/status').get('recording') else None,
            timeout_s=8.0,
            label='data recording started',
        )
        print('PASS: global measurement started by scheduler')

        print('\n[4] Assert loadstep was triggered and completed')
        wait_until(
            lambda: api.data_get('/status') if (api.data_get('/status').get('active_loadsteps') or []) else None,
            timeout_s=8.0,
            label='loadstep became active',
        )

        status_after_loadstep = wait_until(
            lambda: api.data_get('/status') if int(api.data_get('/status').get('completed_loadsteps_count', 0)) >= 1 else None,
            timeout_s=12.0,
            label='loadstep completed',
        )
        print(f"PASS: loadstep completed count={status_after_loadstep.get('completed_loadsteps_count')}")

        print('\n[5] Assert scheduler stopped measurement and run completed')
        wait_until(
            lambda: api.data_get('/status') if not api.data_get('/status').get('recording') else None,
            timeout_s=12.0,
            label='data recording stopped',
        )

        final_schedule = wait_until(
            lambda: api.schedule_get('/schedule/status') if api.schedule_get('/schedule/status').get('state') == 'completed' else None,
            timeout_s=12.0,
            label='schedule completed',
        )

        event_log = final_schedule.get('event_log', [])
        expect(any('Start global measurement' in entry for entry in event_log), 'Missing setup step event in schedule log')
        expect(any('Take loadstep' in entry for entry in event_log), 'Missing loadstep step event in schedule log')
        expect(any('Stop global measurement' in entry for entry in event_log), 'Missing stop step event in schedule log')
        print('PASS: scheduler completed and event log contains expected steps')

        print('\n=== ALL TESTS PASSED ===')
        return 0

    except TestFailure as exc:
        print(f'\nTEST FAILURE: {exc}')
        return 1
    except requests.RequestException as exc:
        print(f'\nHTTP FAILURE: {exc}')
        return 2
    except Exception as exc:
        print(f'\nUNEXPECTED FAILURE: {exc}')
        print(json.dumps({'type': type(exc).__name__}, indent=2))
        return 3
    finally:
        # Keep this test idempotent.
        hard_reset(api)


if __name__ == '__main__':
    raise SystemExit(main())
