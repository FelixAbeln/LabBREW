from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import socket

try:
    from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf
except Exception:
    ServiceBrowser = None
    ServiceInfo = None
    Zeroconf = None


SERVICE_TYPE = "_fcs._tcp.local."


def _local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        sock.close()
    return ip


def _hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "fcs-service"


def _decode_property(value: Any) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    return str(value or "")


class _DiscoveryListener:
    def __init__(self, owner: "MdnsDiscoveryBrowser") -> None:
        self.owner = owner

    def add_service(self, zeroconf: Any, service_type: str, name: str) -> None:
        self.owner._refresh_service(name)

    def update_service(self, zeroconf: Any, service_type: str, name: str) -> None:
        self.owner._refresh_service(name)

    def remove_service(self, zeroconf: Any, service_type: str, name: str) -> None:
        self.owner._remove_service(name)


@dataclass(slots=True)
class MdnsAdvertiser:
    service_label: str
    port: int
    path: str = "/status"
    zeroconf: Optional[Any] = field(init=False, default=None)
    info: Optional[Any] = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.zeroconf = Zeroconf() if Zeroconf is not None else None

    def start(self) -> bool:
        if self.zeroconf is None or ServiceInfo is None:
            return False

        ip = _local_ip()
        host = _hostname()
        instance_name = f"{host} {self.service_label}.{SERVICE_TYPE}"
        server_name = f"{host}.local."

        props = {
            b"path": self.path.encode(),
            b"proto": b"http",
            b"hostname": host.encode(),
            b"label": self.service_label.encode(),
        }

        self.info = ServiceInfo(
            type_=SERVICE_TYPE,
            name=instance_name,
            addresses=[socket.inet_aton(ip)],
            port=self.port,
            properties=props,
            server=server_name,
        )
        self.zeroconf.register_service(self.info)
        return True

    def close(self) -> None:
        if self.zeroconf is None:
            return
        if self.info is not None:
            try:
                self.zeroconf.unregister_service(self.info)
            except Exception:
                pass
        self.zeroconf.close()


@dataclass(slots=True)
class MdnsDiscoveryBrowser:
    service_type: str = SERVICE_TYPE
    zeroconf: Optional[Any] = field(init=False, default=None)
    browser: Optional[Any] = field(init=False, default=None)
    listener: Optional[Any] = field(init=False, default=None)
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
        address = addresses[0] if addresses else ""
        properties = getattr(info, "properties", {}) or {}
        host = _decode_property(properties.get(b"hostname")) or getattr(info, "server", "") or ""
        host = host.rstrip(".")
        label = _decode_property(properties.get(b"label")) or name.split(".", 1)[0].strip()
        path = _decode_property(properties.get(b"path")) or "/status"
        proto = _decode_property(properties.get(b"proto")) or "http"

        self._services[name] = {
            "name": name,
            "display_name": label,
            "host": host,
            "address": address,
            "port": int(getattr(info, "port", 0) or 0),
            "path": path,
            "proto": proto,
        }

    def _remove_service(self, name: str) -> None:
        self._services.pop(name, None)

    def snapshot(self) -> list[dict[str, Any]]:
        return sorted(self._services.values(), key=lambda item: ((item.get("display_name") or "").lower(), (item.get("host") or item.get("address") or "").lower()))

    def close(self) -> None:
        self._services.clear()
        if self.zeroconf is not None:
            try:
                self.zeroconf.close()
            except Exception:
                pass
        self.browser = None
        self.listener = None
        self.zeroconf = None
