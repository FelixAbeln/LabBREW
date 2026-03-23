import threading

from fastapi import FastAPI
import uvicorn

from .._shared.cli import parse_args
from .api.routes_schedule import router as schedule_router, set_runtime
from .control_client import ControlClient
from .data_client import DataClient
from .runtime import ScheduleRuntime


def main():
    args = parse_args('Schedule Service')
    control_url = f'http://{args.backend_host}:{args.backend_port}'
    data_url = f'http://{args.data_backend_host}:{args.data_backend_port}'

    control_client = ControlClient(base_url=control_url)
    data_client = DataClient(base_url=data_url)
    runtime = ScheduleRuntime(control_client=control_client, data_client=data_client)
    thread = threading.Thread(target=runtime.start_background, daemon=True)
    thread.start()

    app = FastAPI()
    set_runtime(runtime)
    app.include_router(schedule_router)

    @app.on_event('shutdown')
    def _shutdown() -> None:
        runtime.shutdown()
        control_client.close()
        data_client.close()

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == '__main__':
    main()
