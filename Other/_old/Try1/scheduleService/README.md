# FCS frontend/service scaffold for SignalStore

This version uses the workbook structure you asked for:

- **Sheet 1: `StartupRoutine`**
- **Sheet 2: `Plan`**

Both sheets use the **same schema**, so the backend runs one consistent step engine for startup and for the main routine.

## What changed

- removed the legacy convenience columns from the template:
  - `temp_sp`
  - `pressure_sp`
  - `allow_add_gas`
  - `agitator`
- added a dedicated `StartupRoutine` worksheet
- kept `Plan` as the main execution worksheet
- updated the loader/runtime so startup and plan are both read from Excel
- updated the UI to show separate tabs for startup and plan
- `controller_actions` now supports **direct ParameterDB names**, which is the preferred mode for your backend

## Workbook format

Both `StartupRoutine` and `Plan` use these columns:

- `enabled`
- `order`
- `step_name`
- `controller_actions`
- `wait_type`
- `wait_source`
- `operator`
- `threshold`
- `threshold_low`
- `threshold_high`
- `time_s`
- `valid_sources`
- `confirmation_message`
- `notes`

## Direct backend parameter names

Use your real SignalStore / ParameterDB names directly inside `controller_actions`.

Examples:

```text
set_temp_Fermentor:18
set_pres_Fermentor:0.60:0.01
brewcan.agitator.0.set_pwm:35
psu.set_enable:true;psu.set_voltage:24
twin.reset:1
```

The general syntax is:

```text
parameter_name:value
parameter_name:value:ramp_rate
```

Multiple actions are separated with semicolons.

## Runtime flow

1. load workbook
2. run `StartupRoutine`
3. transition automatically into `Plan`
4. finish when the last enabled plan step completes

## Helper sheets

The exporter also writes:

- `WritableTargets`
- `SignalKeyGuide`
- `WaitTypes`
- `Operators`
- `HowToUse`

These are reference sheets only. The runtime executes only `StartupRoutine` and `Plan`.

## Running

Start the service:

```bash
python main_service.py
```

Start the UI:

```bash
python main_ui.py
```

## Notes

This scaffold now matches the direction you described much more closely:

- backend remains SignalStore / ParameterDB
- startup logic lives in Excel, not in UI checkboxes
- UI is just a client for load/start/view/control
- runtime keeps running without the UI
