
from __future__ import annotations

import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .cli_renderer import CliRenderer
from .planner import StartupPlanner
from .resolver import CapabilityResolver
from ..domain.models import ManagedProcessState, ServiceSpec
from ..domain.validation import validate_topology
from ..infrastructure.agent_api import AgentApiServer
from ..infrastructure.discovery_adapter import DiscoveryPublisher
from ..infrastructure.health import tcp_probe
from ..infrastructure.process_runner import ProcessRunner


class TopologySupervisor:
    def __init__(
        self,
        *,
        topology,
        root_dir: str | Path,
        log_dir: str | Path,
        advertise_host: str,
        node_id: str,
        node_name: str,
        agent_host: str = '0.0.0.0',
        agent_port: int = 8780,
        check_interval_s: float = 2.0,
    ) -> None:
        validate_topology(topology)
        self.topology = topology
        self.root_dir = Path(root_dir).resolve()
        self.log_dir = Path(log_dir).resolve()
        self.advertise_host = advertise_host
        self.node_id = node_id
        self.node_name = node_name
        self.agent_host = agent_host
        self.agent_port = agent_port
        self.check_interval_s = check_interval_s
        self.renderer = CliRenderer()
        self.resolver = CapabilityResolver()
        self.planner = StartupPlanner()
        self.runner = ProcessRunner(self.root_dir, self.log_dir)
        self.discovery = DiscoveryPublisher(node_id=node_id, node_name=node_name, port=agent_port)
        self.agent_api = AgentApiServer(
            host=agent_host,
            port=agent_port,
            node_id=node_id,
            node_name=node_name,
            service_map=self.service_map,
            summary_provider=self.summary,
            update_status_provider=self.repo_update_status,
            apply_update_action=self.apply_repo_update,
        )
        self._stopping = False
        self._maintenance_lock = threading.RLock()
        self._repo_status_cache: dict[str, Any] = {
            "checked_at": 0.0,
            "status": {
                "repo_url": "https://github.com/FelixAbeln/LabBREW.git",
                "local_revision": None,
                "remote_revision": None,
                "branch": None,
                "outdated": False,
                "dirty": False,
                "error": "not_checked",
            },
        }

        self.resolved = self.resolver.resolve(self.topology, default_advertise_host=advertise_host)
        self.start_order = self.planner.order(self.resolved.service_dependencies)
        self.services: dict[str, ManagedProcessState] = {
            service.name: ManagedProcessState(service=service)
            for service in self.topology.services
            if service.enabled
        }

    def _log(self, service_name: str, message: str) -> None:
        line = f"[SUPERVISOR] {message}"
        print(f"[{service_name}] {line}")
        log_path = self.log_dir / f"{service_name}.log"
        with log_path.open('a', encoding='utf-8') as handle:
            handle.write(line + "")
            handle.flush()

    def _run_git(self, args: list[str], *, timeout_s: float = 20.0) -> str:
        proc = subprocess.run(
            ["git", "-C", str(self.root_dir), *args],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            detail = stderr or stdout or f"git exited with code {proc.returncode}"
            raise RuntimeError(detail)
        return (proc.stdout or "").strip()

    def repo_update_status(self, force: bool = False) -> dict[str, Any]:
        now = time.time()
        with self._maintenance_lock:
            cached_at = float(self._repo_status_cache.get("checked_at") or 0.0)
            cached = self._repo_status_cache.get("status")
            if not force and isinstance(cached, dict) and now - cached_at < 60.0:
                return dict(cached)

            repo_url = "https://github.com/FelixAbeln/LabBREW.git"
            status: dict[str, Any] = {
                "repo_url": repo_url,
                "local_revision": None,
                "remote_revision": None,
                "branch": None,
                "outdated": False,
                "dirty": False,
                "error": None,
            }

            try:
                status["local_revision"] = self._run_git(["rev-parse", "HEAD"])
                status["branch"] = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
                status["dirty"] = bool(self._run_git(["status", "--porcelain"]))

                branch = str(status.get("branch") or "")
                remote_ref = f"refs/heads/{branch}" if branch and branch != "HEAD" else "HEAD"
                remote_line = self._run_git(["ls-remote", repo_url, remote_ref], timeout_s=25.0)
                status["remote_revision"] = remote_line.split()[0] if remote_line else None

                local_rev = str(status.get("local_revision") or "")
                remote_rev = str(status.get("remote_revision") or "")
                status["outdated"] = bool(local_rev and remote_rev and local_rev != remote_rev)
            except Exception as exc:
                status["error"] = str(exc)

            self._repo_status_cache = {
                "checked_at": now,
                "status": dict(status),
            }
            return status

    def _restart_managed_services(self) -> None:
        for name in reversed(self.start_order):
            state = self.services[name]
            self._log(name, "stopping service for update apply")
            self.runner.stop(state, force=False)

        for name in self.start_order:
            state = self.services[name]
            self._log(name, "starting service after update apply")
            self.start_service(state)

    def apply_repo_update(self) -> dict[str, Any]:
        with self._maintenance_lock:
            before = self.repo_update_status(force=True)
            if before.get("error"):
                return {
                    "ok": False,
                    "updated": False,
                    "reason": "status_check_failed",
                    "before": before,
                    "after": before,
                }

            # Determine the currently checked-out branch so we do not
            # unconditionally fetch/pull from "main" and accidentally
            # update the wrong branch.
            try:
                branch_proc = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=str(self.root_dir),
                    capture_output=True,
                    text=True,
                    timeout=10.0,
                    check=False,
                )
            except Exception as exc:
                return {
                    "ok": False,
                    "updated": False,
                    "reason": f"git_branch_detection_failed: {exc}",
                    "before": before,
                    "after": before,
                }

            current_branch = (branch_proc.stdout or "").strip()
            if branch_proc.returncode != 0 or not current_branch or current_branch == "HEAD":
                # Detached HEAD or unable to determine a valid branch; refuse to
                # perform an automatic update in this state.
                return {
                    "ok": False,
                    "updated": False,
                    "reason": "unsupported_git_state_for_update",
                    "details": [branch_proc.stderr.strip()] if branch_proc.stderr else [],
                    "before": before,
                    "after": before,
                }

            updated = False
            restart_requested = False
            details: list[str] = []
            repo_url = str(before.get("repo_url") or "https://github.com/FelixAbeln/LabBREW.git")

            def _run_pip_checked(args: list[str], *, label: str) -> None:
                proc = subprocess.run(
                    [sys.executable, "-m", "pip", *args],
                    cwd=str(self.root_dir),
                    capture_output=True,
                    text=True,
                    timeout=180.0,
                    check=False,
                )
                if proc.returncode != 0:
                    stderr = (proc.stderr or "").strip()
                    stdout = (proc.stdout or "").strip()
                    detail = stderr or stdout or f"pip exited with code {proc.returncode}"
                    raise RuntimeError(f"{label} failed: {detail}")

            try:
                self._run_git(["fetch", repo_url, current_branch], timeout_s=35.0)
                details.append(f"fetched latest {current_branch} from GitHub")
                refreshed = self.repo_update_status(force=True)
                if refreshed.get("outdated"):
                    self._run_git(["pull", "--ff-only", repo_url, current_branch], timeout_s=45.0)
                    details.append("fast-forward pull applied")
                    _run_pip_checked(["install", "-r", str(self.root_dir / "requirements.txt")], label="pip requirements install")
                    details.append("pip requirements install succeeded")
                    _run_pip_checked(["install", str(self.root_dir)], label="pip project install")
                    details.append("pip project install succeeded")
                    updated = True
                    self._restart_requested = True
                    self._stopping = True
                    restart_requested = True
                    details.append("supervisor restart requested")

                if updated and not restart_requested:
                    self._restart_managed_services()
                    self._publish_node()
            except Exception as exc:
                after_err = self.repo_update_status(force=True)
                return {
                    "ok": False,
                    "updated": updated,
                    "reason": str(exc),
                    "details": details,
                    "before": before,
                    "after": after_err,
                    "restart_requested": restart_requested,
                }

            after = self.repo_update_status(force=True)
            return {
                "ok": True,
                "updated": updated,
                "details": details,
                "before": before,
                "after": after,
                "restart_requested": restart_requested,
            }

    def install_signal_handlers(self) -> None:
        def _handler(_signum, _frame) -> None:
            self._stopping = True

        signal.signal(signal.SIGINT, _handler)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, _handler)

    def dependencies_healthy(self, service: ServiceSpec) -> bool:
        for dep_service_name in self.resolved.service_dependencies.get(service.name, set()):
            dep_state = self.services[dep_service_name]
            if dep_state.process is None:
                self._log(service.name, f'dependency {dep_service_name} not started yet')
                return False
            if dep_state.process.poll() is not None:
                self._log(service.name, f'dependency {dep_service_name} exited with code {dep_state.process.poll()}')
                return False
            dep_ok, dep_reason = self._service_health_details(dep_state.service)
            if not dep_ok:
                self._log(service.name, f'dependency {dep_service_name} unhealthy: {dep_reason}')
                return False
        return True

    def _service_health_details(self, service: ServiceSpec) -> tuple[bool, str]:
        if not service.provides:
            return True, 'no provided capabilities to health-check'
        failures: list[str] = []
        for provided in service.provides:
            if provided.healthcheck_type == 'tcp':
                ok, detail = tcp_probe(provided.bind_endpoint.host, provided.bind_endpoint.port, timeout=1.0)
                if ok:
                    return True, f'tcp probe ok for {provided.name} at {provided.bind_endpoint.host}:{provided.bind_endpoint.port}'
                failures.append(f'tcp probe failed for {provided.name} at {provided.bind_endpoint.host}:{provided.bind_endpoint.port}: {detail}')
        return False, '; '.join(failures) if failures else 'no supported health checks'

    def is_service_healthy(self, service: ServiceSpec) -> bool:
        ok, _ = self._service_health_details(service)
        return ok

    def service_map(self) -> dict[str, dict[str, Any]]:
        mapped: dict[str, dict[str, Any]] = {}
        repo_status = self.repo_update_status(force=False)
        update_info = {
            "outdated": bool(repo_status.get("outdated")),
            "local_revision": repo_status.get("local_revision"),
            "remote_revision": repo_status.get("remote_revision"),
            "error": repo_status.get("error"),
        }
        for service_name, state in self.services.items():
            ok, reason = self._service_health_details(state.service)
            if not state.service.provides:
                continue
            first_binding = self.resolved.bindings[state.service.provides[0].name]
            binding = self.resolved.bindings[service_name]
            mapped[service_name] = {
                'healthy': ok,
                'reason': reason,
                'base_url': f"http://{binding.endpoint.host}:{binding.endpoint.port}",
                'docs': state.service.docs,
                'provides': [provided.name for provided in state.service.provides],
                'update': dict(update_info),
            }
        return mapped

    def summary(self) -> dict[str, Any]:
        repo_status = self.repo_update_status(force=False)
        services = self.service_map()
        schedule = services.get('schedule_service')
        control = services.get('control_service')
        data = services.get('data_service')
        return {
            'node_id': self.node_id,
            'node_name': self.node_name,
            'services': services,
            'repo_update': repo_status,
            'schedule_available': bool(schedule and schedule['healthy']),
            'control_available': bool(control and control['healthy']),
            'data_available': bool(data and data['healthy']),
        }

    def _publish_node(self) -> None:
        healthy_services = tuple(sorted(name for name, info in self.service_map().items() if info.get('healthy')))
        self.discovery.publish_node(healthy_services)

    def start_service(self, state: ManagedProcessState) -> None:
        service = state.service
        if state.process is not None and state.process.poll() is None:
            return
        if not self.dependencies_healthy(service):
            return
        args = self.renderer.render_args(service, self.resolved.bindings)
        state.last_start_attempt = time.time()
        self._log(service.name, f'starting service with args: {args}')
        self.runner.start(state, args)
        state.started_at = time.time()

        deadline = time.time() + service.startup_timeout_s
        while time.time() < deadline:
            if state.process is None:
                self._log(service.name, 'process handle disappeared during startup')
                break
            exit_code = state.process.poll()
            if exit_code is not None:
                self._log(service.name, f'process exited during startup with code {exit_code}')
                break
            ok, reason = self._service_health_details(service)
            if ok:
                state.healthy_once = True
                self._log(service.name, f'startup health check passed: {reason}')
                self._publish_node()
                return
            self._log(service.name, f'waiting for healthy startup: {reason}')
            time.sleep(0.5)

        ok, reason = self._service_health_details(service)
        self._log(service.name, f'startup failed; stopping service. Last health status: {reason}')
        self.runner.stop(state, force=True)
        self._publish_node()

    def check_services(self) -> None:
        with self._maintenance_lock:
            self._check_services_locked()

    def _check_services_locked(self) -> None:
        for name in self.start_order:
            state = self.services[name]
            process = state.process
            if process is None:
                now = time.time()
                if state.last_start_attempt is None or now - state.last_start_attempt >= state.service.restart_backoff_s:
                    self._log(name, 'service is not running; attempting start')
                    self.start_service(state)
                continue
            exit_code = process.poll()
            if exit_code is not None:
                state.restart_count += 1
                self._log(name, f'process exited with code {exit_code}; scheduling restart #{state.restart_count}')
                state.process = None
                self._publish_node()
                continue
            ok, reason = self._service_health_details(state.service)
            if not ok:
                state.restart_count += 1
                self._log(name, f'service became unhealthy: {reason}; terminating for restart #{state.restart_count}')
                self.runner.stop(state, force=False)
                self._publish_node()
            else:
                self._log(name, f'service healthy: {reason}')
        self._publish_node()

    def stop_all(self) -> None:
        for name in reversed(self.start_order):
            state = self.services[name]
            self._log(name, 'stopping service')
            self.runner.stop(state, force=False)
        self.discovery.close()
        self.agent_api.stop()

    def run(self) -> None:
        self.install_signal_handlers()
        self.agent_api.start()
        self._publish_node()
        try:
            while not self._stopping:
                self.check_services()
                time.sleep(self.check_interval_s)
        finally:
            self.stop_all()
