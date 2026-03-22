from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class _Subscription:
    token: str
    queue: queue.Queue[dict[str, Any]]
    filters: set[str] | None
    max_queue: int
    dropped_events: int = 0


class EventBroker:
    """Central event fanout with bounded queues and a simple overflow policy."""

    def __init__(self, default_max_queue: int = 1000) -> None:
        self._lock = threading.RLock()
        self._subs: dict[str, _Subscription] = {}
        self._default_max_queue = default_max_queue

    def subscribe(
        self,
        names: list[str] | None = None,
        max_queue: int | None = None,
    ) -> tuple[str, queue.Queue[dict[str, Any]], int]:
        token = uuid.uuid4().hex
        queue_size = max(1, int(max_queue or self._default_max_queue))
        sub = _Subscription(
            token=token,
            queue=queue.Queue(maxsize=queue_size),
            filters=set(names) if names else None,
            max_queue=queue_size,
        )
        with self._lock:
            self._subs[token] = sub
        return token, sub.queue, queue_size

    def unsubscribe(self, token: str) -> None:
        with self._lock:
            self._subs.pop(token, None)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def publish(self, event: dict[str, Any]) -> None:
        name = event.get("name")
        with self._lock:
            subs = list(self._subs.values())

        stale_tokens: list[str] = []
        for sub in subs:
            if sub.filters is not None and name not in sub.filters:
                continue
            if not self._enqueue(sub, event):
                stale_tokens.append(sub.token)

        if stale_tokens:
            with self._lock:
                for token in stale_tokens:
                    self._subs.pop(token, None)

    def _enqueue(self, sub: _Subscription, event: dict[str, Any]) -> bool:
        try:
            sub.queue.put_nowait(event)
            return True
        except queue.Full:
            sub.dropped_events += 1

        try:
            sub.queue.get_nowait()  # drop oldest
        except queue.Empty:
            pass

        overflow_notice = {
            "event": "subscription_overflow",
            "subscription_id": sub.token,
            "dropped_events": sub.dropped_events,
            "max_queue": sub.max_queue,
        }

        try:
            sub.queue.put_nowait(overflow_notice)
        except queue.Full:
            # still clogged after dropping oldest: disconnect the subscriber
            return False

        try:
            sub.queue.put_nowait(event)
            return True
        except queue.Full:
            return False
