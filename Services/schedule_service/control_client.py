from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter


class ControlClient:
    def __init__(self, base_url: str = 'http://127.0.0.1:8766', timeout_s: float = 5.0) -> None:
        self.base_url = base_url.rstrip('/')
        self.timeout_s = timeout_s
        self._session = requests.Session()
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=50, max_retries=0)
        self._session.mount('http://', adapter)
        self._session.mount('https://', adapter)

    def close(self) -> None:
        self._session.close()

    def request_control(self, target: str, owner: str) -> dict[str, Any]:
        return self._post('/control/request', {'target': target, 'owner': owner})

    def release_control(self, target: str, owner: str) -> dict[str, Any]:
        return self._post('/control/release', {'target': target, 'owner': owner})

    def read(self, target: str) -> dict[str, Any]:
        return self._get(f'/control/read/{target}')

    def write(self, target: str, value: Any, owner: str) -> dict[str, Any]:
        return self._post('/control/write', {'target': target, 'value': value, 'owner': owner})

    def ramp(self, *, target: str, value: Any, duration_s: float, owner: str) -> dict[str, Any]:
        return self._post('/control/ramp', {'target': target, 'value': value, 'duration': duration_s, 'owner': owner})

    def ownership(self) -> dict[str, Any]:
        return self._get('/control/ownership')

    def snapshot(self, targets: list[str] | None = None) -> dict[str, Any]:
        query = ''
        if targets:
            joined = ','.join(targets)
            query = f'?targets={joined}'
        return self._get(f'/system/snapshot{query}')

    def _get(self, path: str) -> dict[str, Any]:
        response = self._session.get(f'{self.base_url}{path}', timeout=self.timeout_s)
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._session.post(f'{self.base_url}{path}', json=payload, timeout=self.timeout_s)
        response.raise_for_status()
        return response.json()
