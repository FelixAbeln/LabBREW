"""
Test PWM sender using actual datasource code
"""
import sys
sys.path.insert(0, r'f:\BrewSys\LabBREW\LabBREW')

from Services.parameterDB.sourceDefs.brewtools.transports.pcan_gateway import (
    build_gateway_frame,
    parse_gateway_packet,
    RawCanFrame
)
import socket
import time

GATEWAY_HOST = "192.168.5.37"
GATEWAY_TX_PORT = 55002
GATEWAY_RX_PORT = 55001

def send_and_listen(frame: RawCanFrame, description: str, listen_time=2):
    """Build, send, and listen for response"""
    print(f"\n{'='*70}")
    print(f"TEST: {description}")
    print(f"{'='*70}")
    
    try:
        payload = build_gateway_frame(frame)
        print(f"✓ Built frame: {len(payload)} bytes")
        print(f"  CAN ID: 0x{frame.arbitration_id:08X}")
        print(f"  Data:   {' '.join(f'{b:02X}' for b in frame.data)}")
        print(f"  Flags:  is_extended={frame.is_extended_id}, is_fd={frame.is_fd}")
        print(f"  Payload hex: {payload.hex()}")
    except Exception as e:
        print(f"✗ Frame build failed: {e}")
        return
    
    # Send
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(payload, (GATEWAY_HOST, GATEWAY_TX_PORT))
        print(f"✓ Sent to {GATEWAY_HOST}:{GATEWAY_TX_PORT}")
        sock.close()
    except Exception as e:
        print(f"✗ Send failed: {e}")
        return
    
    # Listen
    time.sleep(0.5)
    print(f"Listening for RX on UDP {GATEWAY_RX_PORT} for {listen_time}s...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('0.0.0.0', GATEWAY_RX_PORT))
        sock.settimeout(listen_time)
        
        count = 0
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                count += 1
                try:
                    frames = parse_gateway_packet(data)
                    for f in frames:
                        can_hex = f"0x{f.arbitration_id:08X}"
                        data_hex = " ".join(f"{b:02X}" for b in f.data)
                        msg_type = f.arbitration_id & 0xFF
                        print(f"  [{count}] {can_hex} ({msg_type:3d}): {data_hex}")
                        
                        # Highlight PWM frames
                        if (f.arbitration_id & 0xFF) == 0x1B:
                            print(f"       ^ *** PWM DETECTED ***")
                except Exception as e:
                    print(f"  [{count}] Parse error: {e}")
            except socket.timeout:
                break
        
        sock.close()
        if count == 0:
            print("  (no frames received)")
    except Exception as e:
        print(f"✗ Listen failed: {e}")

# Test 1: 50% PWM to agitator node 0
print("\n" + "="*70)
print("DATASOURCE PCAN GATEWAY TEST")
print("="*70)

frame1 = RawCanFrame(
    arbitration_id=0x8403a1b,
    data=bytes([0x00, 50]),  # subindex=0, pwm=50%
    is_extended_id=True,
    is_remote_frame=False,
    is_fd=False,
    bitrate_switch=False,
    error_state_indicator=False,
    channel=0
)
send_and_listen(frame1, "50% PWM to agitator node 0")

# Test 2: 100% PWM
frame2 = RawCanFrame(
    arbitration_id=0x8403a1b,
    data=bytes([0x00, 100]),  # subindex=0, pwm=100%
    is_extended_id=True,
    is_remote_frame=False,
    is_fd=False,
    bitrate_switch=False,
    error_state_indicator=False,
    channel=0
)
send_and_listen(frame2, "100% PWM to agitator node 0", listen_time=3)

# Test 3: Different node (node 1)
frame3 = RawCanFrame(
    arbitration_id=0x8403b1b,  # node 1
    data=bytes([0x00, 75]),
    is_extended_id=True,
    is_remote_frame=False,
    is_fd=False,
    bitrate_switch=False,
    error_state_indicator=False,
    channel=0
)
send_and_listen(frame3, "75% PWM to agitator node 1")

print("\n" + "="*70)
print("DONE")
print("="*70)
