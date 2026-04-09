from __future__ import annotations

from collections import Counter

from .errors import ValidationError
from .models import CapabilityArgRule, Topology


def validate_topology(topology: Topology) -> None:
    service_names = [service.name for service in topology.services]
    duplicates = [name for name, count in Counter(service_names).items() if count > 1]
    if duplicates:
        raise ValidationError(f"Duplicate service names: {duplicates}")

    capability_names: list[str] = []
    for service in topology.services:
        capability_names.extend(cap.name for cap in service.provides)
    capability_names.extend(cap.name for cap in topology.external_capabilities)

    dup_caps = [name for name, count in Counter(capability_names).items() if count > 1]
    if dup_caps:
        raise ValidationError(f"Duplicate capability providers: {dup_caps}")

    known_capabilities = set(capability_names)
    for service in topology.services:
        for req in service.requires:
            if req not in known_capabilities:
                raise ValidationError(
                    f"Service '{service.name}' requires unknown capability '{req}'"
                )
        for rule in service.capability_arg_rules:
            _validate_rule(service.name, known_capabilities, rule)


def _validate_rule(
    service_name: str, known_capabilities: set[str], rule: CapabilityArgRule
) -> None:
    if rule.capability not in known_capabilities:
        raise ValidationError(
            f"Service '{service_name}' has arg rule for unknown "
            f"capability '{rule.capability}'"
        )
    if rule.mode == "url" and not rule.url_flag:
        raise ValidationError(
            f"Service '{service_name}' capability '{rule.capability}' "
            "uses url mode without url_flag"
        )
    if rule.mode == "host_port" and (not rule.host_flag or not rule.port_flag):
        raise ValidationError(
            f"Service '{service_name}' capability '{rule.capability}' "
            "uses host_port mode without host_flag/port_flag"
        )
