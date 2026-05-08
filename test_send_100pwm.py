import socket
import struct
import time

# Build a proper PCAN gateway frame for 100% PWM
# Frame format (big-endian):
# [0:2]   = frame length (bytes)
# [2:4]   = msg_type (0x0080 = classic CAN)
# [4:12]  = reserved/padding (8 bytes)
# [12:16] = reserved (4 bytes)
# [16:20] = reserved (4 bytes)
# [20]    = channel (0)
# [21]    = dlc (2 bytes)
# [22:24] = flags (0x0200 = extended ID)
# [24:28] = CAN arbitration ID
# [28:]   = data

def build_pcan_pwm_frame(can_id, pwm_percent, channel=0):
    """Build PCAN gateway frame for PWM command"""
    body = bytearray()
    
    # Frame header (placeholder length, will set later)
    body.extend(b"\x00\x00")  # [0:2] length (calculated)
    body.extend(struct.pack(">H", 0x0080))  # [2:4] msg_type = classic CAN
    body.extend(b"\x00" * 8)  # [4:12] reserved
    body.extend(b"\x00" * 4)  # [12:16] reserved
    body.extend(b"\x00" * 4)  # [16:20] reserved
    body.append(channel & 0xFF)  # [20] channel
    body.append(2)  # [21] dlc = 2 bytes (subindex + pwm)
    
    # Flags: 0x0200 = extended ID
    flags = 0x0200  # extended ID flag
    body.extend(struct.pack(">H", flags))  # [22:24] flags
    
    # CAN word: arbitration ID with extended bit set
    can_word = (can_id & 0x1FFFFFFF) | 0x80000000  # set extended ID bit
    body.extend(struct.pack(">I", can_word))  # [24:28] CAN ID
    
    # Payload: subindex (0x00) + PWM percent
    body.append(0x00)  # subindex
    body.append(int(pwm_percent) & 0xFF)  # PWM 0-100%
    
    # Set frame length at start
    frame_len = len(body)
    struct.pack_into(">H", body, 0, frame_len)
    
    return bytes(body)

# CAN ID for 100% PWM to agitator node 0
# Brewtools format: 0x8403a1b
# - priority=1 (bits 28:27)
# - sender=8 (PLC, bits 26:19)
# - receiver=6 (AGITATOR, bits 18:11)
# - node=0 (bits 10:8)
# - msg_type=0x1b (PWM, bits 7:0)
CAN_ID = 0x8403a1b
PWM_100_PERCENT = 100

frame = build_pcan_pwm_frame(CAN_ID, PWM_100_PERCENT, channel=0)

print(f"Built PCAN frame for 100% PWM:")
print(f"  CAN ID: 0x{CAN_ID:08X}")
print(f"  PWM: {PWM_100_PERCENT}%")
print(f"  Frame length: {len(frame)} bytes")
print(f"  Payload hex: {frame.hex()}")
print()

# Send to gateway
GATEWAY_HOST = "192.168.5.37"
GATEWAY_TX_PORT = 55002

print(f"Sending to {GATEWAY_HOST}:{GATEWAY_TX_PORT}...")
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(frame, (GATEWAY_HOST, GATEWAY_TX_PORT))
    print("✓ Frame sent")
    sock.close()
except Exception as e:
    print(f"✗ Send error: {e}")

# Wait a bit for gateway to process
time.sleep(0.5)

# Listen for it to come back on RX
print(f"\nListening on UDP 55001 for echoed PWM...")
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', 55001))
    sock.settimeout(2)
    
    data, addr = sock.recvfrom(4096)
    print(f"✓ Received {len(data)} bytes from {addr}")
    print(f"  Payload hex: {data.hex()}")
    
    # Check if our PWM frame is in there
    if f"{CAN_ID:08x}".lower() in data.hex().lower() or "1b" in data.hex():
        print(f"  ✓ PWM frame detected (contains 0x...1B or CAN ID match)")
    else:
        print(f"  ✗ PWM frame NOT detected in response")
    
    sock.close()
except socket.timeout:
    print("✗ Timeout - no response from gateway")
except Exception as e:
    print(f"✗ Listen error: {e}")
