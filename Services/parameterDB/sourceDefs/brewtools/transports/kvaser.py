from __future__ import annotations

import time
from typing import Any

from .base import CanTransport, RawCanFrame, TransportDiscoveryCandidate


def discover_kvaser_channels(
    payload: dict[str, Any] | None = None,
    record: dict[str, Any] | None = None,
) -> tuple[list[TransportDiscoveryCandidate], str]:
    _ = payload, record
    try:
        import can
    except ModuleNotFoundError:
        return [], "python-can is not installed"
    except Exception as exc:
        return [], str(exc)

    try:
        configs = can.detect_available_configs(interfaces=["kvaser"])
    except TypeError:
        try:
            configs = [
                cfg
                for cfg in (can.detect_available_configs() or [])
                if str((cfg or {}).get("interface", "")).strip().lower() == "kvaser"
            ]
        except Exception as exc:
            return [], str(exc)
    except Exception as exc:
        return [], str(exc)

    out: list[TransportDiscoveryCandidate] = []
    seen: set[tuple[str, str]] = set()
    for cfg in configs or []:
        if not isinstance(cfg, dict):
            continue
        channel_value = cfg.get("channel", 0)
        channel_text = str(channel_value).strip() or "0"
        key = ("kvaser", channel_text)
        if key in seen:
            continue
        seen.add(key)
        try:
            channel = int(channel_value)
        except Exception:
            channel = 0
        bitrate = int(cfg.get("bitrate") or 500000)
        out.append(
            TransportDiscoveryCandidate(
                title=f"kvaser:{channel_text}",
                subtitle="Kvaser channel",
                source="kvaser",
                transport="kvaser",
                interface="kvaser",
                channel=channel,
                bitrate=bitrate,
                selectable=True,
            )
        )
    return out, ""


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
