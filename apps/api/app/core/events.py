"""Barramento in-process para o tempo real do mapa e da fila de portaria.

Fatia 1 usa memória; na Fatia 6 isto vira ponte para MQTT/NATS sem mudar o contrato
`publish(topic, payload)` usado pelos serviços.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any


class Hub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        message = json.dumps({"topic": topic, "payload": payload}, default=str)
        for queue in list(self._subscribers):
            if queue.full():
                continue  # consumidor lento não trava o pátio
            queue.put_nowait(message)

    async def subscribe(self) -> AsyncIterator[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)


hub = Hub()
