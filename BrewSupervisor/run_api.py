from __future__ import annotations

import os

import uvicorn

from .api.app import app


def main() -> None:
    # Keep supervisor responsive when agent API endpoints are briefly busy.
    os.environ.setdefault("REGISTRY_TIMEOUT_S", "0.6")
    os.environ.setdefault("REGISTRY_CACHE_TTL_S", "0.5")
    os.environ.setdefault("REGISTRY_STALE_GRACE_S", "20.0")

    uvicorn.run(app, host='0.0.0.0', port=8782)

if __name__ == '__main__':
    main()
