from __future__ import annotations

import json
import re
import subprocess
import select
import socket
import struct
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from ipaddress import ip_network
from typing import Any
from urllib.parse import quote
from urllib.request import urlopen

from .base import CanTransport, RawCanFrame, TransportDiscoveryCandidate

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


def _local_ipv4_addresses() -> list[str]:
    hosts: list[str] = []
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET)
    except Exception:
        infos = []
    for info in infos:
        addr = str(info[4][0] or "").strip()
        if not addr or addr.startswith("127."):
            continue
        if addr not in hosts:
            hosts.append(addr)
    return hosts


def _gateway_hosts(payload: dict[str, Any], record: dict[str, Any] | None) -> list[str]:
    out: list[str] = []

    def _add(host: Any) -> None:
        text = str(host or "").strip()
        if text and text not in out:
            out.append(text)

    raw_hosts = payload.get("gateway_hosts")
    if isinstance(raw_hosts, list):
        for host in raw_hosts:
            _add(host)

    _add(payload.get("gateway_host"))
    if isinstance(record, dict):
        cfg = record.get("config")
        if isinstance(cfg, dict):
            _add(cfg.get("gateway_host"))

    max_hosts = max(1, min(256, int(payload.get("max_gateway_hosts") or 128)))
    for local in _local_ipv4_addresses():
        parts = local.split(".")
        if len(parts) == 4:
            try:
                subnet = ip_network(f"{local}/24", strict=False)
            except Exception:
                continue
            for host in subnet.hosts():
                text = str(host)
                if text == local:
                    continue
                _add(text)
                if len(out) >= max_hosts:
                    return out
    return out


def _arp_mac_table() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        proc = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=5, check=False)
        for raw in (proc.stdout or "").splitlines():
            line = raw.strip()
            match = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F\-]{17})\s+\w+", line)
            if match:
                out[match.group(1)] = match.group(2).lower()
    except Exception:
        return out
    return out


def _mac_oui(mac: str) -> str:
    parts = str(mac or "").strip().lower().split("-")
    if len(parts) < 3:
        return ""
    return "-".join(parts[:3])


def _json_device_identity(host: str, timeout_s: float) -> tuple[bool, str, dict[str, str]]:
    request_payload = {"command": "get", "element": "device"}
    encoded = quote(json.dumps(request_payload, separators=(",", ":")))
    url = f"http://{host}/json.php?jcmd={encoded}"
    try:
        with urlopen(url, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return False, "", {}

    if not isinstance(payload, dict) or not bool(payload.get("valid")):
        return False, "", {}

    product_name = str(payload.get("product_name") or "").strip()
    order_no = str(payload.get("order_no") or "").strip()
    serial_no = str(payload.get("serial_no") or "").strip()
    identity = f"{product_name} {order_no}".lower()
    if "pcan" not in identity and "ipeh-" not in identity:
        return False, "", {}

    id_text = ""
    if serial_no:
        id_text = f"SN:{serial_no}"
    elif order_no:
        id_text = f"ID:{order_no}"
    label = product_name or "PCAN Gateway"
    subtitle_identity = f"{label} ({id_text})" if id_text else label
    return True, subtitle_identity, {
        "identity_product_name": product_name,
        "identity_order_no": order_no,
        "identity_serial_no": serial_no,
        "identity_source": "json_device",
    }


def discover_peak_gateways(
    payload: dict[str, Any],
    record: dict[str, Any] | None,
) -> tuple[list[TransportDiscoveryCandidate], str]:
    tx_port = int(payload.get("gateway_tx_port") or 55002)
    rx_port = int(payload.get("gateway_rx_port") or 55001)
    bind_host = str(payload.get("gateway_bind_host") or "0.0.0.0").strip() or "0.0.0.0"
    timeout_s = float(payload.get("probe_timeout_s") or 0.5)
    worker_count = max(1, min(64, int(payload.get("probe_workers") or 32)))
    include_unmatched_hosts = bool(payload.get("include_unmatched_hosts", False))

    hosts = _gateway_hosts(payload, record)
    arp_table = _arp_mac_table()
    out: list[TransportDiscoveryCandidate] = []

    def _probe_host(host: str) -> TransportDiscoveryCandidate:
        is_json_match, json_msg, json_identity = _json_device_identity(host, timeout_s=min(timeout_s, 0.8))
        if is_json_match:
            return TransportDiscoveryCandidate(
                title=f"pcan:{host}",
                subtitle=f"UDP {tx_port}/{rx_port} · {json_msg}",
                source="pcan_gateway_udp",
                transport="pcan_gateway_udp",
                gateway_host=host,
                gateway_tx_port=tx_port,
                gateway_rx_port=rx_port,
                gateway_bind_host=bind_host,
                selectable=True,
                extra={"identity_mac_oui": _mac_oui(arp_table.get(host, "")), **json_identity},
            )

        return TransportDiscoveryCandidate(
            title=f"pcan:{host}",
            subtitle=f"UDP {tx_port}/{rx_port}",
            source="pcan_gateway_udp",
            transport="pcan_gateway_udp",
            gateway_host=host,
            gateway_tx_port=tx_port,
            gateway_rx_port=rx_port,
            gateway_bind_host=bind_host,
            selectable=False,
            error="JSON device identity is not PCAN/PEAK",
            extra={"identity_mac_oui": _mac_oui(arp_table.get(host, ""))},
        )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(_probe_host, host) for host in hosts]
        for future in as_completed(futures):
            try:
                item = future.result()
                if item is not None and (item.selectable or include_unmatched_hosts):
                    out.append(item)
            except Exception:
                pass

    return out, ""


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
