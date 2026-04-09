from __future__ import annotations

import argparse
import signal
import threading
import time
from dataclasses import dataclass
from typing import Any

try:
    from zeroconf import ServiceBrowser, Zeroconf
except Exception:  # pragma: no cover - handled at runtime
    ServiceBrowser = None
    Zeroconf = None


DEFAULT_SERVICE_TYPE = "_fcs._tcp.local."
DEFAULT_EXPECTED_ROLE = "fermenter_agent"
DNS_SD_CATALOG_SERVICE_TYPE = "_services._dns-sd._udp.local."


def _decode_value(value: Any) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return ""
    return str(value or "")


def _decode_properties(properties: dict[Any, Any] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(properties, dict):
        return result
    for key, value in properties.items():
        result[_decode_value(key)] = _decode_value(value)
    return result


@dataclass
class SeenService:
    name: str
    address: str
    port: int
    host: str
    node_id: str
    node_name: str
    role: str
    relevant: bool
    last_event: str
    last_seen_monotonic: float


@dataclass
class SeenServiceType:
    service_type: str
    relevant: bool
    last_event: str
    last_seen_monotonic: float


class MdnsProbeListener:
    def __init__(
        self, zeroconf: Any, service_type: str, expected_role: str, verbose_props: bool
    ) -> None:
        self._zeroconf = zeroconf
        self._service_type = service_type
        self._expected_role = expected_role
        self._verbose_props = verbose_props
        self._lock = threading.Lock()
        self._seen: dict[str, SeenService] = {}

    def add_service(self, _zeroconf: Any, _service_type: str, name: str) -> None:
        self._refresh(name, "ADD")

    def update_service(self, _zeroconf: Any, _service_type: str, name: str) -> None:
        self._refresh(name, "UPD")

    def remove_service(self, _zeroconf: Any, _service_type: str, name: str) -> None:
        with self._lock:
            previous = self._seen.pop(name, None)
        stamp = time.strftime("%H:%M:%S")
        if previous is None:
            print(f"[{stamp}] DEL {name} (not tracked)")
        else:
            print(
                f"[{stamp}] DEL {name} addr={previous.address}:{previous.port} "
                f"node_id={previous.node_id} role={previous.role}"
            )

    def _refresh(self, name: str, event: str) -> None:
        try:
            info = self._zeroconf.get_service_info(
                self._service_type, name, timeout=1000
            )
        except Exception as exc:
            stamp = time.strftime("%H:%M:%S")
            print(f"[{stamp}] {event} {name} info_error={exc}")
            return

        if info is None:
            stamp = time.strftime("%H:%M:%S")
            print(f"[{stamp}] {event} {name} info=<none>")
            return

        try:
            addresses = info.parsed_addresses()
        except Exception:
            addresses = []
        address = addresses[0] if addresses else ""

        props = _decode_properties(getattr(info, "properties", {}) or {})
        role = props.get("role") or ""
        node_id = props.get("node_id") or ""
        node_name = props.get("node_name") or ""
        host = (props.get("hostname") or getattr(info, "server", "") or "").rstrip(".")
        relevant = role == self._expected_role

        seen = SeenService(
            name=name,
            address=address,
            port=int(getattr(info, "port", 0) or 0),
            host=host,
            node_id=node_id,
            node_name=node_name,
            role=role,
            relevant=relevant,
            last_event=event,
            last_seen_monotonic=time.monotonic(),
        )

        with self._lock:
            self._seen[name] = seen

        stamp = time.strftime("%H:%M:%S")
        status = "RELEVANT" if relevant else "other"
        print(
            f"[{stamp}] {event} {name} addr={seen.address}:{seen.port} "
            f"host={seen.host} node_id={seen.node_id} "
            f"role={seen.role or '-'} [{status}]"
        )
        if self._verbose_props:
            print(f"[{stamp}]      TXT={props}")

    def print_summary(self) -> None:
        stamp = time.strftime("%H:%M:%S")
        with self._lock:
            rows = sorted(self._seen.values(), key=lambda item: item.name.lower())

        relevant_rows = [row for row in rows if row.relevant]
        print(
            f"[{stamp}] SUMMARY total={len(rows)} relevant={len(relevant_rows)} "
            f"service_type={self._service_type}"
        )
        for row in rows:
            age_s = max(0.0, time.monotonic() - row.last_seen_monotonic)
            marker = "*" if row.relevant else "-"
            print(
                f"[{stamp}]   {marker} {row.name} {row.address}:{row.port} "
                f"node_id={row.node_id or '-'} role={row.role or '-'} age={age_s:.1f}s"
            )


class DnsSdCatalogListener:
    def __init__(self, relevant_service_types: set[str]) -> None:
        self._relevant_service_types = relevant_service_types
        self._lock = threading.Lock()
        self._seen: dict[str, SeenServiceType] = {}

    def add_service(self, zeroconf: Any, service_type: str, name: str) -> None:
        _ = (zeroconf, service_type)
        self._record(name, "ADD")

    def update_service(self, zeroconf: Any, service_type: str, name: str) -> None:
        _ = (zeroconf, service_type)
        self._record(name, "UPD")

    def remove_service(self, zeroconf: Any, service_type: str, name: str) -> None:
        _ = (zeroconf, service_type)
        with self._lock:
            previous = self._seen.pop(name, None)
        stamp = time.strftime("%H:%M:%S")
        if previous is None:
            print(f"[{stamp}] DEL {name} (not tracked)")
            return
        print(f"[{stamp}] DEL {name}")

    def _record(self, service_name: str, event: str) -> None:
        normalized = service_name if service_name.endswith(".") else f"{service_name}."
        relevant = normalized in self._relevant_service_types
        seen = SeenServiceType(
            service_type=normalized,
            relevant=relevant,
            last_event=event,
            last_seen_monotonic=time.monotonic(),
        )
        with self._lock:
            self._seen[normalized] = seen

        stamp = time.strftime("%H:%M:%S")
        status = "RELEVANT" if relevant else "other"
        print(f"[{stamp}] {event} {normalized} [{status}]")

    def print_summary(self) -> None:
        stamp = time.strftime("%H:%M:%S")
        with self._lock:
            rows = sorted(
                self._seen.values(), key=lambda item: item.service_type.lower()
            )
        relevant_rows = [row for row in rows if row.relevant]
        print(
            f"[{stamp}] SUMMARY service_types total={len(rows)} "
            f"relevant={len(relevant_rows)}"
        )
        for row in rows:
            age_s = max(0.0, time.monotonic() - row.last_seen_monotonic)
            marker = "*" if row.relevant else "-"
            print(f"[{stamp}]   {marker} {row.service_type} age={age_s:.1f}s")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Raw mDNS probe for _fcs._tcp.local services "
            "with relevance filtering."
        )
    )
    parser.add_argument(
        "--service-type",
        default=DEFAULT_SERVICE_TYPE,
        help="Service type to browse (default: _fcs._tcp.local.)",
    )
    parser.add_argument(
        "--expected-role",
        default=DEFAULT_EXPECTED_ROLE,
        help="Role in TXT to mark as relevant (default: fermenter_agent)",
    )
    parser.add_argument(
        "--summary-every",
        type=float,
        default=10.0,
        help="Print a periodic summary every N seconds (0 to disable)",
    )
    parser.add_argument(
        "--verbose-props",
        action="store_true",
        help="Print decoded TXT properties on each add/update event",
    )
    parser.add_argument(
        "--dns-sd-catalog",
        action="store_true",
        help=(
            "Browse _services._dns-sd._udp.local and list "
            "all advertised service types"
        ),
    )
    parser.add_argument(
        "--relevant-service-type",
        action="append",
        default=[],
        help=(
            "Service type to mark as relevant in DNS-SD "
            "catalog mode (can be repeated)"
        ),
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    if Zeroconf is None or ServiceBrowser is None:
        print("zeroconf package is not available. Install dependency 'zeroconf' first.")
        return 2

    service_type = str(args.service_type or "").strip() or DEFAULT_SERVICE_TYPE
    if not service_type.endswith("."):
        service_type = f"{service_type}."

    expected_role = str(args.expected_role or "").strip() or DEFAULT_EXPECTED_ROLE
    summary_every = max(0.0, float(args.summary_every))
    use_dns_sd_catalog = bool(args.dns_sd_catalog)

    relevant_service_types: set[str] = {DEFAULT_SERVICE_TYPE}
    for item in args.relevant_service_type:
        normalized = str(item or "").strip()
        if not normalized:
            continue
        if not normalized.endswith("."):
            normalized = f"{normalized}."
        relevant_service_types.add(normalized)

    if use_dns_sd_catalog:
        service_type = DNS_SD_CATALOG_SERVICE_TYPE

    stop_event = threading.Event()

    def _on_signal(_sig: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_signal)

    if use_dns_sd_catalog:
        relevant_display = ", ".join(sorted(relevant_service_types))
        print(f"Starting DNS-SD catalog probe for service_type={service_type}")
        print(f"Relevant service types: {relevant_display}")
    else:
        print(
            f"Starting mDNS probe for service_type={service_type} "
            f"expected_role={expected_role}"
        )
    print("Press Ctrl+C to stop.")

    zc = Zeroconf()
    if use_dns_sd_catalog:
        listener: Any = DnsSdCatalogListener(
            relevant_service_types=relevant_service_types
        )
    else:
        listener = MdnsProbeListener(
            zc,
            service_type=service_type,
            expected_role=expected_role,
            verbose_props=args.verbose_props,
        )
    browser = ServiceBrowser(zc, service_type, listener)
    _ = browser

    next_summary = (
        time.monotonic() + summary_every if summary_every > 0.0 else float("inf")
    )

    try:
        while not stop_event.wait(0.25):
            if summary_every > 0.0 and time.monotonic() >= next_summary:
                listener.print_summary()
                next_summary = time.monotonic() + summary_every
    finally:
        listener.print_summary()
        zc.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
