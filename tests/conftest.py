from __future__ import annotations

import pytest

from Services.control_service.api import routes_control
from Services.data_service.api import routes as data_routes
from Services.scenario_service.api import routes_scenario


@pytest.fixture(autouse=True)
def reset_route_runtimes() -> None:
    """Ensure route modules start each test with clean global runtime state."""
    routes_control.set_runtime(None)
    data_routes.set_runtime(None)
    routes_scenario.set_runtime(None)
    yield
    routes_control.set_runtime(None)
    data_routes.set_runtime(None)
    routes_scenario.set_runtime(None)
