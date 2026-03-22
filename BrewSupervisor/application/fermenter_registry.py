from __future__ import annotations

from dataclasses import dataclass, field
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
    summary: dict[str, Any] = field(default_factory=dict)
    online: bool = True
    last_error: str | None = None


class FermenterRegistry:
    def __init__(self, browser: Any, timeout_s: float = 3.0) -> None:
        self._browser = browser
        self._timeout_s = timeout_s
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
        )
        try:
            info = self._fetch_json(agent.info_url)
            node.services = info.get('services', {}) if isinstance(info.get('services', {}), dict) else {}
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

    def snapshot(self) -> list[FermenterNode]:
        return [self._build_node(agent) for agent in self._browser.snapshot()]

    def get_node(self, node_id: str) -> FermenterNode | None:
        for node in self.snapshot():
            if node.id == node_id:
                return node
        return None


    def close(self) -> None:
        self._session.close()
