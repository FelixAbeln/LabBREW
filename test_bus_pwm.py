import socket
import struct
import time

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('0.0.0.0', 55001))
sock.settimeout(0.5)

print("Listening for PWM frames (0x840...1B) for 30 seconds...")
print()

pwm_frames = []
other_count = 0
start = time.time()

while time.time() - start < 30:
    try:
        data, addr = sock.recvfrom(4096)
        if len(data) >= 6:
            msg_type = struct.unpack("<H", data[0:2])[0]
            frame_count = struct.unpack("<H", data[2:4])[0]
            
            if msg_type == 0x0080:  # Classic CAN frames
                for i in range(frame_count):
                    offset = 4 + i * 16
                    if offset + 12 > len(data):
                        break
                    
                    arb_id = struct.unpack("<I", data[offset+4:offset+8])[0]
                    dlc = struct.unpack("<I", data[offset+8:offset+12])[0]
                    
                    if dlc > 8:
                        dlc = 8
                    payload = data[offset+12:offset+12+dlc]
                    
                    # Check if PWM (ends in 0x1B)
                    if (arb_id & 0xFF) == 0x1B:
                        msg_hex = f"0x{arb_id:08X}"
                        data_hex = " ".join(f"{b:02X}" for b in payload)
                        print(f"[PWM] {msg_hex}  DATA: {data_hex}")
                        pwm_frames.append((msg_hex, data_hex))
                    else:
                        other_count += 1
    except socket.timeout:
        pass

sock.close()
elapsed = time.time() - start

print()
print(f"[RESULT] {len(pwm_frames)} PWM frames, {other_count} other frames in {elapsed:.1f}s")
if pwm_frames:
    unique_ids = sorted(set(msg[0] for msg in pwm_frames))
    print(f"PWM CAN IDs: {unique_ids}")
else:
    print("No PWM frames detected!")
