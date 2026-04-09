from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

try:
    from .discovery import MdnsAdvertiser
except Exception:  # pragma: no cover
    MdnsAdvertiser = None


class Advertiser(Protocol):
    def start(self) -> bool: ...
    def update_services(self, services: tuple[str, ...]) -> bool: ...
    def close(self) -> None: ...


@dataclass(slots=True)
class NullAdvertiser:
    node_id: str

    def start(self) -> bool:
        return False

    def update_services(self, _services: tuple[str, ...]) -> bool:
        return False

    def close(self) -> None:
        return None


class DiscoveryPublisher:
    def __init__(
        self, *, node_id: str, node_name: str, port: int, api_path: str = "/agent/info"
    ) -> None:
        self.node_id = node_id
        self.node_name = node_name
        self.port = port
        self.api_path = api_path
        self._advertiser: Advertiser | None = None

    def publish_node(self, services: tuple[str, ...]) -> None:
        if MdnsAdvertiser is None:
            self._advertiser = self._advertiser or NullAdvertiser(self.node_id)
            return
        if self._advertiser is None:
            self._advertiser = MdnsAdvertiser(
                node_id=self.node_id,
                node_name=self.node_name,
                port=self.port,
                api_path=self.api_path,
                services=services,
            )
            self._advertiser.start()
            return
        self._advertiser.update_services(services)

    def close(self) -> None:
        if self._advertiser is not None:
            self._advertiser.close()
            self._advertiser = None
