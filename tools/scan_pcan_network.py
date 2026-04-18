#!/usr/bin/env python3
"""Scan a local subnet for PEAK/PCAN-like gateway candidates.

This script builds a fingerprint for a known gateway host (default: 192.168.5.31)
and compares nearby hosts against it using:
- TCP service availability (80/443/8080)
- HTTP headers/title text
- UDP probe behavior on candidate PCAN ports (55001/55002 by default)
- ARP table MAC address lookup (Windows `arp -a`)

Usage examples:
  python tools/scan_pcan_network.py
  python tools/scan_pcan_network.py --network 192.168.5.0/24 --reference 192.168.5.31
  python tools/scan_pcan_network.py --ports 55001 55002 55300 --top 25
"""

from __future__ import annotations

import argparse
import concurrent.futures
import ipaddress
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html import unescape


def _extract_title(html_text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    text = unescape(match.group(1))
    return re.sub(r"\s+", " ", text).strip()


def _safe_decode(data: bytes) -> str:
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            return data.decode(encoding, errors="replace")
        except Exception:
            continue
    return ""


@dataclass
class HostFingerprint:
    ip: str
    tcp_open: list[int] = field(default_factory=list)
    udp_resp: list[int] = field(default_factory=list)
    http_server: str = ""
    http_title: str = ""
    http_status: int = 0
    rdns: str = ""
    arp_mac: str = ""
    errors: list[str] = field(default_factory=list)

    def as_row(self) -> str:
        tcp = ",".join(str(p) for p in self.tcp_open) or "-"
        udp = ",".join(str(p) for p in self.udp_resp) or "-"
        title = self.http_title[:42] + ("..." if len(self.http_title) > 42 else "")
        return (
            f"{self.ip:15}  tcp:{tcp:12} udp:{udp:10} "
            f"status:{self.http_status or '-':>3} server:{(self.http_server or '-')[:22]:22} "
            f"rdns:{(self.rdns or '-')[:24]:24} mac:{self.arp_mac or '-':17} title:{title or '-'}"
        )


def get_arp_table() -> dict[str, str]:
    mapping: dict[str, str] = {}
    try:
        proc = subprocess.run(
            ["arp", "-a"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        text = proc.stdout or ""
        # Windows format: "  192.168.5.31         00-11-22-33-44-55     dynamic"
        for line in text.splitlines():
            line = line.strip()
            m = re.match(
                r"^(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F\-]{17})\s+\w+",
                line,
            )
            if m:
                mapping[m.group(1)] = m.group(2).lower()
    except Exception:
        pass
    return mapping


def tcp_open(ip: str, port: int, timeout: float) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((ip, port)) == 0
    finally:
        sock.close()


def udp_probe_has_response(ip: str, port: int, timeout: float) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        # Minimal non-empty payload; many devices ignore it, which is fine.
        sock.sendto(b"\x00", (ip, port))
        _data, _addr = sock.recvfrom(1024)
        return True
    except Exception:
        return False
    finally:
        sock.close()


def http_probe(ip: str, timeout: float) -> tuple[int, str, str]:
    url = f"http://{ip}/"
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "LabBREW-PCAN-Scanner/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            server = str(resp.headers.get("Server") or "").strip()
            body = _safe_decode(resp.read(8192))
            return status, server, _extract_title(body)
    except urllib.error.HTTPError as e:
        server = str(getattr(e, "headers", {}).get("Server") or "").strip() if getattr(e, "headers", None) else ""
        return int(e.code or 0), server, ""
    except Exception:
        return 0, "", ""


def reverse_dns(ip: str) -> str:
    try:
        host, _aliases, _ips = socket.gethostbyaddr(ip)
        return host
    except Exception:
        return ""


def fingerprint_host(
    ip: str,
    tcp_ports: list[int],
    udp_ports: list[int],
    timeout: float,
    arp_map: dict[str, str],
) -> HostFingerprint:
    fp = HostFingerprint(ip=ip)

    for port in tcp_ports:
        try:
            if tcp_open(ip, port, timeout):
                fp.tcp_open.append(port)
        except Exception as exc:
            fp.errors.append(f"tcp:{port}:{type(exc).__name__}")

    if 80 in fp.tcp_open:
        status, server, title = http_probe(ip, timeout)
        fp.http_status = status
        fp.http_server = server
        fp.http_title = title

    for port in udp_ports:
        try:
            if udp_probe_has_response(ip, port, timeout):
                fp.udp_resp.append(port)
        except Exception as exc:
            fp.errors.append(f"udp:{port}:{type(exc).__name__}")

    fp.rdns = reverse_dns(ip)
    fp.arp_mac = arp_map.get(ip, "")
    return fp


def score_similarity(candidate: HostFingerprint, reference: HostFingerprint) -> int:
    score = 0

    ref_tcp = set(reference.tcp_open)
    cand_tcp = set(candidate.tcp_open)
    score += 20 * len(ref_tcp & cand_tcp)

    ref_udp = set(reference.udp_resp)
    cand_udp = set(candidate.udp_resp)
    score += 20 * len(ref_udp & cand_udp)

    if reference.http_status and candidate.http_status == reference.http_status:
        score += 10

    if reference.http_server and candidate.http_server:
        if reference.http_server.lower() == candidate.http_server.lower():
            score += 20
        elif any(
            token in candidate.http_server.lower()
            for token in re.split(r"[^a-z0-9]+", reference.http_server.lower())
            if token
        ):
            score += 10

    if reference.http_title and candidate.http_title:
        ref_tokens = {t for t in re.split(r"[^a-z0-9]+", reference.http_title.lower()) if t}
        cand_tokens = {t for t in re.split(r"[^a-z0-9]+", candidate.http_title.lower()) if t}
        overlap = len(ref_tokens & cand_tokens)
        score += min(20, overlap * 4)

    if reference.arp_mac and candidate.arp_mac:
        # Compare OUI (first 3 bytes)
        ref_oui = "-".join(reference.arp_mac.split("-")[:3])
        cand_oui = "-".join(candidate.arp_mac.split("-")[:3])
        if ref_oui and ref_oui == cand_oui:
            score += 15

    if reference.rdns and candidate.rdns:
        ref_name = reference.rdns.lower()
        cand_name = candidate.rdns.lower()
        if ref_name == cand_name:
            score += 10
        elif any(tok in cand_name for tok in re.split(r"[^a-z0-9]+", ref_name) if tok):
            score += 5

    return score


def build_host_list(network: str, reference: str) -> list[str]:
    net = ipaddress.ip_network(network, strict=False)
    out = [str(ip) for ip in net.hosts()]
    if reference in out:
        out.remove(reference)
        out.insert(0, reference)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan subnet for PCAN-like gateways and similarity pattern")
    parser.add_argument("--network", default="192.168.5.0/24", help="CIDR subnet to scan")
    parser.add_argument("--reference", default="192.168.5.31", help="Known gateway IP used as fingerprint baseline")
    parser.add_argument("--tcp-ports", nargs="*", type=int, default=[80, 443, 8080], help="TCP ports to test")
    parser.add_argument("--ports", nargs="*", type=int, default=[55001, 55002], help="UDP ports to probe")
    parser.add_argument("--timeout", type=float, default=0.3, help="Per-probe timeout seconds")
    parser.add_argument("--workers", type=int, default=64, help="Parallel workers")
    parser.add_argument("--top", type=int, default=20, help="Top candidate rows to print")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hosts = build_host_list(args.network, args.reference)
    arp_map = get_arp_table()

    print(f"Scanning {len(hosts)} hosts in {args.network} ...")
    print(f"Reference host: {args.reference}")
    print(f"TCP ports: {args.tcp_ports} | UDP ports: {args.ports} | timeout={args.timeout}s")
    print()

    t0 = time.time()
    fps: list[HostFingerprint] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futures = [
            ex.submit(fingerprint_host, ip, list(args.tcp_ports), list(args.ports), args.timeout, arp_map)
            for ip in hosts
        ]
        for fut in concurrent.futures.as_completed(futures):
            try:
                fps.append(fut.result())
            except Exception:
                pass

    elapsed = time.time() - t0
    print(f"Scan complete in {elapsed:.2f}s\n")

    by_ip = {fp.ip: fp for fp in fps}
    reference_fp = by_ip.get(args.reference)
    if reference_fp is None:
        print("Reference host was not scanned/found; cannot compute similarity.")
        return 1

    scored = []
    for fp in fps:
        if fp.ip == args.reference:
            continue
        score = score_similarity(fp, reference_fp)
        scored.append((score, fp))

    scored.sort(key=lambda item: item[0], reverse=True)

    print("Reference fingerprint:")
    print(reference_fp.as_row())
    print()

    print(f"Top {min(args.top, len(scored))} similarity matches:")
    for score, fp in scored[: args.top]:
        print(f"score:{score:3}  {fp.as_row()}")

    print()
    print("Likely gateway candidates (score >= 25):")
    likely = [(s, fp) for s, fp in scored if s >= 25]
    if not likely:
        print("  none")
    else:
        for score, fp in likely:
            print(f"  {fp.ip} (score {score})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
