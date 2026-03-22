
from __future__ import annotations

import signal
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
        )
        self._stopping = False

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
                'provides': [provided.name for provided in state.service.provides],
            }
        return mapped

    def summary(self) -> dict[str, Any]:
        schedule = self.service_map().get('schedule_service')
        control = self.service_map().get('control_service')
        return {
            'node_id': self.node_id,
            'node_name': self.node_name,
            'services': self.service_map(),
            'schedule_available': bool(schedule and schedule['healthy']),
            'control_available': bool(control and control['healthy']),
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
