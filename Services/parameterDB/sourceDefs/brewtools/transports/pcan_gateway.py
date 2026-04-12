from __future__ import annotations

import select
import socket
import struct
import time

from .base import CanTransport, RawCanFrame

TYPE_CLASSIC = 0x0080
TYPE_CLASSIC_CRC = 0x0081
TYPE_FD = 0x0090
TYPE_FD_CRC = 0x0091

FD_LEN_TO_DLC = {
    0: 0,
    1: 1,
    2: 2,
    3: 3,
    4: 4,
    5: 5,
    6: 6,
    7: 7,
    8: 8,
    12: 9,
    16: 10,
    20: 11,
    24: 12,
    32: 13,
    48: 14,
    64: 15,
}
DLC_TO_FD_LEN = {v: k for k, v in FD_LEN_TO_DLC.items()}


def _payload_len_from_dlc(dlc: int, is_fd: bool) -> int:
    if is_fd:
        if dlc not in DLC_TO_FD_LEN:
            raise ValueError(f"invalid CAN FD DLC {dlc}")
        return DLC_TO_FD_LEN[dlc]
    if not 0 <= dlc <= 8:
        raise ValueError(f"invalid classic CAN DLC {dlc}")
    return dlc


def _encode_flags(frame: RawCanFrame) -> int:
    flags = 0
    if frame.is_fd and len(frame.data) > 8:
        flags |= 0x0010
    if frame.is_fd and frame.bitrate_switch:
        flags |= 0x0020
    if frame.is_fd and frame.error_state_indicator:
        flags |= 0x0040
    if frame.is_extended_id:
        flags |= 0x0200
    if not frame.is_fd and frame.is_remote_frame:
        flags |= 0x8000
    return flags


def _encode_can_word(frame: RawCanFrame) -> int:
    can_word = int(frame.arbitration_id) & 0x1FFFFFFF
    if frame.is_remote_frame:
        can_word |= 0x40000000
    if frame.is_extended_id:
        can_word |= 0x80000000
    return can_word


def build_gateway_frame(frame: RawCanFrame) -> bytes:
    msg_type = TYPE_FD if frame.is_fd else TYPE_CLASSIC
    payload_len = len(frame.data)
    if frame.is_fd:
        dlc = FD_LEN_TO_DLC.get(payload_len)
        if dlc is None:
            allowed = ", ".join(str(length) for length in sorted(FD_LEN_TO_DLC.keys()))
            raise ValueError(
                f"invalid CAN FD payload length {payload_len}; allowed lengths: {allowed}"
            )
    else:
        if not 0 <= payload_len <= 8:
            raise ValueError(
                f"invalid classic CAN payload length {payload_len}; allowed range: 0..8"
            )
        dlc = payload_len
    flags = _encode_flags(frame)
    can_word = _encode_can_word(frame)

    body = bytearray()
    body.extend(b"\x00\x00")
    body.extend(struct.pack(">H", msg_type))
    body.extend(b"\x00" * 8)
    body.extend(struct.pack(">I", 0))
    body.extend(struct.pack(">I", 0))
    body.append(frame.channel & 0xFF)
    body.append(dlc & 0xFF)
    body.extend(struct.pack(">H", flags))
    body.extend(struct.pack(">I", can_word))
    body.extend(frame.data)
    struct.pack_into(">H", body, 0, len(body))
    return bytes(body)


def parse_gateway_packet(packet: bytes) -> list[RawCanFrame]:
    frames: list[RawCanFrame] = []
    offset = 0
    packet_len = len(packet)

    while offset < packet_len:
        if packet_len - offset < 28:
            raise ValueError(f"truncated gateway frame at offset {offset}")

        length = struct.unpack_from(">H", packet, offset)[0]
        msg_type = struct.unpack_from(">H", packet, offset + 2)[0]
        if length < 28 or offset + length > packet_len:
            raise ValueError(f"invalid gateway frame length {length} at offset {offset}")

        is_fd = msg_type in (TYPE_FD, TYPE_FD_CRC)
        has_crc = msg_type in (TYPE_CLASSIC_CRC, TYPE_FD_CRC)
        flags = struct.unpack_from(">H", packet, offset + 22)[0]
        can_word = struct.unpack_from(">I", packet, offset + 24)[0]
        dlc = packet[offset + 21]

        payload_len = _payload_len_from_dlc(dlc, is_fd)
        payload_start = offset + 28
        payload_limit = offset + length - (4 if has_crc else 0)
        if payload_limit < payload_start:
            raise ValueError(f"invalid CRC gateway frame length {length} at offset {offset}")

        payload_end = payload_start + payload_len
        if payload_end > payload_limit:
            raise ValueError(f"payload overruns gateway frame at offset {offset}")

        frames.append(
            RawCanFrame(
                arbitration_id=int(can_word & 0x1FFFFFFF),
                data=bytes(packet[payload_start:payload_end]),
                is_extended_id=bool(can_word & 0x80000000),
                is_remote_frame=bool(can_word & 0x40000000),
                is_fd=is_fd,
                bitrate_switch=bool(flags & 0x0020),
                error_state_indicator=bool(flags & 0x0040),
                channel=int(packet[offset + 20]),
                timestamp=time.time(),
            )
        )
        offset += length

    return frames


class PeakGatewayUdpTransport(CanTransport):
    def __init__(
        self,
        *,
        remote_host: str,
        remote_port: int,
        local_host: str = "0.0.0.0",
        local_port: int = 0,
        socket_timeout: float | None = None,
    ) -> None:
        self.remote_host = str(remote_host)
        self.remote_port = int(remote_port)
        self.local_host = str(local_host)
        self.local_port = int(local_port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if socket_timeout is not None:
            self._sock.settimeout(float(socket_timeout))
        self._sock.bind((self.local_host, self.local_port))

    def close(self) -> None:
        self._sock.close()

    def send_frame(self, frame: RawCanFrame) -> None:
        payload = build_gateway_frame(frame)
        self._sock.sendto(payload, (self.remote_host, self.remote_port))

    def recv_frames(self, timeout: float | None = None) -> list[RawCanFrame]:
        if timeout is None:
            packet, _addr = self._sock.recvfrom(4096)
            return parse_gateway_packet(packet)

        ready, _, _ = select.select([self._sock], [], [], timeout)
        if not ready:
            return []
        packet, _addr = self._sock.recvfrom(4096)
        return parse_gateway_packet(packet)
