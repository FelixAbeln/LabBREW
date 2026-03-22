from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter


class DataClient:
    def __init__(self, base_url: str = 'http://127.0.0.1:8769', timeout_s: float = 8.0) -> None:
        self.base_url = base_url.rstrip('/')
        self.timeout_s = timeout_s
        self._session = requests.Session()
        # Keep a bounded reusable connection pool for all scheduler->data-service traffic.
        adapter = HTTPAdapter(pool_connections=16, pool_maxsize=16, max_retries=0, pool_block=True)
        self._session.mount('http://', adapter)
        self._session.mount('https://', adapter)
        self._session.headers.update({'Connection': 'keep-alive'})

    def close(self) -> None:
        self._session.close()

    def setup_measurement(
        self,
        *,
        parameters: list[str],
        hz: float = 10.0,
        output_dir: str = 'data/measurements',
        output_format: str = 'parquet',
        session_name: str = '',
    ) -> dict[str, Any]:
        return self._post(
            '/measurement/setup',
            {
                'parameters': parameters,
                'hz': hz,
                'output_dir': output_dir,
                'output_format': output_format,
                'session_name': session_name,
            },
        )

    def measure_start(self) -> dict[str, Any]:
        return self._post('/measurement/start', {})

    def measure_stop(self) -> dict[str, Any]:
        return self._post('/measurement/stop', {})

    def take_loadstep(
        self,
        *,
        duration_seconds: float = 30.0,
        loadstep_name: str = '',
        parameters: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'duration_seconds': duration_seconds,
            'loadstep_name': loadstep_name,
        }
        if parameters is not None:
            payload['parameters'] = parameters
        return self._post('/loadstep/take', payload)

    def status(self) -> dict[str, Any]:
        return self._get('/status')

    def _get(self, path: str) -> dict[str, Any]:
        response = self._session.get(f'{self.base_url}{path}', timeout=self.timeout_s)
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._session.post(f'{self.base_url}{path}', json=payload, timeout=self.timeout_s)
        response.raise_for_status()
        return response.json()
