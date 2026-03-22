from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...parameterdb_core.client import SupportsSignalRequests
from ...parameterdb_sources.base import DataSourceBase, DataSourceSpec


class SystemTimeSource(DataSourceBase):
    source_type = "system_time"
    display_name = "System Time"
    description = "Publishes the local system time into a hold parameter once per interval."

    def ensure_parameters(self) -> None:
        param_name = self.config.get("parameter_name", "system.time.iso")
        self.ensure_parameter(
            param_name,
            "static",
            value="",
            metadata=self.build_owned_metadata(role="timestamp"),
        )

    def _current_value(self) -> str | float | int:
        mode = str(self.config.get("mode", "iso")).lower()
        now = datetime.now(timezone.utc)
        if mode == "unix_ms":
            return int(now.timestamp() * 1000)
        if mode == "unix":
            return now.timestamp()
        return now.isoformat()

    def run(self) -> None:
        interval = float(self.config.get("update_interval_s", 1.0))
        param_name = self.config.get("parameter_name", "system.time.iso")
        while not self.should_stop():
            self.client.set_value(param_name, self._current_value())
            self.sleep(interval)


class SystemTimeSourceSpec(DataSourceSpec):
    source_type = "system_time"
    display_name = "System Time"
    description = "Publishes system time to a hold parameter"

    def create(self, name: str, client: SupportsSignalRequests, *, config: dict[str, Any] | None = None) -> DataSourceBase:
        return SystemTimeSource(name, client, config=config)

    def default_config(self) -> dict[str, Any]:
        return {
            "parameter_name": "system.time.iso",
            "update_interval_s": 1.0,
            "mode": "iso",
        }


SOURCE = SystemTimeSourceSpec()
