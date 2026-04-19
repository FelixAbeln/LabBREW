# Kvaser CANlib Setup on Raspberry Pi (Leaf v3)

This guide walks through installing and using a Kvaser USB CAN device (e.g. Leaf v3) with CANlib on a Raspberry Pi.

Download LinuxCAN (CANlib SDK):
https://kvaser.com/single-download/?download_id=1011691524

---

## 1. Install prerequisites

```bash
sudo apt update
sudo apt install build-essential dkms linux-headers-$(uname -r)
```

---

## 2. Kernel headers (IMPORTANT for Raspberry Pi 5)

If you are using a Raspberry Pi 5 or a system with an `rpi-2712` kernel:

```bash
uname -r
```

If you see something like:
```text
6.x.x+rpt-rpi-2712
```

Install the correct headers:

```bash
sudo apt update
sudo apt install linux-headers-rpi-2712
```

Verify:

```bash
ls /lib/modules/$(uname -r)/build
```

⚠️ If your kernel updates later, you must rebuild LinuxCAN.

---

## 3. Extract LinuxCAN

```bash
tar -xvzf linuxcan_*.tar.gz
cd linuxcan
```

---

## 4. Build and install CANlib

```bash
make clean
export KV_NO_PCI=1
export KDIR=/lib/modules/$(uname -r)/build
make
sudo -E make install
sudo depmod -a
```

---

## 5. Load drivers

For Kvaser Leaf v3:

```bash
sudo modprobe kvcommon
sudo modprobe mhydra
```

Check:

```bash
lsmod | egrep 'kvcommon|mhydra'
```

---

## 6. Test CAN device

```bash
cd canlib/examples
./listChannels
```

Expected:

```text
Found 1 channel(s).
ch 0: Kvaser Leaf v3 ...
```

---

## 7. Enable drivers at boot

```bash
echo kvcommon | sudo tee -a /etc/modules
echo mhydra | sudo tee -a /etc/modules
```

Reboot and verify:

```bash
lsmod | egrep 'kvcommon|mhydra'
```

---

## 8. Python setup (LabBREW)

```bash
source /opt/labbrew/.venv/bin/activate
pip install -U python-can
```

---

## 9. Test Python CAN access

```bash
python - <<'PY'
import can
bus = can.Bus(interface="kvaser", channel=0, bitrate=500000)
print("opened ok")
bus.shutdown()
PY
```

---

## 10. Fix python-can ioctl bug

### Problem

```text
Function canIoCtl failed - Error in parameter [Error Code -1]
```

### Fix

Locate the installed file path first (works across Python minor versions):

```bash
CANLIB_PY="$(python - <<'PY'
import inspect
import can.interfaces.kvaser.canlib as mod
print(inspect.getfile(mod))
PY
)"
echo "$CANLIB_PY"
```

Backup:

```bash
sudo cp "$CANLIB_PY" "$CANLIB_PY.bak"
```

Then edit `$CANLIB_PY`.

Comment out the LOCAL_TXACK block:

```python
# canIoCtlInit(
#     self._read_handle,
#     canstat.canIOCTL_SET_LOCAL_TXACK,
#     ctypes.byref(ctypes.c_byte(local_echo)),
#     1,
# )
```

---

## 11. Restart service

```bash
sudo systemctl restart labbrew-supervisor
sudo journalctl -u labbrew-supervisor -n 80 --no-pager
```

---

## 12. Configuration

```yaml
interface: kvaser
channel: 0
bitrate: 500000
```

---

## 13. Troubleshooting

### No channels found
```bash
lsmod
sudo modprobe kvcommon
sudo modprobe mhydra
```

### Device not found
- Check channel is `0`
- Verify:
  ```bash
  lsusb
  dmesg | tail
  ```

### Modules missing after reboot
Ensure `/etc/modules` contains:
```text
kvcommon
mhydra
```

### Kernel updated?
Rebuild LinuxCAN:
```bash
cd ~/linuxcan
make clean
export KV_NO_PCI=1
export KDIR=/lib/modules/$(uname -r)/build
make
sudo -E make install
sudo depmod -a
```

---

## 14. Working state checklist

✔ lsusb shows Kvaser device  
✔ lsmod shows kvcommon + mhydra  
✔ listChannels shows 1 channel  
✔ Python test prints "opened ok"

---

## Notes

- Do NOT use `kvaser_usb` (that is SocketCAN, not LinuxCAN)
- This setup uses Kvaser CANlib (LinuxCAN)
