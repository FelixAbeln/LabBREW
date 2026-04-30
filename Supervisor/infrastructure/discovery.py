from __future__ import annotations

import contextlib
import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Any

try:
    from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf
except Exception:
    ServiceBrowser = None
    ServiceInfo = None
    Zeroconf = None

SERVICE_TYPE = "_fcs._tcp.local."


def _local_ip() -> str:
    # Prefer directly enumerated host addresses before route probing.
    try:
        _, _, host_addresses = socket.gethostbyname_ex(socket.gethostname())
        for candidate in host_addresses:
            if candidate and not candidate.startswith("127."):
                return candidate
    except OSError:
        pass

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        sock.close()
    return ip


def _resolve_advertise_ip(advertise_host: str | None) -> str:
    def _is_usable_ipv4(candidate: str) -> bool:
        try:
            parsed = ipaddress.ip_address(candidate)
        except ValueError:
            return False
        if parsed.version != 4:
            return False
        return not (parsed.is_unspecified or parsed.is_loopback)

    raw_host = str(advertise_host or "").strip()
    if not raw_host:
        return _local_ip()

    try:
        socket.inet_aton(raw_host)
        if _is_usable_ipv4(raw_host):
            return raw_host
        return _local_ip()
    except OSError:
        pass

    try:
        resolved = socket.getaddrinfo(raw_host, None, socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return _local_ip()

    for entry in resolved:
        sockaddr = entry[4]
        if not sockaddr:
            continue
        candidate = str(sockaddr[0] or "").strip()
        if candidate and _is_usable_ipv4(candidate):
            return candidate

    return _local_ip()


def _hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "fcs-node"


def _decode_property(value: Any) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    return str(value or "")


class _DiscoveryListener:
    def __init__(self, owner: MdnsDiscoveryBrowser) -> None:
        self.owner = owner

    def add_service(self, _zeroconf: Any, _service_type: str, name: str) -> None:
        self.owner._refresh_service(name)

    def update_service(self, _zeroconf: Any, _service_type: str, name: str) -> None:
        self.owner._refresh_service(name)

    def remove_service(self, _zeroconf: Any, _service_type: str, name: str) -> None:
        self.owner._remove_service(name)


@dataclass(slots=True)
class MdnsAdvertiser:
    node_id: str
    node_name: str
    port: int
    api_path: str = "/agent/info"
    advertise_host: str | None = None
    services: tuple[str, ...] = ()
    zeroconf: Any | None = field(init=False, default=None)
    info: Any | None = field(init=False, default=None)

    def _service_info(self, *, ip: str, services: tuple[str, ...]) -> Any:
        host = _hostname()
        instance_name = f"{self.node_id}.{SERVICE_TYPE}"
        server_name = f"{host}.local."
        props = {
            b"node_id": self.node_id.encode(),
            b"node_name": self.node_name.encode(),
            b"role": b"fermenter_agent",
            b"proto": b"http",
            b"api": self.api_path.encode(),
            b"services": ",".join(services).encode(),
            b"hostname": host.encode(),
        }

        return ServiceInfo(
            type_=SERVICE_TYPE,
            name=instance_name,
            addresses=[socket.inet_aton(ip)],
            port=self.port,
            properties=props,
            server=server_name,
        )

    def __post_init__(self) -> None:
        self.zeroconf = Zeroconf() if Zeroconf is not None else None

    def start(self) -> bool:
        if self.zeroconf is None or ServiceInfo is None:
            return False

        ip = _resolve_advertise_ip(self.advertise_host)
        self.info = self._service_info(ip=ip, services=self.services)
        self.zeroconf.register_service(self.info)
        return True

    def update_services(self, services: tuple[str, ...]) -> bool:
        if self.zeroconf is None or self.info is None:
            return False
        self.services = services
        ip = _resolve_advertise_ip(self.advertise_host)
        self.info = self._service_info(ip=ip, services=self.services)
        self.zeroconf.update_service(self.info)
        return True

    def close(self) -> None:
        if self.zeroconf is None:
            return
        if self.info is not None:
            with contextlib.suppress(Exception):
                self.zeroconf.unregister_service(self.info)
        self.zeroconf.close()


@dataclass(slots=True)
class MdnsDiscoveryBrowser:
    service_type: str = SERVICE_TYPE
    zeroconf: Any | None = field(init=False, default=None)
    browser: Any | None = field(init=False, default=None)
    listener: Any | None = field(init=False, default=None)
    _services: dict[str, dict[str, Any]] = field(init=False, default_factory=dict)

    def start(self) -> bool:
        if Zeroconf is None or ServiceBrowser is None:
            return False
        if self.zeroconf is not None:
            return True
        self.zeroconf = Zeroconf()
        self.listener = _DiscoveryListener(self)
        self.browser = ServiceBrowser(self.zeroconf, self.service_type, self.listener)
        return True

    def _refresh_service(self, name: str) -> None:
        if self.zeroconf is None:
            return
        try:
            info = self.zeroconf.get_service_info(self.service_type, name, timeout=1000)
        except Exception:
            return
        if info is None:
            return
        try:
            addresses = info.parsed_addresses()
        except Exception:
            addresses = []
        props = {
            _decode_property(k): _decode_property(v)
            for k, v in (info.properties or {}).items()
        }
        self._services[name] = {
            "name": name,
            "address": addresses[0] if addresses else "",
            "port": int(info.port),
            "server": str(info.server or ""),
            **props,
        }

    def _remove_service(self, name: str) -> None:
        self._services.pop(name, None)

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._services.values())

    def close(self) -> None:
        if self.zeroconf is not None:
            self.zeroconf.close()
            self.zeroconf = None
