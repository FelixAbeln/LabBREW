from __future__ import annotations

import math
import socket
import struct
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import threading
from typing import Any

from ...parameterdb_core.client import SupportsSignalRequests
from ...parameterdb_sources.base import DataSourceBase, DataSourceSpec


class PapagoMeteoError(Exception):
    """Raised when PAPAGO Meteo communication fails or returns invalid data."""


class _ModbusTcpClient:
    def __init__(
        self, host: str, port: int = 502, unit_id: int = 1, timeout: float = 1.5
    ) -> None:
        self.host = host.strip()
        self.port = int(port)
        self.unit_id = int(unit_id)
        self.timeout = float(timeout)
        self._sock: socket.socket | None = None
        self._tx_id = 0
        self._lock = threading.RLock()

    @property
    def is_connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> None:
        if self._sock is not None:
            return
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        self._sock = sock

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def _recv_exact(self, length: int) -> bytes:
        if self._sock is None:
            raise PapagoMeteoError("PAPAGO Meteo is not connected.")
        data = bytearray()
        while len(data) < length:
            chunk = self._sock.recv(length - len(data))
            if not chunk:
                raise PapagoMeteoError("Connection closed by PAPAGO Meteo.")
            data.extend(chunk)
        return bytes(data)

    def request(self, function_code: int, payload: bytes) -> bytes:
        with self._lock:
            if self._sock is None:
                self.connect()
            assert self._sock is not None

            self._tx_id = (self._tx_id + 1) & 0xFFFF
            pdu = bytes([function_code]) + payload
            header = struct.pack(">HHHB", self._tx_id, 0, len(pdu) + 1, self.unit_id)
            packet = header + pdu

            try:
                self._sock.sendall(packet)
                response_header = self._recv_exact(7)
                rx_tx_id, protocol_id, length, rx_unit_id = struct.unpack(
                    ">HHHB", response_header
                )
                if rx_tx_id != self._tx_id:
                    raise PapagoMeteoError("Mismatched Modbus transaction ID.")
                if protocol_id != 0:
                    raise PapagoMeteoError("Invalid Modbus protocol ID in response.")
                if rx_unit_id != self.unit_id:
                    raise PapagoMeteoError("Unexpected Modbus unit ID in response.")
                response_pdu = self._recv_exact(length - 1)
            except (OSError, TimeoutError) as exc:
                self.close()
                raise PapagoMeteoError(f"Network error talking to PAPAGO Meteo: {exc}") from exc

            if not response_pdu:
                raise PapagoMeteoError("Empty response from PAPAGO Meteo.")

            rx_function = response_pdu[0]
            if rx_function == (function_code | 0x80):
                code = response_pdu[1] if len(response_pdu) > 1 else None
                raise PapagoMeteoError(f"Modbus exception from PAPAGO Meteo: {code}")
            if rx_function != function_code:
                raise PapagoMeteoError("Unexpected Modbus function code in response.")
            return response_pdu[1:]

    def read_input_registers(self, start_address: int, count: int) -> list[int]:
        payload = struct.pack(">HH", int(start_address), int(count))
        response = self.request(0x04, payload)
        if not response:
            raise PapagoMeteoError("Missing read-input-registers payload.")
        byte_count = response[0]
        register_bytes = response[1 : 1 + byte_count]
        if len(register_bytes) != byte_count:
            raise PapagoMeteoError("Short read-input-registers response.")
        if byte_count != int(count) * 2:
            raise PapagoMeteoError(
                f"Unexpected input-register byte count: {byte_count}, expected {int(count) * 2}."
            )
        return [
            struct.unpack(">H", register_bytes[index : index + 2])[0]
            for index in range(0, len(register_bytes), 2)
        ]


@dataclass(frozen=True)
class QuantitySpec:
    key: str
    status_register: int
    int_x10_register: int | None
    float_register: int | None
    unit_register: int | None
    default_unit: str
    label: str


QUANTITIES: dict[str, QuantitySpec] = {
    "sensor_a_value_1": QuantitySpec("sensor_a_value_1", 10, 11, 12, 14, "native", "Sensor A Value 1"),
    "sensor_a_value_2": QuantitySpec("sensor_a_value_2", 20, 21, 22, 24, "native", "Sensor A Value 2"),
    "sensor_a_value_3": QuantitySpec("sensor_a_value_3", 30, 31, 32, 34, "native", "Sensor A Value 3"),
    "sensor_b_value_1": QuantitySpec("sensor_b_value_1", 110, 111, 112, 114, "native", "Sensor B Value 1"),
    "sensor_b_value_2": QuantitySpec("sensor_b_value_2", 120, 121, 122, 124, "native", "Sensor B Value 2"),
    "sensor_b_value_3": QuantitySpec("sensor_b_value_3", 130, 131, 132, 134, "native", "Sensor B Value 3"),
    "wind_direction_deg": QuantitySpec("wind_direction_deg", 210, 211, 212, 214, "deg", "Wind Direction"),
    "wind_speed_m_s": QuantitySpec("wind_speed_m_s", 220, 221, 222, 224, "m/s", "Wind Speed"),
}

SENSOR_STATUS = {0: "not_used", 1: "measuring"}
VALUE_STATUS = {0: "ok", 2: "overflow", 3: "underflow", 4: "invalid"}
SENSOR_TYPE = {
    0: "none",
    2: "temperature_ds",
    3: "temperature_humidity_th3x",
    4: "temperature_tmp",
    5: "co2_t6713",
    7: "atmospheric_pressure",
    8: "ozone_o3",
}


class PapagoMeteoDevice:
    def __init__(
        self,
        host: str,
        port: int = 502,
        unit_id: int = 1,
        timeout: float = 1.5,
    ) -> None:
        if not host:
            raise PapagoMeteoError("Enter a PAPAGO Meteo IP or host name first.")
        self.host = host.strip()
        self.port = int(port)
        self.unit_id = int(unit_id)
        self.timeout = float(timeout)
        self._client = _ModbusTcpClient(
            self.host, self.port, unit_id=self.unit_id, timeout=self.timeout
        )

    def connect(self) -> None:
        self._client.connect()
        self._client.read_input_registers(0, 4)

    def close(self) -> None:
        self._client.close()

    def read_registers(self, start: int, count: int) -> list[int]:
        self.connect()
        return self._client.read_input_registers(start, count)

    def read_snapshot(self, *, prefer_float: bool = False) -> dict[str, Any]:
        # Modbus limits one read-input-registers request to 125 registers.
        # PAPAGO's useful live range spans 0..224, so read it in two chunks.
        registers = [0] * 225
        first = self.read_registers(0, 125)
        second = self.read_registers(125, 100)
        registers[0:125] = first
        registers[125:225] = second
        quantities = {
            key: _decode_quantity(registers, spec, prefer_float=prefer_float)
            for key, spec in QUANTITIES.items()
        }
        return {
            "device_time": _decode_ntp_time(registers, 1),
            "sensor_a_status": _decode_enum(registers, 0, SENSOR_STATUS),
            "sensor_a_type": _decode_enum(registers, 3, SENSOR_TYPE),
            "sensor_b_status": _decode_enum(registers, 100, SENSOR_STATUS),
            "sensor_b_type": _decode_enum(registers, 103, SENSOR_TYPE),
            "wind_sensor_status": _decode_enum(registers, 200, SENSOR_STATUS),
            "quantities": quantities,
        }


def _u16(registers: list[int], address: int) -> int:
    if address < 0 or address >= len(registers):
        raise PapagoMeteoError(
            f"Register {address} outside returned block of {len(registers)} registers."
        )
    return registers[address] & 0xFFFF


def _safe_u16(registers: list[int], address: int | None) -> int | None:
    if address is None or address < 0 or address >= len(registers):
        return None
    return registers[address] & 0xFFFF


def _i16(registers: list[int], address: int) -> int:
    raw = _u16(registers, address)
    return raw - 0x10000 if raw > 0x7FFF else raw


def _float32(registers: list[int], address: int) -> float:
    hi = _u16(registers, address)
    lo = _u16(registers, address + 1)
    return struct.unpack(">f", struct.pack(">HH", hi, lo))[0]


def _decode_enum(registers: list[int], address: int, mapping: dict[int, str]) -> str:
    raw = _safe_u16(registers, address)
    if raw is None:
        return "missing"
    return mapping.get(raw, f"unknown:{raw}")


def _decode_ntp_time(registers: list[int], start: int) -> str:
    try:
        seconds = (_u16(registers, start) << 16) | _u16(registers, start + 1)
        if seconds == 0:
            return ""
        ntp_epoch = datetime(1900, 1, 1, tzinfo=UTC)
        return (ntp_epoch + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
    except Exception:
        return ""


def _decode_quantity(registers: list[int], spec: QuantitySpec, *, prefer_float: bool = False) -> dict[str, Any]:
    status_raw = _safe_u16(registers, spec.status_register)
    quality = VALUE_STATUS.get(status_raw, f"unknown:{status_raw}")
    unit_code = _safe_u16(registers, spec.unit_register)

    value: float | None
    if quality != "ok":
        value = None
    elif prefer_float and spec.float_register is not None:
        value = _float32(registers, spec.float_register)
    elif spec.int_x10_register is not None:
        value = _i16(registers, spec.int_x10_register) / 10.0
    elif spec.float_register is not None:
        value = _float32(registers, spec.float_register)
    else:
        value = None

    if value is not None and not math.isfinite(value):
        value = None
        quality = "invalid_float"

    return {
        "value": value,
        "quality": quality,
        "unit": spec.default_unit,
        "unit_code": unit_code,
        "label": spec.label,
    }


class PapagoMeteoSource(DataSourceBase):
    source_type = "papago_meteo"
    display_name = "PAPAGO Meteo ETH"
    description = "Reads PAPAGO Meteo ETH weather station measurements over Modbus TCP."

    def __init__(
        self,
        name: str,
        client: SupportsSignalRequests,
        *,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name, client, config=config)
        self._device: PapagoMeteoDevice | None = None

    def stop(self) -> None:
        super().stop()
        self._disconnect_device()

    def _prefix(self) -> str:
        return str(self.config.get("parameter_prefix", self.name)).strip() or self.name

    def _quantity_config(self) -> dict[str, Any]:
        configured = self.config.get("quantities")
        if isinstance(configured, dict) and configured:
            return configured
        return {
            "sensor_a_value_1": {"enabled": True, "parameter": f"{self._prefix()}.sensor_a.value_1"},
            "sensor_a_value_2": {"enabled": True, "parameter": f"{self._prefix()}.sensor_a.value_2"},
            "sensor_a_value_3": {"enabled": True, "parameter": f"{self._prefix()}.sensor_a.value_3"},
            "sensor_b_value_1": {"enabled": False, "parameter": f"{self._prefix()}.sensor_b.value_1"},
            "sensor_b_value_2": {"enabled": False, "parameter": f"{self._prefix()}.sensor_b.value_2"},
            "sensor_b_value_3": {"enabled": False, "parameter": f"{self._prefix()}.sensor_b.value_3"},
            "wind_direction_deg": {"enabled": True, "parameter": f"{self._prefix()}.wind.direction_deg"},
            "wind_speed_m_s": {"enabled": True, "parameter": f"{self._prefix()}.wind.speed_m_s"},
        }

    def _enabled_quantities(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for key, item in self._quantity_config().items():
            if key not in QUANTITIES or not isinstance(item, dict):
                continue
            if bool(item.get("enabled", True)):
                result[key] = item
        return result

    def _quantity_param(self, key: str, item: dict[str, Any]) -> str:
        explicit = str(item.get("parameter") or "").strip()
        if explicit:
            return explicit
        return f"{self._prefix()}.{key}"

    def _quality_param(self, key: str, item: dict[str, Any]) -> str:
        explicit = str(item.get("quality_parameter") or "").strip()
        if explicit:
            return explicit
        return f"{self._quantity_param(key, item)}.quality"

    def _status_param(self, key: str) -> str:
        explicit = self.config.get(f"{key}_param")
        if explicit:
            return str(explicit)
        return f"{self._prefix()}.{key}"

    def _set_status(self, key: str, value: Any) -> None:
        self.client.set_value(self._status_param(key), value)

    def _set_error(self, message: str) -> None:
        self._set_status("connected", False)
        self._set_status("last_error", str(message))

    def _connect_device(self) -> PapagoMeteoDevice:
        if self._device is not None:
            return self._device
        self._device = PapagoMeteoDevice(
            host=str(self.config["host"]),
            port=int(self.config.get("port", 502)),
            unit_id=int(self.config.get("unit_id", 1)),
            timeout=float(self.config.get("timeout", 1.5)),
        )
        self._device.connect()
        self._set_status("connected", True)
        self._set_status("last_error", "")
        return self._device

    def _disconnect_device(self) -> None:
        device = self._device
        self._device = None
        if device is not None:
            try:
                device.close()
            except Exception as exc:
                self._set_error(f"Disconnect failed: {exc}")

    def ensure_parameters(self) -> None:
        owned = self.build_owned_metadata(device="papago_meteo")
        for key, item in self._enabled_quantities().items():
            spec = QUANTITIES[key]
            param = self._quantity_param(key, item)
            self.ensure_parameter(
                param,
                "static",
                value=None,
                metadata={
                    **owned,
                    "role": "measurement",
                    "quantity": key,
                    "label": spec.label,
                    "unit": spec.default_unit,
                },
            )
            if bool(item.get("publish_quality", True)):
                self.ensure_parameter(
                    self._quality_param(key, item),
                    "static",
                    value="unknown",
                    metadata={**owned, "role": "quality", "quantity": key},
                )

        for key, value in {
            "connected": False,
            "last_error": "",
            "last_sync": "",
            "device_time": "",
            "sensor_a_status": "",
            "sensor_a_type": "",
            "sensor_b_status": "",
            "sensor_b_type": "",
            "wind_sensor_status": "",
        }.items():
            self.ensure_parameter(
                self._status_param(key),
                "static",
                value=value,
                metadata={**owned, "role": "status"},
            )

    def _publish_snapshot(self, snapshot: dict[str, Any]) -> None:
        for key, item in self._enabled_quantities().items():
            data = snapshot["quantities"].get(key) or {}
            self.client.set_value(self._quantity_param(key, item), data.get("value"))
            if bool(item.get("publish_quality", True)):
                self.client.set_value(self._quality_param(key, item), data.get("quality", "unknown"))

        for key in (
            "device_time",
            "sensor_a_status",
            "sensor_a_type",
            "sensor_b_status",
            "sensor_b_type",
            "wind_sensor_status",
        ):
            self._set_status(key, snapshot.get(key, ""))

        self._set_status("connected", True)
        self._set_status("last_error", "")
        self._set_status("last_sync", datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    def run(self) -> None:
        interval = float(self.config.get("update_interval_s", 2.0))
        reconnect_delay = float(self.config.get("reconnect_delay_s", 2.0))

        while not self.should_stop():
            try:
                device = self._connect_device()
                snapshot = device.read_snapshot(
                    prefer_float=bool(self.config.get("prefer_float", False))
                )
                self._publish_snapshot(snapshot)
                if self.sleep(interval):
                    break
            except Exception as exc:
                self._disconnect_device()
                self._set_error(str(exc))
                if self.sleep(reconnect_delay):
                    break
        self._disconnect_device()
        self._set_status("connected", False)


class PapagoMeteoSourceSpec(DataSourceSpec):
    source_type = "papago_meteo"
    display_name = "PAPAGO Meteo ETH"
    description = "PAPAGO Meteo ETH Modbus-TCP datasource"

    def create(
        self,
        name: str,
        client: SupportsSignalRequests,
        *,
        config: dict[str, Any] | None = None,
    ) -> DataSourceBase:
        return PapagoMeteoSource(name, client, config=config)

    def default_config(self) -> dict[str, Any]:
        return {
            "host": "127.0.0.1",
            "port": 502,
            "unit_id": 1,
            "timeout": 1.5,
            "update_interval_s": 2.0,
            "reconnect_delay_s": 2.0,
            "parameter_prefix": "papago",
            "prefer_float": False,
            "quantities": {},
        }


SOURCE = PapagoMeteoSourceSpec()
