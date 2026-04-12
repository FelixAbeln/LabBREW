from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


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
