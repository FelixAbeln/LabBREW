# Tilt Hydrometer Source (Bridge and BLE)

This source supports two transport modes:

- bridge: Read Tilt Bridge JSON endpoint over HTTP.
- ble: Read Tilt iBeacon advertisements directly with bleak.

## Config Keys

Common:

- transport: bridge or ble
- tilt_color: Red, Green, Black, Purple, Orange, Blue, Yellow, Pink
- parameter_prefix: Prefix for published parameters
- update_interval_s: Loop delay for bridge mode

Bridge mode:

- bridge_url: Tilt Bridge endpoint, usually http://tiltbridge.local/json
- request_timeout_s: HTTP timeout in seconds

BLE mode:

- ble_scan_timeout_s: Duration of each active BLE scan cycle
- ble_idle_s: Delay between scan cycles. Set 0 for continuous scanning.
- ble_stale_after_s: Keep connected true this long after last seen packet to avoid brief advertising gaps.
- ble_device_address: Optional device address filter. Leave empty unless needed.

## Published Parameters

For prefix tilt these are created:

- tilt.gravity
- tilt.temperature_f
- tilt.temperature_c
- tilt.rssi
- tilt.battery_weeks
- tilt.tilt_color
- tilt.raw
- tilt.connected
- tilt.last_error
- tilt.last_sync

connected is true only when the selected color is observed in the current cycle.

When BLE advertisements are sparse, connected remains true until ble_stale_after_s expires.

Battery weeks can be absent in direct BLE advertisements (common with Tilt Pro). If no battery field is present, the source keeps the last known battery_weeks value.

## Suggested Settings

Windows BLE testing:

- transport: ble
- ble_scan_timeout_s: 8 to 12
- ble_idle_s: 0
- ble_stale_after_s: 20 to 45
- ble_device_address: empty

Raspberry Pi production:

- transport: ble
- ble_scan_timeout_s: 4 to 8
- ble_idle_s: 0
- ble_stale_after_s: 20 to 45
- ble_device_address: optional

If Windows still misses advertisements, use transport bridge on Windows and validate BLE mode on Raspberry Pi.

## BLE Probe Script

Use the standalone probe to confirm advertisements are visible to this host process:

python Other/Sims/tilt_ble_probe.py --color green --timeout-s 10 --cycles 6 --idle-s 0

Optional address pinning:

python Other/Sims/tilt_ble_probe.py --color green --address AA:BB:CC:DD:EE:FF --timeout-s 10 --cycles 6

Exit code:

- 0: at least one matching Tilt advertisement detected
- 1: no matching Tilt advertisement detected
- 2: bleak not installed
