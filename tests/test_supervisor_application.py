from __future__ import annotations

from types import SimpleNamespace

from Supervisor.application.supervisor import TopologySupervisor


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