"""
Quick PWM send test
"""
import sys
sys.path.insert(0, r'f:\BrewSys\LabBREW\LabBREW')

from Services.parameterDB.sourceDefs.brewtools.transports.pcan_gateway import (
    build_gateway_frame,
    RawCanFrame
)
import socket
import struct

GATEWAY_HOST = "192.168.5.37"
GATEWAY_TX_PORT = 55002

# Build 100% PWM frame
frame = RawCanFrame(
    arbitration_id=0x8403a1b,
    data=bytes([0x00, 100]),  # subindex=0, pwm=100%
    is_extended_id=True,
    is_remote_frame=False,
    is_fd=False,
    bitrate_switch=False,
    error_state_indicator=False,
    channel=0
)

print("Building 100% PWM frame using datasource code...")
payload = build_gateway_frame(frame)
print(f"✓ Built: {len(payload)} bytes")
print(f"  CAN ID: 0x{frame.arbitration_id:08X}")
print(f"  Data:   {' '.join(f'{b:02X}' for b in frame.data)}")
print(f"  Payload hex: {payload.hex()}")

# Decode it step by step
print("\nFrame structure (expected):")
print(f"  [0:2]   Frame length: {struct.unpack('>H', payload[0:2])[0]} bytes")
print(f"  [2:4]   Msg type: 0x{struct.unpack('>H', payload[2:4])[0]:04X} (0x0080=classic CAN)")
print(f"  [20]    Channel: {payload[20]}")
print(f"  [21]    DLC: {payload[21]}")
print(f"  [22:24] Flags: 0x{struct.unpack('>H', payload[22:24])[0]:04X}")
print(f"  [24:28] CAN ID: 0x{struct.unpack('>I', payload[24:28])[0]:08X}")
print(f"  [28:]   Data: {payload[28:].hex()}")

print(f"\nSending to {GATEWAY_HOST}:{GATEWAY_TX_PORT}...")
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(payload, (GATEWAY_HOST, GATEWAY_TX_PORT))
print("✓ Sent")
sock.close()
