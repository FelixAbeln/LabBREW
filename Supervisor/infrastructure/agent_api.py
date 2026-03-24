from __future__ import annotations

from threading import Thread
from typing import Callable, Any

import requests
from requests.adapters import HTTPAdapter
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
import uvicorn


def _build_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=32, pool_maxsize=64, max_retries=0)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


def build_agent_app(
    *,
    node_id: str,
    node_name: str,
    service_map: Callable[[], dict[str, dict[str, Any]]],
    summary_provider: Callable[[], dict[str, Any]],
    proxy_session: requests.Session,
) -> FastAPI:
    app = FastAPI(title=f"Fermenter Agent {node_name}")

    @app.get('/agent/info')
    def agent_info() -> dict[str, Any]:
        return {
            'node_id': node_id,
            'node_name': node_name,
            'services': service_map(),
        }

    @app.get('/agent/services')
    def agent_services() -> dict[str, Any]:
        return service_map()

    @app.get('/agent/summary')
    def agent_summary() -> dict[str, Any]:
        return summary_provider()

    @app.api_route('/proxy/{service_name}/{service_path:path}', methods=['GET', 'POST', 'PUT', 'DELETE'])
    async def proxy(service_name: str, service_path: str, request: Request):
        services = service_map()
        target = services.get(service_name)
        if not target or not target.get('healthy'):
            raise HTTPException(status_code=404, detail=f'service {service_name!r} not available')
        base_url = target['base_url'].rstrip('/')
        url = f"{base_url}/{service_path.lstrip('/')}"
        body = await request.body()
        headers = {k: v for k, v in request.headers.items() if k.lower() != 'host'}
        try:
            resp = proxy_session.request(
                method=request.method,
                url=url,
                params=request.query_params,
                data=body,
                headers=headers,
                timeout=10,
            )
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        content_type = resp.headers.get('content-type', 'application/json')
        if 'application/json' in content_type:
            return JSONResponse(status_code=resp.status_code, content=resp.json())

        passthrough_headers = {}
        content_disposition = resp.headers.get('content-disposition')
        if content_disposition:
            passthrough_headers['content-disposition'] = content_disposition
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=content_type,
            headers=passthrough_headers,
        )

    return app


class AgentApiServer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        node_id: str,
        node_name: str,
        service_map: Callable[[], dict[str, dict[str, Any]]],
        summary_provider: Callable[[], dict[str, Any]],
    ) -> None:
        self.host = host
        self.port = port
        self._proxy_session = _build_session()
        self.app = build_agent_app(
            node_id=node_id,
            node_name=node_name,
            service_map=service_map,
            summary_provider=summary_provider,
            proxy_session=self._proxy_session,
        )
        self._server = uvicorn.Server(uvicorn.Config(self.app, host=self.host, port=self.port, log_level='info'))
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(target=self._server.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._server.should_exit = True
        self._thread.join(timeout=5)
        self._thread = None
        self._proxy_session.close()
