"""
Standalone test script — sends Brewtools PWM frames to the PCAN gateway and
optionally listens for incoming CAN frames (e.g. RPM) on the RX port.

Usage:
    python test_agitator_pwm.py [pwm_percent] [channel]   # defaults: 25, 0
    python test_agitator_pwm.py [pwm_percent] [channel] --tx-only
    python test_agitator_pwm.py [pwm_percent] [channel] --rx
    python test_agitator_pwm.py --control-only
    python test_agitator_pwm.py 25 0 --host 192.168.5.37 --tx-port 55002 --rx

The script:
1. Builds the exact same UDP packet that service.py produces
2. Sends it to the gateway (TX port)
3. Optionally probes TCP control port (default 45321) with HEJ request
4. Optionally listens briefly on RX port and decodes any frames received

No LabBREW imports needed — all encoding is inlined here.
"""
import argparse
import socket
import struct
import sys
import time

# ── Gateway config ────────────────────────────────────────────────────────────
GATEWAY_HOST  = "192.168.5.37"
GATEWAY_TX_PORT = 55002   # PC → gateway → CAN
GATEWAY_RX_PORT = 55001   # CAN → gateway → PC
GATEWAY_CONTROL_PORT = 45321  # TCP control-plane

# ── Brewtools CAN constants ───────────────────────────────────────────────────
# CAN ID for PWM to agitator node 0:
#   priority=1 (MEDIUM), sender=8 (PLC), recv=6 (AGITATOR), node=0, msg=27 (PWM)
#   Hand-verified against PCAN-View: 0x0840301B
AGITATOR_NODE   = 0
PWM_CAN_ID      = 0x0840301B   # agitator node 0
START_MEAS_ID   = 0x0840281B   # start measurement to agitator node 0 (example)

# ── PCAN Gateway UDP frame format ─────────────────────────────────────────────
TYPE_CLASSIC = 0x0080

def build_gateway_frame(arb_id: int, data: bytes, channel: int = 0) -> bytes:
    """Encode a classic CAN frame into the PCAN Gateway UDP wire format."""
    dlc = len(data)
    assert 0 <= dlc <= 8, f"DLC must be 0-8, got {dlc}"

    flags = 0x0002  # extended ID (PEAK gateway format)
    can_word = (arb_id & 0x1FFFFFFF) | 0x80000000  # extended ID marker

    body = bytearray()
    body.extend(b"\x00\x00")                   # length placeholder (filled below)
    body.extend(struct.pack(">H", TYPE_CLASSIC))
    body.extend(b"\x00" * 8)                   # timestamp (8 bytes, zeroed)
    body.extend(struct.pack(">I", 0))           # reserved
    body.extend(struct.pack(">I", 0))           # reserved
    body.append(channel & 0xFF)                 # CAN channel
    body.append(dlc & 0xFF)                     # DLC
    body.extend(struct.pack(">H", flags))
    body.extend(struct.pack(">I", can_word))
    body.extend(data)
    struct.pack_into(">H", body, 0, len(body))  # fill length field
    return bytes(body)


def parse_gateway_packet(packet: bytes) -> list[dict]:
    """Decode incoming gateway UDP frames. Returns list of frame dicts."""
    frames = []
    offset = 0
    while offset < len(packet):
        if len(packet) - offset < 28:
            break
        length   = struct.unpack_from(">H", packet, offset)[0]
        msg_type = struct.unpack_from(">H", packet, offset + 2)[0]
        if length < 28 or offset + length > len(packet):
            break
        flags    = struct.unpack_from(">H", packet, offset + 22)[0]
        can_word = struct.unpack_from(">I", packet, offset + 24)[0]
        dlc      = packet[offset + 21]
        channel  = packet[offset + 20]
        arb_id   = can_word & 0x1FFFFFFF
        is_ext   = bool(can_word & 0x80000000)
        data     = bytes(packet[offset + 28 : offset + 28 + dlc])
        frames.append({
            "arb_id": arb_id,
            "data":   data,
            "dlc":    dlc,
            "ext":    is_ext,
            "ch":     channel,
            "msg_type": msg_type,
        })
        offset += length
    return frames


def build_pwm_payload(pct: int) -> bytes:
    """subindex (1 byte) + uint32 big-endian (4 bytes) = 5 bytes."""
    pct = max(0, min(100, pct))
    return bytes([0]) + pct.to_bytes(4, "big")


def decode_rpm(data: bytes) -> str:
    """Attempt to decode RPM from a CAN frame (uint32 BE after subindex)."""
    if len(data) >= 5:
        rpm = int.from_bytes(data[1:5], "big")
        return f"{rpm} RPM (uint32 BE)"
    if len(data) == 4:
        rpm = int.from_bytes(data, "big")
        return f"{rpm} RPM (uint32 BE, no subindex)"
    return f"raw={data.hex()}"


def probe_control_port(host: str, port: int, timeout_s: float) -> bool:
    """Connect to gateway control port and attempt a HEJ exchange."""
    req = b"<HEJ_REQ pver=2.1.1 uver=1.7.2>"
    print(f"\n[CTRL] Probing TCP control plane {host}:{port} (timeout {timeout_s:.1f}s)")
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_s) as sock:
            print("[CTRL] TCP connect: OK")
            sock.settimeout(timeout_s)
            sock.sendall(req)
            print(f"[CTRL] Sent HEJ_REQ: {req.decode('ascii')}")
            data = sock.recv(4096)
            text = data.decode("ascii", errors="replace") if data else ""
            if not text:
                print("[CTRL] No response payload.")
                return True
            print(f"[CTRL] RX: {text}")
            if "HEJ_CNF" in text:
                print("[CTRL] HEJ handshake: OK")
                return True
            print("[CTRL] Connected but response did not include HEJ_CNF.")
            return True
    except Exception as exc:
        print(f"[CTRL] FAILED: {exc}")
        return False


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send Brewtools PWM frames to PCAN gateway and optionally verify control/RX flow.")
    parser.add_argument("pwm_percent", nargs="?", type=int, default=25)
    parser.add_argument("channel", nargs="?", type=int, default=0)
    parser.add_argument("--host", default=GATEWAY_HOST, help="Gateway host/IP")
    parser.add_argument("--tx-port", type=int, default=GATEWAY_TX_PORT, help="Gateway UDP TX port (PC -> gateway)")
    parser.add_argument("--rx-port", type=int, default=GATEWAY_RX_PORT, help="Gateway UDP RX port (gateway -> PC)")
    parser.add_argument("--control-port", type=int, default=GATEWAY_CONTROL_PORT, help="Gateway TCP control port")
    parser.add_argument("--rx-timeout", type=float, default=3.0, help="RX listen duration in seconds")
    parser.add_argument("--tcp-timeout", type=float, default=1.5, help="TCP control probe timeout in seconds")
    parser.add_argument("--tx-only", action="store_true", help="Only send UDP PWM frames")
    parser.add_argument("--rx", action="store_true", help="After TX, bind/listen on UDP RX port")
    parser.add_argument("--control-only", action="store_true", help="Only test TCP control-plane connectivity/HEJ")
    parser.add_argument(
        "--control-check",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable or disable TCP control-plane probe",
    )
    return parser.parse_args(argv)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    args = parse_args(sys.argv[1:])
    pwm_pct = int(args.pwm_percent)
    channel = int(args.channel)
    tx_only = bool(args.tx_only) or (not bool(args.rx))

    if args.control_check or args.control_only:
        control_ok = probe_control_port(args.host, args.control_port, args.tcp_timeout)
        if args.control_only:
            raise SystemExit(0 if control_ok else 2)

    print(f"Target PWM: {pwm_pct}%")
    print(f"CAN channel: {channel}")
    print(f"Mode:       {'TX-only' if tx_only else 'TX+RX'}")
    print(
        f"Gateway:    {args.host}  TX→{args.tx_port}  RX←{args.rx_port}  CTRL:{args.control_port}"
    )

    # Build the PWM frame
    payload = build_pwm_payload(pwm_pct)
    udp_frame = build_gateway_frame(PWM_CAN_ID, payload, channel=channel)

    print(f"\n[TX] CAN_ID=0x{PWM_CAN_ID:08X}  DLC={len(payload)}  data={payload.hex()}")
    print(f"     UDP frame ({len(udp_frame)} bytes): {udp_frame.hex()}")

    # TX socket → gateway
    tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tx_sock.sendto(udp_frame, (args.host, args.tx_port))
    print("[TX] Sent.")

    # Send again with a small delay (some gateways need a moment)
    time.sleep(0.1)
    tx_sock.sendto(udp_frame, (args.host, args.tx_port))
    print("[TX] Sent again (2nd).")

    if tx_only:
        tx_sock.close()
        print("\nDone (TX-only).")
        return

    # RX socket — listen for CAN frames coming back from the bus.
    # If RX port is already occupied (e.g. by supervisor), keep TX test successful.
    rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        rx_sock.bind(("0.0.0.0", args.rx_port))
    except OSError as exc:
        rx_sock.close()
        print(f"\n[RX] Skipped: could not bind :{args.rx_port} ({exc}).")
        print("[RX] Another process is already listening. TX already sent successfully.")
        print("\nDone (TX-only fallback).")
        return
    rx_sock.settimeout(args.rx_timeout)

    print(f"\n[RX] Listening on :{args.rx_port} for {args.rx_timeout:.1f} s ...")
    deadline = time.time() + args.rx_timeout
    count = 0
    while time.time() < deadline:
        remaining = deadline - time.time()
        rx_sock.settimeout(max(0.1, remaining))
        try:
            packet, addr = rx_sock.recvfrom(4096)
        except socket.timeout:
            break
        frames = parse_gateway_packet(packet)
        for f in frames:
            count += 1
            note = ""
            if f["arb_id"] == PWM_CAN_ID:
                note = "  ← our own PWM (unexpected echo)"
            print(f"  [RX #{count}] CAN_ID=0x{f['arb_id']:08X}  DLC={f['dlc']}  "
                  f"data={f['data'].hex()}  ch={f['ch']}{note}")
            # Try RPM decode if DLC matches
            if f["dlc"] >= 4:
                print(f"          decoded: {decode_rpm(f['data'])}")

    if count == 0:
        print("  (no frames received — gateway may not echo TX, or no CAN traffic)")

    tx_sock.close()
    rx_sock.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
