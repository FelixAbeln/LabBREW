from __future__ import annotations

import threading
import time
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
    service_agents: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    online: bool = True
    last_error: str | None = None


class FermenterRegistry:
    def __init__(
        self,
        browser: Any,
        timeout_s: float = 0.6,
        snapshot_cache_ttl_s: float = 0.5,
        stale_snapshot_grace_s: float = 20.0,
    ) -> None:
        self._browser = browser
        self._timeout_s = timeout_s
        self._snapshot_cache_ttl_s = max(0.0, float(snapshot_cache_ttl_s))
        self._stale_snapshot_grace_s = max(0.0, float(stale_snapshot_grace_s))
        self._snapshot_lock = threading.Lock()
        self._snapshot_cache: tuple[float, list[FermenterNode]] | None = None
        self._last_non_empty_snapshot: tuple[float, list[FermenterNode]] | None = None
        self._refresh_inflight = False
        self._session = requests.Session()
        adapter = HTTPAdapter(pool_connections=16, pool_maxsize=32, max_retries=0)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def _refresh_snapshot_background(self) -> None:
        try:
            self._compute_snapshot(force_refresh=True)
        finally:
            with self._snapshot_lock:
                self._refresh_inflight = False

    def _fetch_json(self, url: str, *, timeout_s: float | None = None) -> dict[str, Any]:
        timeout = self._timeout_s if timeout_s is None else max(0.05, float(timeout_s))
        response = self._session.get(url, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"value": data}

    def _build_node(self, agent: DiscoveredAgent) -> FermenterNode:
        probe_timeout_s = max(0.05, min(self._timeout_s, 0.6))
        summary_path = str(agent.summary_path or "")
        if not summary_path.startswith("/"):
            summary_path = f"/{summary_path}"

        node = FermenterNode(
            id=agent.node_id,
            name=agent.node_name,
            address=agent.address,
            host=agent.host,
            agent_base_url=agent.base_url,
            info_url=agent.info_url,
            summary_url=f"{agent.base_url}{summary_path}",
            services_hint=list(agent.services_hint),
            service_agents={name: agent.base_url for name in agent.services_hint},
        )
        try:
            info = self._fetch_json(agent.info_url, timeout_s=probe_timeout_s)
            node.services = (
                info.get("services", {})
                if isinstance(info.get("services", {}), dict)
                else {}
            )
            for service_name in node.services:
                node.service_agents[str(service_name)] = agent.base_url
            node.name = info.get("node_name") or node.name
            node.id = info.get("node_id") or node.id
        except Exception as exc:
            node.online = False
            node.last_error = str(exc)
            return node

        try:
            summary_url = node.summary_url
            summary = self._fetch_json(summary_url, timeout_s=probe_timeout_s)
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
                    (node.name or "").lower(),
                    (node.host or "").lower(),
                    (node.address or "").lower(),
                    (node.agent_base_url or "").lower(),
                ),
            )[0]
        return sorted(
            nodes,
            key=lambda node: (
                (node.name or "").lower(),
                (node.host or "").lower(),
                (node.address or "").lower(),
                (node.agent_base_url or "").lower(),
            ),
        )[0]

    def _compute_snapshot(self, *, force_refresh: bool = False) -> list[FermenterNode]:

        discovered_agents = list(self._browser.snapshot())
        unique_agents: list[Any] = []
        seen_agent_keys: set[tuple[str, str]] = set()
        for agent in discovered_agents:
            key = (
                str(getattr(agent, "node_id", "") or "").strip(),
                str(getattr(agent, "base_url", "") or "").strip().rstrip("/").lower(),
            )
            if key in seen_agent_keys:
                continue
            seen_agent_keys.add(key)
            unique_agents.append(agent)

        raw_nodes = [self._build_node(agent) for agent in unique_agents]
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
                    services_hint=sorted(
                        {service for node in group for service in node.services_hint}
                    ),
                    services={
                        str(service_name): service_info
                        for node in group
                        for service_name, service_info in (node.services or {}).items()
                    },
                    service_agents={
                        str(service_name): base_url
                        for node in group
                        for service_name, base_url in (
                            node.service_agents or {}
                        ).items()
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
                merged[-1].last_error = (
                    "; ".join(dict.fromkeys(errors)) if errors else None
                )
        now = time.monotonic()
        effective = list(merged)
        if effective:
            with self._snapshot_lock:
                self._last_non_empty_snapshot = (now, list(effective))
        elif not force_refresh and self._stale_snapshot_grace_s > 0.0:
            with self._snapshot_lock:
                if self._last_non_empty_snapshot is not None:
                    seen_at, previous_nodes = self._last_non_empty_snapshot
                    if (now - seen_at) < self._stale_snapshot_grace_s:
                        effective = list(previous_nodes)

        with self._snapshot_lock:
            self._snapshot_cache = (now, list(effective))
        return list(effective)

    def snapshot(self, *, force_refresh: bool = False) -> list[FermenterNode]:
        now = time.monotonic()
        if not force_refresh:
            with self._snapshot_lock:
                if self._snapshot_cache is not None:
                    cached_at, cached_nodes = self._snapshot_cache
                    cache_is_fresh = self._snapshot_cache_ttl_s > 0.0 and (
                        (now - cached_at) < self._snapshot_cache_ttl_s
                    )
                    if cache_is_fresh:
                        return list(cached_nodes)

                    # Keep API responses snappy: serve stale cache and refresh in background.
                    if not self._refresh_inflight:
                        self._refresh_inflight = True
                        threading.Thread(
                            target=self._refresh_snapshot_background,
                            daemon=True,
                        ).start()
                    return list(cached_nodes)

        return self._compute_snapshot(force_refresh=force_refresh)

    def get_node(self, node_id: str) -> FermenterNode | None:
        for node in self.snapshot():
            if node.id == node_id:
                return node
        return None

    def get_node_for_service(
        self, node_id: str, service_name: str
    ) -> FermenterNode | None:
        matching = [node for node in self.snapshot() if node.id == node_id]
        if not matching:
            return None
        service_matching = [
            node for node in matching if self._supports_service(node, service_name)
        ]
        if service_matching:
            return self._pick_preferred_node(service_matching)
        return self._pick_preferred_node(matching)

    def close(self) -> None:
        with self._snapshot_lock:
            self._snapshot_cache = None
            self._last_non_empty_snapshot = None
            self._refresh_inflight = False
        self._session.close()
