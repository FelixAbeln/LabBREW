"""
Standalone test script — sends Brewtools PWM frames to the PCAN gateway and
listens for incoming CAN frames (e.g. RPM) on the RX port.

Usage:
    python test_agitator_pwm.py [pwm_percent] [channel]   # defaults: 25, 0
    python test_agitator_pwm.py [pwm_percent] [channel] --tx-only

The script:
1. Builds the exact same UDP packet that service.py produces
2. Sends it to the gateway (TX port 55002)
3. Listens briefly on RX port 55001 and decodes any frames received

No LabBREW imports needed — all encoding is inlined here.
"""
import socket
import struct
import sys
import time

# ── Gateway config ────────────────────────────────────────────────────────────
GATEWAY_HOST  = "192.168.5.37"
GATEWAY_TX_PORT = 55002   # PC → gateway → CAN
GATEWAY_RX_PORT = 55001   # CAN → gateway → PC

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


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    pwm_pct = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    channel = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    tx_only = "--tx-only" in sys.argv
    print(f"Target PWM: {pwm_pct}%")
    print(f"CAN channel: {channel}")
    print(f"Mode:       {'TX-only' if tx_only else 'TX+RX'}")
    print(f"Gateway:    {GATEWAY_HOST}  TX→{GATEWAY_TX_PORT}  RX←{GATEWAY_RX_PORT}")

    # Build the PWM frame
    payload = build_pwm_payload(pwm_pct)
    udp_frame = build_gateway_frame(PWM_CAN_ID, payload, channel=channel)

    print(f"\n[TX] CAN_ID=0x{PWM_CAN_ID:08X}  DLC={len(payload)}  data={payload.hex()}")
    print(f"     UDP frame ({len(udp_frame)} bytes): {udp_frame.hex()}")

    # TX socket → gateway
    tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tx_sock.sendto(udp_frame, (GATEWAY_HOST, GATEWAY_TX_PORT))
    print("[TX] Sent.")

    # Send again with a small delay (some gateways need a moment)
    time.sleep(0.1)
    tx_sock.sendto(udp_frame, (GATEWAY_HOST, GATEWAY_TX_PORT))
    print("[TX] Sent again (2nd).")

    if tx_only:
        tx_sock.close()
        print("\nDone (TX-only).")
        return

    # RX socket — listen for CAN frames coming back from the bus
    rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx_sock.bind(("0.0.0.0", GATEWAY_RX_PORT))
    rx_sock.settimeout(3.0)

    print(f"\n[RX] Listening on :{GATEWAY_RX_PORT} for 3 s ...")
    deadline = time.time() + 3.0
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
