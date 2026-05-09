from __future__ import annotations

import json
import os
import re
import subprocess
import select
import socket
import struct
import threading
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

DEFAULT_ROUTE_AUTH_TOKEN = "F908DB674DB61329D710E4F9248160634C87C75FFBC4CD855C23A25EE6E4DB8F"


def _local_ipv4_addresses() -> list[str]:
    hosts: list[str] = []

    def _add(addr: str) -> None:
        text = addr.strip()
        if text and not text.startswith("127.") and text not in hosts:
            hosts.append(text)

    # Most reliable cross-platform method: UDP connect to an external address.
    # No packet is actually sent; the OS picks the outbound interface IP.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # Use a short positive timeout to avoid non-blocking connect quirks.
            sock.settimeout(0.5)
            sock.connect(("8.8.8.8", 80))
            _add(sock.getsockname()[0])
    except Exception:
        pass

    # Fallback: hostname resolution (may fail on Pi if hostname isn't in /etc/hosts)
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET)
    except Exception:
        infos = []
    for info in infos:
        _add(str(info[4][0] or ""))

    # Linux fallback: iterate /sys/class/net and read each interface IP via SIOCGIFADDR.
    try:
        import fcntl
        SIOCGIFADDR = 0x8915
        ifaces_path = "/sys/class/net"
        if os.path.isdir(ifaces_path):
            for iface in os.listdir(ifaces_path):
                if iface == "lo":
                    continue
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                        packed = fcntl.ioctl(
                            s.fileno(),
                            SIOCGIFADDR,
                            struct.pack("256s", iface[:15].encode()),
                        )
                    _add(socket.inet_ntoa(packed[20:24]))
                except Exception:
                    pass
    except Exception:
        pass

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
            match = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F][0-9a-fA-F][:\-](?:[0-9a-fA-F][0-9a-fA-F][:\-]){4}[0-9a-fA-F][0-9a-fA-F])\s+\w+", line)
            if match:
                # Normalise to hyphen-separated for consistent OUI lookup
                out[match.group(1)] = match.group(2).lower().replace(":", "-")
    except Exception:
        return out
    return out


def _mac_oui(mac: str) -> str:
    normalised = str(mac or "").strip().lower().replace(":", "-")
    parts = normalised.split("-")
    if len(parts) < 3:
        return ""
    return "-".join(parts[:3])


def _json_device_identity(host: str, timeout_s: float) -> tuple[bool, str, str, dict[str, Any], str]:
    request_payload = {"command": "get", "element": "device"}
    encoded = quote(json.dumps(request_payload, separators=(",", ":")))
    url = f"http://{host}/json.php?jcmd={encoded}"
    try:
        with urlopen(url, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return False, "", "", {}, "probe failed"

    if not isinstance(payload, dict) or not bool(payload.get("valid")):
        return False, "", "", {}, "invalid JSON device response"

    product_name = str(payload.get("product_name") or "").strip()
    order_no = str(payload.get("order_no") or "").strip()
    serial_no = str(payload.get("serial_no") or "").strip()
    identity = f"{product_name} {order_no}".lower()
    if "pcan" not in identity and "ipeh-" not in identity:
        return False, "", "", {}, "JSON device identity is not PCAN/PEAK"

    label = product_name or "PCAN Gateway"
    if serial_no:
        sn_text = f"SN:{serial_no}"
    elif order_no:
        sn_text = f"ID:{order_no}"
    else:
        sn_text = ""
    can_count_raw = payload.get("CAN_count")
    try:
        can_count = max(1, int(can_count_raw))
    except Exception:
        can_count = 1

    return True, label, sn_text, {
        "identity_product_name": product_name,
        "identity_order_no": order_no,
        "identity_serial_no": serial_no,
        "identity_source": "json_device",
        "identity_can_count": can_count,
    }, ""


def discover_peak_gateways(
    payload: dict[str, Any],
    record: dict[str, Any] | None,
) -> tuple[list[TransportDiscoveryCandidate], str]:
    tx_port = int(payload.get("gateway_tx_port") or 55002)
    rx_port = int(payload.get("gateway_rx_port") or 55001)
    control_port = int(payload.get("gateway_control_port") or 45321)
    bind_host = str(payload.get("gateway_bind_host") or "0.0.0.0").strip() or "0.0.0.0"
    timeout_s = float(payload.get("probe_timeout_s") or 0.5)
    worker_count = max(1, min(64, int(payload.get("probe_workers") or 32)))
    max_can_count = max(1, min(64, int(payload.get("max_can_count") or 8)))
    include_unmatched_hosts = bool(payload.get("include_unmatched_hosts", False))

    hosts = _gateway_hosts(payload, record)
    arp_table = _arp_mac_table()
    out: list[TransportDiscoveryCandidate] = []
    warnings: list[str] = []

    def _probe_host(host: str) -> tuple[list[TransportDiscoveryCandidate], str]:
        is_json_match, device_label, sn_text, json_identity, failure_reason = _json_device_identity(host, timeout_s=min(timeout_s, 0.8))
        if is_json_match:
            reported_can_count = max(1, int(json_identity.get("identity_can_count") or 1))
            can_count = min(reported_can_count, max_can_count)
            warning = ""
            if reported_can_count > max_can_count:
                warning = f"PCAN host {host} reported CAN_count={reported_can_count}; capped to {max_can_count}"
            candidates: list[TransportDiscoveryCandidate] = []
            for channel in range(can_count):
                sub_parts = [f"CAN {channel}", device_label]
                if sn_text:
                    sub_parts.append(sn_text)
                sub_parts.append(f"UDP {tx_port}/{rx_port}")
                candidates.append(
                    TransportDiscoveryCandidate(
                        title=f"pcan:{host}:can{channel}",
                        subtitle=" · ".join(sub_parts),
                        source="pcan_gateway_udp",
                        transport="pcan_gateway_udp",
                        channel=channel,
                        gateway_host=host,
                        gateway_tx_port=tx_port,
                        gateway_rx_port=rx_port,
                        gateway_control_port=control_port,
                        gateway_bind_host=bind_host,
                        selectable=True,
                        extra={"identity_mac_oui": _mac_oui(arp_table.get(host, "")), **json_identity},
                    )
                )
            return candidates, warning

        return [
            TransportDiscoveryCandidate(
                title=f"pcan:{host}",
                subtitle=f"UDP {tx_port}/{rx_port}",
                source="pcan_gateway_udp",
                transport="pcan_gateway_udp",
                gateway_host=host,
                gateway_tx_port=tx_port,
                gateway_rx_port=rx_port,
                gateway_control_port=control_port,
                gateway_bind_host=bind_host,
                selectable=False,
                error=failure_reason or "JSON device identity is not PCAN/PEAK",
                extra={"identity_mac_oui": _mac_oui(arp_table.get(host, ""))},
            )
        ], ""

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(_probe_host, host): host for host in hosts}
        for future in as_completed(futures):
            host = futures[future]
            try:
                items, warning = future.result()
                if warning:
                    warnings.append(warning)
                for item in items or []:
                    if item is not None and (item.selectable or include_unmatched_hosts):
                        out.append(item)
            except Exception as exc:
                warnings.append(f"PCAN probe failed for {host}: {exc}")

    out.sort(key=lambda item: (str(item.gateway_host or ""), int(item.channel or 0), str(item.title or "")))

    return out, "; ".join(warnings)


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
    # PEAK gateway format uses low bits for frame kind on classic CAN:
    # 0x0000 standard, 0x0001 RTR, 0x0002 extended.
    if frame.is_extended_id:
        flags |= 0x0002
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
        control_port: int = 45321,
        control_enabled: bool = True,
        route_name: str = "rt2",
        route_state: str = "0x88000002",
        auth_token: str = DEFAULT_ROUTE_AUTH_TOKEN,
        auth_id: str = "(c) PEAK-System",
        send_fw_dev_probes: bool = True,
        control_tick_s: float = 1.0,
        control_timeout_s: float = 1.5,
        rx_control_enabled: bool = True,
        rx_route_name: str = "rt1",
        rx_route_state: str = "0x08000002",
        rx_auth_token: str = "99D5D2B95B487D70F31CB7F8A34D61624C87C75FFBC4CD855C23A25EE6E4DB8F",
        rx_auth_id: str = "(c) PEAK-System",
        rx_update_state: str = "0xc000002",
        rx_send_fw_dev_probes: bool = True,
        rx_control_tick_s: float = 1.0,
        rx_control_timeout_s: float = 1.5,
        local_host: str = "0.0.0.0",
        local_port: int = 0,
        socket_timeout: float | None = None,
    ) -> None:
        self.remote_host = str(remote_host)
        self.remote_port = int(remote_port)
        self.control_port = int(control_port)
        self.control_enabled = bool(control_enabled)
        self.route_name = str(route_name)
        self.route_state = str(route_state)
        self.auth_token = str(auth_token or "")
        self.auth_id = str(auth_id)
        self.send_fw_dev_probes = bool(send_fw_dev_probes)
        self.control_tick_s = max(0.2, float(control_tick_s))
        self.control_timeout_s = max(0.2, float(control_timeout_s))
        self.rx_control_enabled = bool(rx_control_enabled)
        self.rx_route_name = str(rx_route_name)
        self.rx_route_state = str(rx_route_state)
        self.rx_auth_token = str(rx_auth_token or "")
        self.rx_auth_id = str(rx_auth_id)
        self.rx_update_state = str(rx_update_state)
        self.rx_send_fw_dev_probes = bool(rx_send_fw_dev_probes)
        self.rx_control_tick_s = max(0.2, float(rx_control_tick_s))
        self.rx_control_timeout_s = max(0.2, float(rx_control_timeout_s))
        self.local_host = str(local_host)
        self.local_port = int(local_port)
        self._ctrl_sock: socket.socket | None = None
        self._rx_listener_sock: socket.socket | None = None
        self._rx_ctrl_sock: socket.socket | None = None
        self._rx_ctrl_buffer = ""
        self._rx_lock = threading.Lock()
        self._active_route_state = self.route_state
        self._next_control_tick_s = 0.0
        self._rx_active_route_state = self.rx_route_state
        self._next_rx_control_tick_s = 0.0
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if socket_timeout is not None:
            self._sock.settimeout(float(socket_timeout))
        self._sock.bind((self.local_host, self.local_port))
        
        # Initialize RX listener socket early so gateway can connect immediately
        if self.rx_control_enabled:
            self._open_rx_control_listener()

    def close(self) -> None:
        if self._ctrl_sock is not None:
            try:
                self._ctrl_sock.close()
            except Exception:
                pass
            self._ctrl_sock = None
        if self._rx_ctrl_sock is not None:
            try:
                self._rx_ctrl_sock.close()
            except Exception:
                pass
            self._rx_ctrl_sock = None
        if self._rx_listener_sock is not None:
            try:
                self._rx_listener_sock.close()
            except Exception:
                pass
            self._rx_listener_sock = None
        self._sock.close()

    def _ctrl_send(self, payload: bytes) -> None:
        if self._ctrl_sock is None:
            raise RuntimeError("PCAN control socket is not connected")
        self._ctrl_sock.sendall(payload)

    def _ctrl_recv_until(self, required: str, timeout_s: float | None = None) -> str:
        if self._ctrl_sock is None:
            raise RuntimeError("PCAN control socket is not connected")
        limit_s = self.control_timeout_s if timeout_s is None else max(0.1, float(timeout_s))
        deadline = time.monotonic() + limit_s
        text = ""
        while time.monotonic() < deadline:
            try:
                data = self._ctrl_sock.recv(4096)
            except socket.timeout:
                continue
            except Exception as exc:
                raise RuntimeError(f"PCAN control receive failed: {exc}") from exc
            if not data:
                raise RuntimeError("PCAN control connection closed by gateway")
            chunk = data.decode("ascii", "replace")
            text += chunk
            if required in text:
                return text
        raise RuntimeError(f"PCAN control timeout waiting for {required}")

    @staticmethod
    def _extract_attr(text: str, key: str) -> str:
        quoted = re.search(rf'{re.escape(key)}="([^"]*)"', text)
        if quoted:
            return quoted.group(1)
        bare = re.search(rf"{re.escape(key)}=([^\s>]+)", text)
        return bare.group(1) if bare else ""

    def _build_route_req(self) -> bytes:
        # Format: state as hex value, numeric attrs unquoted, string attrs quoted
        # CAN params match PCAN gateway defaults: 1Mbps, sample point 75%, etc.
        state_hex = int(self.route_state, 0) if isinstance(self.route_state, str) else self.route_state
        msg = (
            f'<ROUTE_REQ kver=2.3.20 mac=0C:72:4B:4A:57:52 partno="IPES-004100" '
            f'devicename="LABBREW-TRANSPORT" name="{self.route_name}" '
            f'state=0x{state_hex:08x} can="can0" bus_state=0x0 fpp=15 ifisup=1 '
            f'can_state=0 bitrate=1000000 sample_point=750 tq=125 prop_seg=2 '
            f'phase_seg1=3 phase_seg2=2 sjw=1 brp=3 clkhz=24000000 restart_ms=1 '
            f'warn_limit=-1 listen_only=0 tripple_sampling=0 port={self.remote_port} '
            f'proto="udp">'
        )
        return msg.encode("ascii")

    def _build_route_auth_req(self) -> bytes:
        msg = f'<ROUTE_AUTH_REQ rtauth="{self.auth_token}" id="{self.auth_id}">'
        return msg.encode("ascii")

    def _build_rx_route_req(self) -> bytes:
        # Format: state as hex value, numeric attrs unquoted, string attrs quoted
        # CAN params match PCAN gateway defaults: 1Mbps, sample point 75%, etc.
        state_hex = int(self.rx_route_state, 0) if isinstance(self.rx_route_state, str) else self.rx_route_state
        msg = (
            f'<ROUTE_REQ kver=2.3.20 mac=0C:72:4B:4A:57:52 partno="IPES-004100" '
            f'devicename="LABBREW-TRANSPORT" name="{self.rx_route_name}" '
            f'state=0x{state_hex:08x} can="can0" bus_state=0x0 fpp=15 ifisup=1 '
            f'can_state=0 bitrate=1000000 sample_point=750 tq=125 prop_seg=2 '
            f'phase_seg1=3 phase_seg2=2 sjw=1 brp=3 clkhz=24000000 restart_ms=1 '
            f'warn_limit=-1 listen_only=0 tripple_sampling=0 port={self.local_port} '
            f'proto="udp">'
        )
        return msg.encode("ascii")

    def _build_rx_route_auth_req(self) -> bytes:
        msg = f'<ROUTE_AUTH_REQ rtauth="{self.rx_auth_token}" id="{self.rx_auth_id}">'
        return msg.encode("ascii")

    def _build_rx_route_update_req(self) -> bytes:
        state = self.rx_update_state or self._rx_active_route_state
        msg = (
            f'<ROUTE_UPDATE_REQ status="0" name="{self.rx_route_name}" '
            f'can="can0" fpp="15" state="{state}">'
        )
        return msg.encode("ascii")

    def _build_route_update_req(self) -> bytes:
        msg = (
            f'<ROUTE_UPDATE_REQ status="0" name="{self.route_name}" '
            f'can="can0" fpp="15" state="{self._active_route_state}">'
        )
        return msg.encode("ascii")

    def _open_control_session(self) -> None:
        try:
            self._ctrl_sock = socket.create_connection((self.remote_host, self.control_port), timeout=self.control_timeout_s)
            self._ctrl_sock.settimeout(self.control_timeout_s)
        except Exception as exc:
            self._ctrl_sock = None
            raise RuntimeError(f"PCAN control connect failed to {self.remote_host}:{self.control_port}: {exc}") from exc

        self._ctrl_send(b"<HEJ_REQ pver=2.1.1 uver=1.7.2>")
        _ = self._ctrl_recv_until("HEJ_CNF")

        self._ctrl_send(self._build_route_req())
        route_cnf_text = self._ctrl_recv_until("ROUTE_CNF")
        route_cnf_match = re.search(r"<ROUTE_CNF[^>]*>", route_cnf_text)
        route_cnf = route_cnf_match.group(0) if route_cnf_match else route_cnf_text
        status_txt = self._extract_attr(route_cnf, "status") or "0"
        try:
            status = int(status_txt)
        except Exception:
            status = -1
        if status != 0:
            errno = self._extract_attr(route_cnf, "errno") or "?"
            errmsg = self._extract_attr(route_cnf, "errmsg") or "route rejected"
            raise RuntimeError(f"PCAN route rejected: status={status} errno={errno} errmsg={errmsg}")

        state = self._extract_attr(route_cnf, "state")
        if state:
            self._active_route_state = state

        if self.auth_token:
            self._ctrl_send(self._build_route_auth_req())
            auth_text = self._ctrl_recv_until("ROUTE_AUTH_CNF")
            auth_match = re.search(r"<ROUTE_AUTH_CNF[^>]*>", auth_text)
            auth_cnf = auth_match.group(0) if auth_match else auth_text
            auth_status_txt = self._extract_attr(auth_cnf, "status") or "0"
            try:
                auth_status = int(auth_status_txt)
            except Exception:
                auth_status = -1
            if auth_status != 0:
                raise RuntimeError(f"PCAN route auth rejected: status={auth_status_txt}")

        self._ctrl_send(self._build_route_update_req())
        if self.send_fw_dev_probes:
            self._ctrl_send(b"<FW_INFO_REQ>")
            self._ctrl_send(b"<DEV_GET_ID_REQ>")

        self._next_control_tick_s = time.monotonic() + self.control_tick_s

    def _open_rx_control_listener(self) -> None:
        try:
            self._rx_listener_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._rx_listener_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._rx_listener_sock.bind((self.local_host, self.control_port))
            self._rx_listener_sock.listen(1)
            self._rx_listener_sock.settimeout(0.1)
        except Exception as exc:
            self._rx_listener_sock = None
            raise RuntimeError(f"PCAN RX control listen failed on {self.local_host}:{self.control_port}: {exc}") from exc

    def _rx_send(self, payload: bytes) -> None:
        if self._rx_ctrl_sock is None:
            return
        self._rx_ctrl_sock.sendall(payload)

    def _build_rx_route_cnf(self) -> bytes:
        msg = (
            f'<ROUTE_CNF status="0" kver="0.0.0" mac="0C:72:4B:4A:57:52" partno="IPES-004100" '
            f'serno="0" name="{self.rx_route_name}" devicename="LABBREW-TRANSPORT" '
            f'can="can0" fpp="15" state="{self.rx_route_state}" nonces="1189146542">'
        )
        return msg.encode("ascii")

    def _build_rx_route_auth_cnf(self) -> bytes:
        return b'<ROUTE_AUTH_CNF noncec="4294937910" id="(c) PEAK-System">'

    @staticmethod
    def _build_fw_info_cnf() -> bytes:
        return b"<FW_INFO_CNF status=0 pver=2.1.1 uver=1.7.2 kver=2.3.20 lver=50a2fh fwver=3.0.1>"

    @staticmethod
    def _build_dev_get_id_cnf() -> bytes:
        return b"<DEV_GET_ID_CNF device_id=4294967295>"

    @staticmethod
    def _build_can_info_cnf() -> bytes:
        return (
            b'<CAN_INFO_CNF can="can0" ifisup=1 can_state=0 bitrate=1000000 sample_point=750 '
            b'tq=125 prop_seg=2 phase_seg1=3 phase_seg2=2 sjw=1 brp=3 clkhz=24000000 '
            b'restart_ms=1 warn_limit=-1 listen_only=0 tripple_sampling=0 status=0>'
        )

    def _handle_rx_control_tags(self, text: str) -> None:
        tags = re.findall(r"<[^>]+>", text)
        for tag in tags:
            if tag.startswith("<HEJ_REQ"):
                self._rx_send(b'<HEJ_CNF pver="2.0.2" uver="1.0.2">')
            elif tag.startswith("<ROUTE_REQ"):
                self._rx_send(self._build_rx_route_cnf())
            elif tag.startswith("<ROUTE_AUTH_REQ"):
                self._rx_send(self._build_rx_route_auth_cnf())
            elif tag.startswith("<FW_INFO_REQ"):
                self._rx_send(self._build_fw_info_cnf())
            elif tag.startswith("<DEV_GET_ID_REQ"):
                self._rx_send(self._build_dev_get_id_cnf())
            elif tag.startswith("<CAN_INFO_REQ"):
                self._rx_send(self._build_can_info_cnf())
            elif tag.startswith("<ROUTE_UPDATE_CNF"):
                continue

    def _ensure_control_session(self) -> None:
        if not self.control_enabled:
            return
        if self._ctrl_sock is None:
            self._open_control_session()
            return
        now = time.monotonic()
        if now < self._next_control_tick_s:
            return
        try:
            self._ctrl_send(self._build_route_update_req())
            self._ctrl_send(b'<CAN_INFO_REQ can="can0">')
            _ = self._ctrl_recv_until("CAN_INFO_CNF")
        except Exception as exc:
            if self._ctrl_sock is not None:
                try:
                    self._ctrl_sock.close()
                except Exception:
                    pass
            self._ctrl_sock = None
            raise RuntimeError(f"PCAN control session lost: {exc}") from exc
        self._next_control_tick_s = now + self.control_tick_s

    def _ensure_rx_control_session(self) -> None:
        if not self.rx_control_enabled:
            return
        with self._rx_lock:
            if self._rx_listener_sock is None:
                try:
                    self._open_rx_control_listener()
                except Exception:
                    return

            if self._rx_ctrl_sock is None:
                try:
                    conn, addr = self._rx_listener_sock.accept()
                    conn.settimeout(0.1)
                    self._rx_ctrl_sock = conn
                    self._rx_ctrl_buffer = ""
                    self._next_rx_control_tick_s = time.monotonic() + self.rx_control_tick_s
                except socket.timeout:
                    return
                except Exception:
                    return

            if self._rx_ctrl_sock is None:
                return

            try:
                chunk = self._rx_ctrl_sock.recv(4096)
                if chunk:
                    self._rx_ctrl_buffer += chunk.decode("ascii", "replace")
                    if ">" in self._rx_ctrl_buffer:
                        complete = self._rx_ctrl_buffer.rsplit(">", 1)
                        self._handle_rx_control_tags(complete[0] + ">")
                        self._rx_ctrl_buffer = complete[1]
                else:
                    raise RuntimeError("PCAN RX control connection closed by gateway")
            except socket.timeout:
                pass
            except Exception:
                try:
                    self._rx_ctrl_sock.close()
                except Exception:
                    pass
                self._rx_ctrl_sock = None
                self._rx_ctrl_buffer = ""
                return

            now = time.monotonic()
            if now >= self._next_rx_control_tick_s:
                try:
                    self._rx_send(self._build_rx_route_update_req())
                except Exception:
                    try:
                        self._rx_ctrl_sock.close()
                    except Exception:
                        pass
                    self._rx_ctrl_sock = None
                    self._rx_ctrl_buffer = ""
                    return
                self._next_rx_control_tick_s = now + self.rx_control_tick_s

    def send_frame(self, frame: RawCanFrame) -> None:
        self._ensure_control_session()
        self._ensure_rx_control_session()
        payload = build_gateway_frame(frame)
        arb_id = int(frame.arbitration_id)
        payload_hex = payload.hex()
        print(f"[PCAN_TX] CAN_ID=0x{arb_id:08X}, len={len(payload)}, payload_hex={payload_hex[:60]}...")
        self._sock.sendto(payload, (self.remote_host, self.remote_port))

    def recv_frames(self, timeout: float | None = None) -> list[RawCanFrame]:
        self._ensure_control_session()
        self._ensure_rx_control_session()
        if timeout is None:
            packet, _addr = self._sock.recvfrom(4096)
            return parse_gateway_packet(packet)

        ready, _, _ = select.select([self._sock], [], [], timeout)
        if not ready:
            return []
        packet, _addr = self._sock.recvfrom(4096)
        return parse_gateway_packet(packet)
