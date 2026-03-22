from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ..domain.models import ManagedProcessState, ServiceSpec


class ProcessRunner:
    def __init__(self, root_dir: str | Path, log_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.log_dir = Path(log_dir).resolve()
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def start(self, state: ManagedProcessState, args: list[str]) -> subprocess.Popen[str]:
        command = [sys.executable, "-m", state.service.module, *args]
        log_path = self.log_dir / f"{state.service.name}.log"
        handle = log_path.open("a", encoding="utf-8")
        handle.write(f"[START] {' '.join(command)}\n")
        handle.flush()
        env = os.environ.copy()
        env.update(dict(state.service.env))
        process = subprocess.Popen(
            command,
            cwd=str(self.root_dir),
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        state.process = process
        return process

    def stop(self, state: ManagedProcessState, force: bool = False) -> None:
        process = state.process
        state.process = None
        if process is None or process.poll() is not None:
            return
        if force:
            process.kill()
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
