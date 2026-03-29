from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter


class HttpServiceProxy:
    def __init__(self, timeout_s: float = 8.0, pool_connections: int = 32, pool_maxsize: int = 64) -> None:
        self.timeout_s = timeout_s
        self._session = requests.Session()
        adapter = HTTPAdapter(pool_connections=pool_connections, pool_maxsize=pool_maxsize, max_retries=0)
        self._session.mount('http://', adapter)
        self._session.mount('https://', adapter)

    def request(
        self,
        *,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        data_body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        request_kwargs: dict[str, Any] = {
            'method': method.upper(),
            'url': url,
            'params': params,
            'timeout': self.timeout_s,
        }
        if data_body is not None:
            request_kwargs['data'] = data_body
            if headers:
                request_kwargs['headers'] = headers
        else:
            request_kwargs['json'] = json_body

        response = self._session.request(**request_kwargs)
        content_type = response.headers.get('content-type', '')
        if 'application/json' in content_type:
            payload: Any = response.json()
        else:
            payload = {'text': response.text}
        return response.status_code, payload

    def request_raw(
        self,
        *,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        data_body: bytes | None = None,
        headers: dict[str, str] | None = None,
        stream: bool = False,
    ) -> requests.Response:
        request_kwargs: dict[str, Any] = {
            'method': method.upper(),
            'url': url,
            'params': params,
            'timeout': self.timeout_s,
            'stream': stream,
        }
        if data_body is not None:
            request_kwargs['data'] = data_body
            if headers:
                request_kwargs['headers'] = headers
        else:
            request_kwargs['json'] = json_body

        return self._session.request(**request_kwargs)

    def close(self) -> None:
        self._session.close()
