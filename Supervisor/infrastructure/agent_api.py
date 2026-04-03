from __future__ import annotations

from threading import Thread
from typing import Callable, Any

import requests
from requests.adapters import HTTPAdapter
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
import uvicorn

from Services.parameterDB.parameterdb_core.client import SignalClient


class CreateParamBody(BaseModel):
    name: str
    parameter_type: str
    value: Any = None
    config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SetValueBody(BaseModel):
    value: Any


class UpdateConfigBody(BaseModel):
    config: dict[str, Any]


class UpdateMetadataBody(BaseModel):
    metadata: dict[str, Any]


class CreateSourceBody(BaseModel):
    name: str
    source_type: str
    config: dict[str, Any] = Field(default_factory=dict)


class ImportSnapshotBody(BaseModel):
    snapshot: dict[str, Any]
    replace_existing: bool = True
    save_to_disk: bool = True


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
    update_status_provider: Callable[[bool], dict[str, Any]] | None = None,
    apply_update_action: Callable[[], dict[str, Any]] | None = None,
) -> FastAPI:
    app = FastAPI(title=f"Fermenter Agent {node_name}")

    db_host = '127.0.0.1'
    db_port = 8765
    ds_port = 8766
    db_timeout = 5.0

    def _db() -> SignalClient:
        return SignalClient(db_host, db_port, timeout=db_timeout)

    def _ds() -> SignalClient:
        return SignalClient(db_host, ds_port, timeout=db_timeout)

    def _wrap(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    def _build_graph_payload() -> dict[str, Any]:
        graph = dict(_db().graph_info() or {})
        try:
            raw_sources = _ds().list_sources() or {}
        except Exception:
            raw_sources = {}

        sources: dict[str, dict[str, Any]] = {}
        for source_name, source_record in raw_sources.items():
            record = dict(source_record or {})
            source_type = str(record.get('source_type') or '').strip()
            graph_meta: dict[str, Any] = {}
            if source_type:
                try:
                    ui_spec = _ds().get_source_type_ui(source_type, name=source_name, mode='edit') or {}
                    graph_meta = dict(ui_spec.get('graph') or {})
                except Exception:
                    graph_meta = {}
            sources[source_name] = {
                **record,
                'graph': graph_meta,
            }

        graph['sources'] = sources
        return graph

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

    @app.get('/agent/repo/status')
    def agent_repo_status(force: bool = False) -> dict[str, Any]:
        if update_status_provider is None:
            raise HTTPException(status_code=501, detail='Repo status provider is not configured')
        return {
            'ok': True,
            'status': update_status_provider(bool(force)),
        }

    @app.post('/agent/repo/update')
    def agent_repo_update() -> dict[str, Any]:
        if apply_update_action is None:
            raise HTTPException(status_code=501, detail='Repo update action is not configured')
        result = apply_update_action()
        if not bool(result.get('ok')):
            raise HTTPException(status_code=500, detail=result)
        return {
            'ok': True,
            **result,
        }

    @app.get('/parameterdb/params')
    def list_params() -> dict[str, Any]:
        return {'ok': True, 'params': _wrap(lambda: _db().describe())}

    @app.get('/parameterdb/graph')
    def get_graph() -> dict[str, Any]:
        return {'ok': True, 'graph': _wrap(_build_graph_payload)}

    @app.get('/parameterdb/stats')
    def get_stats() -> dict[str, Any]:
        return {'ok': True, 'stats': _wrap(lambda: _db().stats())}

    @app.get('/parameterdb/snapshot-file')
    def export_snapshot() -> dict[str, Any]:
        exported = _wrap(lambda: _db().export_snapshot())
        return {'ok': True, **exported}

    @app.post('/parameterdb/snapshot-file')
    def import_snapshot(body: ImportSnapshotBody) -> dict[str, Any]:
        imported = _wrap(lambda: _db().import_snapshot(
            body.snapshot,
            replace_existing=body.replace_existing,
            save_to_disk=body.save_to_disk,
        ))
        return {'ok': True, **imported}

    @app.get('/parameterdb/param-types')
    def list_param_types() -> dict[str, Any]:
        return {'ok': True, 'types': _wrap(lambda: _db().list_parameter_type_ui())}

    @app.get('/parameterdb/param-types/{parameter_type}/ui')
    def get_param_type_ui(parameter_type: str) -> dict[str, Any]:
        return {'ok': True, 'ui': _wrap(lambda: _db().get_parameter_type_ui(parameter_type))}

    @app.post('/parameterdb/params')
    def create_param(body: CreateParamBody) -> dict[str, Any]:
        ok = _wrap(lambda: _db().create_parameter(
            body.name,
            body.parameter_type,
            value=body.value,
            config=body.config,
            metadata=body.metadata,
        ))
        if not ok:
            raise HTTPException(status_code=400, detail='create_parameter returned False')
        return {'ok': True}

    @app.put('/parameterdb/params/{name:path}/value')
    def set_value(name: str, body: SetValueBody) -> dict[str, Any]:
        return {'ok': bool(_wrap(lambda: _db().set_value(name, body.value)))}

    @app.put('/parameterdb/params/{name:path}/config')
    def update_config(name: str, body: UpdateConfigBody) -> dict[str, Any]:
        return {'ok': bool(_wrap(lambda: _db().update_config(name, **body.config)))}

    @app.put('/parameterdb/params/{name:path}/metadata')
    def update_metadata(name: str, body: UpdateMetadataBody) -> dict[str, Any]:
        return {'ok': bool(_wrap(lambda: _db().update_metadata(name, **body.metadata)))}

    @app.delete('/parameterdb/params/{name:path}')
    def delete_param(name: str) -> dict[str, Any]:
        return {'ok': bool(_wrap(lambda: _db().delete_parameter(name)))}

    @app.get('/parameterdb/source-types')
    def list_source_types() -> dict[str, Any]:
        return {'ok': True, 'types': _wrap(lambda: _ds().list_source_types_ui())}

    @app.get('/parameterdb/source-types/{source_type}/ui')
    def get_source_type_ui(source_type: str, name: str | None = None, mode: str | None = None) -> dict[str, Any]:
        return {'ok': True, 'ui': _wrap(lambda: _ds().get_source_type_ui(source_type, name=name, mode=mode))}

    @app.get('/parameterdb/sources')
    def list_sources() -> dict[str, Any]:
        return {'ok': True, 'sources': _wrap(lambda: _ds().list_sources())}

    @app.post('/parameterdb/sources')
    def create_source(body: CreateSourceBody) -> dict[str, Any]:
        _wrap(lambda: _ds().create_source(body.name, body.source_type, config=body.config))
        return {'ok': True}

    @app.put('/parameterdb/sources/{name}')
    def update_source(name: str, body: UpdateConfigBody) -> dict[str, Any]:
        _wrap(lambda: _ds().update_source(name, config=body.config))
        return {'ok': True}

    @app.delete('/parameterdb/sources/{name}')
    def delete_source(name: str) -> dict[str, Any]:
        _wrap(lambda: _ds().delete_source(name))
        return {'ok': True}

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
                stream=True,
            )
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        content_type = resp.headers.get('content-type', 'application/json')
        if 'application/json' in content_type:
            try:
                return JSONResponse(status_code=resp.status_code, content=resp.json())
            finally:
                resp.close()

        passthrough_headers = {}
        content_disposition = resp.headers.get('content-disposition')
        if content_disposition:
            passthrough_headers['content-disposition'] = content_disposition
        content_length = resp.headers.get('content-length')
        if content_length:
            passthrough_headers['content-length'] = content_length
        return StreamingResponse(
            resp.iter_content(chunk_size=64 * 1024),
            status_code=resp.status_code,
            media_type=content_type,
            headers=passthrough_headers,
            background=BackgroundTask(resp.close),
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
        update_status_provider: Callable[[bool], dict[str, Any]] | None = None,
        apply_update_action: Callable[[], dict[str, Any]] | None = None,
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
            update_status_provider=update_status_provider,
            apply_update_action=apply_update_action,
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
