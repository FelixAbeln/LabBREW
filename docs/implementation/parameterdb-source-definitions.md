# ParameterDB Built-in Source Definitions

LabBREW currently ships these built-in source definitions under Services/parameterDB/sourceDefs.

## Available Source Types

| Source Type | Purpose | Transport |
|---|---|---|
| system_time | Publish system time into ParameterDB | local clock |
| tilt_hydrometer | Read one Tilt color and publish gravity/temperature/status | HTTP TiltBridge or direct BLE |
| brewtools_kvaser | Read Brewtools CAN measurements and expose command outputs | Kvaser CAN (python-can) |
| modbus_relay | Control and read Modbus TCP relay boards | Modbus TCP |
| labps3005dn | Control and monitor LABPS3005DN style bench PSU | serial |
| digital_twin | Run FMU-backed digital twin and publish outputs | local FMU runtime |

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
