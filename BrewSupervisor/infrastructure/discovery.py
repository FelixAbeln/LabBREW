from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Optional
import socket
import time

try:
    from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf
except Exception:
    ServiceBrowser = None
    ServiceInfo = None
    Zeroconf = None


SERVICE_TYPE = "_fcs._tcp.local."
EXPECTED_ROLE = "fermenter_agent"


def _decode_property(value: Any) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    return str(value or "")


@dataclass(slots=True)
class DiscoveredAgent:
    service_name: str
    node_id: str
    node_name: str
    address: str
    host: str
    port: int
    proto: str
    api_path: str
    summary_path: str
    services_hint: list[str]
    role: str = EXPECTED_ROLE

    @property
    def base_url(self) -> str:
        return f"{self.proto}://{self.address}:{self.port}"

    @property
    def info_url(self) -> str:
        path = self.api_path if self.api_path.startswith('/') else f'/{self.api_path}'
        return f"{self.base_url}{path}"


class _DiscoveryListener:
    def __init__(self, owner: "MdnsDiscoveryBrowser") -> None:
        self.owner = owner

    def add_service(self, zeroconf: Any, service_type: str, name: str) -> None:
        self.owner._refresh_service(name)

    def update_service(self, zeroconf: Any, service_type: str, name: str) -> None:
        self.owner._refresh_service(name)

    def remove_service(self, zeroconf: Any, service_type: str, name: str) -> None:
        self.owner._remove_service(name)


@dataclass(slots=True)
class MdnsDiscoveryBrowser:
    service_type: str = SERVICE_TYPE
    restart_cooldown_s: float = 10.0
    rebrowse_interval_s: float = 120.0
    preserved_agent_ttl_s: float = 5.0
    zeroconf: Optional[Any] = field(init=False, default=None)
    browser: Optional[Any] = field(init=False, default=None)
    listener: Optional[Any] = field(init=False, default=None)
    _agents: dict[str, DiscoveredAgent] = field(init=False, default_factory=dict)
    _preserved_agent_deadlines: dict[str, float] = field(init=False, default_factory=dict)
    _last_restart_monotonic: float = field(init=False, default=0.0)

    def start(self) -> bool:
        if Zeroconf is None or ServiceBrowser is None:
            return False
        if self.zeroconf is not None:
            return True
        self.zeroconf = Zeroconf()
        self.listener = _DiscoveryListener(self)
        self.browser = ServiceBrowser(self.zeroconf, self.service_type, self.listener)
        self._last_restart_monotonic = time.monotonic()
        return True

    def _close_browser(self) -> None:
        if self.zeroconf is not None:
            try:
                self.zeroconf.close()
            except Exception:
                pass
        self.browser = None
        self.listener = None
        self.zeroconf = None

    def _restart(self) -> bool:
        preserved_agents = dict(self._agents)
        preserve_ttl_s = max(float(self.preserved_agent_ttl_s), 0.0)
        preserve_until = time.monotonic() + preserve_ttl_s if preserved_agents else 0.0
        self._close_browser()
        self._agents = {}
        self._preserved_agent_deadlines = {}
        started = self.start()
        if preserved_agents and preserve_ttl_s > 0.0:
            self._agents.update(preserved_agents)
            self._preserved_agent_deadlines = {
                name: preserve_until
                for name in preserved_agents
            }
        return started

    def _prune_expired_preserved_agents(self, now_monotonic: float | None = None) -> None:
        if not self._preserved_agent_deadlines:
            return
        now = time.monotonic() if now_monotonic is None else now_monotonic
        expired = [
            name
            for name, deadline in self._preserved_agent_deadlines.items()
            if now >= deadline
        ]
        for name in expired:
            self._preserved_agent_deadlines.pop(name, None)
            self._agents.pop(name, None)

    def _restart_interval_s(self) -> float:
        interval = self.rebrowse_interval_s if self._agents else self.restart_cooldown_s
        try:
            normalized = float(interval)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(normalized):
            return 0.0
        return max(0.0, normalized)

    def _should_restart(self, now_monotonic: float) -> bool:
        return (now_monotonic - self._last_restart_monotonic) >= self._restart_interval_s()

    def _ensure_browser_alive(self, now_monotonic: float | None = None) -> None:
        if Zeroconf is None or ServiceBrowser is None:
            return
        if self.zeroconf is None:
            self.start()
            return
        now = time.monotonic() if now_monotonic is None else now_monotonic
        if not self._should_restart(now):
            return
        self._restart()

    def _refresh_service(self, name: str) -> None:
        if self.zeroconf is None:
            return
        try:
            info = self.zeroconf.get_service_info(self.service_type, name, timeout=1000)
        except Exception:
            return
        if info is None:
            return

        try:
            addresses = info.parsed_addresses()
        except Exception:
            addresses = []
        address = addresses[0] if addresses else ""
        properties = getattr(info, "properties", {}) or {}
        role = _decode_property(properties.get(b"role")) or ""
        if role != EXPECTED_ROLE:
            self._preserved_agent_deadlines.pop(name, None)
            self._agents.pop(name, None)
            return

        host = (_decode_property(properties.get(b"hostname")) or getattr(info, "server", "") or "").rstrip('.')
        node_id = _decode_property(properties.get(b"node_id")) or host or address or name.split('.', 1)[0]
        node_name = _decode_property(properties.get(b"node_name")) or node_id
        proto = _decode_property(properties.get(b"proto")) or "http"
        api_path = _decode_property(properties.get(b"api")) or "/agent/info"
        summary_path = _decode_property(properties.get(b"summary")) or "/agent/summary"
        services_raw = _decode_property(properties.get(b"services")) or ""
        services_hint = [s.strip() for s in services_raw.split(',') if s.strip()]

        self._agents[name] = DiscoveredAgent(
            service_name=name,
            node_id=node_id,
            node_name=node_name,
            address=address,
            host=host,
            port=int(getattr(info, "port", 0) or 0),
            proto=proto,
            api_path=api_path,
            summary_path=summary_path,
            services_hint=services_hint,
            role=role,
        )
        self._preserved_agent_deadlines.pop(name, None)

    def _remove_service(self, name: str) -> None:
        self._preserved_agent_deadlines.pop(name, None)
        self._agents.pop(name, None)

    def snapshot(self) -> list[DiscoveredAgent]:
        now = time.monotonic()
        self._prune_expired_preserved_agents(now)
        self._ensure_browser_alive(now)
        return sorted(self._agents.values(), key=lambda item: ((item.node_name or "").lower(), (item.address or item.host or "").lower()))

    def close(self) -> None:
        self._agents.clear()
        self._preserved_agent_deadlines.clear()
        self._close_browser()
