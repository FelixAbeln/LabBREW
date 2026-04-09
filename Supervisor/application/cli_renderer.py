from __future__ import annotations

from ..domain.errors import ResolutionError
from ..domain.models import CapabilityBinding, ServiceSpec


class CliRenderer:
    def render_args(
        self, service: ServiceSpec, bindings: dict[str, CapabilityBinding]
    ) -> list[str]:
        args = list(service.static_args)
        rules_by_capability = {
            rule.capability: rule for rule in service.capability_arg_rules
        }

        for capability in service.requires:
            rule = rules_by_capability.get(capability)
            if rule is None:
                raise ResolutionError(
                    f"Service '{service.name}' requires capability "
                    f"'{capability}' but has no arg rule"
                )
            binding = bindings[capability]
            endpoint = binding.connect_endpoint
            if rule.mode == "url":
                args.extend([rule.url_flag, endpoint.url])
            elif rule.mode == "host_port":
                args.extend(
                    [rule.host_flag, endpoint.host, rule.port_flag, str(endpoint.port)]
                )
            else:
                raise ResolutionError(f"Unsupported arg rule mode: {rule.mode}")
        return args
