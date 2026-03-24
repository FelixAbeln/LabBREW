from __future__ import annotations

import socket
import struct
import threading
from typing import Any

from ...parameterdb_core.client import SupportsSignalRequests
from ...parameterdb_sources.base import DataSourceBase, DataSourceSpec


class RelayError(Exception):
    """Raised when the relay board communication fails or returns invalid data."""


class _ModbusTcpClient:
    def __init__(self, host: str, port: int = 502, unit_id: int = 1, timeout: float = 1.5) -> None:
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
            raise RelayError("Relay board is not connected.")
        data = bytearray()
        while len(data) < length:
            chunk = self._sock.recv(length - len(data))
            if not chunk:
                raise RelayError("Connection closed by relay board.")
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
                rx_tx_id, protocol_id, length, rx_unit_id = struct.unpack(">HHHB", response_header)
                if rx_tx_id != self._tx_id:
                    raise RelayError("Mismatched Modbus transaction ID.")
                if protocol_id != 0:
                    raise RelayError("Invalid Modbus protocol ID in response.")
                if rx_unit_id != self.unit_id:
                    raise RelayError("Unexpected Modbus unit ID in response.")
                response_pdu = self._recv_exact(length - 1)
            except (OSError, TimeoutError) as exc:
                self.close()
                raise RelayError(f"Network error talking to relay board: {exc}") from exc

            if not response_pdu:
                raise RelayError("Empty response from relay board.")

            rx_function = response_pdu[0]
            if rx_function == (function_code | 0x80):
                code = response_pdu[1] if len(response_pdu) > 1 else None
                raise RelayError(f"Modbus exception from relay board: {code}")
            if rx_function != function_code:
                raise RelayError("Unexpected Modbus function code in response.")
            return response_pdu[1:]

    def read_coils(self, start_address: int, count: int) -> list[bool]:
        payload = struct.pack(">HH", int(start_address), int(count))
        response = self.request(0x01, payload)
        if not response:
            raise RelayError("Missing read-coils payload.")
        byte_count = response[0]
        coil_bytes = response[1:1 + byte_count]
        if len(coil_bytes) != byte_count:
            raise RelayError("Short read-coils response.")

        values: list[bool] = []
        for index in range(count):
            byte_index = index // 8
            bit_index = index % 8
            bit = (coil_bytes[byte_index] >> bit_index) & 0x01
            values.append(bool(bit))
        return values

    def write_single_coil(self, address: int, value: bool) -> None:
        payload = struct.pack(">HH", int(address), 0xFF00 if value else 0x0000)
        response = self.request(0x05, payload)
        if len(response) != 4:
            raise RelayError("Invalid write-single-coil response length.")
        written_address, written_value = struct.unpack(">HH", response)
        if written_address != int(address):
            raise RelayError("Relay board acknowledged wrong coil address.")
        if written_value not in (0xFF00, 0x0000):
            raise RelayError("Relay board acknowledged invalid coil value.")


class RelayBoard:
    def __init__(self, host: str, port: int = 502, channel_count: int = 8, unit_id: int = 1, timeout: float = 1.5) -> None:
        if not host:
            raise RelayError("Enter a relay IP or host name first.")
        self.host = host.strip()
        self.port = int(port)
        self.channel_count = int(channel_count)
        self.unit_id = int(unit_id)
        self.timeout = float(timeout)
        self._client = _ModbusTcpClient(self.host, self.port, unit_id=self.unit_id, timeout=self.timeout)

    def connect(self) -> None:
        self._client.connect()
        self._client.read_coils(0, self.channel_count)

    def close(self) -> None:
        self._client.close()

    def all_states(self) -> dict[int, bool]:
        self.connect()
        states = self._client.read_coils(0, self.channel_count)
        return {channel: states[channel - 1] for channel in range(1, self.channel_count + 1)}

    def set_channel(self, channel: int, value: bool) -> None:
        if channel < 1 or channel > self.channel_count:
            raise RelayError(f"Invalid relay channel: {channel}")
        self.connect()
        self._client.write_single_coil(channel - 1, bool(value))


class ModbusRelaySource(DataSourceBase):
    source_type = "modbus_relay"
    display_name = "Modbus Relay Board"
    description = "Mirrors relay channel booleans to a Modbus-TCP relay board and republishes actual relay states."

    def __init__(self, name: str, client: SupportsSignalRequests, *, config: dict[str, Any] | None = None) -> None:
        super().__init__(name, client, config=config)
        self._board: RelayBoard | None = None

    def _channel_count(self) -> int:
        return max(1, int(self.config.get("channel_count", 8)))

    def _prefix(self) -> str:
        return str(self.config.get("parameter_prefix", self.name)).strip() or self.name

    def _channel_param(self, channel: int) -> str:
        explicit = self.config.get("channel_params") or {}
        if isinstance(explicit, dict) and str(channel) in explicit:
            return str(explicit[str(channel)])
        return f"{self._prefix()}.ch{channel}"

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

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in {"1", "true", "on", "yes", "enabled", "enable"}

    def _connect_board(self) -> RelayBoard:
        if self._board is not None:
            return self._board
        self._board = RelayBoard(
            host=str(self.config["host"]),
            port=int(self.config.get("port", 502)),
            channel_count=self._channel_count(),
            unit_id=int(self.config.get("unit_id", 1)),
            timeout=float(self.config.get("timeout", 1.5)),
        )
        self._board.connect()
        self._set_status("connected", True)
        self._set_status("last_error", "")
        return self._board

    def _disconnect_board(self) -> None:
        board = self._board
        self._board = None
        if board is not None:
            try:
                board.close()
            except Exception as exc:
                self._set_error(f"Disconnect failed: {exc}")

    def ensure_parameters(self) -> None:
        owned = self.build_owned_metadata(device="modbus_relay")
        for channel in range(1, self._channel_count() + 1):
            self.ensure_parameter(
                self._channel_param(channel),
                "static",
                value=False,
                metadata={**owned, "role": "relay_state", "channel": channel},
            )
        self.ensure_parameter(self._status_param("connected"), "static", value=False, metadata={**owned, "role": "status"})
        self.ensure_parameter(self._status_param("last_error"), "static", value="", metadata={**owned, "role": "status"})
        self.ensure_parameter(self._status_param("last_sync"), "static", value="", metadata={**owned, "role": "status"})

    def _desired_states(self) -> dict[int, bool]:
        desired: dict[int, bool] = {}
        for channel in range(1, self._channel_count() + 1):
            desired[channel] = self._coerce_bool(self.client.get_value(self._channel_param(channel), False))
        return desired

    def _publish_states(self, actual: dict[int, bool]) -> None:
        for channel, state in actual.items():
            self.client.set_value(self._channel_param(channel), bool(state))

    def _sync_once(self, board: RelayBoard) -> None:
        desired = self._desired_states()
        actual = board.all_states()

        for channel in range(1, self._channel_count() + 1):
            want = bool(desired.get(channel, False))
            have = bool(actual.get(channel, False))
            if want != have:
                board.set_channel(channel, want)

        refreshed = board.all_states()
        self._publish_states(refreshed)
        self._set_status("connected", True)
        self._set_status("last_error", "")
        self._set_status("last_sync", __import__("datetime").datetime.utcnow().isoformat() + "Z")

    def run(self) -> None:
        interval = float(self.config.get("update_interval_s", 0.25))
        reconnect_delay = float(self.config.get("reconnect_delay_s", 2.0))
        while not self.should_stop():
            try:
                board = self._connect_board()
                self._sync_once(board)
                if self.sleep(interval):
                    break
            except Exception as exc:
                self._disconnect_board()
                self._set_error(str(exc))
                if self.sleep(reconnect_delay):
                    break
        self._disconnect_board()
        self._set_status("connected", False)


class ModbusRelaySourceSpec(DataSourceSpec):
    source_type = "modbus_relay"
    display_name = "Modbus Relay Board"
    description = "Modbus-TCP relay datasource"

    def create(self, name: str, client: SupportsSignalRequests, *, config: dict[str, Any] | None = None) -> DataSourceBase:
        return ModbusRelaySource(name, client, config=config)

    def default_config(self) -> dict[str, Any]:
        return {
            "host": "127.0.0.1",
            "port": 502,
            "unit_id": 1,
            "channel_count": 8,
            "timeout": 1.5,
            "update_interval_s": 0.25,
            "reconnect_delay_s": 2.0,
            "parameter_prefix": "relay",
        }


SOURCE = ModbusRelaySourceSpec()
