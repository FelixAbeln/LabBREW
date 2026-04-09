from __future__ import annotations

import asyncio
import contextlib
import json
import time
from datetime import UTC, datetime
from typing import Any
from urllib.request import Request, urlopen

from ...parameterdb_core.client import SupportsSignalRequests
from ...parameterdb_sources.base import DataSourceBase, DataSourceSpec

_TILT_COLORS = (
    "Red",
    "Green",
    "Black",
    "Purple",
    "Orange",
    "Blue",
    "Yellow",
    "Pink",
)

_TILT_COLOR_CANONICAL = {name.lower(): name for name in _TILT_COLORS}

_TILT_COLOR_UUIDS = {
    "Red": "a495bb10c5b14b44b5121370f02d74de",
    "Green": "a495bb20c5b14b44b5121370f02d74de",
    "Black": "a495bb30c5b14b44b5121370f02d74de",
    "Purple": "a495bb40c5b14b44b5121370f02d74de",
    "Orange": "a495bb50c5b14b44b5121370f02d74de",
    "Blue": "a495bb60c5b14b44b5121370f02d74de",
    "Yellow": "a495bb70c5b14b44b5121370f02d74de",
    "Pink": "a495bb80c5b14b44b5121370f02d74de",
}

_APPLE_COMPANY_ID = 0x004C


class TiltHydrometerSource(DataSourceBase):
    source_type = "tilt_hydrometer"
    display_name = "Tilt Hydrometer"
    description = (
        "Reads Tilt Bridge JSON and publishes gravity/temperature "
        "for one selected Tilt color."
    )

    def __init__(
        self,
        name: str,
        client: SupportsSignalRequests,
        *,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name, client, config=config)
        self._last_seen_monotonic: float | None = None
        self._last_battery_weeks: float | None = None

    def _prefix(self) -> str:
        return str(self.config.get("parameter_prefix", self.name)).strip() or self.name

    def _status_param(self, key: str) -> str:
        explicit = self.config.get(f"{key}_param")
        if explicit:
            return str(explicit)
        return f"{self._prefix()}.{key}"

    def _measurement_param(self, key: str) -> str:
        explicit = self.config.get(f"{key}_param")
        if explicit:
            return str(explicit)
        return f"{self._prefix()}.{key}"

    def _set_status(self, key: str, value: Any) -> None:
        self.client.set_value(self._status_param(key), value)

    def _set_error(self, message: str) -> None:
        self._set_status("connected", False)
        self._set_status("last_error", str(message))

    def _selected_color(self) -> str:
        raw = str(self.config.get("tilt_color", "Red") or "Red").strip()
        canonical = _TILT_COLOR_CANONICAL.get(raw.lower())
        if canonical is None:
            allowed = ", ".join(_TILT_COLORS)
            raise ValueError(
                f"Unsupported Tilt color '{raw}'. Allowed colors: {allowed}"
            )
        return canonical

    @staticmethod
    def _to_float(value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_gravity(item: dict[str, Any]) -> float | None:
        raw = item.get("gravity", item.get("Gravity", item.get("sg", item.get("SG"))))
        value = TiltHydrometerSource._to_float(raw)
        if value is None:
            return None
        # Classic Tilt commonly sends integer thousandths: 1048 => 1.048.
        # Tilt Pro commonly sends integer ten-thousandths: 10722 => 1.0722.
        if value >= 5000.0:
            value = value / 10000.0
        elif value > 5.0:
            value = value / 1000.0
        return value

    @staticmethod
    def _normalize_temp_f(item: dict[str, Any]) -> float | None:
        raw = item.get(
            "temp",
            item.get("Temp", item.get("temperature_f", item.get("temperatureF"))),
        )
        value = TiltHydrometerSource._to_float(raw)
        if value is None:
            return None
        # Tilt Pro commonly sends temp in tenths of F: 543 => 54.3 F.
        if value > 250.0:
            value = value / 10.0
        return value

    @staticmethod
    def _temp_c_from_f(temp_f: float | None) -> float | None:
        if temp_f is None:
            return None
        return (temp_f - 32.0) * (5.0 / 9.0)

    @staticmethod
    def _normalize_color(item: dict[str, Any]) -> str:
        return str(item.get("color", item.get("Color", ""))).strip().title()

    def _bridge_url(self) -> str:
        return str(
            self.config.get("bridge_url", "http://tiltbridge.local/json")
            or "http://tiltbridge.local/json"
        ).strip()

    def _transport(self) -> str:
        raw = str(self.config.get("transport", "bridge") or "bridge").strip().lower()
        return raw if raw in {"bridge", "ble"} else "bridge"

    def _ble_stale_after_s(self) -> float:
        explicit = self._to_float(self.config.get("ble_stale_after_s"))
        if explicit is not None:
            return max(0.0, explicit)
        scan_timeout = self._to_float(self.config.get("ble_scan_timeout_s")) or 4.0
        return max(15.0, scan_timeout * 3.0)

    def _fetch_payload(self) -> list[dict[str, Any]]:
        req = Request(
            self._bridge_url(),
            headers={"Accept": "application/json", "User-Agent": "LabBREW-Tilt/1.0"},
        )
        timeout_s = float(self.config.get("request_timeout_s", 3.0))
        with urlopen(req, timeout=timeout_s) as resp:  # nosec: B310 - trusted operator-configured Tilt Bridge URL
            body = resp.read().decode("utf-8", errors="replace")
        data = json.loads(body)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict) and isinstance(data.get("tilts"), list):
            return [item for item in data["tilts"] if isinstance(item, dict)]
        raise ValueError("Tilt Bridge payload must be a JSON list of objects")

    def _tilt_uuid_for_color(self) -> str:
        color = self._selected_color()
        return _TILT_COLOR_UUIDS[color]

    @staticmethod
    def _decode_tilt_from_manufacturer_data(
        manufacturer_data: dict[int, bytes], wanted_uuid: str
    ) -> dict[str, Any] | None:
        blob = manufacturer_data.get(_APPLE_COMPANY_ID)
        # bleak manufacturer_data bytes do not include the 2-byte company ID.
        # Standard iBeacon payload here is 23 bytes:
        # 0x02,0x15 + UUID(16) + major(2) + minor(2) + tx(1).
        if not blob or len(blob) < 23:
            return None
        # Apple iBeacon framing: 0x02 0x15 + UUID(16) + major(2) + minor(2) + tx(1)
        if blob[0] != 0x02 or blob[1] != 0x15:
            return None
        uuid_hex = blob[2:18].hex()
        if uuid_hex.lower() != wanted_uuid.lower():
            return None
        major = int.from_bytes(blob[18:20], byteorder="big", signed=False)
        minor = int.from_bytes(blob[20:22], byteorder="big", signed=False)
        return {
            "Temp": float(major),
            "SG": float(minor),
        }

    async def _discover_ble_measurement(self) -> dict[str, Any] | None:
        try:
            from bleak import BleakScanner
        except ModuleNotFoundError as exc:
            raise RuntimeError("bleak is required for Tilt BLE transport") from exc

        scan_timeout_s = float(self.config.get("ble_scan_timeout_s", 4.0))
        wanted_uuid = self._tilt_uuid_for_color()
        wanted_address = (
            str(self.config.get("ble_device_address", "") or "").strip().lower()
        )
        found_event = asyncio.Event()
        selected: dict[str, Any] = {}

        def _on_detection(device: Any, adv_data: Any) -> None:
            if selected:
                return
            if (
                wanted_address
                and str(getattr(device, "address", "")).strip().lower()
                != wanted_address
            ):
                return
            decoded = self._decode_tilt_from_manufacturer_data(
                getattr(adv_data, "manufacturer_data", {}) or {}, wanted_uuid
            )
            if decoded is None:
                return
            decoded["Color"] = self._selected_color()
            decoded["RSSI"] = float(
                getattr(adv_data, "rssi", getattr(device, "rssi", 0.0))
            )
            selected.update(decoded)
            found_event.set()

        scanner = BleakScanner(detection_callback=_on_detection)
        await scanner.start()
        try:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(found_event.wait(), timeout=scan_timeout_s)
        finally:
            await scanner.stop()
        return dict(selected) if selected else None

    def _fetch_ble_selected(self) -> dict[str, Any] | None:
        return asyncio.run(self._discover_ble_measurement())

    def _find_selected(self, payload: list[dict[str, Any]]) -> dict[str, Any] | None:
        wanted = self._selected_color().lower()
        for item in payload:
            if self._normalize_color(item).lower() == wanted:
                return item
        return None

    def ensure_parameters(self) -> None:
        owned = self.build_owned_metadata(device="tilt_hydrometer")
        self.ensure_parameter(
            self._measurement_param("gravity"),
            "static",
            value=None,
            metadata={**owned, "role": "measurement", "unit": "SG"},
        )
        self.ensure_parameter(
            self._measurement_param("temperature_f"),
            "static",
            value=None,
            metadata={**owned, "role": "measurement", "unit": "F"},
        )
        self.ensure_parameter(
            self._measurement_param("temperature_c"),
            "static",
            value=None,
            metadata={**owned, "role": "measurement", "unit": "C"},
        )
        self.ensure_parameter(
            self._measurement_param("rssi"),
            "static",
            value=None,
            metadata={**owned, "role": "measurement", "unit": "dBm"},
        )
        self.ensure_parameter(
            self._measurement_param("battery_weeks"),
            "static",
            value=None,
            metadata={**owned, "role": "measurement", "unit": "weeks"},
        )
        self.ensure_parameter(
            self._measurement_param("tilt_color"),
            "static",
            value=self._selected_color(),
            metadata={**owned, "role": "status"},
        )
        self.ensure_parameter(
            self._measurement_param("raw"),
            "static",
            value={},
            metadata={**owned, "role": "status"},
        )
        self.ensure_parameter(
            self._status_param("connected"),
            "static",
            value=False,
            metadata={**owned, "role": "status"},
        )
        self.ensure_parameter(
            self._status_param("last_error"),
            "static",
            value="",
            metadata={**owned, "role": "status"},
        )
        self.ensure_parameter(
            self._status_param("last_sync"),
            "static",
            value="",
            metadata={**owned, "role": "status"},
        )

    def _publish_selected(self, selected: dict[str, Any]) -> None:
        gravity = self._normalize_gravity(selected)
        temp_f = self._normalize_temp_f(selected)
        temp_c = self._temp_c_from_f(temp_f)
        battery_weeks = self._to_float(
            selected.get(
                "weeks_on_battery",
                selected.get("WeeksOnBattery", selected.get("battery_weeks")),
            )
        )
        rssi = self._to_float(selected.get("rssi", selected.get("RSSI")))

        if battery_weeks is not None:
            self._last_battery_weeks = battery_weeks
        elif self._last_battery_weeks is not None:
            battery_weeks = self._last_battery_weeks

        self.client.set_value(
            self._measurement_param("tilt_color"),
            self._normalize_color(selected) or self._selected_color(),
        )
        self.client.set_value(self._measurement_param("gravity"), gravity)
        self.client.set_value(self._measurement_param("temperature_f"), temp_f)
        self.client.set_value(self._measurement_param("temperature_c"), temp_c)
        self.client.set_value(self._measurement_param("battery_weeks"), battery_weeks)
        self.client.set_value(self._measurement_param("rssi"), rssi)
        self.client.set_value(self._measurement_param("raw"), dict(selected))
        self._set_status("connected", True)
        self._set_status("last_error", "")
        self._set_status("last_sync", datetime.now(UTC).isoformat())
        self._last_seen_monotonic = time.monotonic()

    def run(self) -> None:
        interval_s = float(self.config.get("update_interval_s", 2.0))
        ble_idle_s = float(self.config.get("ble_idle_s", 0.0))
        while not self.should_stop():
            try:
                if self._transport() == "ble":
                    selected = self._fetch_ble_selected()
                    if selected is None:
                        last_seen = self._last_seen_monotonic
                        age_s = (
                            (time.monotonic() - last_seen)
                            if last_seen is not None
                            else None
                        )
                        if age_s is not None and age_s <= self._ble_stale_after_s():
                            self._set_status("connected", True)
                            self._set_status("last_error", "")
                        else:
                            self._set_error(
                                f"Tilt color '{self._selected_color()}' "
                                "not seen over BLE"
                            )
                    else:
                        self._publish_selected(selected)
                else:
                    payload = self._fetch_payload()
                    selected = self._find_selected(payload)
                    if selected is None:
                        self._set_error(
                            f"Tilt color '{self._selected_color()}' "
                            "not present in bridge payload"
                        )
                    else:
                        self._publish_selected(selected)
            except Exception as exc:
                self._set_error(str(exc))
            sleep_s = ble_idle_s if self._transport() == "ble" else interval_s
            self.sleep(max(0.0, sleep_s))
        self._set_status("connected", False)


class TiltHydrometerSourceSpec(DataSourceSpec):
    source_type = "tilt_hydrometer"
    display_name = "Tilt Hydrometer"
    description = (
        "Reads one Tilt color from Tilt Bridge JSON and publishes SG + temperature."
    )

    def create(
        self,
        name: str,
        client: SupportsSignalRequests,
        *,
        config: dict[str, Any] | None = None,
    ) -> DataSourceBase:
        return TiltHydrometerSource(name, client, config=config)

    def default_config(self) -> dict[str, Any]:
        return {
            "transport": "bridge",
            "bridge_url": "http://tiltbridge.local/json",
            "tilt_color": "Red",
            "parameter_prefix": "tilt",
            "update_interval_s": 2.0,
            "request_timeout_s": 3.0,
            "ble_scan_timeout_s": 4.0,
            "ble_device_address": "",
            "ble_idle_s": 0.0,
            "ble_stale_after_s": 20.0,
        }


SOURCE = TiltHydrometerSourceSpec()
