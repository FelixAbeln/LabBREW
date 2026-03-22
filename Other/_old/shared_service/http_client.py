from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import error, request


@dataclass(slots=True)
class ApiClient:
    base_url: str

    def set_base_url(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _decode_response(self, resp) -> dict:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}

    def _request(self, req: request.Request | str, *, timeout: float) -> dict:
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                return self._decode_response(resp)
        except error.HTTPError as exc:
            message = f"HTTP Error {exc.code}: {exc.reason}"
            try:
                payload = self._decode_response(exc)
                if isinstance(payload, dict):
                    message = str(payload.get("message") or payload.get("error") or message)
            except Exception:
                pass
            raise RuntimeError(message) from exc

    def get(self, path: str, *, timeout: float = 2.0) -> dict:
        return self._request(f"{self.base_url}{path}", timeout=timeout)

    def post(self, path: str, payload: dict | None = None, *, timeout: float = 5.0) -> dict:
        data = json.dumps(payload or {}).encode("utf-8")
        req = request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._request(req, timeout=timeout)
