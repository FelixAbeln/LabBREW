from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/ws")
_runtime = None


def set_runtime(runtime):
    global _runtime
    _runtime = runtime


def _normalize_targets(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    targets = [part.strip() for part in raw.split(",") if part.strip()]
    return targets or None


@router.websocket("/live")
async def live(websocket: WebSocket):
    await websocket.accept()
    targets = _normalize_targets(websocket.query_params.get("targets"))
    interval = websocket.query_params.get("interval", "0.5")
    try:
        sleep_s = max(0.1, float(interval))
    except Exception:
        sleep_s = 0.5

    last_payload = None

    try:
        while True:
            if _runtime is None:
                payload = {"ok": False, "error": "runtime not initialized"}
            else:
                payload = _runtime.get_live_snapshot(targets=targets)

            serialized = json.dumps(payload, sort_keys=True, default=str)
            if serialized != last_payload:
                await websocket.send_json(payload)
                last_payload = serialized

            await asyncio.sleep(sleep_s)
    except WebSocketDisconnect:
        return
