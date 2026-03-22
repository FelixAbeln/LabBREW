from __future__ import annotations

import socket


def tcp_probe(host: str, port: int, timeout: float = 1.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "connection succeeded"
    except OSError as exc:
        return False, f"{exc.__class__.__name__}: {exc}"


def tcp_open(host: str, port: int, timeout: float = 1.0) -> bool:
    ok, _ = tcp_probe(host, port, timeout=timeout)
    return ok
