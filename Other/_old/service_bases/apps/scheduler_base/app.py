from __future__ import annotations

from typing import Any

from ....service_bases.core.app_server import Route
from ....schedule_service.runtime import FcsRuntimeService


class SchedulerBaseApp:
    def __init__(self, runtime: FcsRuntimeService) -> None:
        self.runtime = runtime

    def health(self, _: dict[str, Any]) -> dict[str, Any]:
        return {
            'ok': True,
            'service': 'scheduler',
            'state': self.runtime.status(),
        }

    def status(self, _: dict[str, Any]) -> dict[str, Any]:
        return self.runtime.status()

    def validate_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.runtime.validate_schedule_payload(payload)

    def upload_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.runtime.upload_schedule(payload)

    def current_schedule(self, _: dict[str, Any]) -> dict[str, Any]:
        return self.runtime.current_schedule_payload()

    def start(self, _: dict[str, Any]) -> dict[str, Any]:
        return self.runtime.start_run()

    def pause(self, _: dict[str, Any]) -> dict[str, Any]:
        return self.runtime.pause_run()

    def resume(self, _: dict[str, Any]) -> dict[str, Any]:
        return self.runtime.resume_run()

    def stop(self, _: dict[str, Any]) -> dict[str, Any]:
        return self.runtime.stop_run()

    def confirm(self, _: dict[str, Any]) -> dict[str, Any]:
        return self.runtime.confirm_step()

    def next_step(self, _: dict[str, Any]) -> dict[str, Any]:
        return self.runtime.next_step()

    def previous_step(self, _: dict[str, Any]) -> dict[str, Any]:
        return self.runtime.previous_step()


def build_scheduler_routes(app: SchedulerBaseApp) -> list[Route]:
    return [
        Route('GET', '/status', app.status),
        Route('GET', '/health', app.health),
        Route('GET', '/schedule', app.current_schedule),
        Route('POST', '/schedule/validate', app.validate_schedule),
        Route('POST', '/schedule/upload', app.upload_schedule),
        Route('POST', '/run/start', app.start),
        Route('POST', '/run/pause', app.pause),
        Route('POST', '/run/resume', app.resume),
        Route('POST', '/run/stop', app.stop),
        Route('POST', '/run/confirm', app.confirm),
        Route('POST', '/run/next', app.next_step),
        Route('POST', '/run/previous', app.previous_step),
    ]
