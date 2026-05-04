# PAPAGO Meteo ETH Source

This source reads PAPAGO Meteo ETH weather station registers over Modbus TCP and publishes values into ParameterDB.

## What It Publishes

Default enabled quantities:

- sensor_a_value_1
- sensor_a_value_2
- sensor_a_value_3
- wind_direction_deg
- wind_speed_m_s

Available but disabled by default:

- sensor_b_value_1
- sensor_b_value_2
- sensor_b_value_3

Each enabled quantity can also publish a quality signal at `<quantity_parameter>.quality`.

Always-published status signals:

- connected
- last_error
- last_sync
- device_time
- sensor_a_status
- sensor_a_type
- sensor_b_status
- sensor_b_type
- wind_sensor_status

## Register Notes

- Transport: Modbus TCP, function code `0x04` (Read Input Registers)
- Snapshot range: `0..224` input registers
- The implementation reads in two chunks to satisfy Modbus per-request limits:
  - `0..124` (125 registers)
  - `125..224` (100 registers)

## Config Keys

| Key | Required | Default | Description |
|---|---|---|---|
| `parameter_prefix` | yes | `papago` | Prefix for generated parameter names |
| `host` | yes | `127.0.0.1` | Device hostname or IP |
| `port` | yes | `502` | Modbus TCP port |
| `unit_id` | yes | `1` | Modbus unit/slave ID |
| `timeout` | yes | `1.5` | Request timeout seconds |
| `update_interval_s` | no | `2.0` | Poll interval |
| `reconnect_delay_s` | no | `2.0` | Delay before reconnect after errors |
| `prefer_float` | no | `false` | Prefer IEEE754 float decoding when available |
| `quantities` | no | `{}` | Per-quantity enable/parameter/quality overrides |

Optional status parameter overrides:

- connected_param
- last_error_param
- last_sync_param
- device_time_param
- sensor_a_status_param
- sensor_a_type_param
- sensor_b_status_param
- sensor_b_type_param
- wind_sensor_status_param

## Quantity Mapping Structure

`config.quantities` may override defaults by quantity key.

Example:

```yaml
quantities:
  sensor_a_value_1:
    enabled: true
    parameter: weather.sensor_a.value_1
    publish_quality: true
    quality_parameter: weather.sensor_a.value_1.quality
  sensor_b_value_1:
    enabled: false
```

Supported keys:

- sensor_a_value_1
- sensor_a_value_2
- sensor_a_value_3
- sensor_b_value_1
- sensor_b_value_2
- sensor_b_value_3
- wind_direction_deg
- wind_speed_m_s

## Discovery in UI

The source UI includes a discovery module (`scan_papago_meteo`) that:

1. Builds candidate hosts from manual host, host list, CIDR, or local `/24` auto-scan.
2. Probes host+port pairs for open TCP.
3. Probes open targets via Modbus with candidate unit IDs.
4. Returns only reachable stations as selectable candidates.

## Minimal Example

```yaml
name: weather_01
source_type: papago_meteo
config:
  parameter_prefix: weather
  host: 192.168.0.45
  port: 502
  unit_id: 1
  timeout: 1.5
  update_interval_s: 2.0
  reconnect_delay_s: 2.0
  prefer_float: false
```

## Troubleshooting

- `connected=false` and `last_error` contains timeout:
  - Confirm host, port, and unit ID.
  - Verify TCP reachability to port `502`.
- Values are present but quality is not `ok`:
  - The source forwards device quality codes (overflow/underflow/invalid).
- Wrong value scale:
  - Toggle `prefer_float` and compare against expected device output.
