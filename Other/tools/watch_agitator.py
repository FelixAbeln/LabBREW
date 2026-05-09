"""
Watch agitator PID live. Optionally set RPM setpoint via CLI arg.
Usage:
    python watch_agitator.py           # just watch
    python watch_agitator.py 50        # set setpoint to 50 RPM then watch
    python watch_agitator.py 0         # stop (setpoint 0)
"""
import sys
import socket
import json
import time

sys.path.insert(0, "F:/BrewSys/LabBREW/LabBREW")
from Services.parameterDB.parameterdb_core.protocol import encode_message, read_message, make_request  # noqa: E402


def pdb_call(cmd, payload=None, host="127.0.0.1", port=8765):
    with socket.create_connection((host, port), timeout=5) as s:
        f = s.makefile("rb")
        s.sendall(encode_message(make_request(cmd, payload or {})))
        return read_message(f)


PARAMS = [
    "set_spd_Agitator",
    "brewcan.rpm.0",
    "brewcan.agitator.0.set_pwm",
    "pid_agitator",
    "brewcan.last_can_id",
]

if len(sys.argv) > 1:
    sp = float(sys.argv[1])
    print(f"Setting set_spd_Agitator = {sp}")
    r = pdb_call("set_value", {"name": "set_spd_Agitator", "value": sp})
    print("  ok:", r.get("ok"), r.get("error"))

print(f"{'t':>5}  {'SP':>6}  {'RPM':>8}  {'PWM':>7}  {'PID':>7}  last_can_id")
print("-" * 65)

for i in range(40):
    r = pdb_call("snapshot_names", {"names": PARAMS})
    v = r.get("result", {})
    sp  = v.get("set_spd_Agitator")
    rpm = v.get("brewcan.rpm.0")
    pwm = v.get("brewcan.agitator.0.set_pwm")
    pid = v.get("pid_agitator")
    cid = v.get("brewcan.last_can_id")
    pwm_s = f"{pwm:.1f}%" if pwm is not None else "None"
    pid_s = f"{pid:.1f}" if pid is not None else "None"
    rpm_s = f"{rpm:.1f}" if rpm is not None else "None"
    print(f"{i*0.5:>5.1f}  {str(sp):>6}  {rpm_s:>8}  {pwm_s:>7}  {pid_s:>7}  {cid}")
    time.sleep(0.5)
