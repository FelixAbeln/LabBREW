from __future__ import annotations

import contextlib
import time
from typing import Any

from ...parameterdb_core.client import SupportsSignalRequests
from ...parameterdb_sources.base import DataSourceBase, DataSourceSpec


class PSUError(Exception):
    """Raised when the PSU returns an invalid response or communication fails."""


class LABPS3005DN:
    """Simple serial driver for the Velleman LABPS3005DN / QJE3005P-style PSU."""

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
        self.ser: Any | None = None
        if auto_connect:
            self.connect()

    def connect(self) -> None:
        if self.ser and self.ser.is_open:
            return
        try:
            import serial
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "pyserial is required for the labps3005dn datasource"
            ) from exc
        self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        time.sleep(0.5)

    def close(self) -> None:
        if self.ser and self.ser.is_open:
            self.ser.close()

    def _ensure_open(self) -> None:
        if not self.ser or not self.ser.is_open:
            raise PSUError("Serial port is not open")

    def _write(self, cmd: str) -> None:
        self._ensure_open()
        full = cmd + "\\n"
        self.ser.reset_input_buffer()
        self.ser.write(full.encode("ascii"))
        self.ser.flush()
        time.sleep(self.settle_time)

    def _read(self) -> str:
        self._ensure_open()
        return self.ser.read_all().decode("ascii", errors="ignore").strip()

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

    def set_current(self, amps: float) -> None:
        if not (0.0 <= amps <= 5.0):
            raise ValueError("Current must be between 0.000 and 5.000 A")
        self._write(f"ISET1:{amps:0.3f}")

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

    def get_status(self) -> dict[str, Any]:
        raw = self.get_status_raw()
        if len(raw) != 3 or any(c not in "01" for c in raw):
            return {
                "raw": raw,
                "mode": "unknown",
                "output": "unknown",
                "protection": "unknown",
            }
        return {
            "raw": raw,
            "mode": "CV" if raw[0] == "1" else "CC",
            "output": raw[1] == "1",
            "protection": raw[2] == "1",
        }


class LabPsuSource(DataSourceBase):
    source_type = "labps3005dn"
    display_name = "LABPS3005DN PSU"
    description = (
        "Mirrors static setpoint parameters to a serial bench PSU "
        "and publishes measured readbacks."
    )

    def __init__(
        self,
        name: str,
        client: SupportsSignalRequests,
        *,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name, client, config=config)
        self._driver: LABPS3005DN | None = None
        self._last_applied_voltage: float | None = None
        self._last_applied_current: float | None = None
        self._last_applied_enable: bool | None = None

    def _param_name(self, key: str) -> str:
        explicit = self.config.get(f"{key}_param")
        if explicit:
            return str(explicit)
        prefix = str(self.config.get("parameter_prefix", self.name))
        default_map = {
            "set_enable": f"{prefix}.set_enable",
            "set_voltage": f"{prefix}.set_voltage",
            "set_current": f"{prefix}.set_current",
            "voltage_meas": f"{prefix}.meas_voltage",
            "current_meas": f"{prefix}.meas_current",
            "output_state": f"{prefix}.output_state",
            "mode": f"{prefix}.mode",
            "protection": f"{prefix}.protection",
            "status_raw": f"{prefix}.status_raw",
            "connected": f"{prefix}.connected",
            "last_error": f"{prefix}.last_error",
            "last_sync": f"{prefix}.last_sync",
            "idn": f"{prefix}.idn",
        }
        return default_map[key]

    def _set_readback(self, key: str, value: Any) -> None:
        self.client.set_value(self._param_name(key), value)

    def _set_error(self, message: str) -> None:
        self._set_readback("connected", False)
        self._set_readback("last_error", message)

    def _connect_driver(self) -> LABPS3005DN:
        if self._driver is not None:
            return self._driver
        self._driver = LABPS3005DN(
            port=str(self.config["port"]),
            baudrate=int(self.config.get("baudrate", 9600)),
            timeout=float(self.config.get("timeout", 1.0)),
            settle_time=float(self.config.get("settle_time", 0.08)),
            auto_connect=True,
        )
        self._set_readback("connected", True)
        self._set_readback("last_error", "")
        with contextlib.suppress(Exception):
            self._set_readback("idn", self._driver.identify())
        return self._driver

    def _disconnect_driver(self) -> None:
        drv = self._driver
        self._driver = None
        if drv is not None:
            try:
                drv.close()
            except Exception as exc:
                self._set_error(f"Disconnect failed: {exc}")

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in {
            "1",
            "true",
            "on",
            "yes",
            "enable",
            "enabled",
        }

    @staticmethod
    def _coerce_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return float(default)
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def ensure_parameters(self) -> None:
        owned = self.build_owned_metadata(device="bench_psu")
        self.ensure_parameter(
            self._param_name("set_enable"),
            "static",
            value=False,
            metadata={**owned, "role": "command"},
        )
        self.ensure_parameter(
            self._param_name("set_voltage"),
            "static",
            value=float(self.config.get("initial_voltage", 0.0)),
            metadata={**owned, "role": "command", "unit": "V"},
        )
        self.ensure_parameter(
            self._param_name("set_current"),
            "static",
            value=float(self.config.get("initial_current", 0.0)),
            metadata={**owned, "role": "command", "unit": "A"},
        )
        self.ensure_parameter(
            self._param_name("voltage_meas"),
            "static",
            value=0.0,
            metadata={**owned, "role": "measurement", "unit": "V"},
        )
        self.ensure_parameter(
            self._param_name("current_meas"),
            "static",
            value=0.0,
            metadata={**owned, "role": "measurement", "unit": "A"},
        )
        self.ensure_parameter(
            self._param_name("output_state"),
            "static",
            value=False,
            metadata={**owned, "role": "status"},
        )
        self.ensure_parameter(
            self._param_name("mode"),
            "static",
            value="unknown",
            metadata={**owned, "role": "status"},
        )
        self.ensure_parameter(
            self._param_name("protection"),
            "static",
            value=False,
            metadata={**owned, "role": "status"},
        )
        self.ensure_parameter(
            self._param_name("status_raw"),
            "static",
            value="",
            metadata={**owned, "role": "status"},
        )
        self.ensure_parameter(
            self._param_name("connected"),
            "static",
            value=False,
            metadata={**owned, "role": "status"},
        )
        self.ensure_parameter(
            self._param_name("last_error"),
            "static",
            value="",
            metadata={**owned, "role": "status"},
        )
        self.ensure_parameter(
            self._param_name("last_sync"),
            "static",
            value="",
            metadata={**owned, "role": "status"},
        )
        self.ensure_parameter(
            self._param_name("idn"),
            "static",
            value="",
            metadata={**owned, "role": "status"},
        )

    def _read_commands(self) -> tuple[bool, float, float]:
        enable = self._coerce_bool(
            self.client.get_value(self._param_name("set_enable"), False)
        )
        voltage = self._coerce_float(
            self.client.get_value(self._param_name("set_voltage"), 0.0), 0.0
        )
        current = self._coerce_float(
            self.client.get_value(self._param_name("set_current"), 0.0), 0.0
        )
        return enable, voltage, current

    def _apply_commands(
        self, drv: LABPS3005DN, enable: bool, voltage: float, current: float
    ) -> None:
        if self._last_applied_enable is None:
            try:
                status = drv.get_status()
                self._last_applied_enable = bool(status.get("output"))
            except Exception:
                self._last_applied_enable = None

        enable_changed = (
            self._last_applied_enable is None or enable != self._last_applied_enable
        )
        current_changed = (
            self._last_applied_current is None
            or abs(current - self._last_applied_current) > 1e-9
        )
        voltage_changed = (
            self._last_applied_voltage is None
            or abs(voltage - self._last_applied_voltage) > 1e-9
        )

        if not (enable_changed or current_changed or voltage_changed):
            return

        if not enable and self._last_applied_enable is not False:
            drv.output_off()
            self._last_applied_enable = False
        if current_changed:
            drv.set_current(current)
            self._last_applied_current = current
        if voltage_changed:
            drv.set_voltage(voltage)
            self._last_applied_voltage = voltage
        if enable and self._last_applied_enable is not True:
            drv.output_on()
            self._last_applied_enable = True

    def _poll_readbacks(self, drv: LABPS3005DN) -> None:
        status = drv.get_status()
        self._set_readback("connected", True)
        self._set_readback("last_error", "")
        self._set_readback(
            "last_sync", __import__("datetime").datetime.utcnow().isoformat() + "Z"
        )
        self._set_readback("voltage_meas", drv.measure_voltage())
        self._set_readback("current_meas", drv.measure_current())
        self._set_readback("output_state", bool(status.get("output")))
        self._set_readback("mode", status.get("mode", "unknown"))
        self._set_readback("protection", bool(status.get("protection")))
        self._set_readback("status_raw", status.get("raw", ""))

    def run(self) -> None:
        interval = float(self.config.get("update_interval_s", 0.25))
        reconnect_delay = float(self.config.get("reconnect_delay_s", 2.0))
        while not self.should_stop():
            try:
                drv = self._connect_driver()
                enable, voltage, current = self._read_commands()
                self._apply_commands(drv, enable, voltage, current)
                self._poll_readbacks(drv)
                if self.sleep(interval):
                    break
            except Exception as exc:
                self._disconnect_driver()
                self._last_applied_voltage = None
                self._last_applied_current = None
                self._last_applied_enable = None
                self._set_error(str(exc))
                if self.sleep(reconnect_delay):
                    break
        self._disconnect_driver()


class LabPsuSourceSpec(DataSourceSpec):
    source_type = "labps3005dn"
    display_name = "LABPS3005DN PSU"
    description = "Bench PSU serial datasource"

    def create(
        self,
        name: str,
        client: SupportsSignalRequests,
        *,
        config: dict[str, Any] | None = None,
    ) -> DataSourceBase:
        return LabPsuSource(name, client, config=config)

    def default_config(self) -> dict[str, Any]:
        return {
            "port": "COM5",
            "baudrate": 9600,
            "timeout": 1.0,
            "settle_time": 0.08,
            "update_interval_s": 0.25,
            "reconnect_delay_s": 2.0,
            "parameter_prefix": "psu",
            "initial_voltage": 0.0,
            "initial_current": 0.0,
        }


SOURCE = LabPsuSourceSpec()
