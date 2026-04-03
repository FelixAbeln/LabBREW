from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from ..infrastructure.discovery import DiscoveredAgent


@dataclass(slots=True)
class FermenterNode:
    id: str
    name: str
    address: str
    host: str
    agent_base_url: str
    info_url: str
    summary_url: str
    services_hint: list[str] = field(default_factory=list)
    services: dict[str, Any] = field(default_factory=dict)
    service_agents: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    online: bool = True
    last_error: str | None = None


class FermenterRegistry:
    def __init__(self, browser: Any, timeout_s: float = 3.0, snapshot_cache_ttl_s: float = 0.5) -> None:
        self._browser = browser
        self._timeout_s = timeout_s
        self._snapshot_cache_ttl_s = max(0.0, float(snapshot_cache_ttl_s))
        self._snapshot_lock = threading.Lock()
        self._snapshot_cache: tuple[float, list[FermenterNode]] | None = None
        self._session = requests.Session()
        adapter = HTTPAdapter(pool_connections=16, pool_maxsize=32, max_retries=0)
        self._session.mount('http://', adapter)
        self._session.mount('https://', adapter)

    def _fetch_json(self, url: str) -> dict[str, Any]:
        response = self._session.get(url, timeout=self._timeout_s)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"value": data}

    def _build_node(self, agent: DiscoveredAgent) -> FermenterNode:
        node = FermenterNode(
            id=agent.node_id,
            name=agent.node_name,
            address=agent.address,
            host=agent.host,
            agent_base_url=agent.base_url,
            info_url=agent.info_url,
            summary_url=f"{agent.base_url}{agent.summary_path if agent.summary_path.startswith('/') else '/' + agent.summary_path}",
            services_hint=list(agent.services_hint),
            service_agents={name: agent.base_url for name in agent.services_hint},
        )
        try:
            info = self._fetch_json(agent.info_url)
            node.services = info.get('services', {}) if isinstance(info.get('services', {}), dict) else {}
            for service_name in node.services.keys():
                node.service_agents[str(service_name)] = agent.base_url
            node.name = info.get('node_name') or node.name
            node.id = info.get('node_id') or node.id
        except Exception as exc:
            node.online = False
            node.last_error = str(exc)
            return node

        try:
            summary_url = node.summary_url
            summary = self._fetch_json(summary_url)
            node.summary = summary
        except Exception as exc:
            node.last_error = str(exc)
        return node

    @staticmethod
    def _supports_service(node: FermenterNode, service_name: str) -> bool:
        if service_name in node.service_agents:
            return True
        if service_name in node.services:
            return True
        return service_name in node.services_hint

    @staticmethod
    def _pick_preferred_node(nodes: list[FermenterNode]) -> FermenterNode:
        online_nodes = [node for node in nodes if node.online]
        if online_nodes:
            return sorted(
                online_nodes,
                key=lambda node: (
                    (node.name or '').lower(),
                    (node.host or '').lower(),
                    (node.address or '').lower(),
                    (node.agent_base_url or '').lower(),
                ),
            )[0]
        return sorted(
            nodes,
            key=lambda node: (
                (node.name or '').lower(),
                (node.host or '').lower(),
                (node.address or '').lower(),
                (node.agent_base_url or '').lower(),
            ),
        )[0]

    def snapshot(self, *, force_refresh: bool = False) -> list[FermenterNode]:
        if not force_refresh and self._snapshot_cache_ttl_s > 0.0:
            with self._snapshot_lock:
                if self._snapshot_cache is not None:
                    cached_at, cached_nodes = self._snapshot_cache
                    if (time.monotonic() - cached_at) < self._snapshot_cache_ttl_s:
                        return list(cached_nodes)

        raw_nodes = [self._build_node(agent) for agent in self._browser.snapshot()]
        grouped: dict[str, list[FermenterNode]] = {}
        for node in raw_nodes:
            grouped.setdefault(node.id, []).append(node)

        merged: list[FermenterNode] = []
        for node_id in sorted(grouped.keys()):
            group = grouped[node_id]
            primary = self._pick_preferred_node(group)
            merged.append(
                FermenterNode(
                    id=primary.id,
                    name=primary.name,
                    address=primary.address,
                    host=primary.host,
                    agent_base_url=primary.agent_base_url,
                    info_url=primary.info_url,
                    summary_url=primary.summary_url,
                    services_hint=sorted({service for node in group for service in node.services_hint}),
                    services={
                        str(service_name): service_info
                        for node in group
                        for service_name, service_info in (node.services or {}).items()
                    },
                    service_agents={
                        str(service_name): base_url
                        for node in group
                        for service_name, base_url in (node.service_agents or {}).items()
                    },
                    summary={
                        str(key): value
                        for node in group
                        for key, value in (node.summary or {}).items()
                    },
                    online=any(node.online for node in group),
                    last_error=None,
                )
            )
            if not merged[-1].online:
                errors = [node.last_error for node in group if node.last_error]
                merged[-1].last_error = '; '.join(dict.fromkeys(errors)) if errors else None
        with self._snapshot_lock:
            self._snapshot_cache = (time.monotonic(), list(merged))
        return list(merged)

    def get_node(self, node_id: str) -> FermenterNode | None:
        for node in self.snapshot():
            if node.id == node_id:
                return node
        return None

    def get_node_for_service(self, node_id: str, service_name: str) -> FermenterNode | None:
        matching = [node for node in self.snapshot() if node.id == node_id]
        if not matching:
            return None
        service_matching = [node for node in matching if self._supports_service(node, service_name)]
        if service_matching:
            return self._pick_preferred_node(service_matching)
        return self._pick_preferred_node(matching)


    def close(self) -> None:
        with self._snapshot_lock:
            self._snapshot_cache = None
        self._session.close()
