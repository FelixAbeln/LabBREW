from __future__ import annotations

import pytest
from types import SimpleNamespace

from Supervisor.application.supervisor import TopologySupervisor, _normalize_mdns_advertise_host


def _build_supervisor_stub() -> TopologySupervisor:
    supervisor = object.__new__(TopologySupervisor)
    supervisor.node_id = "test-node"
    supervisor.node_name = "Test Node"
    supervisor._repo_status_cache = {
        "checked_at": 123.0,
        "status": {
            "repo_url": "https://example.invalid/repo.git",
            "local_revision": "abc123",
            "remote_revision": "def456",
            "branch": "main",
            "outdated": True,
            "dirty": False,
            "error": None,
        },
    }
    supervisor._restart_requested = False
    supervisor.services = {
        "control_service": SimpleNamespace(
            service=SimpleNamespace(
                name="control_service",
                provides=[SimpleNamespace(name="control")],
                docs="control docs",
            )
        )
    }
    supervisor.resolved = SimpleNamespace(
        bindings={
            "control_service": SimpleNamespace(
                endpoint=SimpleNamespace(host="127.0.0.1", port=8767)
            )
        }
    )
    supervisor._service_health_details = lambda _service: (True, "ok")
    return supervisor


def test_service_map_uses_cached_repo_status_without_refresh() -> None:
    supervisor = _build_supervisor_stub()

    def _unexpected_repo_refresh(*_args, **_kwargs):
        raise AssertionError("repo_update_status should not run during service_map")

    supervisor.repo_update_status = _unexpected_repo_refresh

    mapped = TopologySupervisor.service_map(supervisor)

    assert mapped["control_service"]["healthy"] is True
    assert mapped["control_service"]["base_url"] == "http://127.0.0.1:8767"
    assert mapped["control_service"]["update"] == {
        "outdated": True,
        "local_revision": "abc123",
        "remote_revision": "def456",
        "error": None,
    }


def test_summary_uses_cached_repo_status_without_refresh() -> None:
    supervisor = _build_supervisor_stub()

    def _unexpected_repo_refresh(*_args, **_kwargs):
        raise AssertionError("repo_update_status should not run during summary")

    supervisor.repo_update_status = _unexpected_repo_refresh

    summary = TopologySupervisor.summary(supervisor)

    assert summary["control_available"] is True
    assert summary["repo_update"]["outdated"] is True
    assert summary["repo_update"]["local_revision"] == "abc123"
    assert summary["repo_update"]["remote_revision"] == "def456"


# ---------------------------------------------------------------------------
# _normalize_mdns_advertise_host
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    None,
    "",
    "  ",
    "0.0.0.0",
    "::",
    "localhost",
    "127.0.0.1",
    "127.1.2.3",
    "::1",           # IPv6 loopback
    "fe80::1",       # link-local IPv6
    "192.168.1.1/24",  # CIDR notation — not a valid IP literal
    "1",             # integer string accepted by ip_address() but non-canonical
])
def test_normalize_mdns_advertise_host_rejects_unusable(value) -> None:
    assert _normalize_mdns_advertise_host(value) is None


@pytest.mark.parametrize("value", [
    "192.168.1.10",
    "10.0.0.1",
    "172.16.0.5",
])
def test_normalize_mdns_advertise_host_accepts_routable_ipv4(value) -> None:
    assert _normalize_mdns_advertise_host(value) == value


def test_normalize_mdns_advertise_host_strips_whitespace() -> None:
    assert _normalize_mdns_advertise_host("  10.0.0.2  ") == "10.0.0.2"