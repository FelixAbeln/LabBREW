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
estimated_rate = stats.get('estimated_cycle_rate_hz')
avg_scan_duration = stats.get('avg_scan_duration_s')
last_scan_duration = stats.get('last_scan_duration_s')
print(f"  Estimated rate: {f'{estimated_rate:.1f} Hz' if estimated_rate is not None else '-'}")
print(f"  Avg scan: {f'{avg_scan_duration:.4f}s' if avg_scan_duration is not None else '-'}")
print(f"  Utilization: {float(stats.get('estimated_utilization', 0)) * 100:.1f}%")
print(f"  Last scan: {f'{last_scan_duration:.4f}s' if last_scan_duration is not None else '-'}")

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
