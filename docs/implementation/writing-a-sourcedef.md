# Writing a ParameterDB Source Definition (SourceDef)

A **SourceDef** is a self-contained folder under `Services/parameterDB/sourceDefs/` that
teaches LabBREW how to connect to one category of hardware or software data source.
It is distinct from a **plugin** (a parameter computation type under `plugins/`):

| Concept | Lives in | Purpose |
|---|---|---|
| Plugin | `plugins/<name>/` | Computes a parameter value each scan cycle |
| SourceDef | `sourceDefs/<name>/` | Connects to hardware, polls measurements, and creates parameters on startup |

Related documentation:
- [ParameterDB Source Definitions Reference](parameterdb-source-definitions.md)
- [Writing a ParameterDB Plugin (parameter computation)](writing-a-parameterdb-plugin.md)

---

## 1. Folder structure

```text
Services/parameterDB/sourceDefs/
└── mydevice/
    ├── service.py   # required — SourceBase subclass + factory
    └── ui.py        # required — get_ui_spec(), optional run_ui_action()
```

No `__init__.py` is needed. The loader discovers source types by scanning for folders that
contain `service.py`.

---

## 2. `service.py` — the runtime source

This file provides the class that actually talks to hardware. Extend `SourceBase`.

```python
from __future__ import annotations

from typing import Any

from ...parameterdb_sources.source_base import SourceBase


class MyDeviceSource(SourceBase):
    source_type = "mydevice"
    display_name = "My Device"
    description  = "One-line summary shown in the UI."

    def __init__(self, name: str, config: dict[str, Any], store, logger=None):
        super().__init__(name, config=config, store=store, logger=logger)
        self._connected = False

    # --- Lifecycle ---

    def start(self) -> None:
        """Called once when the source is activated. Open connections here."""
        host = self.config.get("host", "127.0.0.1")
        port = int(self.config.get("port", 9000))
        # open socket / serial port / CAN channel / etc.
        self._connected = True

    def stop(self) -> None:
        """Called when the source is stopped or deleted. Release resources here."""
        self._connected = False

    # --- Polling ---

    def poll(self) -> None:
        """Called by the runtime on update_interval_s cadence.
        Read hardware and write values into the store."""
        if not self._connected:
            return

        # Read your device
        raw_value = 42.0  # replace with actual read

        # Publish into ParameterDB — use the configured prefix
        prefix = self.config.get("parameter_prefix", self.name)
        param_name = f"{prefix}.value"
        self.store.set_value(param_name, raw_value)

    # --- Parameter ownership ---

    def owned_parameters(self) -> list[str]:
        """Return parameter names this source creates.
        Used by the UI 'Delete + Clean' option to remove owned params."""
        prefix = self.config.get("parameter_prefix", self.name)
        return [f"{prefix}.value"]
```

Key rules:
- `start()` and `stop()` bracket the source lifetime. Do not raise from `stop()`.
- `poll()` is called on the configured interval. Never block for longer than the interval.
- Call `self.store.set_value(name, value)` to publish readings.
- The `owned_parameters()` list is used by the **Delete + Clean** UI button to remove
  parameters when the source is deleted.

---

## 3. `ui.py` — the frontend contract

`ui.py` has two responsibilities:

1. `get_ui_spec()` — returns a dict describing the create/edit form and optional auto-discovery panel.
2. `run_ui_action()` — handles on-demand actions triggered from the discovery panel (optional, only needed if auto-discovery is wanted).

### 3.1 `get_ui_spec()`

```python
def get_ui_spec(record: dict | None = None, mode: str | None = None) -> dict:
    ...
```

- `record` — the existing source record when editing, `None` when creating.
- `mode`  — `"control"` when the supervisor requests the operator control spec;
            `None` or `"create"` / `"edit"` otherwise.

The function must return a dict conforming to the spec described in section 4.

---

## 4. The UI Spec — full schema

```python
{
    "source_type": "mydevice",       # must match service.py source_type
    "display_name": "My Device",
    "description": "Shown in the create-source header.",

    # --- Optional: auto-discovery module panel ---
    "module": { ... },               # see section 5

    # --- Optional: graph dependency hints ---
    "graph": {
        "depends_on": ["some.param.name"]
    },

    # --- Create-mode form ---
    "create": {
        "required": ["name", "config.host"],
        "defaults": {
            "config": {
                "host": "127.0.0.1",
                "port": 9000,
                "parameter_prefix": "mydevice",
                "update_interval_s": 1.0,
            }
        },
        "sections": [ ... ],         # see section 6
    },

    # --- Edit-mode form ---
    "edit": {
        "sections": [ ... ],
    },

    # --- Operator control spec (returned when mode == "control") ---
    # This is a separate dict, not part of the create/edit spec.
    # See section 7.
}
```

---

## 5. The `module` key — auto-discovery panel

When a source type benefits from hardware scanning (e.g. "find BLE
devices", "scan network for relay boards", "detect CAN adapters"), you add a `module` key
to the spec. When `replace_form: True` is set, the entire create form is replaced with
just Name + Prefix fields plus the discovery panel.

`menu.run` is required for module actions. Use `{"mode": "auto"}` for immediate scanning or
`{"mode": "manual"}` for button-triggered scans.

```python
"module": {
    "id": "myDeviceDiscovery",          # unique string, used by React as component key
    "display_name": "My Device Discovery",
    "description": "Short text shown above the scan results.",
    "replace_form": True,               # True → hide form sections, show only Name + Prefix + module

    "menu": {

        # Optional manual fields shown above the scan button.
        # Set to [] for fully automatic discovery — user fills nothing.
        "fields": [],

        # Standard run contract for module actions.
        "run": {
            "mode": "auto",                  # "auto" | "manual"
            "poll_interval_s": 3.0,           # optional; only meaningful for mode="auto"
            "request_timeout_s": 8.0,         # optional; frontend abort timeout per request
            "cancel_inflight_on_cleanup": True,
        },

        # If True, discovered items persist across poll cycles (new items are merged in,
        # old items are NOT removed when absent from the latest scan).
        "preserve_results": True,

        # If True, backend warnings from run_ui_action are never shown in the UI.
        # Use when transient failures (e.g. mDNS not resolving) are expected noise.
        "suppress_warnings": False,

        # The backend action to invoke when scanning.
        "action": {
            "id":     "scan",           # used as React key
            "action": "scan_devices",   # must match run_ui_action names
            "label":  "Scan Network",   # button text when run.mode is "manual"
        },

        # How to display and apply the scan results.
        "result": {
            "list_key":     "devices",        # key in run_ui_action() response dict
            "key_fields":   ["host", "port"], # unique identity across poll merges
            "title_key":    "host",           # bold first line of each card
            "subtitle_keys": ["port"],        # secondary text on each card
            "status_key":   "reachable",      # bool — True shows green "ready" badge
            "error_key":    "error",          # shown when status is False
            "apply_label":  "Use This Device",
            "empty_message": "No devices found.",
            # Maps result item fields → config keys when user clicks "Use This Device".
            "apply_map": {
                "host": "host",
                "port": "port",
            },
        },
    },
},
```

### Field spec (when `fields` is not empty)

Each item in `fields` is a manual input rendered above the scan button:

```python
{
    "key":        "host",          # field state key in the module panel
    "config_key": "host",          # config key patched when value changes (defaults to key)
    "label":      "Host / CIDR",
    "type":       "string",        # "string" | "int" | "float" | "enum"
    "default":    "192.168.0.0/24",
    "choices":    [],              # required when type == "enum"
    "min":        None,            # optional for int/float
}
```

---

## 6. `create` / `edit` sections

Used when `module.replace_form` is `False` (or absent), or for the edit form.

```python
"sections": [
    {
        "title": "Identity",
        "fields": [
            {"key": "name",                   "label": "Source Name",       "type": "string", "required": True},
            {"key": "config.parameter_prefix","label": "Parameter Prefix",  "type": "string", "required": True},
        ],
    },
    {
        "title": "Connection",
        "fields": [
            {"key": "config.host",  "label": "Host",    "type": "string", "required": True},
            {"key": "config.port",  "label": "Port",    "type": "int",    "required": True},
        ],
    },
]
```

Field types: `"string"`, `"int"`, `"float"`, `"bool"`, `"enum"`, `"json"`, `"parameter_ref"`, `"parameter_ref_list"`.

Additional field attributes:

| Attribute | Type | Description |
|---|---|---|
| `help` | string | Small hint shown below the field |
| `choices` | list | Required for `type=enum` |
| `visible_when` | dict | `{config_key: value}` — field hidden unless config matches |
| `required` | bool | Triggers validation on save |
| `default` | any | Used when building initial form data |

---

## 7. `run_ui_action()` — the discovery backend

Add this function when `menu.action.action` is set. It performs the actual hardware scan
and returns a list of discovered devices for the frontend to display as cards.

```python
def run_ui_action(
    action: str,
    payload: dict[str, Any] | None = None,
    record:  dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    action  — the action name string from the frontend (matches menu.action.action)
    payload — form field values from the module panel (module menu.fields state)
              plus any user-typed values; treat as hints, not trusted input
    record  — the current source record when editing existing source, None when creating
    """
    action_name = str(action or "").strip().lower()
    if action_name not in {"scan_devices", "scan"}:
        raise ValueError(f"Unsupported action: {action}")

    devices: list[dict[str, Any]] = []
    warnings: list[str] = []

    # --- Perform hardware / network scan ---
    found_items, error = _scan_network(payload)
    if error:
        warnings.append(error)
    devices.extend(found_items)

    # Return dict.  "devices" must match result.list_key in the module spec.
    return {
        "ok":       True,
        "action":   action_name,
        "devices":  devices,          # ← must match module.menu.result.list_key
        "scanned":  len(devices),     # optional — shown in "no results" message
        "warnings": warnings,         # list of strings; suppressed if suppress_warnings=True
    }
```

### Item dict schema

Each item in the returned list must contain at minimum the fields referenced in your
`apply_map` and the `title_key`, `subtitle_keys`, `status_key`, `error_key` fields:

```python
{
    "host":      "192.168.1.42",    # title_key
    "port":      502,               # subtitle_key
    "reachable": True,              # status_key — True → "ready" badge, False → error text
    "error":     "",                # error_key  — shown when reachable is False
    "selectable": True,             # required for button to be enabled
    # Any extra fields referenced by apply_map:
    "unit_id":   1,
    "channel_count": 8,
}
```

### Loader contract

The loader (`parameterdb_sources/loader.py`) calls `run_ui_action` using keyword
arguments:

```python
result = run_ui_action(action=action_name, payload=action_payload, record=record)
```

If that raises `TypeError` (old signature) it falls back to positional. Always use
keyword arguments in your signature.

---

## 8. How the React panel works end-to-end

Understanding this helps you design your `run_ui_action` response and `apply_map` correctly.

```text
User opens "Add source" modal
    │
    ├─ Frontend fetches GET /parameterdb/source-types/{type}/ui
    │   └─ Returns get_ui_spec() dict
    │
    ├─ If module.replace_form == True:
    │   └─ Show: [Type dropdown] [Name field] [Prefix field] [SourceModulePanel]
    │
    ├─ SourceModulePanel mounts:
    │   ├─ If run.mode == "auto" → immediately calls runAction()
    │   └─ If run.poll_interval_s > 0 → sets up a poll loop (setTimeout)
    │
    ├─ runAction() calls:
    │   POST /parameterdb/source-types/{type}/module-actions/{action}
    │   Body: { payload: <module field state>, name: <source name if editing> }
    │   └─ Backend calls run_ui_action(action, payload, record) → returns dict
    │
    ├─ Frontend reads response.result[list_key]:
    │   ├─ If preserve_results == True → merge new items with existing (keep old)
    │   └─ If preserve_results == False → replace list entirely
    │
    ├─ Each item renders as a card:
    │   ├─ title  = item[title_key]
    │   ├─ subtitle = item[subtitle_keys].join(' · ')
    │   ├─ badge:
    │   │   ├─ item[status_key] == True  → green "ready" badge
    │   │   ├─ item[status_key] == False → red error text
    │   │   └─ isItemSelected(item) == True → green "selected" badge (overrides others)
    │   └─ button:
    │       ├─ Disabled if status == False or already selected
    │       └─ On click → applyResultItem(item):
    │           apply_map entries → patch draft.config
    │           Card turns green ("selected") immediately
    │
    └─ User clicks Save → draft.config is validated and POST /parameterdb/sources
```

### Green "selected" state

A card becomes green when **all** `apply_map` config values match the current draft.
For example, if `apply_map = {"host": "host", "port": "port"}`, the card for
`{host: "192.168.1.42", port: 502}` is selected when `draft.config.host == "192.168.1.42"`
AND `draft.config.port == 502` (string-compared).

This means when a user opens the **edit** form for an existing source and the module panel
auto-scans, the current device is automatically highlighted as selected.

---

## 9. Complete minimal example

Below is a minimal but complete source def for a hypothetical UDP sensor.

### `service.py`

```python
from __future__ import annotations
import socket
from typing import Any
from ...parameterdb_sources.source_base import SourceBase


class UdpSensorSource(SourceBase):
    source_type  = "udp_sensor"
    display_name = "UDP Sensor"
    description  = "Reads a UDP sensor and publishes measurements."

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(0.5)

    def stop(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass

    def poll(self) -> None:
        host = self.config.get("host", "127.0.0.1")
        port = int(self.config.get("port", 9000))
        prefix = self.config.get("parameter_prefix", self.name)
        try:
            self._sock.sendto(b"READ\n", (host, port))
            data, _ = self._sock.recvfrom(64)
            value = float(data.decode().strip())
            self.store.set_value(f"{prefix}.value", value)
        except Exception as exc:
            self.store.set_value(f"{prefix}.error", str(exc))

    def owned_parameters(self) -> list[str]:
        prefix = self.config.get("parameter_prefix", self.name)
        return [f"{prefix}.value", f"{prefix}.error"]
```

### `ui.py`

```python
from __future__ import annotations
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any


def _probe_host(host: str, port: int, timeout: float) -> dict[str, Any] | None:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(b"PING\n", (host, port))
        data, _ = sock.recvfrom(64)
        sock.close()
        return {
            "host": host, "port": port,
            "reachable": True, "error": "", "selectable": True,
        }
    except Exception:
        return None


def _scan_subnet(payload: dict) -> tuple[list[dict], str]:
    port = int(payload.get("port") or 9000)
    timeout = float(payload.get("timeout") or 0.08)
    # Build candidate list — scan local /24 subnet plus localhost
    hosts = ["127.0.0.1"]
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
        parts = local_ip.split(".")
        if len(parts) == 4:
            base = ".".join(parts[:3])
            hosts += [f"{base}.{i}" for i in range(1, 255)]
    except Exception:
        pass

    found: list[dict] = []
    with ThreadPoolExecutor(max_workers=32) as pool:
        futures = {pool.submit(_probe_host, h, port, timeout): h for h in hosts}
        for f in as_completed(futures):
            item = f.result()
            if item is not None:
                found.append(item)
    return found, ""


def get_ui_spec(record: dict | None = None, mode: str | None = None) -> dict:
    return {
        "source_type": "udp_sensor",
        "display_name": "UDP Sensor",
        "description": "Reads a UDP sensor and publishes measurements.",

        "module": {
            "id": "udpSensorDiscovery",
            "display_name": "UDP Sensor Discovery",
            "description": "Scan network for reachable UDP sensors.",
            "replace_form": True,
            "menu": {
                "fields": [],
                "run": {
                    "mode": "auto",
                    "cancel_inflight_on_cleanup": True,
                },
                "action": {
                    "id":     "scan",
                    "action": "scan_sensors",
                    "label":  "Scan Network",
                },
                "result": {
                    "list_key":     "devices",
                    "title_key":    "host",
                    "subtitle_keys": ["port"],
                    "status_key":   "reachable",
                    "error_key":    "error",
                    "apply_label":  "Use This Sensor",
                    "empty_message": "No UDP sensors found on network.",
                    "apply_map": {
                        "host": "host",
                        "port": "port",
                    },
                },
            },
        },

        "create": {
            "required": ["name", "config.host"],
            "defaults": {
                "config": {
                    "host": "127.0.0.1",
                    "port": 9000,
                    "parameter_prefix": "sensor",
                    "update_interval_s": 1.0,
                }
            },
            "sections": [
                {
                    "title": "Identity",
                    "fields": [
                        {"key": "name",                    "label": "Source Name",      "type": "string", "required": True},
                        {"key": "config.parameter_prefix", "label": "Param Prefix",     "type": "string", "required": True},
                    ],
                },
                {
                    "title": "Connection",
                    "fields": [
                        {"key": "config.host", "label": "Host", "type": "string", "required": True},
                        {"key": "config.port", "label": "Port", "type": "int",    "required": True},
                    ],
                },
            ],
        },

        "edit": {
            "sections": [
                {
                    "title": "Identity",
                    "fields": [
                        {"key": "name",                    "label": "Source Name",  "type": "string", "required": True},
                        {"key": "config.parameter_prefix", "label": "Param Prefix", "type": "string", "required": True},
                    ],
                },
                {
                    "title": "Connection",
                    "fields": [
                        {"key": "config.host",            "label": "Host",               "type": "string", "required": True},
                        {"key": "config.port",            "label": "Port",               "type": "int",    "required": True},
                        {"key": "config.update_interval_s","label":"Poll Interval (s)",   "type": "float",  "required": True},
                    ],
                },
            ],
        },
    }


def run_ui_action(
    action: str,
    payload: dict[str, Any] | None = None,
    record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action_name = str(action or "").strip().lower()
    if action_name not in {"scan_sensors", "scan"}:
        raise ValueError(f"Unsupported action: {action}")

    devices, error = _scan_subnet(dict(payload or {}))
    warnings = [error] if error else []

    return {
        "ok":       True,
        "action":   action_name,
        "devices":  devices,
        "scanned":  len(devices),
        "warnings": warnings,
    }
```

---

## 10. Checklist

- [ ] `sourceDefs/<name>/service.py` exists with a `SourceBase` subclass
- [ ] `service.py` class has `source_type`, `display_name`, `description`
- [ ] `start()` / `stop()` / `poll()` implemented; `stop()` never raises
- [ ] `sourceDefs/<name>/ui.py` exists with `get_ui_spec()`
- [ ] `get_ui_spec()` `source_type` matches `service.py` exactly
- [ ] `create.defaults.config` covers all the fields your `poll()` uses
- [ ] If using auto-discovery: `module` key added, `run_ui_action()` present
- [ ] `run_ui_action()` returns `{"ok": True, "<list_key>": [...], "warnings": [...]}`
- [ ] Each discovery item has a `selectable: True` field (controls button enabled state)
- [ ] `apply_map` keys match actual `config` keys used by `service.py`
- [ ] `key_fields` set if using `preserve_results: True` (uniquely identifies each item)
- [ ] Unit tests written for `get_ui_spec()` metadata and `run_ui_action()` with mocked I/O
