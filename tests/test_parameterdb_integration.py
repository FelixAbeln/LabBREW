from __future__ import annotations

import time

import pytest

from Services.parameterDB.parameterdb_core.client import SignalClient


@pytest.mark.integration
def test_parameterdb_status_contract_smoke() -> None:
    """Optional integration smoke test adapted from the db status check script.

    This test is skipped when no local ParameterDB service is reachable.
    """
    session = SignalClient("127.0.0.1", 8765, timeout=1).session()

    try:
        session.connect()
    except Exception as exc:  # pragma: no cover - skip path depends on local runtime
        pytest.skip(f"ParameterDB not reachable on 127.0.0.1:8765: {exc}")

    try:
        stats = session.stats()
        assert isinstance(stats, dict)
        assert "parameter_count" in stats
        assert "mode" in stats

        estimated_rate = stats.get("estimated_cycle_rate_hz")
        if estimated_rate is not None:
            assert float(estimated_rate) >= 0.0

        snapshot = session.snapshot()
        assert isinstance(snapshot, dict)

        # Adapted from the legacy test_db_status script: check for scan movement.
        time.sleep(0.1)
        snap1 = session.snapshot()
        time.sleep(0.2)
        snap2 = session.snapshot()
        if snap1 == snap2:
            pytest.skip("ParameterDB snapshots unchanged during sample window; scan movement not observed")
    finally:
        session.close()
