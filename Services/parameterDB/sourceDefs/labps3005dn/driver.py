import serial
import time
from typing import Optional


class PSUError(Exception):
    """Raised when the PSU returns an invalid response or communication fails."""
    pass


class LABPS3005DN:
    """
    Simple driver for Velleman LABPS3005DN / QJE3005P-style bench PSU.

    Notes:
    - Uses a virtual serial COM port over USB
    - This device appears to expect literal '\\n' at the end of commands
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        timeout: float = 1.0,
        settle_time: float = 0.08,
        auto_connect: bool = True,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.settle_time = settle_time
        self.ser: Optional[serial.Serial] = None

        if auto_connect:
            self.connect()

    def connect(self) -> None:
        if self.ser and self.ser.is_open:
            return
        self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        time.sleep(0.5)

    def close(self) -> None:
        if self.ser and self.ser.is_open:
            self.ser.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _ensure_open(self) -> None:
        if not self.ser or not self.ser.is_open:
            raise PSUError("Serial port is not open")

    def _write(self, cmd: str) -> None:
        self._ensure_open()
        full = cmd + "\\n"   # literal backslash+n for this PSU
        self.ser.reset_input_buffer()
        self.ser.write(full.encode("ascii"))
        self.ser.flush()
        time.sleep(self.settle_time)

    def _read(self) -> str:
        self._ensure_open()
        response = self.ser.read_all().decode("ascii", errors="ignore").strip()
        return response

    def _query(self, cmd: str) -> str:
        self._write(cmd)
        return self._read()

    @staticmethod
    def _parse_float(value: str, field_name: str) -> float:
        try:
            return float(value)
        except ValueError as exc:
            raise PSUError(f"Invalid {field_name} response: {value!r}") from exc

    def identify(self) -> str:
        return self._query("*IDN?")

    def set_voltage(self, volts: float) -> None:
        if not (0.0 <= volts <= 30.0):
            raise ValueError("Voltage must be between 0.00 and 30.00 V")
        self._write(f"VSET1:{volts:05.2f}")

    def get_voltage_setpoint(self) -> float:
        return self._parse_float(self._query("VSET1?"), "voltage setpoint")

    def set_current(self, amps: float) -> None:
        if not (0.0 <= amps <= 5.0):
            raise ValueError("Current must be between 0.000 and 5.000 A")
        self._write(f"ISET1:{amps:0.3f}")

    def get_current_setpoint(self) -> float:
        return self._parse_float(self._query("ISET1?"), "current setpoint")

    def measure_voltage(self) -> float:
        return self._parse_float(self._query("VOUT1?"), "measured voltage")

    def measure_current(self) -> float:
        return self._parse_float(self._query("IOUT1?"), "measured current")

    def output_on(self) -> None:
        self._write("OUTPUT1")

    def output_off(self) -> None:
        self._write("OUTPUT0")

    def get_status_raw(self) -> str:
        return self._query("STATUS?")

    def get_status(self) -> dict:
        raw = self.get_status_raw()
        if len(raw) != 3 or any(c not in "01" for c in raw):
            return {"raw": raw, "mode": "unknown", "output": "unknown", "protection": "unknown"}

        return {
            "raw": raw,
            "mode": "CV" if raw[0] == "1" else "CC",
            "output": raw[1] == "1",
            "protection": raw[2] == "1",
        }
