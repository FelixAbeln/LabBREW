"""Data service entry point.

A FastAPI-based service for recording parameter values from parameterDB
at a configurable frequency, storing to files, and generating loadstep averages.
"""

import threading
from fastapi import FastAPI
import uvicorn

from .._shared.cli import parse_args
from .runtime import DataRecordingRuntime
from .api.routes import router as measurement_router, set_runtime


def main():
    """Main entry point for the data service."""
    args = parse_args("Data Service")

    # Create and start the runtime
    runtime = DataRecordingRuntime(host=args.backend_host, port=args.backend_port)

    thread = threading.Thread(target=runtime.run, daemon=True)
    thread.start()

    # Create and configure FastAPI app
    app = FastAPI(title="Data Service", description="Parameter data logging service")
    set_runtime(runtime)
    app.include_router(measurement_router)

    # Run the API server
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
