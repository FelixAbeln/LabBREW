# ParameterDB Built-in Source Definitions

LabBREW ships these built-in source definitions under `Services/parameterDB/sourceDefs`.

Each source type is defined by a **SourceDef** — a pair of files:
- `service.py` — runtime class (`SourceBase` subclass) that owns a set of ParameterDB parameters and publishes values into them at its configured rate.
- `ui.py` — declarative spec consumed by the frontend to render the create/edit form, validate required fields, and describe how the source appears in the parameter dependency graph.

For a full developer guide on building a new source type, see
[writing-a-sourcedef.md](writing-a-sourcedef.md).

## Available Source Types

| Source Type | Purpose | Transport | Auto-Discovery |
|---|---|---|---|
| system_time | Publish system time into ParameterDB | local clock | — |
| tilt_hydrometer | Read one Tilt color and publish gravity/temperature/status | HTTP TiltBridge or direct BLE | BLE scan + TiltBridge HTTP |
| brewtools | Read Brewtools CAN measurements and expose command outputs | Kvaser CAN (python-can) and PCAN UDP gateway | Kvaser channel detect + UDP subnet probe |
| modbus_relay | Control and read Modbus TCP relay boards | Modbus TCP | TCP port scan + Modbus probe |
| labps3005dn | Control and monitor LABPS3005DN style bench PSU | serial | — |
| digital_twin | Run FMU-backed digital twin and publish outputs | local FMU runtime | — |

---

## system_time

Publishes the node's system clock into ParameterDB on every scan tick. Useful as a timestamp anchor and for schedule condition expressions that reference wall-clock time.

### Config keys

| Key | Required | Default | Description |
|---|---|---|---|
| `parameter_prefix` | yes | `system.time` | Namespace prefix for the generated parameter. The ISO timestamp parameter is named `<prefix>.iso`. |
| `parameter_name` | no | *(derived)* | Optional override for the full parameter name. If absent, `<parameter_prefix>.iso` is used. |
| `update_interval_s` | no | `1.0` | Publish interval in seconds. |

### Example

```yaml
name: system_clock
source_type: system_time
config:
  parameter_prefix: system.time
  update_interval_s: 1.0
```

This creates one ParameterDB parameter named `system.time.iso` that updates every second with an ISO-8601 string.

---

## tilt_hydrometer

Reads one Tilt hydrometer by color and publishes gravity, temperature, and battery status into ParameterDB.

### Transport modes

| Transport | Description |
|---|---|
| `bridge` | Fetches JSON from a TiltBridge HTTP endpoint (e.g. `http://tiltbridge.local/json`) |
| `ble` | Scans local Bluetooth for Tilt iBeacon advertisements directly |

### Auto-discovery

The create modal auto-scans for Tilt devices using `scan_tilts`:

1. Tries the configured TiltBridge URL (default `http://tiltbridge.local/json`).
2. Runs a BLE scan using Bleak (Windows WinRT backend).
3. Discovered Tilts appear as cards — click **Use This Tilt** to populate transport, color, and address.
4. The panel polls every **3 seconds** and merges new finds with the existing list (previously-seen Tilts stay visible even if absent from the latest scan).
5. DNS/mDNS warnings (e.g. `tiltbridge.local` not resolving) are suppressed — a missing bridge is treated as no bridge results found.

### Config keys

| Key | Required | Default | Description |
|---|---|---|---|
| `parameter_prefix` | yes | `tilt` | Namespace for generated parameters |
| `transport` | yes | `bridge` | `bridge` or `ble` |
| `tilt_color` | yes | `Red` | One of: Red Green Black Purple Orange Blue Yellow Pink |
| `bridge_url` | bridge only | `http://tiltbridge.local/json` | TiltBridge JSON endpoint |
| `request_timeout_s` | bridge only | `3.0` | HTTP request timeout |
| `ble_scan_timeout_s` | ble only | `4.0` | Duration of each BLE scan pass |
| `ble_idle_s` | ble only | `0.0` | Gap between BLE scan passes; 0 = continuous |
| `ble_stale_after_s` | ble only | `20.0` | Keep `connected=True` this many seconds after last seen advertisement |
| `ble_device_address` | ble only | `""` | Optional adapter address filter |
| `update_interval_s` | no | `2.0` | Poll interval in seconds |

### Example (BLE)

```yaml
name: tilt_green
source_type: tilt_hydrometer
config:
  parameter_prefix: tilt.green
  transport: ble
  tilt_color: Green
  ble_device_address: "FA:CE:FA:74:AE:18"
  ble_stale_after_s: 20.0
  update_interval_s: 2.0
```

### BLE notes

- Direct BLE support works with both classic Tilt and Tilt Pro scaling.
- Battery weeks may be unavailable in direct BLE mode (especially Tilt Pro). The source retains the last known value once seen.
- The Bleak callback signature must be exactly `def on_detection(device, adv_data)` — no default keyword arguments. This is a WinRT backend requirement.

---

## brewtools (CAN)

Receives Brewtools CAN measurements and mirrors them into ParameterDB, with optional writable command outputs for actuator/control workflows.

### Transport modes

| Transport | Description | Typical use |
|---|---|---|
| `kvaser` | Direct CAN via python-can + Kvaser interface/driver stack | Node has a locally attached Kvaser adapter |
| `pcan_gateway_udp` | UDP bridge mode for PEAK PCAN-Ethernet Gateway | Node talks over Ethernet/UDP to a remote PEAK gateway |

### Auto-discovery

The create modal auto-scans for CAN channels using `scan_channels`:

1. Calls `python-can detect_available_configs(interfaces=["kvaser"])` for local Kvaser adapters.
2. Probes the full local /24 subnet with parallel UDP probes (32 workers, 80 ms timeout per host) to find PEAK gateways.
3. Only hosts that actually respond are shown as cards.
4. Click **Use This Channel** to populate transport, interface, channel, bitrate, and gateway address fields.

### Key features

- Optional command outputs for agitator PWM, density calibration (`calibrate` + `calibrate_sg`), and pressure zeroing.
- Automatic dependency graph exposure for those command parameters (`depends_on`) so operator ordering stays logical in the UI.
- Node allowlists for agitator, density, and pressure devices with runtime discovery fallback when lists are empty.

### Common config keys

| Key | Transport | Description |
|---|---|---|
| `parameter_prefix` | both | Base namespace for generated parameters |
| `transport` | both | `kvaser` or `pcan_gateway_udp` |
| `interface` | `kvaser` | python-can interface name (typically `"kvaser"`) |
| `channel` | `kvaser` | CAN channel index (0-based) |
| `bitrate` | `kvaser` | CAN bitrate, default `500000` |
| `gateway_host` | `pcan_gateway_udp` | PEAK gateway IP/hostname |
| `gateway_tx_port` | `pcan_gateway_udp` | UDP TX port (default `55002`) |
| `gateway_rx_port` | `pcan_gateway_udp` | UDP RX port (default `55001`) |
| `gateway_bind_host` | `pcan_gateway_udp` | Local UDP bind address (default `0.0.0.0`) |
| `recv_timeout_s` | both | Receive timeout for transport loop |
| `reconnect_delay_s` | both | Delay before reconnect attempts after transport failure |
| `density_request_interval_s` | both | How often to request a density reading |
| `agitator_nodes` | both | Optional list of node IDs to expose agitator controls for |
| `density_nodes` | both | Optional list of node IDs to expose density controls for |
| `pressure_nodes` | both | Optional list of node IDs to expose pressure controls for |

### Minimal PEAK gateway example

```yaml
name: brewcan_01
source_type: brewtools
config:
  parameter_prefix: brewcan
  transport: pcan_gateway_udp
  gateway_host: 192.168.0.30
  gateway_tx_port: 55002
  gateway_rx_port: 55001
  gateway_bind_host: 0.0.0.0
  recv_timeout_s: 0.1
  reconnect_delay_s: 2.0
  density_request_interval_s: 2.0
```

---

## modbus_relay

Controls Modbus TCP relay boards and publishes actual relay channel states into ParameterDB.

### Auto-discovery

The create modal auto-scans for relay boards using `scan_relays`:

1. Scans the full local /24 subnet + localhost for open TCP connections on ports 4196 and 502.
2. For each open port, probes Modbus read-coils descending from 32 → 1 channels to identify the board type.
3. Only boards that respond with valid Modbus data appear as cards.
4. Click **Use This Board** to populate host, port, unit_id, and channel_count.

### Config keys

| Key | Required | Default | Description |
|---|---|---|---|
| `parameter_prefix` | yes | `relay` | Namespace for generated relay parameters (e.g. `relay.ch1`) |
| `host` | yes | `127.0.0.1` | Relay board IP address |
| `port` | yes | `502` | Modbus TCP port |
| `unit_id` | yes | `1` | Modbus unit/slave ID |
| `channel_count` | yes | `8` | Number of relay channels |
| `timeout` | yes | `1.5` | Modbus request timeout in seconds |
| `update_interval_s` | no | `0.25` | Poll interval |
| `reconnect_delay_s` | no | `2.0` | Delay before reconnect after failure |

---

## Deleting a Source and Its Parameters

When a datasource is deleted through the ParameterDB UI, you are prompted with three options:

| Button | Behaviour |
|---|---|
| **Delete** | Removes the source definition and stops its runtime. Parameters it created remain in ParameterDB. |
| **Delete + Clean** | Removes the source **and** all parameters it owns. A parameter is considered owned when its metadata carries `created_by = "data_source"` and `owner = <source_name>`. |
| **Cancel** | No action taken. |

The cascade removal is performed server-side via the `delete_owned_parameters=true` query parameter on the `DELETE /parameterdb/sources/{name}` agent endpoint. Only parameters explicitly owned by that source are removed — parameters created by other means are not affected.
