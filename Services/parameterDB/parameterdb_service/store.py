from __future__ import annotations

import threading
from typing import Any

from .event_broker import EventBroker
from .plugin_api import ParameterBase, ParameterRecord


_SCALAR_TYPES = (int, float, bool, str, bytes, type(None))


def _values_equal(a: Any, b: Any) -> bool:
    """Return True when a and b should be considered the same value.

    For simple scalar types (int, float, bool, str, bytes, None) a normal
    equality check is performed — this covers the vast majority of sensor
    readings and suppresses redundant publish events efficiently.

    For all other types (dict, list, objects, numpy arrays, …) we conservatively
    return False so that a publish/revision bump always happens.  This avoids
    missing change events for mutable containers, types with exotic ``__eq__``
    implementations, or anything where ``bool(a == b)`` may raise (e.g. numpy
    arrays).
    """
    if not (isinstance(a, _SCALAR_TYPES) and isinstance(b, _SCALAR_TYPES)):
        return False
    # Preserve type-level changes (e.g. 1 -> True) as real changes.
    if type(a) is not type(b):
        return False
    try:
        return bool(a == b)
    except Exception:
        return False


class ParameterStore:
    """
    Thread-safe parameter store.

    Public methods return snapshots/copies only. Live mutable parameter objects are
    kept behind underscore-prefixed methods for the narrow internal runtime path
    used by the engine and service lifecycle hooks.
    """

    def __init__(self, event_broker: EventBroker | None = None) -> None:
        self._params: dict[str, ParameterBase] = {}
        self._lock = threading.RLock()
        self._revision = 0
        self._event_broker = event_broker

    def attach_event_broker(self, broker: EventBroker) -> None:
        with self._lock:
            self._event_broker = broker

    def _touch_unlocked(self) -> int:
        self._revision += 1
        return self._revision

    def revision(self) -> int:
        with self._lock:
            return self._revision

    def _publish(self, event: dict[str, Any]) -> None:
        broker = None
        with self._lock:
            broker = self._event_broker
        if broker is not None:
            broker.publish(dict(event))

    def exists(self, name: str) -> bool:
        with self._lock:
            return name in self._params

    def add(self, param: ParameterBase) -> None:
        record = param.to_record()
        with self._lock:
            if param.name in self._params:
                raise ValueError(f"Parameter '{param.name}' already exists")
            self._params[param.name] = param
            rev = self._touch_unlocked()
        self._publish({
            "event": "parameter_added",
            "name": record.name,
            "parameter_type": record.parameter_type,
            "value": record.value,
            "signal_value": record.signal_value,
            "config": record.config,
            "state": record.state,
            "metadata": record.metadata,
            "store_revision": rev,
        })

    def remove(self, name: str) -> bool:
        with self._lock:
            existed = self._params.pop(name, None) is not None
            rev = self._touch_unlocked() if existed else self._revision
        if existed:
            self._publish({
                "event": "parameter_removed",
                "name": name,
                "store_revision": rev,
            })
        return existed

    def get_record(self, name: str) -> ParameterRecord:
        with self._lock:
            try:
                return self._params[name].to_record()
            except KeyError as exc:
                raise KeyError(f"Unknown parameter '{name}'") from exc

    def set_value(self, name: str, value: Any, *, source: str = "external") -> None:
        with self._lock:
            param = self._params[name]
            old = param.get_value()
            param.set_value(value)
            new = param.get_value()
            # For scan/mirror writes, only publish if the value actually changed.
            # This avoids event spam when mirrors repeatedly write the same value.
            if source == "scan" and _values_equal(old, new):
                return
            rev = self._touch_unlocked()
        self._publish({
            "event": "value_changed",
            "name": name,
            "value": new,
            "source": str(source or "external"),
            "store_revision": rev,
        })

    def get_value(self, name: str, default: Any = None) -> Any:
        with self._lock:
            param = self._params.get(name)
            return default if param is None else param.get_value()

    def get_signal_value(self, name: str, default: Any = None) -> Any:
        """Return the raw signal value (pre-pipeline) for the named parameter."""
        with self._lock:
            param = self._params.get(name)
            return default if param is None else param.get_signal_value()

    def update_config(self, name: str, **changes: Any) -> None:
        with self._lock:
            self._params[name].update_config(**changes)
            config = dict(self._params[name].config)
            rev = self._touch_unlocked()
        self._publish({
            "event": "config_changed",
            "name": name,
            "config": config,
            "store_revision": rev,
        })

    def update_metadata(self, name: str, **metadata: Any) -> None:
        with self._lock:
            self._params[name].metadata.update(metadata)
            data = dict(self._params[name].metadata)
            rev = self._touch_unlocked()
        self._publish({
            "event": "metadata_changed",
            "name": name,
            "metadata": data,
            "store_revision": rev,
        })

    def list_names(self) -> list[str]:
        with self._lock:
            return sorted(self._params)

    def records(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {
                name: {
                    "parameter_type": record.parameter_type,
                    "value": record.value,
                    "signal_value": record.signal_value,
                    "config": record.config,
                    "state": record.state,
                    "metadata": record.metadata,
                }
                for name, record in (
                    (param.name, param.to_record())
                    for param in self._params.values()
                )
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {name: p.get_value() for name, p in self._params.items()}

    def signal_snapshot(self) -> dict[str, Any]:
        """Return a dict mapping every parameter name to its raw signal value."""
        with self._lock:
            return {name: p.get_signal_value() for name, p in self._params.items()}

    def snapshot_names(self, names: list[str]) -> dict[str, Any]:
        with self._lock:
            snapshots: dict[str, Any] = {}
            for name in names:
                param = self._params.get(name)
                snapshots[name] = None if param is None else param.get_value()
            return snapshots

    # ----------------------------
    # Narrow internal runtime API
    # ----------------------------

    def _get_runtime_param(self, name: str) -> ParameterBase:
        with self._lock:
            try:
                return self._params[name]
            except KeyError as exc:
                raise KeyError(f"Unknown parameter '{name}'") from exc

    def _iter_runtime_params(self) -> list[ParameterBase]:
        with self._lock:
            return list(self._params.values())

    def _remove_runtime_param(self, name: str) -> ParameterBase | None:
        with self._lock:
            param = self._params.pop(name, None)
            rev = self._touch_unlocked() if param is not None else self._revision
        if param is not None:
            self._publish({
                "event": "parameter_removed",
                "name": name,
                "store_revision": rev,
            })
        return param

    def publish_scan_value_if_changed(self, name: str, old: Any, new: Any) -> None:
        if not _values_equal(old, new):
            with self._lock:
                rev = self._touch_unlocked()
            self._publish({
                "event": "value_changed",
                "name": name,
                "value": new,
                "source": "scan",
                "store_revision": rev,
            })

    def publish_scan_state(self, name: str, state: dict[str, Any]) -> None:
        self._publish({
            "event": "state_changed",
            "name": name,
            "state": dict(state),
        })
