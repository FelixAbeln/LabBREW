# PostgreSQL Persistence Testing Guide

This guide walks you through setting up and testing the PostgreSQL persistence backends for LabBREW control rules, datasource configs, and parameter snapshots.

## Prerequisites

- Local PostgreSQL running on `localhost:5432`
- LabBREW environment set up and running
- Python 3.11+ with dependencies installed
- `psycopg[binary]` installed

## Step 1: Prepare Local PostgreSQL Database

Create a database and required tables (PowerShell example):

```powershell
& .\.venv\Scripts\python.exe - <<'PY'
import psycopg
from psycopg import sql

host, port, user, password = "localhost", 5432, "postgres", "root"
db = "labbrew"

with psycopg.connect(host=host, port=port, user=user, password=password, dbname="postgres", autocommit=True) as conn:
  with conn.cursor() as cur:
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,))
    if cur.fetchone() is None:
      cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db)))

with psycopg.connect(host=host, port=port, user=user, password=password, dbname=db, autocommit=True) as conn:
  with conn.cursor() as cur:
    cur.execute("""CREATE TABLE IF NOT EXISTS parameterdb_snapshot_parameters (name TEXT PRIMARY KEY, parameter_type TEXT NOT NULL, value_json TEXT NOT NULL, config_json TEXT NOT NULL, state_json TEXT NOT NULL, metadata_json TEXT NOT NULL, updated_at DOUBLE PRECISION NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS parameterdb_snapshot_meta (singleton_id INTEGER PRIMARY KEY, format_version INTEGER NOT NULL, saved_at DOUBLE PRECISION, store_revision BIGINT NOT NULL, updated_at DOUBLE PRECISION NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS datasource_datasource_sources (name TEXT PRIMARY KEY, source_type TEXT NOT NULL, config_json TEXT NOT NULL, updated_at DOUBLE PRECISION NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS control_rules_control_rules (rule_id TEXT PRIMARY KEY, rule_json TEXT NOT NULL, updated_at DOUBLE PRECISION NOT NULL)""")

print("Postgres schema ready.")
PY
```

## Step 2: Verify Tables Exist

```sql
\c labbrew
\dt
```

You should see:

- `parameterdb_snapshot_parameters`
- `parameterdb_snapshot_meta`
- `datasource_datasource_sources`
- `control_rules_control_rules`

## Step 3: Run Supervisor with Postgres Topology

```bash
# Terminal 1: Start the supervisor with postgres-enabled topology
python run_supervisor.py --topology data/system_topology.postgres-test.yaml

# Expected output:
# [INFO] BrewSupervisor listening on http://127.0.0.1:8080
# [INFO] ParameterDB backend: postgres
# [INFO] ParameterDB_DataSource backend: postgres
# [INFO] Control service backend: postgres
```

## Step 4: Verify Backend Status in Agent API

In another terminal, query the agent persistence endpoint:

```bash
# Check overall persistence status
curl http://127.0.0.1:8080/fermenters/supervisor/agent/persistence | jq .

# Expected response:
# {
#   "ok": true,
#   "persistence": {
#     "snapshot_persistence": {
#       "backend": "postgres",
#       "available": true,
#       "healthy": true,
#       "postgres_config": {
#         "host": "localhost",
#         "port": 5432,
#         "database": "labbrew",
#         "table_prefix": "parameterdb"
#       }
#     },
#     "source_persistence": {
#       "backend": "postgres",
#       "available": true,
#       "healthy": true,
#       "postgres_config": {
#         "host": "localhost",
#         "port": 5432,
#         "database": "labbrew",
#         "table_prefix": "datasource"
#       }
#     },
#     "rules_persistence": {
#       "backend": "postgres",
#       "available": true,
#       "healthy": true,
#       "postgres_config": {
#         "host": "localhost",
#         "port": 5432,
#         "database": "labbrew",
#         "table_prefix": "control_rules"
#       }
#     }
#   }
# }
```

## Step 5: Check System Summary Includes All Backends

```bash
# Get full agent info with all three persistence statuses
curl http://127.0.0.1:8080/fermenters/supervisor/agent/info | jq '.persistence, .datasource_persistence, .rules_persistence'

# Get summary (used by UI System tab)
curl http://127.0.0.1:8080/fermenters/supervisor/agent/summary | jq '.datasource_persistence, .rules_persistence'
```

## Step 6: Test UI Displays All Backends

1. Open BrewSupervisor UI: `http://localhost:3000`
2. Navigate to **System** tab
3. Verify three persistence backend cards appear:
   - **ParameterDB snapshot backend**: Shows postgres, with host/port info
   - **Source config backend**: Shows postgres datasource target
   - **Control rules backend**: Shows postgres control_rules target
4. All should show green health pills (✓ available, ✓ healthy)

## Step 7: Test Sidebar Badge Integration

1. In the **Fermenters** sidebar, select the supervisor fermenter
2. Verify the **persistence** badge appears with color:
   - **Green** (✓): All backends healthy
   - **Yellow** (⚠): Any backend unhealthy but available
   - **Red** (✗): Any backend unavailable

The badge tooltip shows which backend(s) are degraded.

## Testing Persistence Data Flow

### Test ParameterDB Snapshot Persistence

```bash
# 1. Write a parameter to ParameterDB
curl -X POST http://127.0.0.1:8765/set_parameter \
  -H "Content-Type: application/json" \
  -d '{"name": "test_param", "type": "FLOAT", "value": 3.14}'

# 2. Verify data in database
psql -h localhost -p 5432 -U postgres -d labbrew -c \
  "SELECT * FROM parameterdb_snapshot_parameters WHERE name='test_param';"

# Expected: One row with value='3.14'
```

### Test Control Rules Persistence

```bash
# 1. Create a control rule through the HTTP API
curl -X POST http://127.0.0.1:8767/system/rule \
  -H "Content-Type: application/json" \
  -d '{"rule_id": "test_rule", "definition": {"type": "test"}}'

# 2. List rules (will be loaded from postgres)
curl http://127.0.0.1:8767/system/rules

# 3. Verify in database
psql -h localhost -p 5432 -U postgres -d labbrew -c \
  "SELECT * FROM control_rules_control_rules WHERE rule_id='test_rule';"

# Expected: One row with the rule definition as JSON
```

### Test Datasource Persistence

```bash
# Note: DataSource sources are managed primarily through admin protocol
# But you can verify persistence through the stats endpoint

# 1. View datasource stats (includes persistence backend info)
curl http://127.0.0.1:8080/fermenters/supervisor/agent/info | jq '.datasource_persistence'

# 2. Verify in database
psql -h localhost -p 5432 -U postgres -d labbrew -c \
  "SELECT * FROM datasource_datasource_sources;"
```

## Troubleshooting

### Connection Refused

```
Error: could not connect to server: Connection refused
```

**Solution**: Verify local Postgres service is running and listening on `localhost:5432`.

### Database Already Exists

If you need to reset the database, drop and recreate `labbrew`, then rerun Step 1.

### Supervisor Won't Start with Postgres

**Check logs**:
```bash
# If using run_supervisor.py directly, errors appear in console
# If using as service, check service logs for connection errors

# Verify topology file is valid YAML
python -c "import yaml; yaml.safe_load(open('data/system_topology.postgres-test.yaml'))"
```

**Common issues**:
- `host` is `localhost` - if needed, use `127.0.0.1`
- `password` incorrect - verify it matches your local postgres user credentials
- table prefixes do not match configured service prefixes

### Performance Issues

If writes are slow:
```bash
# Check that sslmode: disable is set (recommended for local testing)
# For production, use sslmode: require with proper certificates

# Verify indices are created
psql -h localhost -p 5432 -U postgres -d labbrew -c "\di"
```

## Cleaning Up

Stop your local Postgres service using your OS/service manager when finished.

## Next Steps

Once persistence is verified working:
1. Update production topology with real PostgreSQL credentials
2. Set up SSL certificates if connecting to remote database
3. Configure automated backups (see deployment docs)
4. Test failover scenarios (stop postgres container and verify graceful degradation)
