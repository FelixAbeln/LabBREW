# Writing a ParameterDB Plugin

This guide covers everything needed to add a new plugin to ParameterDB, from the folder
structure through to tests. Follow the sections in order the first time; use it as a
checklist on subsequent plugins.

Related documentation:
- [ParameterDB Binary Protocol API](../api/parameterdb-api.md)
- [Plugin Runtime State Contract](../requirements/parameterdb-plugin-state-contract.md)

---

## 1. What a plugin is

A ParameterDB plugin is a self-contained directory under `Services/parameterDB/plugins/`
that teaches the engine about one new `parameter_type`. Each scan cycle the engine calls
`scan()` on every live parameter instance in dependency order, then publishes the updated
value and state to all subscribers.

Plugins communicate through the **store only** — they never hold references to other
`ParameterBase` objects directly. Reading happens via `ctx.store.get_value()` /
`ctx.store.snapshot()`, writing happens via `ctx.store.set_value()`.

---

## 2. Folder structure

```
Services/parameterDB/plugins/
└── myplugin/
    ├── implementation.py   # required — ParameterBase subclass + PluginSpec + PLUGIN sentinel
    └── ui.py               # optional but strongly recommended — get_ui_spec()
```

No `__init__.py` is required (the loader uses `importlib.import_module` with the dotted
path derived from the Services root).

The autodiscovery path (`autodiscover_plugins`) scans every subdirectory that contains
`implementation.py`, so the directory name **is** the plugin name for humans but the
canonical identity is `parameter_type` on the class.

---

## 3. `implementation.py` skeleton

```python
from __future__ import annotations

from typing import Any

from ...parameterdb_service.plugin_api import ParameterBase, PluginSpec


class MyParameter(ParameterBase):
    # --- Identity ---
    parameter_type = "myplugin"           # unique snake_case string
    display_name   = "My Plugin"          # shown in UI
    description    = "One-line summary."  # shown in UI

    # --- Optional: custom __init__ for extra instance state ---
    def __init__(self, name, *, config=None, value=None, metadata=None):
        super().__init__(name, config=config, value=value, metadata=metadata)
        # Add Python-only instance state here (NOT in self.state — that is published).
        self._some_cache: str = ""

    # --- Dependency declaration ---
    def dependencies(self) -> list[str]:
        """Return parameter names this plugin READS during scan().
        The engine uses this list to topologically sort scan order."""
        deps = [self.config.get("source"), self.config.get("enable_param")]
        return [str(d) for d in deps if d]

    def write_targets(self) -> list[str]:
        """Return parameter names this plugin WRITES during scan().
        The engine warns if multiple plugins write the same target."""
        return []  # or list(self._output_targets()) if mirror output is supported

    # --- Core scan ---
    def scan(self, ctx) -> None:
        # 1. Read config
        source_name  = self.config.get("source")
        enable_param = self.config.get("enable_param")

        # 2. Validate required config — set last_error, return early
        if not source_name:
            self.state["last_error"] = "myplugin requires 'source'"
            return

        # 3. Enable gate
        enabled = True
        if enable_param:
            enabled = bool(ctx.store.get_value(enable_param, True))
        self.state["enabled"] = bool(enabled)
        if not enabled:
            self.state.pop("last_error", None)
            return

        # 4. Read inputs from store
        raw_value = ctx.store.get_value(source_name)
        if raw_value is None:
            self.state["last_error"] = f"Missing value for {source_name}"
            return

        # 5. Compute output
        result = float(raw_value) * 2.0   # example

        # 6. Update self.value and publish domain state
        self.value = result
        self.state["source_value"] = raw_value
        self.state.pop("last_error", None)


# --- PluginSpec: factory + metadata for the registry ---
class MyPlugin(PluginSpec):
    parameter_type = "myplugin"
    display_name   = "My Plugin"
    description    = "One-line summary."

    def create(self, name, *, config=None, value=None, metadata=None) -> ParameterBase:
        return MyParameter(name, config=config, value=value, metadata=metadata)

    def default_config(self) -> dict[str, Any]:
        return {
            "source":       "",
            "enable_param": "",
        }

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source":       {"type": "string"},
                "enable_param": {"type": "string"},
            },
            "required": ["source"],
        }


# Module-level sentinel — the loader looks for exactly this name.
PLUGIN = MyPlugin()
```

Key rules:
- The loader imports `implementation.py` and reads `PLUGIN`. If `PLUGIN` is missing or is
  not a `PluginSpec` instance, loading fails.
- `parameter_type` must be **unique** across all plugins.
- Never `raise` from `scan()` for predictable domain errors. Set `self.state["last_error"]`
  and return. The engine catches unexpected exceptions, sets `connected = False`, and
  continues the scan loop.

---

## 4. Engine lifecycle — what happens each cycle

```
ScanEngine.scan_once()
  for each param in topological order:
    old_value = param.get_value()
    try:
        param.scan(ctx)           ← your code runs here
    except Exception as exc:
        param.state["last_error"] = str(exc)
        param.state["connected"]  = False
    new_value = param.get_value()

    # Engine post-processing (always applied after scan):
    if state["last_error"] is non-empty:
        state["connected"] = False
    elif state.get("enabled") is False:
        state["connected"] = False
        state["last_error"] = ""
    else:
        state["connected"] = True
        state["last_error"] = ""
        state["last_sync"]  = <UTC ISO-8601 timestamp>

    publish value_changed  (if value changed)
    publish scan_state     (always)
```

Consequences:
- **Never set `connected` or `last_sync` yourself** — the engine owns them.
- Setting `self.state["enabled"] = False` in `scan()` is the correct way to signal
  "intentionally inactive this cycle". The engine will set `connected = False` for you.
- Once `last_error` is non-empty, `connected` is forced to `False` regardless of anything
  else in `state`.

---

## 5. `ctx` — the ScanContext

```python
@dataclass
class ScanContext:
    now:         float          # time.time() at start of this scan cycle
    dt:          float          # seconds since the previous scan cycle
    cycle_count: int            # monotonically increasing cycle counter
    store:       ParameterStore
```

Useful store methods available inside `scan()`:

| Method | Purpose |
|---|---|
| `ctx.store.get_value(name, default)` | Read one parameter value |
| `ctx.store.snapshot()` | Read all values as `dict[str, Any]` |
| `ctx.store.set_value(name, value)` | Write to a **declared** `write_targets()` name |
| `ctx.store.exists(name)` | Check whether a parameter exists |

---

## 6. Dependency declaration

The engine builds a dependency graph every time the store revision changes (parameter
added/removed). Declare dependencies accurately so the scan order is correct.

```python
def dependencies(self) -> list[str]:
    # Include every parameter name read during scan().
    # Names that don't exist in the store generate a graph warning but do not error.
    deps = [
        self.config.get("pv"),
        self.config.get("sp"),
        self.config.get("enable_param"),
    ]
    return [str(d) for d in deps if d]

def write_targets(self) -> list[str]:
    # Include every parameter name written during scan().
    # The engine warns if two plugins declare the same write target.
    return self._output_targets()   # delegate to mirror-output helper if present
```

---

## 7. Mirror output (optional but standard)

All active plugins that produce a scalar output (`pid`, `deadband`, `math`, `condition`)
follow the same mirror-output pattern. Copy this verbatim and adjust the value type if
needed.

```python
def _output_targets(self) -> list[str]:
    raw = self.config.get("output_params") or []
    if isinstance(raw, str):
        raw = [raw]
    result: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if not item:
                continue
            name = str(item).strip()
            if name and name != self.name:
                result.append(name)
    return list(dict.fromkeys(result))   # preserve order, deduplicate

def write_targets(self) -> list[str]:
    return self._output_targets()

def _write_output_targets(self, store, value) -> None:
    written: list[str] = []
    missing: list[str] = []
    for target in self._output_targets():
        if not store.exists(target):
            missing.append(target)
            continue
        store.set_value(target, value)
        written.append(target)
    self.state["output_targets"] = written
    if missing:
        self.state["missing_output_targets"] = missing
    else:
        self.state.pop("missing_output_targets", None)
```

Call `self._write_output_targets(ctx.store, self.value)` at the end of `scan()` after
setting `self.value`. Add `output_params` to `default_config()`, `schema()`, and to the
UI spec (`"Mirror Output To"` field, `parameter_ref` type).

See the [Plugin Runtime State Contract](../requirements/parameterdb-plugin-state-contract.md#mirror-output-convention)
for the full published state key specification.

---

## 8. `ui.py` — the editor spec

The UI spec tells the frontend how to render create and edit forms. It is optional but
every shipping plugin should have one.

```python
def get_ui_spec() -> dict:
    return {
        "parameter_type": "myplugin",
        "display_name":   "My Plugin",
        "description":    "One-line summary shown in the plugin picker.",

        # ── Create form ────────────────────────────────────────────────────
        "create": {
            "required": ["name", "config.source"],
            "defaults": {
                "value":    0.0,
                "config":   {"source": "", "enable_param": "", "output_params": []},
                "metadata": {},
            },
            "sections": [
                {
                    "title": "Identity",
                    "fields": [
                        {
                            "key":      "name",
                            "label":    "Name",
                            "type":     "string",
                            "required": True,
                            "help":     "Unique parameter name.",
                        },
                    ],
                },
                {
                    "title": "Inputs",
                    "fields": [
                        {
                            "key":      "config.source",
                            "label":    "Source",
                            "type":     "parameter_ref",
                            "required": True,
                            "help":     "Parameter whose value is read.",
                        },
                        {
                            "key":   "config.enable_param",
                            "label": "Enable Parameter",
                            "type":  "parameter_ref",
                            "help":  "Optional flag that gates evaluation.",
                        },
                        {
                            "key":   "config.output_params",
                            "label": "Mirror Output To",
                            "type":  "parameter_ref",
                            "help":  "Optional parameters that receive the output value.",
                        },
                    ],
                },
                {
                    "title": "Initial Value",
                    "fields": [
                        {
                            "key":   "value",
                            "label": "Initial Output",
                            "type":  "float",
                            "help":  "Stored until the first successful scan.",
                        },
                    ],
                },
            ],
        },

        # ── Edit form ──────────────────────────────────────────────────────
        "edit": {
            "allow_rename": False,
            "sections": [
                {
                    "title": "Identity",
                    "fields": [
                        {"key": "name",  "label": "Name",           "type": "string", "readonly": True},
                        {"key": "value", "label": "Current Output", "type": "readonly"},
                    ],
                },
                {
                    "title": "Inputs",
                    "fields": [
                        {"key": "config.source",        "label": "Source",           "type": "parameter_ref", "required": True},
                        {"key": "config.enable_param",  "label": "Enable Parameter", "type": "parameter_ref"},
                        {"key": "config.output_params", "label": "Mirror Output To", "type": "parameter_ref"},
                    ],
                },
                {
                    "title": "State",
                    "fields": [
                        {"key": "state.source_value",           "label": "Source Value",    "type": "readonly"},
                        {"key": "state.output_targets",         "label": "Output Targets",  "type": "readonly"},
                        {"key": "state.missing_output_targets", "label": "Missing Targets", "type": "readonly"},
                        {"key": "state.last_error",             "label": "Last Error",      "type": "readonly"},
                    ],
                },
            ],
        },
    }
```

### UI field types

| type | Description |
|---|---|
| `string` | Single-line text; also the fallback default |
| `text` | Multi-line text area |
| `float` | Numeric input |
| `bool` | Checkbox / toggle |
| `enum` | Dropdown; requires `"options": [...]` list |
| `parameter_ref` | DB parameter name picker |
| `readonly` | Display-only; no edit control |

---

## 9. Tests

All plugin tests live in `tests/`. A minimal test set covers four areas:

### 9.1 Default config and schema contract

```python
def test_myplugin_default_config_and_schema() -> None:
    plugin = MyPlugin()
    defaults = plugin.default_config()
    schema  = plugin.schema()

    assert "source" in defaults
    assert "output_params" in defaults
    assert "source" in schema["required"]
    assert "output_params" in schema["properties"]
```

### 9.2 Happy-path scan

```python
from types import SimpleNamespace
from Services.parameterDB.plugins.myplugin.implementation import MyPlugin
from Services.parameterDB.plugins.static.implementation import StaticParameter
from Services.parameterDB.parameterdb_service.store import ParameterStore

def _ctx(store):
    return SimpleNamespace(store=store, dt=0.1)

def test_myplugin_happy_path() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.temp", value=50.0))

    plugin = MyPlugin()
    param  = plugin.create("out", config={"source": "reactor.temp"}, value=0.0)

    param.scan(_ctx(store))

    assert param.get_value() == 100.0          # 50.0 * 2
    assert param.state.get("last_error") == ""
```

### 9.3 Missing / invalid config

```python
def test_myplugin_missing_source_sets_error() -> None:
    plugin = MyPlugin()
    param  = plugin.create("out", config={}, value=0.0)

    param.scan(_ctx(ParameterStore()))

    assert "last_error" in param.state
    assert param.get_value() == 0.0   # value unchanged
```

### 9.4 Mirror output

```python
def test_myplugin_mirrors_output() -> None:
    store = ParameterStore()
    store.add(StaticParameter("reactor.temp", value=50.0))
    store.add(StaticParameter("mirror.target", value=0.0))

    plugin = MyPlugin()
    param  = plugin.create(
        "out",
        config={"source": "reactor.temp", "output_params": ["mirror.target"]},
        value=0.0,
    )

    param.scan(_ctx(store))

    assert param.get_value() == 100.0
    assert store.get_value("mirror.target") == 100.0
    assert "mirror.target" in param.state["output_targets"]
```

Run them with:

```
.venv/Scripts/python.exe -m pytest tests/test_myplugin.py -v
```

---

## 10. Checklist

Use this when reviewing a new plugin before merging.

### Implementation

- [ ] `parameter_type`, `display_name`, `description` set on both `ParameterBase` and `PluginSpec` subclasses
- [ ] Module-level `PLUGIN = MyPlugin()` sentinel present
- [ ] `scan()` never raises for expected domain errors — uses `self.state["last_error"]` instead
- [ ] `scan()` never sets `connected`, `last_sync` — engine-managed
- [ ] `dependencies()` lists every parameter name read from the store during scan
- [ ] `write_targets()` lists every parameter name written to the store during scan
- [ ] `enable_param` gate follows the standard pattern: set `state["enabled"] = False`, clear `last_error`, return
- [ ] Mirror output uses the standard `_output_targets` / `_write_output_targets` helpers
- [ ] `default_config()` includes `output_params: []` if mirror output is supported
- [ ] `schema()` includes `output_params` in `properties` if mirror output is supported

### UI spec

- [ ] `create.required` includes `"name"` and any truly required config keys
- [ ] `create.defaults.config` matches `default_config()` exactly
- [ ] `edit` section has a `"State"` group with `state.last_error` (and `state.output_targets` / `state.missing_output_targets` if mirror output is present)
- [ ] `"Mirror Output To"` field present in both create and edit if `output_params` is in config

### Tests

- [ ] Default config + schema contract test
- [ ] Happy-path scan test
- [ ] Missing / invalid config sets `last_error` and leaves `self.value` unchanged
- [ ] Mirror output writes correct value and records `output_targets`
- [ ] Missing mirror target recorded in `missing_output_targets`
- [ ] Enable-gate test: disabled plugin leaves value unchanged

### Contract

- [ ] Plugin row added to conformance table in [parameterdb-plugin-state-contract.md](../requirements/parameterdb-plugin-state-contract.md)
