# Data Service

A high-frequency data logging service that records parameter values from parameterDB at a configurable rate, stores them to files (Parquet, CSV, or JSONL), and supports loadstep averaging.

## Features

- **Configurable sampling rate**: 1-150 Hz
- **Multiple output formats**: Parquet, CSV, JSON Lines (JSONL)
- **Real-time recording**: Records parameter values in a background thread
- **Loadstep averaging**: Automatically computes averages over specified time periods
- **ParamaterDB integration**: Directly reads from parameterDB, same as control_service
- **File-based storage**: Automatic file creation and buffering for efficient I/O

## Architecture

### Service Components

- **`service.py`**: FastAPI entry point. Starts the runtime thread and exposes HTTP API.
- **`runtime.py`**: Background recording loop. Manages measurement sessions, records samples, and handles loadsteps.
- **`api/routes.py`**: REST API endpoints for measurement control and status.
- **`storage/writer.py`**: File writers for different formats (Parquet, CSV, JSONL).
- **`storage/loadstep.py`**: Loadstep averaging logic.

### How It Works

1. **Setup Phase**: Configure which parameters to record and at what frequency via `/measurement/setup`
2. **Recording Phase**: Start recording with `/measurement/start`
3. **Loadstep Capture**: Optionally call `/loadstep/take` during recording to capture averaged data
4. **Finalization**: Stop recording with `/measurement/stop` to flush data and get summary

## API Endpoints

### Measurement Control

#### `POST /measurement/setup`
Configure a measurement session.

**Request:**
```json
{
  "parameters": ["sensor_temp", "pressure_psi"],
  "hz": 50.0,
  "output_dir": "data/measurements",
  "output_format": "parquet",
  "session_name": "reactor_run_001"
}
```

**Response:**
```json
{
  "ok": true,
  "session_name": "reactor_run_001",
  "parameters": ["sensor_temp", "pressure_psi"],
  "hz": 50.0,
  "output_format": "parquet"
}
```

#### `POST /measurement/start`
Begin recording measurements.

**Response:**
```json
{
  "ok": true,
  "message": "Started recording session: reactor_run_001"
}
```

#### `POST /measurement/stop`
Stop recording and finalize the file.

**Response:**
```json
{
  "ok": true,
  "message": "Recording stopped: reactor_run_001",
  "samples_recorded": 5000,
  "file": "data/measurements/reactor_run_001.parquet",
  "completed_loadsteps": 2,
  "loadsteps": [
    {
      "name": "loadstep_20260322_120000",
      "duration_seconds": 30.0,
      "average": {"sensor_temp": 85.3, "pressure_psi": 42.1},
      "timestamp": "2026-03-22T12:00:00.000000"
    }
  ]
}
```

### Loadstep Recording

#### `POST /loadstep/take`
Start recording a loadstep (averaged data over time).

**Request:**
```json
{
  "duration_seconds": 30.0,
  "loadstep_name": "cool_down_phase",
  "parameters": ["sensor_temp", "pressure_psi"]
}
```

**Response:**
```json
{
  "ok": true,
  "loadstep_name": "cool_down_phase",
  "duration_seconds": 30.0,
  "parameters": ["sensor_temp", "pressure_psi"]
}
```

### Parameter Discovery

The data service does not currently expose a dedicated HTTP endpoint for listing
available parameters. Instead, it relies on the same ParameterDB used by
`control_service`. To discover which parameters can be recorded, query
ParameterDB directly (or use whatever discovery mechanisms are provided by
`control_service`), then configure the data service with the desired parameter
names.
### Status & Health

#### `GET /status`
Get current service status.

**Response:**
```json
{
  "backend_connected": true,
  "recording": true,
  "config": {
    "parameters": ["sensor_temp", "pressure_psi"],
    "hz": 50.0,
    "session_name": "reactor_run_001"
  },
  "samples_recorded": 2500,
  "active_loadsteps": ["cool_down_phase"],
  "completed_loadsteps_count": 1
}
```

#### `GET /health`
Health check.

**Response:**
```json
{
  "status": "healthy",
  "details": {...}
}
```

## Usage Examples

### Basic Recording Session

```bash
# Start the service
python -m Services.data_service.service

# In another terminal, make API calls:

# 1. Setup measurement
curl -X POST http://localhost:8000/measurement/setup \
  -H "Content-Type: application/json" \
  -d '{
    "parameters": ["temp_fermenter", "ph_value"],
    "hz": 10.0,
    "output_format": "parquet",
    "session_name": "fermentation_001"
  }'

# 2. Start recording
curl -X POST http://localhost:8000/measurement/start

# 3. Record a loadstep (30-second average)
curl -X POST http://localhost:8000/loadstep/take \
  -H "Content-Type: application/json" \
  -d '{"duration_seconds": 30.0, "loadstep_name": "stable_phase"}'

# 4. Check status
curl http://localhost:8000/status

# 5. Stop recording
curl -X POST http://localhost:8000/measurement/stop
```

### High-Frequency Recording

```bash
# Record at 150 Hz (maximum)
curl -X POST http://localhost:8000/measurement/setup \
  -H "Content-Type: application/json" \
  -d '{
    "parameters": ["accelerometer_x", "accelerometer_y", "accelerometer_z"],
    "hz": 150.0,
    "output_format": "parquet",
    "session_name": "vibration_test"
  }'
```

### Multiple Loadsteps

```bash
# Start recording
curl -X POST http://localhost:8000/measurement/start

# Record first phase (60 seconds)
curl -X POST http://localhost:8000/loadstep/take \
  -H "Content-Type: application/json" \
  -d '{"duration_seconds": 60.0, "loadstep_name": "ramp_up"}'

# Record second phase (90 seconds)
curl -X POST http://localhost:8000/loadstep/take \
  -H "Content-Type: application/json" \
  -d '{"duration_seconds": 90.0, "loadstep_name": "steady_state"}'

# Stop, automatically finalizes completed loadsteps
curl -X POST http://localhost:8000/measurement/stop
```

## Output Formats

### Parquet (Default)
- Binary columnar format (Apache Parquet)
- Efficient storage and querying
- Requires: `pyarrow` (optional, falls back to buffering if unavailable)
- File extension: `.parquet`

### CSV
- Text-based, human-readable
- Header: `timestamp,datetime,param1,param2,...`
- Easy to import into Excel/pandas
- File extension: `.csv`

### JSONL (JSON Lines)
- One JSON object per line
- Format: `{"timestamp": X, "datetime": Y, "data": {...}}`
- Streaming-friendly
- File extension: `.jsonl`

## Configuration

The service accepts standard CLI arguments for connection details:

```bash
python -m Services.data_service.service \
  --host 127.0.0.1 \
  --port 8000 \
  --backend-host 127.0.0.1 \
  --backend-port 8765
```

- `--host`: API server host (default: 127.0.0.1)
- `--port`: API server port (default: 8000)
- `--backend-host`: parameterDB host (default: 127.0.0.1)
- `--backend-port`: parameterDB port (default: 8765)

## Data Files

Recorded data is saved to `data/measurements/` by default. Each session creates a file named:
- `{session_name}.parquet` (or `.csv`, `.jsonl`)

## Design Notes

### Similarities to control_service

- Uses the same `SignalStoreBackend` for parameterDB communication
- FastAPI + threading architecture
- Standard CLI argument parsing
- Health check endpoints

### Data Recording Accuracy

- The service maintains a circular buffer for in-memory data
- Samples are timestamped when recorded
- File writes are buffered for efficiency (batch writes for Parquet/CSV)
- Loadstep averaging collects samples for the specified duration

### Error Handling

- Missing parameters are handled gracefully (returns None/null in output)
- Backend disconnections don't crash the service
- File I/O errors are logged but don't stop recording (data remains in buffer)

## Limitations

- Hz range: 1-150 (validation enforced)
- Parameter values must be numeric for loadstep averaging
- If pyarrow is not installed, Parquet data is buffered in memory only

## Troubleshooting

### 400 Bad Request on /measurement/setup

**Problem:** Getting `400 Client Error: Bad Request for url: http://localhost:8766/measurement/setup`

**Cause:** One or more of the requested parameters don't exist in parameterDB.

**Solution:**
1. First, discover available parameters:
   ```bash
   curl http://localhost:8766/parameters/available
   ```
2. Use parameter names from the response in your setup request
3. Ensure parameterDB is running and populated with data

### Cannot connect to service

**Problem:** `ConnectionError: Cannot connect to Data Service`

**Solution:**
1. Verify the backend supervisor is running: `python run_supervisor.py`
2. Check the correct port (default is 8000, test uses 8766)
3. Ensure parameterDB is running on the backend

### No parameters available

**Problem:** `/parameters/available` returns empty list

**Cause:** parameterDB has no parameters or connection failed

**Solution:**
1. Verify parameterDB is running and accessible
2. Check backend connection: `GET /health`
3. Populate parameterDB with test data if needed

