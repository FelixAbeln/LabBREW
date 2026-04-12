from __future__ import annotations

import time

from .base import CanTransport, RawCanFrame


class KvaserTransport(CanTransport):
    def __init__(
        self,
        *,
        interface: str = "kvaser",
        channel: int = 0,
        bitrate: int = 500000,
        receive_own_messages: bool = False,
        **bus_kwargs,
    ) -> None:
        try:
            import can
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "python-can is required for the Kvaser transport"
            ) from exc

        self._can = can
        self._bus = can.Bus(
            interface=interface,
            channel=channel,
            bitrate=bitrate,
            receive_own_messages=receive_own_messages,
            **bus_kwargs,
        )

    def close(self) -> None:
        self._bus.shutdown()

    def send_frame(self, frame: RawCanFrame) -> None:
        msg = self._can.Message(
            arbitration_id=int(frame.arbitration_id),
            data=bytes(frame.data),
            is_extended_id=bool(frame.is_extended_id),
            is_fd=bool(frame.is_fd),
            bitrate_switch=bool(frame.bitrate_switch),
            error_state_indicator=bool(frame.error_state_indicator),
            is_remote_frame=bool(frame.is_remote_frame),
            channel=frame.channel,
        )
        self._bus.send(msg)

    def recv_frames(self, timeout: float | None = None) -> list[RawCanFrame]:
        msg = self._bus.recv(timeout=timeout)
        if msg is None or getattr(msg, "is_error_frame", False):
            return []
        return [
            RawCanFrame(
                arbitration_id=int(msg.arbitration_id),
                data=bytes(msg.data),
                is_extended_id=bool(getattr(msg, "is_extended_id", True)),
                is_fd=bool(getattr(msg, "is_fd", False)),
                bitrate_switch=bool(getattr(msg, "bitrate_switch", False)),
                error_state_indicator=bool(getattr(msg, "error_state_indicator", False)),
                is_remote_frame=bool(getattr(msg, "is_remote_frame", False)),
                channel=int(getattr(msg, "channel", 0) or 0),
                timestamp=float(getattr(msg, "timestamp", time.time()) or time.time()),
            )
        ]
