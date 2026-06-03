from __future__ import annotations

import asyncio
import json
from typing import Any


class NotificationBroker:
    def __init__(self) -> None:
        self._listeners: set[asyncio.Queue[str]] = set()

    async def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._listeners.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._listeners.discard(queue)

    async def publish(self, event: str, data: dict[str, Any]) -> None:
        self.publish_nowait(event, data)

    def publish_nowait(self, event: str, data: dict[str, Any]) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        stale: list[asyncio.Queue[str]] = []
        for listener in self._listeners:
            try:
                listener.put_nowait(payload)
            except RuntimeError:
                stale.append(listener)
        for listener in stale:
            self._listeners.discard(listener)


broker = NotificationBroker()
