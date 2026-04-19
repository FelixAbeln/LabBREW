import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from .._shared.cli import build_shared_parser
from .control_client import ControlClient
from .data_client import DataClient
from .api.routes_scenario import router as scenario_router
from .api.routes_scenario import set_runtime
from .runtime import ScenarioRuntime


def main() -> None:
    parser = build_shared_parser("Scenario Service")
    parser.set_defaults(backend_port=8767, data_backend_port=8769, port=8770)
    args = parser.parse_args()
    control_url = str(args.backend_url or f"http://{args.backend_host}:{args.backend_port}")
    data_url = str(args.data_backend_url or f"http://{args.data_backend_host}:{args.data_backend_port}")

    control_client = ControlClient(base_url=control_url)
    data_client = DataClient(base_url=data_url)
    runtime = ScenarioRuntime(control_client=control_client, data_client=data_client)
    thread = threading.Thread(target=runtime.start_background, daemon=True)
    thread.start()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            runtime.shutdown()
            control_client.close()
            data_client.close()

    app = FastAPI(lifespan=lifespan)
    set_runtime(runtime)
    app.include_router(scenario_router)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
