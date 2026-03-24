#!/usr/bin/env python
"""Quick test to verify ParameterDB is running and scan cycling."""

from Services.parameterDB.parameterdb_core.client import SignalClient
import time

# Connect to database
session = SignalClient("127.0.0.1", 8765, timeout=3).session()
session.connect()

# Check stats
print("✓ Connected to ParameterDB")
stats = session.stats()
print(f"  Mode: {stats.get('mode')}")
print(f"  Parameters: {stats.get('parameter_count')}")
print(f"  Estimated rate: {stats.get('estimated_cycle_rate_hz'):.1f} Hz")
print(f"  Avg scan: {stats.get('avg_scan_duration_s'):.4f}s")
print(f"  Utilization: {float(stats.get('estimated_utilization', 0)) * 100:.1f}%")
print(f"  Last scan: {stats.get('last_scan_duration_s'):.4f}s")

# Check if cycling by sampling twice
time.sleep(0.1)
snap1 = session.snapshot()
time.sleep(0.2)
snap2 = session.snapshot()

if snap1 != snap2:
    print("✓ Database is scanning and updating")
else:
    print("✗ Database may not be updating - snapshots identical")

session.close()
