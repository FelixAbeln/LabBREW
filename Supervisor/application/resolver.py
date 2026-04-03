from __future__ import annotations

from dataclasses import dataclass

from ..domain.errors import ResolutionError
from ..domain.models import CapabilityBinding, Endpoint, Topology


@dataclass(frozen=True, slots=True)
class ResolvedTopology:
    bindings: dict[str, CapabilityBinding]
    service_dependencies: dict[str, set[str]]


class CapabilityResolver:
    def resolve(self, topology: Topology, default_advertise_host: str) -> ResolvedTopology:
        bindings: dict[str, CapabilityBinding] = {}
        for external in topology.external_capabilities:
            bindings[external.name] = CapabilityBinding(
                name=external.name,
                connect_endpoint=external.endpoint,
                advertise_endpoint=external.endpoint,
                provider_service=None,
                external=True,
            )

        for service in topology.services:
            if not service.enabled:
                continue
            for provided in service.provides:
                connect_endpoint = provided.bind_endpoint
                advertise_endpoint = Endpoint(
                    host=default_advertise_host,
                    port=provided.port,
                    proto=provided.proto,
                    path=provided.path,
                )
                bindings[provided.name] = CapabilityBinding(
                    name=provided.name,
                    connect_endpoint=connect_endpoint,
                    advertise_endpoint=advertise_endpoint,
                    provider_service=service.name,
                    external=False,
                )

        dependencies: dict[str, set[str]] = {}
        for service in topology.services:
            if not service.enabled:
                continue
            deps: set[str] = set()
            for capability in service.requires:
                binding = bindings.get(capability)
                if binding is None:
                    raise ResolutionError(
                        f"Capability '{capability}' required by '{service.name}' could not be resolved"
                    )
                if binding.provider_service and binding.provider_service != service.name:
                    deps.add(binding.provider_service)
            dependencies[service.name] = deps

        return ResolvedTopology(bindings=bindings, service_dependencies=dependencies)
