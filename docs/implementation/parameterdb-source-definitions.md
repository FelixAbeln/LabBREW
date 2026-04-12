# ParameterDB Built-in Source Definitions

LabBREW ships these built-in source definitions under `Services/parameterDB/sourceDefs`.

Each source type is defined by a **SourceDef** — a pair of files:
- `service.py` — runtime class (`SourceBase` subclass) that owns a set of ParameterDB parameters and publishes values into them at its configured rate.
- `ui.py` — declarative spec consumed by the frontend to render the create/edit form, validate required fields, and describe how the source appears in the parameter dependency graph.

## Available Source Types

| Source Type | Purpose | Transport |
|---|---|---|
| system_time | Publish system time into ParameterDB | local clock |
| tilt_hydrometer | Read one Tilt color and publish gravity/temperature/status | HTTP TiltBridge or direct BLE |
| brewtools | Read Brewtools CAN measurements and expose command outputs | Kvaser CAN (python-can) and PCAN UDP gateway |
| modbus_relay | Control and read Modbus TCP relay boards | Modbus TCP |
| labps3005dn | Control and monitor LABPS3005DN style bench PSU | serial |
| digital_twin | Run FMU-backed digital twin and publish outputs | local FMU runtime |

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

## brewtools (CAN)

Receives Brewtools CAN measurements and mirrors them into ParameterDB, with optional writable command outputs for actuator/control workflows.

### Transport modes

| Transport | Description | Typical use |
|---|---|---|
| `kvaser` | Direct CAN via python-can + Kvaser interface/driver stack | Node has a locally attached Kvaser adapter |
| `pcan_gateway_udp` | UDP bridge mode for PEAK PCAN-Ethernet Gateway | Node talks over Ethernet/UDP to a remote PEAK gateway |

### Key features

- Optional command outputs for agitator PWM, density calibration (`calibrate` + `calibrate_sg`), and pressure zeroing.
- Automatic dependency graph exposure for those command parameters (`depends_on`) so operator ordering stays logical in the UI.
- Node allowlists for agitator, density, and pressure devices with runtime discovery fallback when lists are empty.

### Common config keys

| Key | Transport | Description |
|---|---|---|
| `parameter_prefix` | both | Base namespace for generated parameters |
| `channel`, `bitrate` | `kvaser` | Direct CAN channel settings |
| `gateway_host` | `pcan_gateway_udp` | PEAK gateway IP/hostname |
| `gateway_tx_port`, `gateway_rx_port` | `pcan_gateway_udp` | UDP ports used for send/receive |
| `gateway_bind_host` | `pcan_gateway_udp` | Local bind address for UDP receive socket |
| `recv_timeout_s` | both | Receive timeout for transport loop |
| `reconnect_delay_s` | both | Delay before reconnect attempts after transport failure |

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
```

## Tilt Notes

Direct BLE support works with both classic Tilt and Tilt Pro scaling.

Battery weeks may be unavailable in direct BLE mode, especially on Tilt Pro advertisements. In that case:

- tilt.battery_weeks may remain null until a value is observed
- the source retains the last known battery_weeks value once seen

The BLE mode includes a stale timeout window to avoid connected flapping when advertisements are sparse.

Relevant config keys:

- transport: ble
- ble_scan_timeout_s
- ble_idle_s
- ble_stale_after_s
- ble_device_address

For usage details and probe commands, see docs/implementation/tilt-hydrometer-source.md.

---

## Deleting a Source and Its Parameters

When a datasource is deleted through the ParameterDB UI, you are prompted with three options:

| Button | Behaviour |
|---|---|
| **Delete** | Removes the source definition and stops its runtime. Parameters it created remain in ParameterDB. |
| **Delete + Clean** | Removes the source **and** all parameters it owns. A parameter is considered owned when its metadata carries `created_by = "data_source"` and `owner = <source_name>`. |
| **Cancel** | No action taken. |

The cascade removal is performed server-side via the `delete_owned_parameters=true` query parameter on the `DELETE /parameterdb/sources/{name}` agent endpoint. Only parameters explicitly owned by that source are removed — parameters created by other means are not affected.
