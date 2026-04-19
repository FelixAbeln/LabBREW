#!/usr/bin/env python3
"""Broadcast probe utility to discover UDP-based gateway discovery behavior.

Sends small probe payloads to subnet broadcast + global broadcast over a range
of ports, then listens for replies and prints source IP/port + payload preview.

Usage:
  python tools/probe_gateway_discovery_udp.py
  python tools/probe_gateway_discovery_udp.py --network 192.168.5.0/24 --ports 55000 55001 55002 30400
"""

from __future__ import annotations

import argparse
import ipaddress
import socket
import time
from typing import Iterable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UDP broadcast discovery probe")
    parser.add_argument("--network", default="192.168.5.0/24", help="CIDR subnet")
    parser.add_argument("--ports", nargs="*", type=int, default=[55000, 55001, 55002, 55003, 30400, 45300])
    parser.add_argument("--listen-seconds", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=0.25)
    return parser.parse_args()


def subnet_broadcast(network: str) -> str:
    return str(ipaddress.ip_network(network, strict=False).broadcast_address)


def payloads() -> Iterable[bytes]:
    # Probe variants; many devices ignore unknown payloads, but replies are useful clues.
    return [
        b"",
        b"DISCOVER",
        b"PCAN_DISCOVER",
        b"PEAK",
        b"WHOIS",
        b"\x00",
        b"\x55\xaa\x55\xaa",
    ]


def main() -> int:
    args = parse_args()
    bcast = subnet_broadcast(args.network)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", 0))
    sock.settimeout(args.timeout)

    local_port = sock.getsockname()[1]
    print(f"Local UDP socket: 0.0.0.0:{local_port}")
    print(f"Subnet broadcast: {bcast}")
    print(f"Ports: {args.ports}")

    targets = [bcast, "255.255.255.255"]
    sent = 0
    for addr in targets:
        for port in args.ports:
            for data in payloads():
                try:
                    sock.sendto(data, (addr, int(port)))
                    sent += 1
                except Exception:
                    pass
    print(f"Sent {sent} probe datagrams; listening for replies...\n")

    deadline = time.time() + max(0.1, float(args.listen_seconds))
    seen: set[tuple[str, int, bytes]] = set()
    while time.time() < deadline:
        try:
            data, src = sock.recvfrom(4096)
        except socket.timeout:
            continue
        except Exception:
            break

        key = (src[0], src[1], data[:64])
        if key in seen:
            continue
        seen.add(key)

        preview = data[:64].hex(" ")
        print(f"reply from {src[0]}:{src[1]} len={len(data)}")
        print(f"  hex: {preview}")

    if not seen:
        print("No UDP discovery replies captured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
