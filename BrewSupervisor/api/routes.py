from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
import requests
from fastapi.responses import JSONResponse

from .models import FermenterView
from .schedule_import.parser import parse_schedule_workbook
from .schedule_import.validator import validate_schedule_payload


def _read_json_response(proxy: Any, *, method: str, url: str, params: dict[str, Any] | None = None, json_body: Any = None) -> tuple[int, Any]:
    try:
        return proxy.request(method=method, url=url, params=params, json_body=json_body)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f'Upstream request failed: {exc}') from exc


def _read_best_effort(proxy: Any, *, method: str, url: str, params: dict[str, Any] | None = None, json_body: Any = None) -> tuple[int | None, Any]:
    try:
        return proxy.request(method=method, url=url, params=params, json_body=json_body)
    except requests.RequestException as exc:
        return None, {'ok': False, 'detail': str(exc)}


def _to_view(node: Any) -> FermenterView:
    return FermenterView(
        id=node.id,
        name=node.name,
        address=node.address,
        host=node.host,
        online=node.online,
        agent_base_url=node.agent_base_url,
        services_hint=node.services_hint,
        services=node.services,
        summary=node.summary,
        last_error=node.last_error,
    )


def _build_agent_proxy_url(node: Any, suffix: str) -> str:
    suffix = suffix if suffix.startswith('/') else f'/{suffix}'
    return f"{node.agent_base_url}{suffix}"


def _build_service_proxy_url(node: Any, service_name: str, suffix: str = '') -> str:
    suffix = suffix.lstrip('/')
    url = f"{node.agent_base_url}/proxy/{service_name}"
    if suffix:
        url += f"/{suffix}"
    return url


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get('/health')
    def health() -> dict[str, str]:
        return {'ok': 'true'}

    @router.get('/fermenters', response_model=list[FermenterView])
    def list_fermenters(request: Request):
        registry = request.app.state.registry
        return [_to_view(node) for node in registry.snapshot()]

    @router.get('/fermenters/{fermenter_id}', response_model=FermenterView)
    def get_fermenter(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail='Fermenter not found')
        return _to_view(node)

    @router.get('/fermenters/{fermenter_id}/agent/info')
    def get_agent_info(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail='Fermenter not found')
        status_code, payload = _read_json_response(proxy, method='GET', url=_build_agent_proxy_url(node, '/agent/info'))
        return JSONResponse(status_code=status_code, content=payload)

    @router.get('/fermenters/{fermenter_id}/agent/services')
    def get_agent_services(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail='Fermenter not found')
        status_code, payload = _read_json_response(proxy, method='GET', url=_build_agent_proxy_url(node, '/agent/services'))
        return JSONResponse(status_code=status_code, content=payload)

    @router.get('/fermenters/{fermenter_id}/summary')
    def get_summary(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail='Fermenter not found')
        status_code, payload = _read_json_response(proxy, method='GET', url=_build_agent_proxy_url(node, '/agent/summary'))
        return JSONResponse(status_code=status_code, content=payload)

    async def _proxy_via_agent(request: Request, fermenter_id: str, service_name: str, service_path: str = ''):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail='Fermenter not found')
        body = None
        if request.method in {'POST', 'PUT', 'PATCH'}:
            try:
                body = await request.json()
            except Exception:
                body = None
        status_code, payload = _read_json_response(
            proxy,
            method=request.method,
            url=_build_service_proxy_url(node, service_name, service_path),
            params=dict(request.query_params),
            json_body=body,
        )
        return JSONResponse(status_code=status_code, content=payload)

    @router.put('/fermenters/{fermenter_id}/schedule/validate-import')
    async def validate_schedule_import(fermenter_id: str, request: Request, file: UploadFile = File(...)):
        registry = request.app.state.registry
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail='Fermenter not found')

        payload = parse_schedule_workbook(await file.read(), filename=file.filename or 'schedule.xlsx')
        result = validate_schedule_payload(payload)
        return {
            'ok': result['valid'],
            'valid': result['valid'],
            'errors': result['errors'],
            'warnings': result['warnings'],
            'schedule': payload,
            'summary': {
                'setup_step_count': len(payload.get('setup_steps', [])),
                'plan_step_count': len(payload.get('plan_steps', [])),
            },
        }

    @router.put('/fermenters/{fermenter_id}/schedule/import')
    async def import_schedule(fermenter_id: str, request: Request, file: UploadFile = File(...)):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail='Fermenter not found')

        payload = parse_schedule_workbook(await file.read(), filename=file.filename or 'schedule.xlsx')
        result = validate_schedule_payload(payload)
        if not result['valid']:
            return JSONResponse(status_code=422, content={
                'ok': False,
                'valid': False,
                'errors': result['errors'],
                'warnings': result['warnings'],
                'schedule': payload,
            })

        status_code, forwarded = _read_json_response(
            proxy,
            method='PUT',
            url=_build_service_proxy_url(node, 'schedule_service', 'schedule'),
            json_body=payload,
        )
        return JSONResponse(status_code=status_code, content={
            'ok': 200 <= status_code < 300,
            'valid': True,
            'errors': [],
            'warnings': result['warnings'],
            'schedule': payload,
            'forwarded': forwarded,
        })

    @router.get('/fermenters/{fermenter_id}/dashboard')
    def get_dashboard(fermenter_id: str, request: Request):
        registry = request.app.state.registry
        proxy = request.app.state.proxy
        node = registry.get_node(fermenter_id)
        if node is None:
            raise HTTPException(status_code=404, detail='Fermenter not found')

        status_code, schedule_status = _read_best_effort(
            proxy,
            method='GET',
            url=_build_service_proxy_url(node, 'schedule_service', 'schedule/status'),
        )
        schedule = schedule_status if status_code and 200 <= status_code < 300 and isinstance(schedule_status, dict) else None

        schedule_definition: Any = None
        status_code, schedule_payload = _read_best_effort(
            proxy,
            method='GET',
            url=_build_service_proxy_url(node, 'schedule_service', 'schedule'),
        )
        if status_code and 200 <= status_code < 300 and isinstance(schedule_payload, dict):
            schedule_definition = schedule_payload.get('schedule')

        owned_target_values: list[dict[str, Any]] = []
        for target in schedule.get('owned_targets', []) if isinstance(schedule, dict) else []:
            target_status, target_payload = _read_best_effort(
                proxy,
                method='GET',
                url=_build_service_proxy_url(node, 'control_service', f'control/read/{target}'),
            )
            if target_status and 200 <= target_status < 300 and isinstance(target_payload, dict):
                owned_target_values.append({
                    'target': target,
                    'ok': bool(target_payload.get('ok')),
                    'value': target_payload.get('value', '-'),
                    'owner': target_payload.get('current_owner'),
                })
            else:
                detail = target_payload.get('detail') if isinstance(target_payload, dict) else None
                owned_target_values.append({
                    'target': target,
                    'ok': False,
                    'value': 'read failed',
                    'owner': None,
                    'detail': detail,
                })

        return {
            'fermenter': _to_view(node).model_dump(),
            'schedule': schedule,
            'schedule_definition': schedule_definition,
            'owned_target_values': owned_target_values,
        }

    @router.api_route('/fermenters/{fermenter_id}/services/{service_name}/{service_path:path}', methods=['GET', 'POST', 'PUT', 'DELETE'])
    @router.api_route('/fermenters/{fermenter_id}/services/{service_name}', methods=['GET', 'POST', 'PUT', 'DELETE'])
    async def proxy_service(fermenter_id: str, service_name: str, request: Request, service_path: str = ''):
        return await _proxy_via_agent(request, fermenter_id, service_name, service_path)

    @router.api_route('/fermenters/{fermenter_id}/schedule/{service_path:path}', methods=['GET', 'POST', 'PUT', 'DELETE'])
    @router.api_route('/fermenters/{fermenter_id}/schedule', methods=['GET', 'POST', 'PUT', 'DELETE'])
    async def proxy_schedule(fermenter_id: str, request: Request, service_path: str = ''):
        return await _proxy_via_agent(request, fermenter_id, 'schedule_service', f'schedule/{service_path}'.rstrip('/'))

    @router.api_route('/fermenters/{fermenter_id}/control/{service_path:path}', methods=['GET', 'POST', 'PUT', 'DELETE'])
    @router.api_route('/fermenters/{fermenter_id}/control', methods=['GET', 'POST', 'PUT', 'DELETE'])
    async def proxy_control(fermenter_id: str, request: Request, service_path: str = ''):
        return await _proxy_via_agent(request, fermenter_id, 'control_service', f'control/{service_path}'.rstrip('/'))

    @router.api_route('/fermenters/{fermenter_id}/rules/{service_path:path}', methods=['GET', 'POST', 'PUT', 'DELETE'])
    @router.api_route('/fermenters/{fermenter_id}/rules', methods=['GET', 'POST', 'PUT', 'DELETE'])
    async def proxy_rules(fermenter_id: str, request: Request, service_path: str = ''):
        return await _proxy_via_agent(request, fermenter_id, 'control_service', f'rules/{service_path}'.rstrip('/'))

    @router.api_route('/fermenters/{fermenter_id}/system/{service_path:path}', methods=['GET', 'POST', 'PUT', 'DELETE'])
    @router.api_route('/fermenters/{fermenter_id}/system', methods=['GET', 'POST', 'PUT', 'DELETE'])
    async def proxy_system(fermenter_id: str, request: Request, service_path: str = ''):
        return await _proxy_via_agent(request, fermenter_id, 'control_service', f'system/{service_path}'.rstrip('/'))

    @router.api_route('/fermenters/{fermenter_id}/ws/{service_path:path}', methods=['GET', 'POST', 'PUT', 'DELETE'])
    @router.api_route('/fermenters/{fermenter_id}/ws', methods=['GET', 'POST', 'PUT', 'DELETE'])
    async def proxy_ws(fermenter_id: str, request: Request, service_path: str = ''):
        return await _proxy_via_agent(request, fermenter_id, 'control_service', f'ws/{service_path}'.rstrip('/'))

    return router
