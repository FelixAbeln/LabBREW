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
            "gateway_bind_host": self.gateway_bind_host,
            "selectable": self.selectable,
            "error": self.error,
        }
        if self.extra:
            payload.update(self.extra)
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
