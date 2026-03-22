from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Proto = Literal["http", "tcp"]
HealthcheckType = Literal["tcp"]


@dataclass(frozen=True, slots=True)
class Endpoint:
    host: str
    port: int
    proto: Proto
    path: str = ""

    @property
    def url(self) -> str:
        if self.proto == "http":
            path = self.path if self.path.startswith("/") else f"/{self.path}" if self.path else ""
            return f"http://{self.host}:{self.port}{path}"
        return f"{self.proto}://{self.host}:{self.port}"


@dataclass(frozen=True, slots=True)
class CapabilityBinding:
    name: str
    connect_endpoint: Endpoint
    advertise_endpoint: Endpoint
    provider_service: str | None = None
    external: bool = False

    @property
    def endpoint(self) -> Endpoint:
        """Backward-compatible alias for call sites that still expect a single endpoint."""
        return self.connect_endpoint


@dataclass(frozen=True, slots=True)
class ProvidedCapability:
    name: str
    bind_host: str
    port: int
    proto: Proto = "http"
    path: str = ""
    advertise: bool = True
    healthcheck_type: HealthcheckType = "tcp"

    @property
    def bind_endpoint(self) -> Endpoint:
        return Endpoint(host=self.bind_host, port=self.port, proto=self.proto, path=self.path)


@dataclass(frozen=True, slots=True)
class CapabilityArgRule:
    capability: str
    mode: Literal["url", "host_port"]
    url_flag: str | None = None
    host_flag: str | None = None
    port_flag: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalCapability:
    name: str
    endpoint: Endpoint


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    name: str
    module: str
    provides: tuple[ProvidedCapability, ...] = ()
    requires: tuple[str, ...] = ()
    capability_arg_rules: tuple[CapabilityArgRule, ...] = ()
    static_args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    startup_timeout_s: float = 20.0
    restart_backoff_s: float = 3.0
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class Topology:
    services: tuple[ServiceSpec, ...]
    external_capabilities: tuple[ExternalCapability, ...] = ()
    advertise_service_type: str = "_fcs._tcp.local."


@dataclass(slots=True)
class ManagedProcessState:
    service: ServiceSpec
    restart_count: int = 0
    healthy_once: bool = False
    started_at: float | None = None
    last_start_attempt: float | None = None
    process: object | None = None
