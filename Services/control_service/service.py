import threading

from fastapi import FastAPI
import uvicorn

from .._shared.cli import parse_args
from .runtime import ControlRuntime
from .api.routes_rules import router as rules_router
from .api.routes_system import router as system_router
from .api.routes_control import router as control_router, set_runtime as set_control_runtime
from .api.routes_ws import router as ws_router, set_runtime as set_ws_runtime


def main():
    args = parse_args("Control Service")

    runtime = ControlRuntime(host=args.backend_host, port=args.backend_port)

    thread = threading.Thread(target=runtime.run, daemon=True)
    thread.start()

    app = FastAPI()
    set_control_runtime(runtime)
    set_ws_runtime(runtime)
    app.include_router(rules_router)
    app.include_router(system_router)
    app.include_router(control_router)
    app.include_router(ws_router)

    @app.on_event('shutdown')
    def _shutdown() -> None:
        runtime.stop()

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
