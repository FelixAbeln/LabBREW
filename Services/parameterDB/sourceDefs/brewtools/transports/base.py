from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RawCanFrame:
    arbitration_id: int
    data: bytes
    is_extended_id: bool = True
    is_fd: bool = False
    bitrate_switch: bool = False
    error_state_indicator: bool = False
    is_remote_frame: bool = False
    channel: int = 0
    timestamp: float | None = None


@dataclass(slots=True)
class TransportDiscoveryCandidate:
    title: str
    subtitle: str
    source: str
    transport: str
    interface: str = ""
    channel: int = 0
    bitrate: int = 500000
    gateway_host: str = ""
    gateway_tx_port: int = 55002
    gateway_rx_port: int = 55001
    gateway_control_port: int = 45321
    gateway_control_enabled: bool = True
    gateway_route_name: str = "rt2"
    gateway_route_state: str = "0x88000002"
    gateway_auth_token: str = "F908DB674DB61329D710E4F9248160634C87C75FFBC4CD855C23A25EE6E4DB8F"
    gateway_auth_id: str = "(c) PEAK-System"
    gateway_send_fw_dev_probes: bool = True
    gateway_control_tick_s: float = 1.0
    gateway_control_timeout_s: float = 1.5
    gateway_rx_control_enabled: bool = True
    gateway_rx_route_name: str = "rt1"
    gateway_rx_route_state: str = "0x08000002"
    gateway_rx_auth_token: str = "99D5D2B95B487D70F31CB7F8A34D61624C87C75FFBC4CD855C23A25EE6E4DB8F"
    gateway_rx_auth_id: str = "(c) PEAK-System"
    gateway_rx_update_state: str = "0xc000002"
    gateway_bind_host: str = "0.0.0.0"
    selectable: bool = False
    error: str = ""
    extra: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "title": self.title,
            "subtitle": self.subtitle,
            "source": self.source,
            "transport": self.transport,
            "interface": self.interface,
            "channel": self.channel,
            "bitrate": self.bitrate,
            "gateway_host": self.gateway_host,
            "gateway_tx_port": self.gateway_tx_port,
            "gateway_rx_port": self.gateway_rx_port,
            "gateway_control_port": self.gateway_control_port,
            "gateway_control_enabled": self.gateway_control_enabled,
            "gateway_route_name": self.gateway_route_name,
            "gateway_route_state": self.gateway_route_state,
            "gateway_auth_token": self.gateway_auth_token,
            "gateway_auth_id": self.gateway_auth_id,
            "gateway_send_fw_dev_probes": self.gateway_send_fw_dev_probes,
            "gateway_control_tick_s": self.gateway_control_tick_s,
            "gateway_control_timeout_s": self.gateway_control_timeout_s,
            "gateway_rx_control_enabled": self.gateway_rx_control_enabled,
            "gateway_rx_route_name": self.gateway_rx_route_name,
            "gateway_rx_route_state": self.gateway_rx_route_state,
            "gateway_rx_auth_token": self.gateway_rx_auth_token,
            "gateway_rx_auth_id": self.gateway_rx_auth_id,
            "gateway_rx_update_state": self.gateway_rx_update_state,
            "gateway_bind_host": self.gateway_bind_host,
            "selectable": self.selectable,
            "error": self.error,
        }
        if self.extra:
            conflicting_extra: dict[str, Any] = {}
            for key, value in self.extra.items():
                if key in payload:
                    conflicting_extra[key] = value
                    continue
                payload[key] = value
            if conflicting_extra:
                payload["extra"] = conflicting_extra
        return payload


class CanTransport(ABC):
    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_frame(self, frame: RawCanFrame) -> None:
        raise NotImplementedError

    @abstractmethod
    def recv_frames(self, timeout: float | None = None) -> list[RawCanFrame]:
        raise NotImplementedError
