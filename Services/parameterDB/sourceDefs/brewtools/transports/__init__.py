from typing import Any, Callable

from .base import RawCanFrame, CanTransport, TransportDiscoveryCandidate
from .kvaser import KvaserTransport, discover_kvaser_channels
from .pcan_gateway import PeakGatewayUdpTransport, discover_peak_gateways

TransportDiscoveryFunction = Callable[
    [dict[str, Any] | None, dict[str, Any] | None],
    tuple[list[TransportDiscoveryCandidate], str],
]

TRANSPORT_DISCOVERY_FUNCTIONS: dict[str, TransportDiscoveryFunction] = {
    "kvaser": discover_kvaser_channels,
    "pcan_gateway_udp": discover_peak_gateways,
}


def discover_transport_candidates(
    payload: dict[str, Any] | None = None,
    record: dict[str, Any] | None = None,
    *,
    transports: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    selected = transports or list(TRANSPORT_DISCOVERY_FUNCTIONS.keys())
    candidates: list[dict[str, Any]] = []
    warnings: list[str] = []

    for transport_name in selected:
        discover = TRANSPORT_DISCOVERY_FUNCTIONS.get(str(transport_name))
        if discover is None:
            warnings.append(f"{transport_name}: discovery is not registered")
            continue
        items, error = discover(payload, record)
        if error:
            warnings.append(f"{transport_name}: {error}")
        candidates.extend(item.as_dict() for item in items)

    return candidates, warnings

__all__ = [
    "RawCanFrame",
    "CanTransport",
    "TransportDiscoveryCandidate",
    "KvaserTransport",
    "discover_kvaser_channels",
    "PeakGatewayUdpTransport",
    "discover_peak_gateways",
    "TRANSPORT_DISCOVERY_FUNCTIONS",
    "discover_transport_candidates",
]
