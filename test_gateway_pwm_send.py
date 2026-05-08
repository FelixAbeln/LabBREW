import socket
import struct

# Manual PWM frame to gateway
# PCAN gateway frame format:
# - msg_type (2 bytes): 0x0080 = classic CAN
# - count (2 bytes): 1 frame
# - flags (4 bytes): 0
# - arb_id (4 bytes): 0x8403a1b (PWM for node 0)
# - dlc (4 bytes): 2 bytes of data
# - data[0:2]: 0x00, 0x32 (50% PWM)

GATEWAY_HOST = "192.168.5.37"
GATEWAY_TX_PORT = 55002

# Build PCAN gateway frame
payload = bytearray()
payload += struct.pack("<H", 0x0080)          # msg_type = classic CAN
payload += struct.pack("<H", 1)               # count = 1 frame
payload += struct.pack("<I", 0)               # flags
payload += struct.pack("<I", 0x8403a1b)       # arb_id = PWM node 0
payload += struct.pack("<I", 2)               # dlc = 2 bytes
payload += bytes([0x00, 0x32])                # data: subindex=0, pwm=50%

print(f"Sending manual PWM frame to {GATEWAY_HOST}:{GATEWAY_TX_PORT}")
print(f"Payload hex: {payload.hex()}")
print(f"Frame: CAN_ID=0x8403a1b, DATA=00 32 (50% PWM)")

try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(bytes(payload), (GATEWAY_HOST, GATEWAY_TX_PORT))
    print("✓ Sent successfully")
    sock.close()
except Exception as e:
    print(f"✗ Error: {e}")
