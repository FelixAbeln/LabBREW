from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ...parameterdb_core.client import SupportsSignalRequests
from ...parameterdb_sources.base import DataSourceBase, DataSourceSpec


class SystemTimeSource(DataSourceBase):
    source_type = "system_time"
    display_name = "System Time"
    description = (
        "Publishes the local system time into a hold parameter once per interval."
    )

    def _status_param(self, key: str) -> str:
        explicit = self.config.get(f"{key}_param")
        if explicit:
            return str(explicit)
        prefix = (
            str(self.config.get("parameter_prefix", self.name)).strip() or self.name
        )
        return f"{prefix}.{key}"

    def _set_status(self, key: str, value: Any) -> None:
        self.client.set_value(self._status_param(key), value)

    def _set_error(self, message: str) -> None:
        self._set_status("connected", False)
        self._set_status("last_error", str(message))

    def ensure_parameters(self) -> None:
        param_name = self.config.get("parameter_name", "system.time.iso")
        owned = self.build_owned_metadata(role="timestamp")
        self.ensure_parameter(
            param_name,
            "static",
            value="",
            metadata=owned,
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

    def _current_value(self) -> str | float | int:
        mode = str(self.config.get("mode", "iso")).lower()
        now = datetime.now(UTC)
        if mode == "unix_ms":
            return int(now.timestamp() * 1000)
        if mode == "unix":
            return now.timestamp()
        return now.isoformat()

    def run(self) -> None:
        interval = float(self.config.get("update_interval_s", 1.0))
        param_name = self.config.get("parameter_name", "system.time.iso")
        while not self.should_stop():
            try:
                self.client.set_value(param_name, self._current_value())
                self._set_status("connected", True)
                self._set_status("last_error", "")
                self._set_status("last_sync", datetime.now(UTC).isoformat())
            except Exception as exc:
                self._set_error(str(exc))
            self.sleep(interval)
        self._set_status("connected", False)


class SystemTimeSourceSpec(DataSourceSpec):
    source_type = "system_time"
    display_name = "System Time"
    description = "Publishes system time to a hold parameter"

    def create(
        self,
        name: str,
        client: SupportsSignalRequests,
        *,
        config: dict[str, Any] | None = None,
    ) -> DataSourceBase:
        return SystemTimeSource(name, client, config=config)

    def default_config(self) -> dict[str, Any]:
        return {
            "parameter_name": "system.time.iso",
            "update_interval_s": 1.0,
            "mode": "iso",
        }


SOURCE = SystemTimeSourceSpec()
